#!/usr/bin/env python3
"""Reproyecta el ``goes_store`` de S3 (grilla fija del ABI) a la grilla lat/lon que usa el modelo.

El ``goes_store`` de la ingesta (``scripts/ingest/ingest_goes.py``) guarda **un archivo por banda y
por día** en la grilla fija del satélite::

    s3://<bucket>/goes_store/<AAAA-MM-DD>/goes_<AAAAMMDD>_<banda>.nc   (time, y, x) + lat/lon 2D

con ``time`` = los 144 barridos del día (uno cada 10 min) y cada banda codificada en ``int16``
(``scale_factor``/``add_offset``, ``_FillValue = -1``). Este formato NO es el que consumen el
Extractor_GOES (``scripts/model/extract_goes_features.py``) ni el Compositor_RGB: ambos esperan los
recortes ya reproyectados a lat/lon y agrupados **por hora, con todas las bandas juntas**, como los
deja ``scripts/pipeline/process_goes.py``::

    data/crops/<region>/goes_latlon/<AAAAMMDD>/goes_<AAAAMMDDHH>.nc    (time, latitude, longitude)

Este script cierra ese hueco: lee las bandas del ``goes_store`` desde S3, reproyecta cada barrido a
una grilla lat/lon regular con la misma lógica de ``process_goes.py`` (vecino más cercano con un
KDTree sobre lat/lon del ABI, sin inventar valores ni corregir paralaje) y escribe un NetCDF por
hora con las bandas pedidas, preservando la codificación ``int16``. La salida queda lista para el
post-proceso del modelo sin tocar ``extract_goes_features.py``.

Se reutilizan ``grid``, ``nearest_index`` y ``reproject`` de ``process_goes`` (misma reproyección) y
las regiones y utilidades de ``common``. El acceso a S3 usa credenciales de la cuenta (el bucket de
destino es privado), a diferencia del acceso anónimo de ``common.s3`` a los Pools de Datos Abiertos.

Entrada y salida::

    s3://<bucket>/goes_store/<AAAA-MM-DD>/goes_<AAAAMMDD>_<banda>.nc   (grilla ABI)
    data/crops/<region>/goes_latlon/<AAAAMMDD>/goes_<AAAAMMDDHH>.nc    (grilla lat/lon regular)

Uso::

    uv run python scripts/pipeline/postprocess_goes_store.py --start 2019-04-03
    uv run python scripts/pipeline/postprocess_goes_store.py --start 2019-04-03 --bands C08 C13
    uv run python scripts/pipeline/postprocess_goes_store.py --start 2019-04-03 --max-scans 12 --force
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import numpy as np
import s3fs
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

# Se reutiliza tal cual la reproyección por vecino más cercano del pipeline histórico.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import process_goes as pg  # noqa: E402

# Bucket y prefijo de origen del data lake (los mismos que escribe scripts/ingest/ingest_goes.py).
# Se pueden sobreescribir por variables de entorno para apuntar a otro bucket sin tocar el código.
SRC_BUCKET = os.environ.get("DEST_BUCKET", "mesocyclonic-test-data-20261015013924290100000003")
SRC_PREFIX = os.environ.get("GOES_STORE_PREFIX", "goes_store")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bandas por defecto: las que necesita la receta ir_wv v1 y el Extractor_GOES (C13 ventana, C08 WV).
DEFAULT_BANDS = ("C08", "C13")

# Atributos de codificación que no deben quedar en los ``attrs`` de la variable escrita: se pasan por
# el ``encoding`` y h5netcdf rechaza la escritura si están en ambos lados.
CODING_ATTRS = frozenset({"scale_factor", "add_offset", "_FillValue"})


def dest_fs() -> s3fs.S3FileSystem:
    """``S3FileSystem`` con credenciales de la cuenta, fijado a la región del bucket privado."""
    return s3fs.S3FileSystem(client_kwargs={"region_name": AWS_REGION})


def store_key(day: dt.date, band: str) -> str:
    """Ruta ``s3://`` del archivo de una ``band`` del ``goes_store`` para ``day``."""
    return f"s3://{SRC_BUCKET}/{SRC_PREFIX}/{day:%Y-%m-%d}/goes_{day:%Y%m%d}_{band}.nc"


def open_band(fs: s3fs.S3FileSystem, day: dt.date, band: str) -> xr.Dataset | None:
    """Abre la banda ``band`` del día ``day`` sin decodificar; ``None`` si el archivo no existe.

    Se abre con ``mask_and_scale=False`` para conservar los enteros ``int16`` y su codificación, que
    se vuelve a aplicar idéntica al escribir la salida (así los valores no se alteran ni una vez).
    """
    key = store_key(day, band)
    if not fs.exists(key):
        return None
    buf = fs.open(key, "rb")
    return xr.open_dataset(buf, engine="h5netcdf", mask_and_scale=False)


def encodings(sources: dict[str, xr.Dataset], bands: list[str]) -> dict[str, dict]:
    """Codificación ``int16`` (escala, desfase, relleno) de cada banda, tomada de su archivo origen."""
    enc = {}
    for b in bands:
        da = sources[b][b]
        enc[b] = common.COMPRESSION | {
            "dtype": "int16",
            "scale_factor": float(np.asarray(da.attrs["scale_factor"]).ravel()[0]),
            "add_offset": float(np.asarray(da.attrs["add_offset"]).ravel()[0]),
            "_FillValue": int(np.asarray(da.attrs.get("_FillValue", -1)).ravel()[0]),
        }
    return enc


def reproject_scans(
    sources: dict[str, xr.Dataset],
    bands: list[str],
    idx: np.ndarray,
    valid: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    scans: slice,
) -> xr.Dataset:
    """Reproyecta los barridos ``scans`` de cada banda a la grilla (``lat``, ``lon``) regular.

    Para cada banda decodifica a kelvin, aplica el índice del vecino más cercano (``idx``) y pone NaN
    donde no hay píxel a tiro (``valid``). Devuelve un Dataset ``(time, latitude, longitude)`` con las
    bandas como ``float32``; la codificación ``int16`` se restituye al escribir.
    """
    data = {}
    first = sources[bands[0]]
    times = first["time"].values[scans]
    for b in bands:
        da = sources[b][b]
        scale = float(np.asarray(da.attrs["scale_factor"]).ravel()[0])
        offset = float(np.asarray(da.attrs["add_offset"]).ravel()[0])
        fill = int(np.asarray(da.attrs.get("_FillValue", -1)).ravel()[0])
        raw = np.asarray(da.values[scans])  # (n_scan, y, x) enteros
        bt = np.where(raw == fill, np.nan, raw * scale + offset).astype("f4")
        flat = bt.reshape(bt.shape[0], -1)[:, idx]  # (n_scan, lat, lon)
        flat[:, ~valid] = np.nan
        # Solo los atributos descriptivos: la escala, el desfase y el relleno vuelven por el encoding
        # (dejarlos también en attrs hace que h5netcdf rechace la escritura por clave duplicada).
        attrs = {k: v for k, v in da.attrs.items() if k not in CODING_ATTRS}
        data[b] = (("time", "latitude", "longitude"), flat, attrs)
    return xr.Dataset(
        data,
        coords={
            "time": times,
            "latitude": ("latitude", lat, {"units": "degrees_north"}),
            "longitude": ("longitude", lon, {"units": "degrees_east"}),
        },
        attrs=dict(first.attrs)
        | {"note": "reproyectado del goes_store a lat/lon por vecino más cercano (sin paralaje)"},
    )


def group_by_hour(times: np.ndarray) -> dict[int, list[int]]:
    """Agrupa los índices de ``times`` (``datetime64``) por hora UTC, en orden ascendente."""
    hours: dict[int, list[int]] = {}
    for k, t in enumerate(times):
        hour = int(np.datetime64(t, "h").item().hour)
        hours.setdefault(hour, []).append(k)
    return hours


def process_day(
    fs: s3fs.S3FileSystem,
    day: dt.date,
    reg: common.Region,
    bands: list[str],
    lat: np.ndarray,
    lon: np.ndarray,
    radius: float,
    max_scans: int | None,
    force: bool,
) -> int:
    """Reproyecta un día del ``goes_store`` y escribe un NetCDF por hora; devuelve las horas escritas.

    Abre las bandas pedidas desde S3, calcula una sola vez el índice del vecino más cercano (la grilla
    del ABI es fija), agrupa los barridos por hora y escribe ``goes_<AAAAMMDDHH>.nc`` con todas las
    bandas. ``max_scans`` limita los barridos leídos (para pruebas rápidas). Salta las horas ya
    escritas salvo ``force``.
    """
    sources: dict[str, xr.Dataset] = {}
    for b in bands:
        ds = open_band(fs, day, b)
        if ds is None:
            for opened in sources.values():
                opened.close()
            print(
                f"  aviso: {day}: falta la banda {b} en el goes_store; se omite el día", flush=True
            )
            return 0
        sources[b] = ds
    try:
        first = sources[bands[0]]
        lat_src = np.asarray(first["lat"].values)
        lon_src = np.asarray(first["lon"].values)
        idx, valid = pg.nearest_index(lat_src, lon_src, lat, lon, radius)
        times = first["time"].values
        if max_scans is not None:
            times = times[:max_scans]
        by_hour = group_by_hour(times)
        enc = encodings(sources, bands)
        dest = common.folder(reg.name, "goes_latlon") / f"{day:%Y%m%d}"
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for hour, scan_idx in sorted(by_hour.items()):
            out_file = dest / f"goes_{day:%Y%m%d}{hour:02d}.nc"
            if out_file.exists() and not force:
                continue
            lo, hi = scan_idx[0], scan_idx[-1] + 1
            out = reproject_scans(sources, bands, idx, valid, lat, lon, slice(lo, hi))
            out.attrs.update(common.stamp(reg))
            common.write(out, out_file, enc)
            written += 1
        return written
    finally:
        for ds in sources.values():
            ds.close()


def main() -> None:
    """Punto de entrada: reproyecta cada día pedido del ``goes_store`` de S3 a ``goes_latlon``."""
    p = common.parser(__doc__, "las horas")
    p.add_argument(
        "--bands",
        nargs="+",
        default=list(DEFAULT_BANDS),
        help="bandas a reproyectar (por defecto C08 C13, las que usan el modelo y la receta ir_wv)",
    )
    p.add_argument(
        "--resolution",
        type=float,
        default=0.02,
        help="paso de la grilla lat/lon en grados (por defecto 0,02 ≈ 2 km)",
    )
    p.add_argument(
        "--radius",
        type=float,
        default=0.05,
        help="distancia máxima al píxel más cercano, en grados",
    )
    p.add_argument(
        "--max-scans",
        type=int,
        default=None,
        help="limita los barridos leídos por día (para pruebas rápidas; por defecto todos)",
    )
    a = p.parse_args()
    reg = common.region_of(a)
    lat, lon = pg.grid(reg, a.resolution)
    fs = dest_fs()

    for day in common.days(a):
        t0 = time.time()
        n = process_day(fs, day, reg, a.bands, lat, lon, a.radius, a.max_scans, a.force)
        if n:
            print(
                f"{day}: {n} horas en {len(lat)} × {len(lon)} puntos "
                f"(bandas {', '.join(a.bands)}, {time.time() - t0:.0f} s)",
                flush=True,
            )
        elif n == 0:
            print(f"{day}: nada que escribir (ya existe o falta origen)", flush=True)


if __name__ == "__main__":
    main()
