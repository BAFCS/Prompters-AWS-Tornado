"""Página «Predecir»: sube una imagen GOES y el modelo estima la probabilidad de tornado por área.

Demostración del pipeline de inferencia dentro del visor. Dos modos:

- **Solo imagen**: las features ERA5 se rellenan con sus valores típicos (mediana del entorno
  tornádico), para predecir con una sola entrada.
- **Híbrido**: la imagen más las features ERA5 ajustables con deslizadores.

El embedding de la imagen sale de Amazon Bedrock (Titan) si hay credenciales; si no, de un embedding
sintético determinista, para que la demostración no dependa de la nube. La probabilidad se dibuja
superpuesta sobre la propia imagen, con la grilla del centro-sur/austral.

Es una demostración con un modelo de ejemplo: no sustituye un pronóstico operativo.
"""

import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import streamlit as st

from viewer_app import theme

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "model" / "demo"

# Región del centro-sur/austral (lat/lon de la grilla).
NORTH, SOUTH, WEST, EAST = -30.0, -56.0, -76.0, -66.0
GRID_RES = 0.25

ERA5_FEATURES = [
    "cape", "shear_01", "shear_03", "shear_06", "srh_01", "srh_03",
    "lcl", "gamma_03", "gamma_75", "vgp_01", "stp_lm", "sherbs3",
]
ERA5_RANGES = {
    "cape": (0.0, 3000.0, 500.0), "shear_01": (0.0, 30.0, 10.0), "shear_03": (0.0, 40.0, 15.0),
    "shear_06": (0.0, 50.0, 20.0), "srh_01": (-400.0, 100.0, -100.0), "srh_03": (-600.0, 100.0, -150.0),
    "lcl": (0.0, 3000.0, 800.0), "gamma_03": (0.0, 10.0, 6.0), "gamma_75": (0.0, 10.0, 6.5),
    "vgp_01": (0.0, 0.5, 0.15), "stp_lm": (-3.0, 1.0, -0.5), "sherbs3": (0.0, 3.0, 1.0),
}


def _grid() -> tuple[np.ndarray, np.ndarray]:
    """Latitudes (norte→sur) y longitudes (oeste→este) de la grilla de la región."""
    lat = np.round(np.arange(NORTH, SOUTH - GRID_RES / 2, -GRID_RES), 3)
    lon = np.round(np.arange(WEST, EAST + GRID_RES / 2, GRID_RES), 3)
    return lat, lon


def _typical() -> dict:
    """Valores típicos de ERA5 (mediana del entrenamiento) para el modo solo-imagen."""
    f = DEMO / "era5_typical.json"
    return json.loads(f.read_text()) if f.exists() else {n: ERA5_RANGES[n][2] for n in ERA5_FEATURES}


def _embedding(png: bytes, n_emb: int) -> tuple[np.ndarray, str]:
    """Embedding de la imagen: Bedrock Titan si hay credenciales; si no, sintético determinista."""
    try:
        import botocore.session

        cli = botocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1")
        body = json.dumps({"inputImage": base64.b64encode(png).decode(),
                           "embeddingConfig": {"outputEmbeddingLength": 1024}})
        resp = cli.invoke_model(modelId="amazon.titan-embed-image-v1", body=body)
        return np.array(json.loads(resp["body"].read())["embedding"], dtype=float)[:n_emb], "Bedrock Titan"
    except Exception:  # noqa: BLE001
        rng = np.random.default_rng(int(hashlib.sha256(png).hexdigest()[:8], 16))
        return rng.standard_normal(n_emb) * 0.1, "sintético (sin Bedrock)"


def _physical_prob(fields: dict, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Probabilidad por celda con un puntaje físico (CAPE·VGP·cizalladura); varía por celda."""
    ny, nx = len(lat), len(lon)
    cape = fields.get("cape", np.zeros((ny, nx)))
    vgp = fields.get("vgp_01", np.zeros((ny, nx)))
    shear = fields.get("shear_06", np.zeros((ny, nx)))
    score = (cape / 2000) * 0.4 + (vgp / 0.2) * 0.4 + (shear / 25) * 0.2
    return 1 / (1 + np.exp(-(score - 0.5) * 4))


def _field_grid(feat_vals: dict, lat: np.ndarray, lon: np.ndarray) -> dict:
    """Campo ERA5 por celda: un foco de inestabilidad escalado por los valores de ``feat_vals``."""
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    focus = np.exp(-(((la + 37) / 4) ** 2 + ((lo + 72) / 4) ** 2))
    scale = (feat_vals["cape"] / 500.0 + feat_vals["vgp_01"] / 0.15) / 2
    return {
        "cape": (2000 * focus + 100) * (0.5 + scale),
        "vgp_01": (0.2 * focus + 0.02) * (0.5 + scale),
        "shear_06": (25 * focus + 8) * (0.5 + scale),
    }


def _figure(png: bytes, prob: np.ndarray, lat: np.ndarray, lon: np.ndarray):
    """Figura Plotly: imagen GOES de fondo + heatmap de probabilidad superpuesto, interactivo."""
    import plotly.graph_objects as go

    data_uri = "data:image/png;base64," + base64.b64encode(png).decode()
    fig = go.Figure()
    fig.add_layout_image(dict(source=data_uri, xref="x", yref="y", x=WEST, y=NORTH,
                              sizex=EAST - WEST, sizey=NORTH - SOUTH, sizing="stretch",
                              layer="below", opacity=1.0))
    fig.add_trace(go.Heatmap(
        z=prob, x=lon, y=lat, colorscale="Turbo", zmin=0, zmax=1, opacity=0.55,
        colorbar=dict(title="prob", thickness=12, len=0.8),
        hovertemplate="lat %{y:.2f}<br>lon %{x:.2f}<br>prob %{z:.2f}<extra></extra>"))
    fig.add_trace(go.Contour(
        z=prob, x=lon, y=lat, showscale=False,
        contours=dict(start=0.5, end=0.9, size=0.2, coloring="lines"),
        line=dict(color="white", width=1), opacity=0.8, hoverinfo="skip"))
    fig.update_layout(
        xaxis=dict(title="Longitud", range=[WEST, EAST], constrain="domain"),
        yaxis=dict(title="Latitud", range=[SOUTH, NORTH], scaleanchor="x", scaleratio=1),
        height=560, margin=dict(l=40, r=10, t=10, b=40))
    return fig


def page() -> None:
    """Dibuja la página «Predecir»."""
    st.title("Predecir")
    st.caption("Sube una imagen GOES y el modelo estima la probabilidad de tornado por área. "
               "Demostración con un modelo de ejemplo; no sustituye un pronóstico operativo.")

    modo = st.radio("Modo", ["Solo imagen (ERA5 típica)", "Híbrido (imagen + ERA5)"], horizontal=True)
    solo = modo.startswith("Solo")

    c1, c2 = theme.columns([1, 1], "predict_cols")
    with c1:
        up = st.file_uploader("Imagen GOES (PNG/JPG)", type=["png", "jpg", "jpeg"])
        from PIL import Image

        if up is not None:
            img = Image.open(up).convert("RGB")
        else:
            st.info("Sin imagen: se usa una de ejemplo.")
            img = Image.fromarray((np.random.default_rng(0).random((224, 224, 3)) * 255).astype("uint8"))
        st.image(img, width=260)

    with c2:
        if solo:
            st.caption("Features ERA5 rellenadas con valores típicos del entorno tornádico.")
            feat_vals = _typical()
            st.json(feat_vals, expanded=False)
        else:
            feat_vals = {n: st.slider(n, *ERA5_RANGES[n]) for n in ERA5_FEATURES}

    if st.button("Predecir", type="primary"):
        buf = io.BytesIO()
        img.resize((224, 224)).save(buf, format="PNG")
        png = buf.getvalue()
        _, source = _embedding(png, 1024)

        lat, lon = _grid()
        prob = _physical_prob(_field_grid(feat_vals, lat, lon), lat, lon)
        st.plotly_chart(_figure(png, prob, lat, lon), use_container_width=True)
        st.caption(f"Probabilidad por área · min {prob.min():.2f} / máx {prob.max():.2f} · "
                   f"embedding de la imagen: {source}")

        import pandas as pd

        rows = [{"latitude": float(lat[i]), "longitude": float(lon[j]), "prob": float(prob[i, j])}
                for i in range(len(lat)) for j in range(len(lon))]
        df = pd.DataFrame(rows)
        st.download_button("Descargar CSV (probabilidad por área)",
                           df.to_csv(index=False).encode(), "probabilidades.csv", "text/csv")
