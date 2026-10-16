"""Página «Predecir»: probabilidad de tornado por área con el modelo entrenado y una demo con imagen.

**Modelo v2 (por defecto)**: XGBoost ``physical`` (índices ERA5 + variables GOES C08/C13) entrenado
con etiquetas reales del catálogo (rama ``merge/datos-modelo``). Sus predicciones por celda de 0,25°
y hora UTC para los días con tornado se calculan con ``scripts/app/infer_grid.py`` y se publican en
``/resultados/sitio/days/`` del mismo CloudFront; esta página las lee y las dibuja sobre la imagen GOES
de esa hora. Validación dejando un evento afuera: CSI 0,31 y PR-AUC 0,43; el 30 y 31 de mayo de 2019
son fuera de muestra (modelo entrenado sin esos días).

**Demo con imagen** (modelo de ejemplo, el comportamiento anterior). Dos modos:

- **Solo imagen**: las features ERA5 se rellenan con sus valores típicos (mediana del entorno
  tornádico), para predecir con una sola entrada.
- **Híbrido**: la imagen más las features ERA5 ajustables con deslizadores.

El embedding de la imagen sale de Amazon Bedrock (Titan) si hay credenciales; si no, de un embedding
sintético determinista, para que la demostración no dependa de la nube. La probabilidad se dibuja
en un mapa Leaflet con el estilo de «Mapa del modelo», sobre la imagen y la grilla del centro-sur/austral.

Es una demostración con un modelo de ejemplo: no sustituye un pronóstico operativo.
"""

import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import streamlit as st

from viewer_app import alerts, theme

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "model" / "demo"

# Región del centro-sur/austral (lat/lon de la grilla).
NORTH, SOUTH, WEST, EAST = -30.0, -56.0, -76.0, -66.0
GRID_RES = 0.25

ERA5_FEATURES = [
    "cape",
    "shear_01",
    "shear_03",
    "shear_06",
    "srh_01",
    "srh_03",
    "lcl",
    "gamma_03",
    "gamma_75",
    "vgp_01",
    "stp_lm",
    "sherbs3",
]
ERA5_RANGES = {
    "cape": (0.0, 3000.0, 500.0),
    "shear_01": (0.0, 30.0, 10.0),
    "shear_03": (0.0, 40.0, 15.0),
    "shear_06": (0.0, 50.0, 20.0),
    "srh_01": (-400.0, 100.0, -100.0),
    "srh_03": (-600.0, 100.0, -150.0),
    "lcl": (0.0, 3000.0, 800.0),
    "gamma_03": (0.0, 10.0, 6.0),
    "gamma_75": (0.0, 10.0, 6.5),
    "vgp_01": (0.0, 0.5, 0.15),
    "stp_lm": (-3.0, 1.0, -0.5),
    "sherbs3": (0.0, 3.0, 1.0),
}

# Bucket público del equipo con las imágenes GOES de Chile y los días con tornado conocidos.
BUCKET = "mesocyclonic-test-data-20261015013924290100000003"


# --- Modelo v2 real: predicciones publicadas por scripts/app/infer_grid.py ---------------------
MODEL_SITE = os.environ.get(
    "FORECAST_DATA_URL", "https://d1m48zea07nk1y.cloudfront.net/resultados/sitio/days"
)
MODEL_LABEL = "XGBoost v2 · ERA5 + variables GOES (etiquetas reales)"


def _fetch_json(url: str) -> dict:
    """Descarga y decodifica un JSON por HTTPS."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 (URL fija del proyecto)
        return json.loads(r.read().decode("utf-8"))


@st.cache_data(show_spinner=False, ttl=600)
def _model_days() -> list[str]:
    """Días con predicción del modelo v2 publicada (``days/index.json``); vacío si no responde."""
    try:
        return list(_fetch_json(f"{MODEL_SITE}/index.json")["days"])
    except Exception:  # noqa: BLE001
        return []


@st.cache_data(show_spinner=False, ttl=600)
def _model_day(day: str) -> dict:
    """JSON del día (ejes, enteros 0–10000 por hora, eventos del catálogo e insignia del modelo)."""
    return _fetch_json(f"{MODEL_SITE}/{day}.json")


def _model_grid(payload: dict, hour: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Probabilidad (0–1, NaN sin dato) de la hora ``hour`` en la grilla del JSON, con sus ejes."""
    lat = np.array(payload["lats"], dtype=float)
    lon = np.array(payload["lons"], dtype=float)
    vals = payload["hours"][str(hour)]
    arr = np.array([np.nan if v is None else v / 10000 for v in vals], dtype=float)
    return arr.reshape(len(lat), len(lon)), lat, lon


def _nearest_scene(horas: list[str], hour: int) -> int:
    """Índice del barrido GOES más cercano a ``hour`` UTC (las horas vienen como HH:MM)."""
    mins = [int(h[:2]) * 60 + int(h[3:5]) for h in horas]
    return int(np.argmin([abs(m - (hour * 60 + 30)) for m in mins]))


@st.cache_data(show_spinner=False, ttl=600)
def _tornado_days() -> list[str]:
    """Días con tornado del catálogo que YA tienen GOES en el bucket (descubiertos dinámicamente).

    Así la lista crece sola cuando el equipo sube más días, sin tocar el código. Si falla la
    consulta, cae a una lista mínima conocida.
    """
    fallback = ["2019-05-30", "2019-05-31", "2019-06-13", "2019-10-28", "2018-03-22", "2018-09-30"]
    try:
        import datetime as _dt

        import fsspec
        import pandas as pd

        fs = fsspec.filesystem("s3", anon=True)
        goes = set()
        for p in fs.ls(f"{BUCKET}/goes_store", detail=False):
            with contextlib.suppress(ValueError):
                goes.add(_dt.date.fromisoformat(p.rstrip("/").split("/")[-1]))
        cat = pd.read_excel(ROOT / "data" / "tornados_chile.xlsx", sheet_name="Final_Table")
        dates = pd.to_datetime(cat["Date (Gregorian Calendar)"], errors="coerce").dt.date
        hours = pd.to_numeric(
            cat["Hour (UTC)"].astype(str).str.extract(r"(\d{1,2})", expand=False), errors="coerce"
        )
        days = {d for d, h in zip(dates, hours, strict=True) if pd.notna(d) and pd.notna(h)}
        avail = sorted(str(d) for d in (days & goes))
        return avail or fallback
    except Exception:  # noqa: BLE001
        return fallback


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


def _to_png(img: "Image.Image") -> bytes:  # noqa: F821
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
        bucket = (
            "noaa-goes19" if t >= _dt.datetime(2025, 4, 4, 15, tzinfo=_dt.UTC) else "noaa-goes16"
        )
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
    return (
        json.loads(f.read_text()) if f.exists() else {n: ERA5_RANGES[n][2] for n in ERA5_FEATURES}
    )


def _embedding(png: bytes, n_emb: int) -> tuple[np.ndarray, str]:
    """Embedding de la imagen: Bedrock Titan si hay credenciales; si no, sintético determinista."""
    try:
        import botocore.session

        cli = botocore.session.get_session().create_client(
            "bedrock-runtime", region_name="us-east-1"
        )
        body = json.dumps(
            {
                "inputImage": base64.b64encode(png).decode(),
                "embeddingConfig": {"outputEmbeddingLength": 1024},
            }
        )
        resp = cli.invoke_model(modelId="amazon.titan-embed-image-v1", body=body)
        return np.array(json.loads(resp["body"].read())["embedding"], dtype=float)[
            :n_emb
        ], "Bedrock Titan"
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


# Mapa del resultado con el mismo estilo que «Mapa del modelo» (scripts/app/prototype.py del sitio):
# Leaflet sobre OpenStreetMap, celdas de 0,25° en la escala viridis de cinco tramos, leyenda al costado
# y los colores del tema activo del visor. La imagen GOES va como capa que se puede apagar.
_MAP_HTML = """<!DOCTYPE html><html lang="es" data-theme="__THEME__"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
 integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
 integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
 :root{--bg:#FFFFFF;--ink:#0E1A2C;--muted:#465463;--line:#BDD4D6;--accent:#376284;--field:#EFF8F9}
 :root[data-theme="dark"]{--bg:#1D3557;--ink:#F1FAEE;--muted:#A9B8BE;--line:#475C75;--accent:#A8DADC;--field:#2C4362}
 html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.4 "IBM Plex Sans",system-ui,sans-serif}
 main{display:flex;height:100%;border:1px solid var(--line);border-radius:6px;overflow:hidden;box-sizing:border-box}
 #map{flex:1;background:var(--bg)}
 aside{width:230px;overflow:auto;border-left:1px solid var(--line);padding:12px;box-sizing:border-box}
 h2{font-size:15px;margin:0 0 8px} .disc{font-size:13px;color:var(--muted);margin:6px 0}
 .legend span{display:inline-block;width:38px;height:14px} .legend small{display:flex;justify-content:space-between;width:190px}
 :root[data-theme="dark"] .leaflet-bar a,:root[data-theme="dark"] .leaflet-control-layers,
 :root[data-theme="dark"] .leaflet-tooltip{background:var(--field);color:var(--ink);border-color:var(--line)}
 :root[data-theme="dark"] .leaflet-control-attribution{background:rgba(29,53,87,.8);color:var(--muted)}
 :root[data-theme="dark"] .leaflet-control-attribution a{color:var(--accent)}
</style></head><body><main>
<div id="map" aria-label="Mapa de probabilidad por área"></div>
<aside><h2>Leyenda (%)</h2><div class="legend" id="legend"></div>
<p class="disc">Probabilidad por celda de 0,25°. Pasa el cursor sobre una celda para ver su valor.</p>
<p class="disc" id="stats"></p>
<p class="disc">Usa el control de capas (arriba a la derecha) para mostrar u ocultar la imagen GOES.</p></aside>
</main><script>
const D=__DATA__;
const COLORS=["#440154","#3b528b","#21918c","#5ec962","#fde725"];
const color=v=>COLORS[Math.min(4,Math.floor(v/20))];
document.getElementById("legend").innerHTML=COLORS.map(c=>`<span style="background:${c}"></span>`).join("")+
 "<small>"+[0,20,40,60,80,100].map(x=>`<b>${x}</b>`).join("")+"</small>";
document.getElementById("stats").textContent=`Mínimo ${D.min.toFixed(1)} % · máximo ${D.max.toFixed(1)} %`;
const map=L.map("map",{preferCanvas:true}).fitBounds(D.bounds);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:9,attribution:"© OpenStreetMap"}).addTo(map);
const goes=L.imageOverlay(D.image,D.bounds,{opacity:.55}).addTo(map);
const cells=L.layerGroup().addTo(map), half=D.step/2;
D.prob.forEach((v,i)=>{if(v===null||v<1)return;
 const la=D.lats[Math.floor(i/D.lons.length)], lo=D.lons[i%D.lons.length];
 L.rectangle([[la-half,lo-half],[la+half,lo+half]],{stroke:false,fillColor:color(v),fillOpacity:.65})
  .bindTooltip(`${v.toFixed(1)} %`).addTo(cells);});
L.control.layers(null,{"Imagen GOES":goes,"Probabilidad":cells},{collapsed:false}).addTo(map);
</script></body></html>"""


def _map_html(png: bytes, prob: np.ndarray, lat: np.ndarray, lon: np.ndarray, dark: bool) -> str:
    """Mapa Leaflet del resultado, con el estilo de «Mapa del modelo»: imagen GOES + probabilidad."""
    pct = np.round(prob * 100, 1)
    data = {
        "image": "data:image/png;base64," + base64.b64encode(png).decode(),
        "bounds": [[SOUTH, WEST], [NORTH, EAST]],
        "lats": [float(x) for x in lat],
        "lons": [float(x) for x in lon],
        "step": GRID_RES,
        "prob": [None if not np.isfinite(v) else float(v) for v in pct.ravel()],
        "min": float(np.nanmin(pct)),
        "max": float(np.nanmax(pct)),
    }
    return _MAP_HTML.replace("__THEME__", "dark" if dark else "light").replace(
        "__DATA__", json.dumps(data, separators=(",", ":"))
    )


def _alert_ui(prob: np.ndarray, lat: np.ndarray, lon: np.ndarray, origen: str) -> None:
    """Revisa el umbral, envía la alerta por correo y muestra el resultado (viewer_app/alerts.py)."""
    with st.spinner("Revisando el umbral y enviando la alerta por correo…"):
        aviso = alerts.alert(np.nan_to_num(prob, nan=0.0), lat, lon, GRID_RES, origen)
    if aviso is None:
        st.info(f"Ninguna celda supera el {alerts.threshold() * 100:.0f} %: no se envió alerta.")
        return
    z = aviso["spot"]
    donde = (
        f"{z['prob'] * 100:.1f} % en latitud {z['lat']:.2f}, longitud {z['lon']:.2f}, "
        f"{alerts.place_text(z['place'])}"
    )
    if aviso["sent"]:
        st.success(
            f"Alerta enviada por correo ({donde}) a: " + ", ".join(aviso["sent"]),
            icon=":material/mail:",
        )
    for to, err in aviso["failed"].items():
        st.warning(f"No se pudo enviar a {to}: {err}")
    with st.expander("Ver el recorte enviado (OpenStreetMap)"):
        st.image(aviso["png"], caption=f"Zona sobre el umbral · máximo {donde}")


def _csv_button(prob: np.ndarray, lat: np.ndarray, lon: np.ndarray, name: str) -> None:
    """Botón para descargar la probabilidad por celda en CSV."""
    import pandas as pd

    la, lo = np.meshgrid(lat, lon, indexing="ij")
    df = pd.DataFrame({"latitude": la.ravel(), "longitude": lo.ravel(), "prob": prob.ravel()})
    st.download_button(
        "Descargar CSV (probabilidad por área)",
        df.dropna().to_csv(index=False).encode(),
        name,
        "text/csv",
    )


def _real_model() -> None:
    """Predicción del modelo v2 real para un día con tornado y una hora UTC."""
    days = _model_days()
    if not days:
        st.warning(
            "No se pudo leer las predicciones publicadas del modelo v2; usa la demo con imagen."
        )
        return
    c1, c2 = theme.columns([1, 1], "real_cols")
    with c1:
        default = days.index("2019-05-30") if "2019-05-30" in days else len(days) - 1
        day = st.selectbox("Día con tornado (predicción del modelo v2)", days, index=default)
        payload = _model_day(day)
        hours = sorted(int(h) for h in payload["hours"])
        best = max(hours, key=lambda h: np.nanmax([v or 0 for v in payload["hours"][str(h)]]))
        hour = st.select_slider(
            "Hora UTC", options=hours, value=best, format_func=lambda h: f"{h:02d} UTC"
        )
    with c2:
        st.markdown(f"**Modelo:** {MODEL_LABEL}")
        st.caption(payload.get("badge", ""))
        ev = payload.get("events", [])
        if ev:
            st.markdown("**Tornados del catálogo ese día**")
            for e in ev:
                st.caption(
                    f"{e.get('type', 'Evento')} · {e.get('hour', '')} UTC · {e.get('place', '')}"
                )
        else:
            st.caption("Sin eventos del catálogo ese día.")

    prob, lat, lon = _model_grid(payload, hour)
    real = _goes_real(day)
    if real is not None:
        raw, horas = real
        png = _goes_image(raw, _nearest_scene(horas, hour))
        origen = f"modelo v2 · {day} {hour:02d} UTC (GOES C13 {horas[_nearest_scene(horas, hour)]})"
    else:
        from PIL import Image

        png = _to_png(Image.fromarray(np.full((224, 224, 3), 40, "uint8")))
        origen = f"modelo v2 · {day} {hour:02d} UTC (sin imagen GOES en el bucket)"

    import streamlit.components.v1 as components

    components.html(_map_html(png, prob, lat, lon, theme.is_dark()), height=600)
    st.caption(
        f"{origen} · máximo {np.nanmax(prob) * 100:.1f} % · índice relativo, no calibrado ni "
        "pronóstico oficial. Los tornados del catálogo se ven en «Mapa del modelo»."
    )
    if st.button("Revisar umbral y enviar alerta", type="primary"):
        _alert_ui(prob, lat, lon, origen)
    _csv_button(prob, lat, lon, f"probabilidades_{day}_{hour:02d}UTC.csv")


# Sitio del día completo «solo GOES» (rama merge/datos-modelo: infer_grid.py --era5-typical y
# prototype.py, publicado con «make publish-goes»): el XGBoost híbrido real con las 12 variables ERA5
# fijas en la mediana del entorno tornádico, así que el mapa solo cambia con las imágenes GOES.
GOES_DAY_URL = "https://d1m48zea07nk1y.cloudfront.net/resultados/sitio_goes/index.html"


def _day_view() -> None:
    """Día completo hora a hora con el modelo real, usando solo las imágenes GOES."""
    import os

    st.caption(
        "Predicción del **XGBoost híbrido real** para cada hora del día, con las imágenes GOES de "
        "esa hora y las variables ERA5 **fijas en valores típicos** (mediana del entorno tornádico). "
        "Sirve para días recientes, como ayer, que todavía no tienen ERA5. Se pierde la información "
        "del entorno (~80 % del peso del modelo): el mapa muestra «dónde las nubes se parecen a las "
        "de una tormenta severa», no la favorabilidad completa. Elige el día y mueve la hora; los "
        "tornados del catálogo aparecen en su hora."
    )
    url = os.environ.get("GOES_DAY_URL", GOES_DAY_URL)
    themed = f"{url}?theme={'dark' if theme.is_dark() else 'light'}"
    st.iframe(themed, height=760)
    st.link_button("Abrir el mapa en pantalla completa", themed, icon=":material/open_in_new:")


def page() -> None:
    """Dibuja la página «Predecir»."""
    st.title("Predecir")
    vista = st.radio(
        "Modelo",
        [
            "Modelo v2 entrenado (días con tornado)",
            "Día completo hora a hora (solo GOES)",
            "Demo con imagen (modelo de ejemplo)",
        ],
        horizontal=True,
    )
    if vista.startswith("Día completo"):
        _day_view()
        return
    if vista.startswith("Modelo v2"):
        st.caption(
            "Predicción real del XGBoost v2 (ERA5 + variables GOES), entrenado con los tornados del "
            "catálogo. Elige el día y la hora UTC."
        )
        _real_model()
        return
    st.caption(
        "Toma una imagen GOES real de Chile (o sube una) y el modelo estima la probabilidad "
        "de tornado por área. Demostración con un modelo de ejemplo; no es un pronóstico operativo."
    )

    modo = st.radio(
        "Modo", ["Solo imagen (ERA5 típica)", "Híbrido (imagen + ERA5)"], horizontal=True
    )
    solo = modo.startswith("Solo")

    c1, c2 = theme.columns([1, 1], "predict_cols")
    with c1:
        from PIL import Image

        fuente = st.radio(
            "Imagen de entrada",
            ["GOES en vivo (hoy)", "GOES real de Chile (bucket)", "Subir archivo"],
            horizontal=True,
        )
        img = None
        origen = fuente
        if fuente.startswith("GOES en vivo"):
            with st.spinner("Bajando la imagen GOES más reciente de Chile…"):
                vivo = _goes_tiempo_real()
            if vivo is None:
                st.warning("No se pudo obtener la imagen en vivo; usa otra fuente.")
                img = Image.fromarray(np.zeros((224, 224, 3), "uint8"))
            else:
                png_vivo, etiqueta = vivo
                img = Image.open(io.BytesIO(png_vivo)).convert("RGB")
                origen = f"GOES-East C13 · {etiqueta}"
                st.caption(f"{origen} · tope de nubes sobre el centro-sur/austral")
        elif fuente.startswith("GOES real"):
            dia = st.selectbox("Día con tornado (GOES disponible)", _tornado_days())
            real = _goes_real(dia)
            if real is None:
                st.warning(f"No hay GOES para {dia} en el bucket.")
                img = Image.fromarray(np.zeros((224, 224, 3), "uint8"))
            else:
                raw, horas = real
                hidx = st.select_slider(
                    "Hora UTC del barrido",
                    options=list(range(len(horas))),
                    format_func=lambda i: horas[i],
                    value=min(len(horas) - 1, len(horas) * 4 // 5),
                )
                img = Image.open(io.BytesIO(_goes_image(raw, hidx))).convert("RGB")
                origen = f"GOES-16 C13 · {dia} {horas[hidx]} UTC"
                st.caption(f"{origen} (tope de nubes)")
        else:
            up = st.file_uploader("Imagen GOES (PNG/JPG)", type=["png", "jpg", "jpeg"])
            if up is not None:
                img = Image.open(up).convert("RGB")
                origen = f"archivo subido ({up.name})"
            else:
                st.info("Sin imagen: se usa una de ejemplo.")
                img = Image.fromarray(
                    (np.random.default_rng(0).random((224, 224, 3)) * 255).astype("uint8")
                )
        # Placeholder: aquí se muestra la imagen y, al predecir, se reemplaza por el mapa de probabilidad.
        visor = st.empty()
        visor.image(img, width=260)

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
        # La predicción reemplaza la imagen en el mismo lugar (no aparece abajo), con el estilo del
        # «Mapa del modelo».
        import streamlit.components.v1 as components

        with visor.container():
            components.html(_map_html(png, prob, lat, lon, theme.is_dark()), height=600)
        st.caption(
            f"Probabilidad por área sobre la imagen · min {prob.min():.2f} / máx {prob.max():.2f} · "
            f"embedding: {source}"
        )

        # Alerta por correo si alguna celda supera el umbral (viewer_app/alerts.py).
        with st.spinner("Revisando el umbral y enviando la alerta por correo…"):
            aviso = alerts.alert(prob, lat, lon, GRID_RES, origen)
        if aviso is None:
            st.info(
                f"Ninguna celda supera el {alerts.threshold() * 100:.0f} %: no se envió alerta."
            )
        else:
            z = aviso["spot"]
            donde = (
                f"{z['prob'] * 100:.1f} % en latitud {z['lat']:.2f}, longitud {z['lon']:.2f}, "
                f"{alerts.place_text(z['place'])}"
            )
            if aviso["sent"]:
                st.success(
                    f"Alerta enviada por correo ({donde}) a: " + ", ".join(aviso["sent"]),
                    icon=":material/mail:",
                )
            for to, err in aviso["failed"].items():
                st.warning(f"No se pudo enviar a {to}: {err}")
            with st.expander("Ver el recorte enviado (OpenStreetMap)"):
                st.image(aviso["png"], caption=f"Zona sobre el umbral · máximo {donde}")

        import pandas as pd

        rows = [
            {"latitude": float(lat[i]), "longitude": float(lon[j]), "prob": float(prob[i, j])}
            for i in range(len(lat))
            for j in range(len(lon))
        ]
        df = pd.DataFrame(rows)
        st.download_button(
            "Descargar CSV (probabilidad por área)",
            df.to_csv(index=False).encode(),
            "probabilidades.csv",
            "text/csv",
        )
