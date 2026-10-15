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

# Bucket público del equipo con las imágenes GOES de Chile y los días con tornado conocidos.
BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
# Días con tornado que tienen imagen GOES en el bucket (caso real para predecir).
TORNADO_DAYS = [
    "2019-05-30", "2019-05-31", "2019-06-13", "2019-10-28",
    "2018-03-22", "2018-09-30", "2020-04-25", "2020-05-03",
]


@st.cache_data(show_spinner=False)
def _goes_real(day: str) -> tuple[bytes, list[str]] | None:
    """Baja C13 del día desde el bucket y devuelve (NetCDF en bytes, lista de horas HH:MM)."""
    import fsspec

    fs = fsspec.filesystem("s3", anon=True)
    key = f"{BUCKET}/goes_store/{day}/goes_{day.replace('-', '')}_C13.nc"
    if not fs.exists(key):
        return None
    with fs.open(key, "rb") as f:
        raw = f.read()
    import pandas as pd
    import xarray as xr

    ds = xr.load_dataset(io.BytesIO(raw))
    horas = [str(t)[11:16] for t in pd.to_datetime(ds["time"].values)]
    return raw, horas


def _goes_image(raw: bytes, hour_idx: int) -> bytes:
    """Convierte el barrido ``hour_idx`` de C13 en un PNG RECORTADO a la región del modelo.

    El modelo se entrenó en el centro-sur/austral (lat NORTH..SOUTH, lon WEST..EAST). La imagen del
    bucket cubre un área más amplia, así que se reproyecta de la grilla ABI (lat/lon 2-D) a una
    grilla regular de esa región, para que la imagen y el mapa de probabilidad coincidan.
    """
    import xarray as xr
    from scipy.spatial import cKDTree

    ds = xr.load_dataset(io.BytesIO(raw))
    arr = ds["C13"].isel(time=hour_idx).values.astype(float)
    lat2d = ds["lat"].values
    lon2d = ds["lon"].values

    # grilla regular de la región del modelo (misma extensión que el mapa)
    glat = np.arange(NORTH, SOUTH - 0.05, -0.05)
    glon = np.arange(WEST, EAST + 0.05, 0.05)
    gla, glo = np.meshgrid(glat, glon, indexing="ij")

    ok = np.isfinite(lat2d.ravel()) & np.isfinite(lon2d.ravel()) & np.isfinite(arr.ravel())
    k = np.cos(np.deg2rad((NORTH + SOUTH) / 2))
    tree = cKDTree(np.column_stack([lat2d.ravel()[ok], lon2d.ravel()[ok] * k]))
    _, idx = tree.query(np.column_stack([gla.ravel(), glo.ravel() * k]))
    sub = arr.ravel()[ok][idx].reshape(gla.shape)

    sub = np.nan_to_num(sub, nan=float(np.nanmean(sub)))
    lo, hi = np.percentile(sub, 2), np.percentile(sub, 98)
    norm = np.clip((sub - lo) / (hi - lo + 1e-9), 0, 1)
    img8 = (255 * (1 - norm)).astype("uint8")  # invertido: nubes frías claras
    from PIL import Image

    return _to_png(Image.fromarray(np.stack([img8, img8, img8], axis=-1)))


def _to_png(img) -> bytes:
    """Serializa una imagen PIL a PNG en bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@st.cache_data(show_spinner=False, ttl=300)
def _goes_tiempo_real() -> tuple[bytes, str] | None:
    """Baja la imagen C13 más reciente de GOES-East en vivo y la recorta a la región del modelo.

    Usa el bucket público de NOAA (``noaa-goes19``, GOES-East actual; ``noaa-goes16`` antes de
    abr-2025), producto ``ABI-L2-CMIPF`` banda 13 (full-disk). Reproyecta de la grilla geoestacionaria
    ABI a la región centro-sur/austral. Devuelve (PNG recortado, etiqueta con la hora UTC), o None.

    Es más pesado que las imágenes recortadas del bucket del equipo (full-disk ~23 MB); en la EC2
    (us-east-1, misma región que NOAA) es rápido. Cachea 5 min (TTL) para no rebajar en cada clic.
    """
    import datetime as _dt

    import fsspec
    import h5py

    fs = fsspec.filesystem("s3", anon=True)
    now = _dt.datetime.now(_dt.UTC)
    # Busca en la hora actual y, si está vacía, en la anterior.
    for back in (0, 1):
        t = now - _dt.timedelta(hours=back)
        bucket = "noaa-goes19" if t >= _dt.datetime(2025, 4, 4, 15, tzinfo=_dt.UTC) else "noaa-goes16"
        prefix = f"{bucket}/ABI-L2-CMIPF/{t.year}/{t.timetuple().tm_yday:03d}/{t.hour:02d}/"
        try:
            c13 = sorted(f for f in fs.ls(prefix, detail=False) if "C13" in f)
        except FileNotFoundError:
            c13 = []
        if c13:
            key = c13[-1]
            with fs.open(key, "rb") as f:
                raw = f.read()
            with h5py.File(io.BytesIO(raw), "r") as h:
                x, y, lat, lon = _abi_latlon(h)
                cmi = h["CMI"][:]
            png = _crop_to_region(cmi, lat, lon)
            # hora del nombre del archivo (campo sYYYYJJJHHMMSS)
            stamp = key.split("_s")[1][:11]
            hh = f"{stamp[7:9]}:{stamp[9:11]}"
            return png, f"{t:%Y-%m-%d} {hh} UTC (en vivo)"
    return None


def _abi_latlon(h: "object") -> tuple:
    """Lat/lon de la grilla ABI usando scripts/common.latlon_abi."""
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "scripts"))
    import common

    return common.latlon_abi(h)


def _crop_to_region(cmi: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> bytes:
    """Recorta/reproyecta la banda a la región del modelo (vecino más cercano) y devuelve PNG."""
    from PIL import Image
    from scipy.spatial import cKDTree

    glat = np.arange(NORTH, SOUTH - 0.05, -0.05)
    glon = np.arange(WEST, EAST + 0.05, 0.05)
    gla, glo = np.meshgrid(glat, glon, indexing="ij")
    arr = np.asarray(cmi, dtype=float)
    ok = np.isfinite(lat.ravel()) & np.isfinite(lon.ravel()) & np.isfinite(arr.ravel())
    k = np.cos(np.deg2rad((NORTH + SOUTH) / 2))
    tree = cKDTree(np.column_stack([lat.ravel()[ok], lon.ravel()[ok] * k]))
    _, idx = tree.query(np.column_stack([gla.ravel(), glo.ravel() * k]))
    sub = arr.ravel()[ok][idx].reshape(gla.shape)
    sub = np.nan_to_num(sub, nan=float(np.nanmean(sub)))
    lo, hi = np.percentile(sub, 2), np.percentile(sub, 98)
    norm = np.clip((sub - lo) / (hi - lo + 1e-9), 0, 1)
    img8 = (255 * (1 - norm)).astype("uint8")
    return _to_png(Image.fromarray(np.stack([img8, img8, img8], axis=-1)))


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
    st.caption("Toma una imagen GOES real de Chile (o sube una) y el modelo estima la probabilidad "
               "de tornado por área. Demostración con un modelo de ejemplo; no es un pronóstico operativo.")

    modo = st.radio("Modo", ["Solo imagen (ERA5 típica)", "Híbrido (imagen + ERA5)"], horizontal=True)
    solo = modo.startswith("Solo")

    c1, c2 = theme.columns([1, 1], "predict_cols")
    with c1:
        from PIL import Image

        fuente = st.radio("Imagen de entrada",
                          ["GOES en vivo (hoy)", "GOES real de Chile (bucket)", "Subir archivo"],
                          horizontal=True)
        img = None
        if fuente.startswith("GOES en vivo"):
            with st.spinner("Bajando la imagen GOES más reciente de Chile…"):
                vivo = _goes_tiempo_real()
            if vivo is None:
                st.warning("No se pudo obtener la imagen en vivo; usa otra fuente.")
                img = Image.fromarray(np.zeros((224, 224, 3), "uint8"))
            else:
                png_vivo, etiqueta = vivo
                img = Image.open(io.BytesIO(png_vivo)).convert("RGB")
                st.caption(f"GOES-East C13 · {etiqueta} · tope de nubes sobre el centro-sur/austral")
        elif fuente.startswith("GOES real"):
            dia = st.selectbox("Día con tornado (GOES disponible)", TORNADO_DAYS)
            real = _goes_real(dia)
            if real is None:
                st.warning(f"No hay GOES para {dia} en el bucket.")
                img = Image.fromarray(np.zeros((224, 224, 3), "uint8"))
            else:
                raw, horas = real
                hidx = st.select_slider("Hora UTC del barrido", options=list(range(len(horas))),
                                        format_func=lambda i: horas[i],
                                        value=min(len(horas) - 1, len(horas) * 4 // 5))
                img = Image.open(io.BytesIO(_goes_image(raw, hidx))).convert("RGB")
                st.caption(f"GOES-16 C13 · {dia} {horas[hidx]} UTC (tope de nubes)")
        else:
            up = st.file_uploader("Imagen GOES (PNG/JPG)", type=["png", "jpg", "jpeg"])
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
