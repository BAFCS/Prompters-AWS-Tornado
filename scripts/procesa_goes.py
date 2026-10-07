#!/usr/bin/env python3
"""Reproyecta los recortes GOES de la grilla fija del ABI a una grilla lat/lon regular.

La grilla fija del satélite es curva vista en lat/lon, y la mayoría de las herramientas (plotly,
el cruce con ERA5) esperan una grilla regular. Se usa vecino más cercano: cada punto de la grilla
nueva toma el valor del píxel GOES más próximo, así que los valores no se alteran ni se inventan.
Los puntos a más de ``--radio`` grados de cualquier píxel quedan vacíos. No se corrige paralaje.

Entrada y salida::

    data/recortes/<region>/goes/AAAAMMDD/goes_AAAAMMDDHH.nc          (time, y, x)
    data/recortes/<region>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc   (time, latitude, longitude)

Uso::

    uv run python scripts/procesa_goes.py --inicio 2019-05-30
    uv run python scripts/procesa_goes.py --inicio 2019-05-30 --resolucion 0.04
"""

import argparse
import time
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.spatial import KDTree

import comun


def grilla(reg: comun.Region, res: float) -> tuple[np.ndarray, np.ndarray]:
    """Latitudes (norte a sur) y longitudes (oeste a este) de la grilla regular de paso ``res``."""
    lat = np.round(np.arange(reg.norte, reg.sur - res / 2, -res), 6)
    lon = np.round(np.arange(reg.oeste, reg.este + res / 2, res), 6)
    return lat, lon


def indice(
    lat_src: np.ndarray, lon_src: np.ndarray, lat: np.ndarray, lon: np.ndarray, radio: float
) -> tuple[np.ndarray, np.ndarray]:
    """Para cada punto de la grilla (``lat``, ``lon``), el índice plano del píxel GOES más cercano.

    Las distancias se miden en grados con la longitud escalada por el coseno de la latitud media.
    Devuelve el índice y una máscara de los puntos que tienen un píxel a menos de ``radio`` grados.
    """
    k = np.cos(np.deg2rad(lat.mean()))
    ok = np.isfinite(lat_src.ravel()) & np.isfinite(lon_src.ravel())
    orig = np.flatnonzero(ok)
    arbol = KDTree(np.column_stack([lat_src.ravel()[ok], lon_src.ravel()[ok] * k]))
    LA, LO = np.meshgrid(lat, lon, indexing="ij")
    dist, i = arbol.query(np.column_stack([LA.ravel(), LO.ravel() * k]), distance_upper_bound=radio)
    valido = np.isfinite(dist)
    return orig[np.where(valido, i, 0)].reshape(LA.shape), valido.reshape(LA.shape)


def reproyecta(
    ds: xr.Dataset, idx: np.ndarray, valido: np.ndarray, lat: np.ndarray, lon: np.ndarray
) -> xr.Dataset:
    """Aplica el índice ``idx`` a cada banda de ``ds`` y devuelve el dataset en la grilla regular."""
    datos = {}
    for v, da in ds.data_vars.items():
        plano = da.values.reshape(da.sizes["time"], -1)[:, idx]
        plano[:, ~valido] = np.nan
        datos[v] = (("time", "latitude", "longitude"), plano.astype("f4"), da.attrs)
    return xr.Dataset(
        datos,
        coords={
            "time": ds["time"].values,
            "t_medio": ("time", ds["t_medio"].values),
            "latitude": ("latitude", lat, {"units": "degrees_north"}),
            "longitude": ("longitude", lon, {"units": "degrees_east"}),
        },
        attrs=ds.attrs
        | {"nota": ds.attrs.get("nota", "") + "; reproyectado a lat/lon por vecino más cercano"},
    )


def guarda(out: xr.Dataset, fuente: xr.Dataset, salida: Path) -> None:
    """Escribe ``out`` con la misma codificación entera (escala y desfase) que tenía ``fuente``."""
    enc = {}
    for v in out.data_vars:
        e = fuente[v].encoding
        enc[v] = comun.COMPRESION | {
            "dtype": "int16", "scale_factor": e["scale_factor"], "add_offset": e["add_offset"], "_FillValue": -1,
        }  # fmt: skip
    comun.escribe(out, salida, enc)


def main() -> None:
    """Punto de entrada: reproyecta cada hora descargada de cada día pedido."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    comun.args_fechas(p)
    comun.args_region(p)
    p.add_argument(
        "--resolucion",
        type=float,
        default=0.02,
        help="paso de la grilla en grados (por defecto 0,02 ≈ 2 km)",
    )
    p.add_argument(
        "--radio", type=float, default=0.05, help="distancia máxima al píxel más cercano, en grados"
    )
    p.add_argument("--forzar", action="store_true", help="rehace las horas que ya existen")
    a = p.parse_args()
    reg = comun.region_de(a)
    lat, lon = grilla(reg, a.resolucion)

    for dia in comun.dias(a):
        origen = comun.RECORTES / reg.nombre / "goes" / f"{dia:%Y%m%d}"
        horas = sorted(origen.glob("goes_*.nc"))
        if not horas:
            print(
                f"{dia}: sin recortes GOES en {origen} (corre antes descarga_goes.py)", flush=True
            )
            continue
        dest = comun.carpeta(reg.nombre, "goes_latlon") / f"{dia:%Y%m%d}"
        dest.mkdir(exist_ok=True)
        idx = valido = None
        t0 = time.time()
        for r in horas:
            salida = dest / r.name
            if salida.exists() and not a.forzar:
                continue
            with xr.open_dataset(r, engine="h5netcdf") as ds:
                if idx is None or valido is None:
                    idx, valido = indice(ds["lat"].values, ds["lon"].values, lat, lon, a.radio)
                guarda(reproyecta(ds.drop_vars(["lat", "lon"]), idx, valido, lat, lon), ds, salida)
        print(
            f"{dia}: {len(horas)} horas en {len(lat)} × {len(lon)} puntos ({time.time() - t0:.0f} s)",
            flush=True,
        )


if __name__ == "__main__":
    main()
