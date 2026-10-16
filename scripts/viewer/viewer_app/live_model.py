"""Predicción en vivo con el modelo v2 real (XGBoost ``physical``: índices ERA5 + variables GOES).

Para una hora ``t`` (UTC) baja de NOAA las bandas C08 y C13 de GOES-East de ``t-4`` a ``t`` (lo que
necesitan las variables GOES y sus rezagos t-1..t-3), las reproyecta a lat/lon con los mismos
scripts del pipeline, calcula las Variables_GOES sobre la grilla ERA5 de 0,25° de la región y corre
el modelo con ``sm_job/inference.py`` (la misma ruta que SageMaker). Las variables ERA5 salen de:

- ``"tipico"``: fijas en la mediana del entorno tornádico (``models/v2_physical/era5_typical.json``),
  así que el mapa solo cambia con la imagen GOES. Sirve para cualquier hora, incluida la actual.
- ``"real"``: los índices ERA5 del día (``data/crops/<región>/era5_indices``) si están en el visor;
  si no (ERA5 llega con ~5 días de retraso), se usan los típicos y se avisa.

El modelo no usa embeddings de imagen, así que no llama a Bedrock: el costo es solo la descarga de
GOES (pública) y unos segundos de cómputo.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
for _p in ("scripts", "scripts/model"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

import extract_goes_features as egf  # noqa: E402
import table as tb  # noqa: E402
from sm_job import inference  # noqa: E402

import common  # noqa: E402

MODEL_DIR = ROOT / "models" / "v2_physical"
TYPICAL = MODEL_DIR / "era5_typical.json"
REGION = "south-central-austral"
GRID_STEP = 0.25
GOES_WINDOW_DEG = 0.25  # ventana de las Variables_GOES, la misma del entrenamiento
HISTORY_H = 4  # horas previas que necesitan las variables GOES (t-1) y sus rezagos (t-3)
MODEL_LABEL = "XGBoost v2 (ERA5 + variables GOES, etiquetas reales del catálogo)"


def grid() -> tuple[np.ndarray, np.ndarray]:
    """Grilla ERA5 de 0,25° de la región, de norte a sur y de oeste a este."""
    reg = common.REGIONS[REGION]
    lat = np.round(np.arange(reg.north, reg.south - GRID_STEP / 2, -GRID_STEP), 4)
    lon = np.round(np.arange(reg.west, reg.east + GRID_STEP / 2, GRID_STEP), 4)
    return lat, lon


def latest_hour(now: dt.datetime | None = None) -> dt.datetime:
    """Última hora UTC con imágenes GOES publicadas (hay ~15 min de latencia)."""
    now = now or dt.datetime.now(dt.UTC)
    t = (now - dt.timedelta(minutes=20)).replace(minute=0, second=0, microsecond=0)
    return t.replace(tzinfo=None)


def _goes_file(t: dt.datetime) -> Path:
    """Archivo GOES reproyectado a lat/lon de la hora ``t`` (UTC, sin zona)."""
    return common.CROPS / REGION / "goes_latlon" / f"{t:%Y%m%d}" / f"goes_{t:%Y%m%d%H}.nc"


def _run(script: str, *args: str) -> None:
    """Corre un script del pipeline con el mismo Python del visor."""
    cmd = [sys.executable, str(ROOT / "scripts" / "pipeline" / script), *args]
    subprocess.run(cmd, check=True, cwd=ROOT, capture_output=True, text=True, timeout=900)


def ensure_goes(t: dt.datetime, log: Callable[[str], object] = print) -> list[dt.datetime]:
    """Baja y reproyecta C08/C13 de ``t-4`` a ``t`` si faltan; devuelve las horas sin datos."""
    hours = [t - dt.timedelta(hours=k) for k in range(HISTORY_H, -1, -1)]
    by_day: dict[dt.date, list[int]] = {}
    for h in hours:
        if not _goes_file(h).exists():
            by_day.setdefault(h.date(), []).append(h.hour)
    for day, hs in by_day.items():
        log(f"Bajando GOES C08/C13 de NOAA: {day} {min(hs):02d}–{max(hs):02d} UTC…")
        _run(
            "download_goes.py", "--start", day.isoformat(), "--bands", "8", "13",
            "--hours", str(min(hs)), str(max(hs)), "--region", REGION,
        )  # fmt: skip
        _run("process_goes.py", "--start", day.isoformat(), "--region", REGION)
    return [h for h in hours if not _goes_file(h).exists()]


def goes_features(t: dt.datetime, lat: np.ndarray, lon: np.ndarray) -> pd.DataFrame:
    """Variables_GOES de ``t-3`` a ``t`` sobre la grilla (las horas previas son los rezagos)."""
    reader = egf.GoesReader(common.CROPS, REGION, egf.BANDS)
    hours = [t - dt.timedelta(hours=k) for k in range(3, -1, -1)]
    parts = [egf.to_frame(egf.hour_rows(reader, h, lat, lon, GOES_WINDOW_DEG / 2)) for h in hours]
    return pd.concat(parts, ignore_index=True)


def typical_values() -> dict:
    """Valores ERA5 típicos (mediana del entorno tornádico)."""
    return json.loads(TYPICAL.read_text())


def era5_frame(
    t: dt.datetime, lat: np.ndarray, lon: np.ndarray, mode: str
) -> tuple[pd.DataFrame, str]:
    """Tabla ERA5 de ``t-3`` a ``t`` y de dónde salió (``"real"`` o ``"tipico"``)."""
    if mode == "real":
        days = sorted({(t - dt.timedelta(hours=k)).date() for k in range(4)})
        files = [common.CROPS / REGION / "era5_indices" / f"era5_idx_{d:%Y%m%d}.nc" for d in days]
        if all(f.exists() for f in files):
            import xarray as xr

            parts = []
            for f in files:
                with xr.open_dataset(f, engine="h5netcdf") as ds:
                    v = [c for c in tb.ERA5_FEATURES if c in ds.data_vars]
                    parts.append(
                        ds[v].sel(latitude=lat, longitude=lon).to_dataframe().reset_index()
                    )
            df = pd.concat(parts, ignore_index=True)
            df["time"] = tb.utc(df["time"])
            return df, "real"
    values = typical_values()
    times = [t - dt.timedelta(hours=k) for k in range(3, -1, -1)]
    idx = pd.MultiIndex.from_product([times, lat, lon], names=tb.POINT)
    df = idx.to_frame(index=False)
    for v in tb.ERA5_FEATURES:
        df[v] = float(values[v])
    df["time"] = tb.utc(df["time"])
    return df, "tipico"


def predict(t: dt.datetime, mode: str = "tipico", log: Callable[[str], object] = print) -> dict:
    """Probabilidad del modelo v2 por celda para la hora ``t`` (UTC, sin zona).

    Devuelve ``prob`` (``len(lat)`` × ``len(lon)``), ``lat``, ``lon``, ``era5`` (de dónde salió
    ERA5), ``missing`` (horas GOES que no se pudieron bajar) y ``png`` (C13 de la hora ``t``).
    """
    missing = ensure_goes(t, log)
    if t in missing:
        raise RuntimeError(f"NOAA no tiene todavía imágenes GOES de {t:%Y-%m-%d %H} UTC")
    lat, lon = grid()
    log("Calculando las variables GOES y corriendo el modelo v2…")
    goes = goes_features(t, lat, lon)
    era5, source = era5_frame(t, lat, lon, mode)
    cells = tb.candidate_cells([pd.Timestamp(t, tz="UTC")], lat, lon)
    bundle = inference.model_fn(str(MODEL_DIR))
    df = tb.build(bundle.config, cells, era5, goes, None)
    pred = inference.predict_fn(df, bundle)
    pivot = pred.pivot_table(index="latitude", columns="longitude", values="probability")
    prob = pivot.reindex(index=lat, columns=lon).to_numpy()
    return {
        "prob": prob, "lat": lat, "lon": lon, "era5": source, "missing": missing,
        "png": c13_png(t), "time": t,
    }  # fmt: skip


def c13_png(t: dt.datetime) -> bytes:
    """PNG de la temperatura de brillo C13 de la hora ``t`` (frío = blanco), de norte a sur."""
    import xarray as xr
    from PIL import Image

    with xr.open_dataset(_goes_file(t), engine="h5netcdf") as ds:
        bt = ds["C13"].isel(time=-1).values.astype("f4")
        lats = ds["latitude"].values
    if lats[0] < lats[-1]:
        bt = bt[::-1]
    g = np.clip((303.15 - np.nan_to_num(bt, nan=303.15)) / (303.15 - 183.15), 0, 1)
    img = Image.fromarray((g * 255).astype("uint8"), "L").convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
