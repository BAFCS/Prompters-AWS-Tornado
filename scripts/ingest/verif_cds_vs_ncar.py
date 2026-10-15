#!/usr/bin/env python3
"""Verifica (A) hasta qué fecha reciente sirve CDS y (B) que un día común coincida con ncar.

A) Pide a CDS días recientes (2026-09-15, 2026-08-15) para ver hasta dónde llega ERA5T.
B) Baja por CDS el día 2026-05-20 (que ncar ya tiene en era5_store) y compara la temperatura
   media a 500 hPa entre ambas fuentes. Si la diferencia es pequeña (~<0.5 K), son equivalentes
   y CDS puede usarse para rellenar lo que falta sin "arruinar" el dataset.
"""

from __future__ import annotations

import cdsapi
import s3fs
import xarray as xr

BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
AREA = [-30, -76, -56, -66]
PL = ["1000", "850", "500"]

c = cdsapi.Client(quiet=True)


def pedir(d: str, out: str) -> None:
    """Baja de CDS un día (una variable, 3 niveles, 12:00 UTC) recortado a Chile."""
    y, m, day = d.split("-")
    c.retrieve(
        "reanalysis-era5-pressure-levels",
        {
            "product_type": ["reanalysis"],
            "variable": ["temperature"],
            "pressure_level": PL,
            "year": [y],
            "month": [m],
            "day": [day],
            "time": ["12:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": AREA,
        },
        out,
    )


# A) ¿hasta qué fecha reciente?
for d in ["2026-09-15", "2026-08-15"]:
    try:
        pedir(d, "/tmp/reciente.nc")
        print(f"CDS DISPONIBLE {d}")
        break
    except Exception as e:  # noqa: BLE001
        print(f"CDS NO {d}: {e!s:.90}")

# B) comparar día común 2026-05-20 (CDS vs ncar en S3)
pedir("2026-05-20", "/tmp/cds520.nc")
cds = xr.open_dataset("/tmp/cds520.nc")
fs = s3fs.S3FileSystem()
nc = xr.open_zarr(s3fs.S3Map(f"s3://{BUCKET}/era5_store/era5_20260520.zarr", s3=fs))

tdim = "valid_time" if "valid_time" in cds.dims else "time"
tc = float(cds["t"].sel(pressure_level=500).isel({tdim: 0}).mean())
tn = float(nc["t"].sel(level=500).isel(time=12).mean())
print(f"T500 medio CDS={tc:.2f}K  ncar={tn:.2f}K  dif={abs(tc - tn):.3f}K")
