#!/usr/bin/env python3
"""Reproyecta los recortes GOES de la grilla fija del ABI a una grilla lat/lon regular.

La grilla fija del satélite es curva vista en lat/lon, y la mayoría de las herramientas (plotly,
el cruce con ERA5) esperan una grilla regular. Se usa vecino más cercano: cada punto de la grilla
nueva toma el valor del píxel GOES más próximo, así que los valores no se alteran ni se inventan.
Los puntos a más de ``--radius`` grados de cualquier píxel quedan vacíos. No se corrige paralaje.

Entrada y salida::

    data/crops/<region>/goes/AAAAMMDD/goes_AAAAMMDDHH.nc          (time, y, x)
    data/crops/<region>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc   (time, latitude, longitude)

Uso::

    uv run python scripts/pipeline/process_goes.py --start 2019-05-30
    uv run python scripts/pipeline/process_goes.py --start 2019-05-30 --resolution 0.04
"""

import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.spatial import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402


def grid(reg: common.Region, res: float) -> tuple[np.ndarray, np.ndarray]:
    """Latitudes (norte a sur) y longitudes (oeste a este) de la grilla regular de paso ``res``."""
    lat = np.round(np.arange(reg.north, reg.south - res / 2, -res), 6)
    lon = np.round(np.arange(reg.west, reg.east + res / 2, res), 6)
    return lat, lon


def nearest_index(
    lat_src: np.ndarray, lon_src: np.ndarray, lat: np.ndarray, lon: np.ndarray, radius: float
) -> tuple[np.ndarray, np.ndarray]:
    """Para cada punto de la grilla (``lat``, ``lon``), el índice plano del píxel GOES más cercano.

    Las distancias se miden en grados con la longitud escalada por el coseno de la latitud media.
    Devuelve el índice y una máscara de los puntos que tienen un píxel a menos de ``radius`` grados.
    """
    k = np.cos(np.deg2rad(lat.mean()))
    ok = np.isfinite(lat_src.ravel()) & np.isfinite(lon_src.ravel())
    orig = np.flatnonzero(ok)
    tree = KDTree(np.column_stack([lat_src.ravel()[ok], lon_src.ravel()[ok] * k]))
    LA, LO = np.meshgrid(lat, lon, indexing="ij")
    dist, i = tree.query(np.column_stack([LA.ravel(), LO.ravel() * k]), distance_upper_bound=radius)
    valid = np.isfinite(dist)
    return orig[np.where(valid, i, 0)].reshape(LA.shape), valid.reshape(LA.shape)


def reproject(
    ds: xr.Dataset, idx: np.ndarray, valid: np.ndarray, lat: np.ndarray, lon: np.ndarray
) -> xr.Dataset:
    """Aplica el índice ``idx`` a cada banda de ``ds`` y devuelve el dataset en la grilla regular."""
    data = {}
    for v, da in ds.data_vars.items():
        flat = da.values.reshape(da.sizes["time"], -1)[:, idx]
        flat[:, ~valid] = np.nan
        data[v] = (("time", "latitude", "longitude"), flat.astype("f4"), da.attrs)
    return xr.Dataset(
        data,
        coords={
            "time": ds["time"].values,
            "t_mid": ("time", ds["t_mid"].values),
            "latitude": ("latitude", lat, {"units": "degrees_north"}),
            "longitude": ("longitude", lon, {"units": "degrees_east"}),
        },
        attrs=ds.attrs
        | {"note": ds.attrs.get("note", "") + "; reproyectado a lat/lon por vecino más cercano"},
    )


def save(out: xr.Dataset, source: xr.Dataset, out_file: Path) -> None:
    """Escribe ``out`` con la misma codificación entera (escala y desfase) que tenía ``source``."""
    enc = {}
    for v in out.data_vars:
        e = source[v].encoding
        enc[v] = common.COMPRESSION | {
            "dtype": "int16", "scale_factor": e["scale_factor"], "add_offset": e["add_offset"], "_FillValue": -1,
        }  # fmt: skip
    common.write(out, out_file, enc)


def main() -> None:
    """Punto de entrada: reproyecta cada hora descargada de cada día pedido."""
    p = common.parser(__doc__, "las horas")
    p.add_argument(
        "--resolution",
        type=float,
        default=0.02,
        help="paso de la grilla en grados (por defecto 0,02 ≈ 2 km)",
    )
    p.add_argument(
        "--radius",
        type=float,
        default=0.05,
        help="distancia máxima al píxel más cercano, en grados",
    )
    a = p.parse_args()
    reg = common.region_of(a)
    lat, lon = grid(reg, a.resolution)

    for day in common.days(a):
        origin = common.CROPS / reg.name / "goes" / f"{day:%Y%m%d}"
        hours = sorted(origin.glob("goes_*.nc"))
        if not hours:
            print(
                f"{day}: sin recortes GOES en {origin} (corre antes download_goes.py)", flush=True
            )
            continue
        dest = common.folder(reg.name, "goes_latlon") / f"{day:%Y%m%d}"
        dest.mkdir(exist_ok=True)
        idx = valid = None
        t0 = time.time()
        for r in hours:
            out_file = dest / r.name
            if out_file.exists() and not a.force:
                continue
            with xr.open_dataset(r, engine="h5netcdf") as ds:
                if idx is None or valid is None:
                    idx, valid = nearest_index(
                        ds["lat"].values, ds["lon"].values, lat, lon, a.radius
                    )
                save(reproject(ds.drop_vars(["lat", "lon"]), idx, valid, lat, lon), ds, out_file)
        print(
            f"{day}: {len(hours)} horas en {len(lat)} × {len(lon)} puntos ({time.time() - t0:.0f} s)",
            flush=True,
        )


if __name__ == "__main__":
    main()
