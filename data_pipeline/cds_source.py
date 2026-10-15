"""Lee ERA5 del CDS (Copernicus) desde un bucket S3 público y lo normaliza al formato del proyecto.

El bucket de datos "buenos" guarda ERA5 recortado a Chile vía el CDS: pesa pocos MB por día (el
recorte lo hace el servidor), a diferencia de NSF-NCAR que obliga a bajar el globo entero. Pero el
CDS usa **otros nombres** de variables y dimensiones que ``process_era5.hourly_indices``:

| concepto            | CDS                 | lo que espera el proyecto |
|---------------------|---------------------|---------------------------|
| nivel de presión    | ``pressure_level``  | ``level``                 |
| tiempo              | ``valid_time``      | ``time``                  |
| viento 10 m         | ``u10`` / ``v10``   | ``10u`` / ``10v``         |
| temperatura 2 m     | ``t2m``             | ``2t``                    |
| punto de rocío 2 m  | ``d2m``             | ``2d``                    |

Este módulo baja los dos NetCDF del día (presión y superficie) con acceso anónimo
(``--no-sign-request`` / ``anon=True``) y devuelve datasets ya renombrados, listos para
``hourly_indices``. No descarga nada del bucket NSF-NCAR.
"""

from __future__ import annotations

import datetime as dt
import io

import fsspec
import xarray as xr

# Renombrados CDS -> formato del proyecto.
PL_RENAME = {"pressure_level": "level", "valid_time": "time"}
SFC_RENAME = {
    "valid_time": "time",
    "u10": "10u",
    "v10": "10v",
    "t2m": "2t",
    "d2m": "2d",
}


def _open_s3(url: str) -> xr.Dataset:
    """Abre un NetCDF en S3 con acceso anónimo (bucket público de datos abiertos)."""
    fs = fsspec.filesystem("s3", anon=True)
    with fs.open(url, "rb") as f:
        return xr.load_dataset(io.BytesIO(f.read()))


def load_day(bucket: str, day: dt.date, prefix: str = "era5_cds") -> tuple[xr.Dataset, xr.Dataset]:
    """Devuelve ``(pl, sfc)`` del día, normalizados al formato que esperan los índices.

    ``bucket`` sin ``s3://``. Busca ``<prefix>/<AAAA-MM-DD>/era5_pl_AAAAMMDD.nc`` y ``..._sfc_...``.
    """
    base = f"{bucket}/{prefix}/{day:%Y-%m-%d}"
    stamp = f"{day:%Y%m%d}"
    pl = _open_s3(f"{base}/era5_pl_{stamp}.nc")
    sfc = _open_s3(f"{base}/era5_sfc_{stamp}.nc")
    # Renombrar solo las claves presentes (dimensiones o variables).
    pl = pl.rename({k: v for k, v in PL_RENAME.items() if k in pl.variables or k in pl.dims})
    sfc = sfc.rename({k: v for k, v in SFC_RENAME.items() if k in sfc.variables or k in sfc.dims})
    return pl, sfc


def available_days(bucket: str, prefix: str = "era5_cds") -> list[dt.date]:
    """Días con ERA5 CDS disponibles en el bucket (carpetas ``<prefix>/<AAAA-MM-DD>/``)."""
    fs = fsspec.filesystem("s3", anon=True)
    out: list[dt.date] = []
    for p in fs.ls(f"{bucket}/{prefix}", detail=False):
        name = p.rstrip("/").split("/")[-1]
        try:
            out.append(dt.date.fromisoformat(name))
        except ValueError:
            continue
    return sorted(out)
