#!/usr/bin/env python3
"""Capa curada analysis-ready: empareja ERA5 y GOES por celda-hora y la escribe como fuente NUEVA.

Genera, para cada día, una tabla **una fila por celda-hora** de la grilla ERA5 (0,25°, horaria), con:

- Las variables físicas de ERA5 (``era5_store/era5_YYYYMMDD.zarr``), muestreadas por nivel donde
  corresponde (geopotencial, temperatura y viento en niveles de presión; 10u/10v/2t/2d/sp/cape en
  superficie).
- Estadísticos de GOES por celda (``goes_store/<fecha>/goes_YYYYMMDD_CNN.nc``), **regrillando de fino
  a grueso**: los píxeles GOES de ~2 km que caen dentro de cada celda ERA5 de 0,25° se agregan a
  ``BT_min``, media, p10, p50 y fracción fría (<235/220/210 K) por banda. Para la banda IR ventana
  (C13) se añade además la tasa de enfriamiento ``dBT_min/dt`` entre horas consecutivas.
- Flags de calidad: ``goes_valid_frac`` (fracción de celdas con dato), banda ausente → columnas NaN
  (nunca 0), y un flag de terreno alto donde la presión de superficie es baja (Andes).

Reglas (ver ``docs/PROPUESTA_ENTRENAMIENTO.md``):

- **No destructivo**: solo LEE ``era5_store/`` y ``goes_store/`` y ESCRIBE en un prefijo nuevo
  (``curated/analysis_ready/``). Nunca toca las fuentes.
- **Fino a grueso**: GOES se agrega a la celda ERA5; jamás se interpola ERA5 hacia GOES.
- **NaN explícitos**: una banda ausente o un escaneo inválido deja NaN, no 0.
- **Idempotente**: salta los días cuyo Parquet ya está en el destino (``--force`` para rehacer).

Uso::

    uv run python scripts/model/match_era5_goes.py --date 2024-06-20
    uv run python scripts/model/match_era5_goes.py --start 2024-06-18 --end 2024-06-21
    uv run python scripts/model/match_era5_goes.py --date 2024-06-20 --no-upload --output-dir /tmp/cur

Lectura de las fuentes públicas: anónima (``--no-sign-request`` equivalente). Escritura al bucket:
con credenciales de la cuenta (o ``--no-upload`` para dejar el Parquet en local y revisarlo).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import s3fs
import xarray as xr

# --- Configuración -----------------------------------------------------------------------------

BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
ERA5_PREFIX = "era5_store"
GOES_PREFIX = "goes_store"
DEST_PREFIX = "curated/analysis_ready"  # prefijo NUEVO; no colisiona con las fuentes
AWS_REGION = "us-east-1"

# Bandas GOES que se intentan emparejar (si falta un archivo, sus columnas quedan NaN).
BANDS = (13, 8, 9, 10, 14, 15)
# Umbrales de "fracción fría" en K para la temperatura de brillo (topes convectivos).
COLD_THRESHOLDS = (235.0, 220.0, 210.0)
# Presión de superficie (Pa) bajo la cual se marca terreno alto (Andes); ~800 hPa.
HIGH_TERRAIN_SP = 80000.0


def s3_anon() -> s3fs.S3FileSystem:
    """Sistema de archivos S3 anónimo para LEER las fuentes públicas."""
    return s3fs.S3FileSystem(anon=True)


def open_era5(fs: s3fs.S3FileSystem, day: dt.date) -> xr.Dataset | None:
    """Abre el store Zarr de ERA5 del día, o ``None`` si no existe."""
    root = f"s3://{BUCKET}/{ERA5_PREFIX}/era5_{day:%Y%m%d}.zarr"
    try:
        mapper = s3fs.S3Map(root=root, s3=fs, check=False)
        return xr.open_zarr(mapper, consolidated=True)
    except Exception as e:  # noqa: BLE001
        print(f"  {day}: sin ERA5 ({e!s:.80})", flush=True)
        return None


def open_goes_band(fs: s3fs.S3FileSystem, day: dt.date, band: int) -> xr.Dataset | None:
    """Abre el NetCDF de GOES de una banda del día, o ``None`` si no existe/está vacío."""
    key = f"{BUCKET}/{GOES_PREFIX}/{day:%Y-%m-%d}/goes_{day:%Y%m%d}_C{band:02d}.nc"
    try:
        if not fs.exists(key):
            return None
        with fs.open(f"s3://{key}", "rb") as f:
            return xr.load_dataset(io.BytesIO(f.read()))
    except Exception as e:  # noqa: BLE001
        print(f"  {day}: banda C{band:02d} ilegible ({e!s:.60})", flush=True)
        return None


def cell_edges(centers: np.ndarray) -> np.ndarray:
    """Bordes de celda a partir de centros equiespaciados (para asignar píxeles a celdas)."""
    centers = np.asarray(centers, dtype=float)
    step = float(np.median(np.diff(np.sort(centers)))) if centers.size > 1 else 0.25
    edges = np.empty(centers.size + 1)
    order = np.argsort(centers)
    c = centers[order]
    edges[1:-1] = (c[:-1] + c[1:]) / 2.0
    edges[0] = c[0] - step / 2.0
    edges[-1] = c[-1] + step / 2.0
    return edges


def regrid_band_hourly(
    goes: xr.Dataset,
    band: int,
    lat_c: np.ndarray,
    lon_c: np.ndarray,
    hours: np.ndarray,
) -> dict[str, np.ndarray]:
    """Agrega los píxeles GOES de la banda a la grilla ERA5 (celda-hora), de fino a grueso.

    Devuelve un diccionario de arreglos ``(hora, lat, lon)`` con BT_min, media, p10, p50 y las
    fracciones frías. Píxeles fuera de rango o inválidos se ignoran; celdas sin píxel quedan NaN.
    """
    var = f"C{band:02d}"
    if var not in goes:
        return {}
    bt = goes[var].values  # (time, y, x)
    glat = goes["lat"].values  # 2D (y, x)
    glon = goes["lon"].values
    gtime = pd.to_datetime(goes["time"].values)

    nlat, nlon, nh = lat_c.size, lon_c.size, hours.size
    lat_edges = cell_edges(lat_c)
    lon_edges = cell_edges(lon_c)
    # Índice de celda de cada píxel (una vez; la grilla GOES es estática en el día).
    yi = np.digitize(glat.ravel(), np.sort(lat_edges)) - 1
    xi = np.digitize(glon.ravel(), np.sort(lon_edges)) - 1
    # digitize usa el orden ascendente; ERA5 lat suele ser descendente -> remapear.
    lat_desc = lat_c[0] > lat_c[-1]
    if lat_desc:
        yi = (nlat - 1) - yi
    valid_cell = (yi >= 0) & (yi < nlat) & (xi >= 0) & (xi < nlon)

    # Hora de cada escaneo GOES (0..23) para colapsar a la hora ERA5.
    scan_hour = gtime.hour.values

    out: dict[str, np.ndarray] = {}
    bt_min = np.full((nh, nlat, nlon), np.nan)
    bt_mean = np.full((nh, nlat, nlon), np.nan)
    bt_p10 = np.full((nh, nlat, nlon), np.nan)
    bt_p50 = np.full((nh, nlat, nlon), np.nan)
    cold = {thr: np.full((nh, nlat, nlon), np.nan) for thr in COLD_THRESHOLDS}

    flat_cell = np.where(valid_cell, yi * nlon + xi, -1)
    ncell = nlat * nlon
    for h in range(nh):
        sel = scan_hour == hours[h]
        if not sel.any():
            continue
        vals = bt[sel].reshape(sel.sum(), -1)  # (escaneos_de_la_hora, px)
        vals = vals.reshape(-1)
        cells = np.tile(flat_cell, sel.sum())
        ok = (cells >= 0) & np.isfinite(vals)
        if not ok.any():
            continue
        vals, cells = vals[ok], cells[ok]
        # Agregación por celda con bincount/agrupación.
        order = np.argsort(cells)
        vals, cells = vals[order], cells[order]
        uniq, start = np.unique(cells, return_index=True)
        groups = np.split(vals, start[1:])
        for cidx, grp in zip(uniq, groups, strict=False):
            yy, xx = divmod(int(cidx), nlon)
            bt_min[h, yy, xx] = np.min(grp)
            bt_mean[h, yy, xx] = np.mean(grp)
            bt_p10[h, yy, xx] = np.percentile(grp, 10)
            bt_p50[h, yy, xx] = np.percentile(grp, 50)
            n = grp.size
            for thr in COLD_THRESHOLDS:
                cold[thr][h, yy, xx] = np.mean(grp < thr)

    out[f"{var}_bt_min"] = bt_min
    out[f"{var}_bt_mean"] = bt_mean
    out[f"{var}_bt_p10"] = bt_p10
    out[f"{var}_bt_p50"] = bt_p50
    for thr in COLD_THRESHOLDS:
        out[f"{var}_frac_lt{int(thr)}"] = cold[thr]
    return out


def build_day_table(fs: s3fs.S3FileSystem, day: dt.date) -> pd.DataFrame | None:
    """Construye la tabla analysis-ready (una fila por celda-hora) para ``day``."""
    era5 = open_era5(fs, day)
    if era5 is None:
        return None
    lat_c = era5["latitude"].values
    lon_c = era5["longitude"].values
    hours = pd.to_datetime(era5["time"].values).hour.values
    nh, nlat, nlon = hours.size, lat_c.size, lon_c.size

    # Rejilla base de la tabla.
    H, LA, LO = np.meshgrid(hours, lat_c, lon_c, indexing="ij")
    tab = pd.DataFrame({
        "date": day.isoformat(),
        "hour_utc": H.ravel().astype(int),
        "lat": LA.ravel().astype(np.float32),
        "lon": LO.ravel().astype(np.float32),
    })

    # Variables ERA5 de superficie (una por celda-hora).
    for v in ("10u", "10v", "2t", "2d", "sp", "cape"):
        if v in era5:
            arr = era5[v].values  # (time, lat, lon)
            tab[f"era5_{v}"] = np.asarray(arr, dtype=np.float32).ravel()
    # Variables de nivel de presión: se toma 850 y 500 hPa como representativos (ambiente de capa
    # baja/media), si existen; el resto de niveles queda para una vista futura.
    if "level" in era5.dims:
        levels = list(era5["level"].values)
        for v in ("t", "u", "v", "z"):
            if v not in era5:
                continue
            for lv in (850, 500):
                if lv in levels:
                    arr = era5[v].sel(level=lv).values
                    tab[f"era5_{v}{lv}"] = np.asarray(arr, dtype=np.float32).ravel()

    # Flag de terreno alto (Andes): sp baja.
    if "era5_sp" in tab:
        tab["terreno_alto"] = (tab["era5_sp"] < HIGH_TERRAIN_SP).astype(np.int8)

    # GOES por banda.
    bands_present = 0
    for band in BANDS:
        g = open_goes_band(fs, day, band)
        var = f"C{band:02d}"
        if g is None or var not in g:
            # Banda ausente -> columnas NaN (se crean al final si ninguna banda las puso).
            continue
        bands_present += 1
        stats = regrid_band_hourly(g, band, lat_c, lon_c, hours)
        for name, arr in stats.items():
            tab[f"goes_{name}"] = np.asarray(arr, dtype=np.float32).ravel()
        g.close()

    # Tasa de enfriamiento del tope (C13) entre horas consecutivas, por celda.
    col = "goes_C13_bt_min"
    if col in tab:
        cube = tab[col].values.reshape(nh, nlat, nlon)
        d = np.full_like(cube, np.nan)
        d[1:] = cube[1:] - cube[:-1]
        tab["goes_C13_dbtmin_dt"] = d.ravel()

    # Fracción de celdas con dato GOES (calidad).
    if col in tab:
        valid = np.isfinite(tab[col].values)
        tab["goes_valid_frac"] = float(valid.mean())
    else:
        tab["goes_valid_frac"] = 0.0
    tab["goes_bands_present"] = bands_present

    era5.close()
    return tab


def write_table(tab: pd.DataFrame, day: dt.date, *, upload: bool, output_dir: Path) -> str:
    """Escribe la tabla como Parquet en el prefijo curado (S3) o en local si ``--no-upload``."""
    name = f"curated_{day:%Y%m%d}.parquet"
    key = f"{DEST_PREFIX}/{day:%Y}/{name}"
    if not upload:
        out = output_dir / f"{day:%Y}"
        out.mkdir(parents=True, exist_ok=True)
        path = out / name
        tab.to_parquet(path, index=False)
        return str(path)
    import boto3

    buf = io.BytesIO()
    tab.to_parquet(buf, index=False)
    buf.seek(0)
    boto3.client("s3", region_name=AWS_REGION).upload_fileobj(buf, BUCKET, key)
    return f"s3://{BUCKET}/{key}"


def dest_exists(day: dt.date) -> bool:
    """Indica si el Parquet del día ya está en el destino S3 (idempotencia)."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        key = f"{DEST_PREFIX}/{day:%Y}/curated_{day:%Y%m%d}.parquet"
        try:
            boto3.client("s3", region_name=AWS_REGION).head_object(Bucket=BUCKET, Key=key)
            return True
        except ClientError:
            return False
    except Exception:  # noqa: BLE001
        return False


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Días entre ``start`` y ``end`` inclusive."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def parse_args() -> argparse.Namespace:
    """Interpreta los argumentos de la línea de comandos."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--date", type=dt.date.fromisoformat, help="un solo día AAAA-MM-DD")
    p.add_argument("--start", type=dt.date.fromisoformat, help="primer día de un rango")
    p.add_argument("--end", type=dt.date.fromisoformat, help="último día (inclusive)")
    p.add_argument("--no-upload", action="store_true", help="escribe en --output-dir, no en S3")
    p.add_argument("--output-dir", type=Path, default=Path("data/curated"))
    p.add_argument("--force", action="store_true", help="rehace días cuyo Parquet ya está en S3")
    return p.parse_args()


def main() -> int:
    """Punto de entrada: construye la tabla curada por día y la escribe al prefijo nuevo."""
    a = parse_args()
    if a.date:
        days = [a.date]
    elif a.start and a.end:
        days = date_range(a.start, a.end)
    else:
        print("ERROR: usa --date o --start/--end", file=sys.stderr)
        return 1

    fs = s3_anon()
    hechos = 0
    for day in days:
        if not a.force and not a.no_upload and dest_exists(day):
            print(f"  {day}: ya existe en {DEST_PREFIX}/, saltado", flush=True)
            hechos += 1
            continue
        tab = build_day_table(fs, day)
        if tab is None or tab.empty:
            print(f"  {day}: sin datos (ERA5 ausente); saltado", flush=True)
            continue
        dest = write_table(tab, day, upload=not a.no_upload, output_dir=a.output_dir)
        hechos += 1
        print(
            f"  {day}: {len(tab):,} filas, {tab.shape[1]} columnas, "
            f"GOES válido {tab['goes_valid_frac'].iloc[0]:.0%} -> {dest}",
            flush=True,
        )
    print(f"listo: {hechos}/{len(days)} días", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
