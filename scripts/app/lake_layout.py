"""Constantes del Lago_Datos: el único lugar con los supuestos sobre la estructura de Nico.

Transcribe ``docs/DATOS_AWS.md`` y los scripts de ``scripts/ingest/`` (rama ``intentos-nico``):
prefijos y patrones de nombres en el bucket, variables, niveles de presión, renombres CDS→ncar y
la forma y codificación de GOES. También fija las rutas que espera el pipeline de Daniel
(``scripts/model/build_table.py`` y ``extract_goes_features.py``), relativas a
``data/crops/<región>/``.

``lake.py`` y ``adapter.py`` importan de aquí y no definen literales propios (Req. 9.15). Si Nico
cambia la estructura, se actualiza solo este módulo y la expectativa de
``tests/test_app_contracts.py``, después de confirmarlo con él.

Marcadores de los patrones (``str.format``): ``ymd`` = AAAAMMDD, ``iso`` = AAAA-MM-DD,
``yyyy`` = AAAA, ``mm`` = MM, ``hh`` = HH (UTC), ``kind`` ∈ {"pl", "sfc"} y ``band`` = nombre de
banda ABI (``"C08"``, ``"C13"``…).
"""

from __future__ import annotations

# --- Prefijos del bucket (docs/DATOS_AWS.md §2) -------------------------------------------------
ERA5_STORE_PREFIX = "era5_store"
ERA5_CDS_PREFIX = "era5_cds_year"
GOES_STORE_PREFIX = "goes_store"

# --- Patrones de rutas relativas al bucket -----------------------------------------------------
# ERA5 vía NSF NCAR: un Zarr por día con pl + sfc fusionados (ingest_ncar_zarr._zarr_store).
ERA5_STORE_PATTERN = "era5_store/era5_{ymd}.zarr"
# ERA5 vía Copernicus CDS: dos NetCDF por día (ingest_cds_year.main).
ERA5_CDS_PATTERN = "era5_cds_year/{yyyy}/{mm}/era5_{kind}_{ymd}.nc"
CDS_KINDS = ("pl", "sfc")
# GOES C13 de la tanda anual documentada en DATOS_AWS.md (un archivo por día, sin banda en el
# nombre). Es lo que hay hoy en el bucket para 2025-10-15 → 2026-09-30.
GOES_STORE_PATTERN = "goes_store/{iso}/goes_{ymd}.nc"
# GOES por banda (commit ec238df): ingest_goes.dest_path ahora escribe un archivo por banda y día,
# goes_<AAAAMMDD>_CNN.nc. Aún no figura en DATOS_AWS.md; se usa solo para bandas extra (p. ej. C08).
GOES_BAND_STORE_PATTERN = "goes_store/{iso}/goes_{ymd}_{band}.nc"

# --- ERA5 (DATOS_AWS.md §3; ingest_ncar_zarr.PL_VARS/SFC_VARS/PRESSURE_LEVELS_HPA) ---------------
LEVELS = (1000, 925, 850, 700, 500, 300)  # hPa
PL_VARS = ("u", "v", "t", "z")
SFC_VARS = ("10u", "10v", "2t", "2d", "sp", "cape")
DIMS = ("time", "level", "latitude", "longitude")
# CDS usa otros nombres de coordenadas y de variables de superficie (DATOS_AWS.md §5).
CDS_RENAME = {
    "valid_time": "time",
    "pressure_level": "level",
    "u10": "10u",
    "v10": "10v",
    "t2m": "2t",
    "d2m": "2d",
}
# Coordenadas auxiliares del NetCDF de CDS que no existen en el Zarr de ncar.
CDS_DROP = ("number", "expver")

# --- GOES (DATOS_AWS.md §3; ingest_goes.build_dataset/encoding) ---------------------------------
GOES_VAR = "C13"
GOES_DIMS = ("time", "y", "x")
GOES_SHAPE = (466, 882)  # (y, x) = 882 × 466 en la grilla fija del ABI, recorte Chile
GOES_FILL = -1  # _FillValue del int16 crudo
# Bandas que necesita la configuración "physical" de Daniel (extract_goes_features.BANDS).
# C08 solo existe si se corrió ingest_goes_multiband.py con --bands 8 (ver GUIA_GOES_PARALELO.md).
GOES_PHYSICAL_BANDS = ("C08", "C13")

# --- Salidas que espera el pipeline de Daniel (relativas a data/crops/<región>/) -----------------
ERA5_IDX_PATTERN = "era5_indices/era5_idx_{ymd}.nc"
GOES_LATLON_PATTERN = "goes_latlon/{ymd}/goes_{ymd}{hh}.nc"
GOES_RES = 0.02  # grados, paso de la grilla regular (process_goes.py --resolution)
