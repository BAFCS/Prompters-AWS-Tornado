"""Adaptador: trae los datos del bucket del equipo al formato que espera el preprocesamiento.

El bucket público (``era5_store`` + ``goes_store``) guarda ERA5 crudo en Zarr y GOES por día en la
grilla fija del ABI (lat/lon 2-D). Los scripts del modelo (``build_table``, ``extract_goes_features``)
esperan, en cambio, el formato del proyecto en ``data/crops/<region>/``:

* ``era5_indices/era5_idx_AAAAMMDD.nc`` — índices ya calculados (cizalladura, SRH, VGP, STP…).
* ``goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc`` — un archivo por hora, bandas C13/C08 en grilla
  lat/lon regular, codificadas con ``scale_factor``/``add_offset``.

Este módulo hace las dos conversiones, sin tocar la lógica de features ni el modelo:

1. **ERA5**: lee ``era5_store/era5_AAAAMMDD.zarr``, calcula los índices con
   ``process_era5.process_day`` y los escribe como ``era5_idx_AAAAMMDD.nc``.
2. **GOES**: lee ``goes_store/AAAA-MM-DD/goes_AAAAMMDD{,_C08}.nc`` (grilla ABI 2-D, ya decodificado),
   los **reproyecta a grilla regular** con ``process_goes`` y los parte por hora en
   ``goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc``, re-codificando a int16 (lo que espera el extractor).

Lee del bucket con acceso anónimo (``anon=True``); no requiere credenciales.

Uso:
    uv run python scripts/model/sync_from_bucket.py --bucket <bucket> --start 2019-05-30
    uv run python scripts/model/sync_from_bucket.py --bucket <bucket> --start 2025-10-15 --end 2025-10-17
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
from pathlib import Path

import fsspec
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

import process_era5 as pe  # noqa: E402
import process_goes as pg  # noqa: E402

import common  # noqa: E402

GOES_RES = 0.02  # paso de la grilla regular GOES en grados (~2 km), como en process_goes
GOES_RADIUS = 0.05  # radio máximo para el vecino más cercano
# El bucket ya trae BT decodificada en kelvin; se re-codifica a int16 con esta escala.
BT_SCALE = 0.01
BT_OFFSET = 250.0


def _open_zarr(bucket: str, day: dt.date) -> xr.Dataset:
    """Abre el día de ERA5 del store Zarr del bucket (acceso anónimo)."""
    m = fsspec.get_mapper(f"s3://{bucket}/era5_store/era5_{day:%Y%m%d}.zarr", anon=True)
    return xr.open_zarr(m)


def _open_goes_nc(bucket: str, day: dt.date, band_file: str) -> xr.Dataset | None:
    """Abre un NetCDF de ``goes_store`` del bucket, o None si no existe."""
    fs = fsspec.filesystem("s3", anon=True)
    key = f"{bucket}/goes_store/{day:%Y-%m-%d}/{band_file}"
    if not fs.exists(key):
        return None
    with fs.open(key, "rb") as f:
        return xr.load_dataset(io.BytesIO(f.read()))


def sync_era5(bucket: str, day: dt.date, region: str, force: bool) -> bool:
    """Calcula los índices ERA5 del día desde el Zarr del bucket y los guarda como era5_idx."""
    out_file = common.folder(region, "era5_indices") / f"era5_idx_{day:%Y%m%d}.nc"
    if out_file.exists() and not force:
        print(f"  ERA5 {day}: ya existe, se omite", flush=True)
        return True
    ds = _open_zarr(bucket, day).load()
    pl = ds[["u", "v", "t", "z"]]
    sfc = ds[[v for v in ("10u", "10v", "2t", "2d", "sp", "cape") if v in ds]]
    reg = common.REGIONS[region]
    idx = pe.process_day(pl, sfc, reg)
    # process_era5 usa CAPE internamente pero no lo escribe; build_table.ERA5_FEATURES sí lo espera.
    # Lo añadimos al índice desde el sfc, alineado al mismo eje temporal.
    if "cape" in sfc:
        cape = np.maximum(sfc["cape"].sel(time=idx["time"]).values, 0.0)
        idx["cape"] = (
            ("time", "latitude", "longitude"),
            cape.astype("f4"),
            {"long_name": "Convective available potential energy", "units": "J kg-1"},
        )
    common.write(idx, out_file)
    print(
        f"  ERA5 {day}: índices escritos ({dict(idx.sizes)}, cape={'sí' if 'cape' in idx else 'no'})",
        flush=True,
    )
    return True


def _reproject_band(ds_abi: xr.Dataset, band: str, reg: common.Region) -> xr.Dataset:
    """Reproyecta una banda del bucket (grilla ABI 2-D) a grilla regular lat/lon."""
    lat, lon = pg.grid(reg, GOES_RES)
    idx, valid = pg.nearest_index(ds_abi["lat"].values, ds_abi["lon"].values, lat, lon, GOES_RADIUS)
    out = pg.reproject(ds_abi[[band]], idx, valid, lat, lon)
    return out


def sync_goes(bucket: str, day: dt.date, region: str, force: bool) -> bool:
    """Reproyecta GOES del bucket y lo parte por hora en goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc."""
    out_dir = common.folder(region, "goes_latlon") / f"{day:%Y%m%d}"
    if out_dir.is_dir() and any(out_dir.glob("goes_*.nc")) and not force:
        print(f"  GOES {day}: ya existe, se omite", flush=True)
        return True

    # C13: tanda anual sin sufijo (goes_AAAAMMDD.nc) o archivo por banda (goes_AAAAMMDD_C13.nc).
    c13 = _open_goes_nc(bucket, day, f"goes_{day:%Y%m%d}.nc")
    if c13 is None:
        c13 = _open_goes_nc(bucket, day, f"goes_{day:%Y%m%d}_C13.nc")
    c08 = _open_goes_nc(bucket, day, f"goes_{day:%Y%m%d}_C08.nc")
    if c13 is None:
        print(f"  GOES {day}: sin archivo C13 en el bucket; se omite", flush=True)
        return False
    reg = common.REGIONS[region]

    # Reproyecta cada banda a grilla regular y las junta.
    bands: dict[str, xr.DataArray] = {}
    r13 = _reproject_band(c13, "C13", reg)
    bands["C13"] = r13["C13"]
    if c08 is not None:
        r08 = _reproject_band(c08, "C08", reg)
        bands["C08"] = r08["C08"]
    else:
        print(
            f"  GOES {day}: aviso, sin C08 (goes_wv_ir_max/cooling quedarán limitadas)", flush=True
        )

    merged = xr.Dataset(bands, coords=r13.coords)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Partir por hora: una imagen por barrido -> archivo de la hora de su inicio.
    # Se agrupa por una coordenada de hora derivada del tiempo (xarray no acepta un índice suelto).
    times = pd.to_datetime(merged["time"].values)
    hour_key = xr.DataArray(times.floor("h").values, dims="time", coords={"time": merged["time"]})
    written = 0
    for hour, group in merged.groupby(hour_key):
        hour_dt = pd.Timestamp(hour).to_pydatetime()
        enc = {}
        for v in group.data_vars:
            enc[v] = common.COMPRESSION | {
                "dtype": "int16", "scale_factor": BT_SCALE, "add_offset": BT_OFFSET, "_FillValue": -1,
            }  # fmt: skip
        out_file = out_dir / f"goes_{hour_dt:%Y%m%d%H}.nc"
        common.write(group, out_file, enc)
        written += 1
    print(f"  GOES {day}: {written} archivos horarios reproyectados", flush=True)
    return True


def main() -> None:
    """Punto de entrada: sincroniza ERA5 y/o GOES del bucket al formato del proyecto."""
    p = argparse.ArgumentParser(
        description="Trae datos del bucket del equipo al formato del modelo."
    )
    p.add_argument("--bucket", required=True, help="Bucket S3 público (sin s3://)")
    p.add_argument("--start", required=True, help="Primer día AAAA-MM-DD")
    p.add_argument("--end", default="", help="Último día AAAA-MM-DD (por defecto = start)")
    p.add_argument("--region", default="south-central-austral", help="Región de recorte")
    p.add_argument(
        "--only", choices=["era5", "goes", "both"], default="both", help="Qué sincronizar"
    )
    p.add_argument("--force", action="store_true", help="Recalcular aunque ya exista")
    a = p.parse_args()

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end) if a.end else start
    days = [start + dt.timedelta(days=k) for k in range((end - start).days + 1)]
    print(f"Sincronizando {len(days)} día(s) desde s3://{a.bucket} ({a.only})", flush=True)

    for day in days:
        print(f"{day}:", flush=True)
        try:
            if a.only in ("era5", "both"):
                sync_era5(a.bucket, day, a.region, a.force)
            if a.only in ("goes", "both"):
                sync_goes(a.bucket, day, a.region, a.force)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR en {day}: {e!r}", flush=True)


if __name__ == "__main__":
    main()
