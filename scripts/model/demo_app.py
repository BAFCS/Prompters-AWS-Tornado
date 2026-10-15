"""Demo visual del pipeline multimodal: imagen GOES + features ERA5 -> predicción del modelo.

App de Streamlit para mostrar el pipeline en vivo en la presentación:

1. El usuario sube una imagen (un recorte GOES, o cualquier imagen de prueba).
2. Ajusta con deslizadores las features físicas de ERA5 (CAPE, cizalladura, SRH, VGP, STP...).
3. Al pulsar **Predecir**, la imagen se convierte en un embedding (Bedrock Titan si hay
   credenciales; si no, un embedding sintético determinista para que la demo nunca se caiga) y se
   une con las features ERA5 en el mismo vector que entrena el modelo.
4. El modelo XGBoost (el entrenado en ``data/model/demo/model_demo.json``) devuelve la probabilidad
   de entorno tornádico.

Es una demostración del flujo de inferencia, con el modelo sintético: sirve para enseñar que la
cadena imagen+features -> embedding -> XGBoost -> probabilidad funciona de punta a punta.

Ejecutar:
    uv run streamlit run scripts/model/demo_app.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import streamlit as st
import xgboost as xgb
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "model" / "demo"
MODEL_FILE = DEMO / "model_demo.json"
META_FILE = DEMO / "model_meta.json"

# Rangos realistas de cada feature ERA5 para los deslizadores (mín, máx, por defecto).
ERA5_RANGES = {
    "cape": (0.0, 3000.0, 500.0),
    "shear_01": (0.0, 30.0, 10.0),
    "shear_03": (0.0, 40.0, 15.0),
    "shear_06": (0.0, 50.0, 20.0),
    "srh_01": (-400.0, 100.0, -100.0),   # negativa en el hemisferio sur
    "srh_03": (-600.0, 100.0, -150.0),
    "lcl": (0.0, 3000.0, 800.0),
    "gamma_03": (0.0, 10.0, 6.0),
    "gamma_75": (0.0, 10.0, 6.5),
    "vgp_01": (0.0, 0.5, 0.15),
    "stp_lm": (-3.0, 1.0, -0.5),         # rama left-mover, negativa
    "sherbs3": (0.0, 3.0, 1.0),
}


@st.cache_resource
def load_model() -> tuple[xgb.XGBClassifier, dict]:
    """Carga el modelo XGBoost de la demo y su metadata (columnas y features)."""
    meta = json.loads(META_FILE.read_text())
    model = xgb.XGBClassifier()
    model.load_model(str(MODEL_FILE))
    return model, meta


def image_embedding(png: bytes, n_emb: int) -> np.ndarray:
    """Embedding de la imagen: Bedrock Titan si hay credenciales; si no, sintético determinista.

    El sintético se deriva del hash de la imagen, para que una misma imagen dé siempre el mismo
    vector (la demo es reproducible y nunca se cae por falta de credenciales).
    """
    try:
        import botocore.session

        cli = botocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1")
        body = json.dumps({"inputImage": base64.b64encode(png).decode(),
                           "embeddingConfig": {"outputEmbeddingLength": 1024}})
        resp = cli.invoke_model(modelId="amazon.titan-embed-image-v1", body=body)
        vec = np.array(json.loads(resp["body"].read())["embedding"], dtype=float)
        return vec[:n_emb], "Bedrock Titan (real)"
    except Exception:  # noqa: BLE001
        seed = int(hashlib.sha256(png).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        return rng.standard_normal(n_emb) * 0.1, "sintético (sin credenciales Bedrock)"


def main() -> None:
    """App de la demo."""
    st.set_page_config(page_title="Demo predictor de tornados", page_icon="🌪️", layout="wide")
    st.title("🌪️ Demo — Predictor multimodal de entorno tornádico")
    st.caption("Imagen GOES + features ERA5 → embedding → XGBoost → probabilidad. "
               "Modelo de demostración (entrenado con etiquetas sintéticas).")

    if not MODEL_FILE.exists():
        st.error(f"Falta el modelo de demo en {MODEL_FILE}. Genera primero el modelo sintético.")
        return

    model, meta = load_model()
    n_emb = meta.get("n_emb", 1024)

    col_img, col_feat = st.columns([1, 1])

    with col_img:
        st.subheader("1. Imagen (recorte GOES)")
        up = st.file_uploader("Sube una imagen (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if up is not None:
            img = Image.open(up).convert("RGB")
        else:
            st.info("Sin imagen: se usa una aleatoria de ejemplo.")
            arr = (np.random.default_rng(0).random((224, 224, 3)) * 255).astype("uint8")
            img = Image.fromarray(arr)
        st.image(img, caption="Entrada visual", width=280)

    with col_feat:
        st.subheader("2. Features ERA5 (entorno)")
        feat_vals: dict[str, float] = {}
        for name, (lo, hi, dflt) in ERA5_RANGES.items():
            feat_vals[name] = st.slider(name, lo, hi, dflt)

    st.divider()
    if st.button("🚀 Predecir", type="primary", use_container_width=True):
        # Imagen -> PNG -> embedding
        buf = io.BytesIO()
        img.resize((224, 224)).save(buf, format="PNG")
        emb, source = image_embedding(buf.getvalue(), n_emb)

        # Vector completo en el orden que espera el modelo
        row = {}
        for name, val in feat_vals.items():
            row[name] = val
        for i, v in enumerate(emb):
            row[f"emb_{i:04d}"] = float(v)
        # alinear a las columnas del modelo (rezagos y pca se completan con NaN/lo disponible)
        import pandas as pd

        cols = meta["model_columns"]
        x = pd.DataFrame([{c: row.get(c, np.nan) for c in cols}])

        try:
            prob = float(model.predict_proba(x)[:, 1][0])
        except Exception as e:  # noqa: BLE001
            st.warning(f"El modelo espera columnas reducidas (PCA). Demo con features ERA5 solamente. ({e!s:.80})")
            # fallback: solo features ERA5 contra un umbral físico simple
            prob = min(max((feat_vals["cape"] / 2000 + feat_vals["vgp_01"] / 0.2) / 2, 0), 1)

        st.subheader("3. Resultado")
        st.metric("Probabilidad de entorno tornádico", f"{prob * 100:.1f}%")
        st.progress(prob)
        if prob >= 0.5:
            st.error("⚠️ Entorno FAVORABLE a tornado (según el modelo de demo)")
        else:
            st.success("✅ Entorno poco favorable (según el modelo de demo)")
        st.caption(f"Embedding de la imagen: {source} · {n_emb} dims · "
                   f"{len(feat_vals)} features ERA5")


if __name__ == "__main__":
    main()
