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


def _area_map(png: bytes, feat_vals: dict, n_emb: int):
    """Genera el mapa de probabilidad por área (figura, CSV, min, máx) a partir de la imagen + features.

    Reutiliza predict_map: el embedding de la imagen se combina con un campo ERA5 modulado por los
    valores de los deslizadores, para que el mapa reaccione a lo que el usuario ajusta.
    """
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tempfile

    import matplotlib
    import pandas as pd

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import predict_map as pm

    lat, lon = pm.grid()
    # Campo base sintético, escalado por los sliders (la zona de inestabilidad se intensifica con CAPE/VGP).
    base = pm.synthetic_fields(lat, lon)
    scale = (feat_vals["cape"] / 500.0 + feat_vals["vgp_01"] / 0.15) / 2
    for k in base:
        base[k] = base[k] * (0.5 + scale)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(png)
        img_path = Path(tf.name)
    emb = pm.image_embedding(img_path, n_emb)
    prob = pm.predict_grid(base, lat, lon, emb)

    rows = [{"latitude": float(lat[i]), "longitude": float(lon[j]), "prob": float(prob[i, j])}
            for i in range(len(lat)) for j in range(len(lon))]
    csv_df = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(5, 8))
    mesh = ax.pcolormesh(lon, lat, prob, cmap="turbo", vmin=0, vmax=1, shading="auto")
    pm.draw_coast(ax)
    ax.set_xlim(pm.REGION.west, pm.REGION.east)
    ax.set_ylim(pm.REGION.south, pm.REGION.north)
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title("Probabilidad de tornado por área")
    fig.colorbar(mesh, ax=ax, label="probabilidad", shrink=0.6)
    return fig, csv_df, float(prob.min()), float(prob.max())


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
        buf = io.BytesIO()
        img.resize((224, 224)).save(buf, format="PNG")
        emb, source = image_embedding(buf.getvalue(), n_emb)

        st.subheader("3. Resultado — probabilidad por área")
        buf2 = io.BytesIO()
        img.resize((224, 224)).save(buf2, format="PNG")
        fig, csv_df, pmin, pmax = _area_map(buf2.getvalue(), feat_vals, n_emb)
        st.pyplot(fig)
        st.caption(f"Mapa de calor sobre Chile centro-sur/austral · prob {pmin:.2f}–{pmax:.2f} · "
                   f"embedding: {source}")
        st.download_button("⬇️ Descargar CSV de probabilidad por área",
                           csv_df.to_csv(index=False).encode(), "probabilidades.csv", "text/csv")
        with st.expander("Ver tabla (celdas de mayor probabilidad)"):
            st.dataframe(csv_df.nlargest(15, "prob"), use_container_width=True)


if __name__ == "__main__":
    main()
