"""Construye los datos de entrenamiento del modelo de tornados: muestreo + descarga paralela.

Este es el punto de entrada que tus compañeros corren directamente. Hace dos cosas, por separado:

1. **Plan de muestreo** (``--plan``): lee el catálogo, decide positivos (con vecindad que sigue al
   tornado) y días negativos estratificados, y escribe el manifiesto. No descarga nada.
2. **Materialización** (``--materialize``): para los días del manifiesto, descarga ERA5 y GOES
   **en paralelo** (varios días a la vez) y calcula las variables, reutilizando los scripts del
   proyecto (``scripts/pipeline``). Cachea los índices para no volver a descargar.

Pensado para probar primero con **un solo día** (``--start`` ... ``--end`` iguales, o ``--one-day``)
antes de escalar a toda la muestra.

Uso típico:

    # 1. Ver el plan de muestreo (sin descargar)
    uv run python data_pipeline/build_data.py --plan

    # 2. Probar la materialización con UN día
    uv run python data_pipeline/build_data.py --materialize --one-day 2019-05-30

    # 3. Materializar toda la muestra con 6 descargas en paralelo
    uv run python data_pipeline/build_data.py --materialize --workers 6
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sampling import (  # noqa: E402
    SampleConfig,
    event_days,
    negative_days_plan,
    positive_rows,
    summarize,
)

import common  # noqa: E402

OUT_DIR = ROOT / "data" / "model"
CATALOG = ROOT / "data" / "tornados_chile.xlsx"

# Prefijos en S3 donde se cachean los datos pesados ya procesados (reutilizables por el equipo).
S3_PREFIXES = {
    "era5_indices": "era5_indices",
    "era5_sfc": "data/crops/{region}/era5_sfc",
    "goes": "data/crops/{region}/goes",
}

# Solo las variables que usan los índices (ERA5) y las bandas útiles para severos (GOES).
ERA5_PL = ["u", "v", "t", "z"]
ERA5_SFC = ["10u", "10v", "2t", "2d", "sp", "cape"]
GOES_BANDS = ["13", "8", "2"]  # C13 tope (clave), C08 vapor de agua, C02 textura


def read_catalog(path: Path) -> pd.DataFrame:
    """Lee y normaliza el catálogo (fecha, lat, lon, hora UTC) reutilizando la lógica del visor."""
    d = pd.read_excel(path, sheet_name="Final_Table")
    d["date"] = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    d["lat"] = d["Latitude"].map(_coord)
    d["lon"] = d["Longitude"].map(_coord)
    d["hour_utc"] = pd.to_numeric(
        d["Hour (UTC)"].astype(str).str.extract(r"(\d{1,2})", expand=False), errors="coerce"
    )
    return d


def _coord(value: object) -> float:
    """Convierte una coordenada del catálogo (texto o número) a grados decimales con signo."""
    import numpy as np

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    s = str(value).strip().replace(",", ".")
    sign = -1.0 if any(c in s.upper() for c in ("S", "W", "O", "-")) else 1.0
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return sign * abs(float(digits))
    except ValueError:
        return float("nan")


def build_plan(cfg: SampleConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Construye el plan de muestreo (positivos + días negativos) y su resumen."""
    catalog = read_catalog(CATALOG)
    events = event_days(catalog)
    pos = positive_rows(events, cfg)
    neg_days = negative_days_plan(events, cfg)
    return pos, neg_days, summarize(pos, neg_days, cfg)


def _s3_sync_up(day: dt.date, region: str, bucket: str) -> None:
    """Sube a S3 los archivos del día ya procesados (índice ERA5, era5_sfc y recortes GOES)."""
    import fsspec

    fs = fsspec.filesystem("s3")
    stamp = f"{day:%Y%m%d}"
    uploads = [
        (common.folder(region, "era5_indices") / f"era5_idx_{stamp}.nc",
         f"{bucket}/era5_indices/era5_idx_{stamp}.nc"),
        (common.folder(region, "era5_sfc") / f"era5_sfc_{stamp}.nc",
         f"{bucket}/data/crops/{region}/era5_sfc/era5_sfc_{stamp}.nc"),
    ]
    goes_dir = common.folder(region, "goes") / stamp
    for local, key in uploads:
        if local.exists():
            fs.put(str(local), key)
    if goes_dir.is_dir():
        for f in goes_dir.glob("*.nc"):
            fs.put(str(f), f"{bucket}/data/crops/{region}/goes/{stamp}/{f.name}")


def _s3_has_index(day: dt.date, bucket: str) -> bool:
    """¿El índice ERA5 del día ya está cacheado en S3? (evita re-descargar ERA5)."""
    import fsspec

    fs = fsspec.filesystem("s3")
    return fs.exists(f"{bucket}/era5_indices/era5_idx_{day:%Y%m%d}.nc")


def _s3_pull_index(day: dt.date, region: str, bucket: str) -> None:
    """Baja desde S3 el índice ERA5 ya calculado del día."""
    import fsspec

    fs = fsspec.filesystem("s3")
    dest = common.folder(region, "era5_indices") / f"era5_idx_{day:%Y%m%d}.nc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fs.get(f"{bucket}/era5_indices/era5_idx_{day:%Y%m%d}.nc", str(dest))


def _materialize_day(day: dt.date, region: str, bucket: str = "") -> tuple[str, bool, str]:
    """Descarga ERA5 + GOES de un día, calcula variables y (si hay bucket) sube/reutiliza en S3.

    Cada día corre en su propio proceso (contexto spawn vía el pool): s3fs no tolera fork.
    Si el índice ya está en S3, lo reutiliza y evita la descarga pesada de ERA5.
    """
    iso = day.isoformat()
    idx_file = common.folder(region, "era5_indices") / f"era5_idx_{day:%Y%m%d}.nc"

    # Caché: si ya está en S3, lo bajamos y listo (no se re-descarga ERA5).
    if bucket and _s3_has_index(day, bucket):
        if not idx_file.exists():
            _s3_pull_index(day, region, bucket)
        return (iso, True, "reutilizado desde S3 (caché)")
    if idx_file.exists():
        if bucket:
            _s3_sync_up(day, region, bucket)
        return (iso, True, "índice local; subido a S3")
    try:
        subprocess.run(
            ["uv", "run", "python", "scripts/pipeline/download_era5.py", "--start", iso,
             "--region", region, "--pl", *ERA5_PL, "--sfc", *ERA5_SFC],
            check=True, timeout=900, cwd=ROOT,
        )
        subprocess.run(
            ["uv", "run", "python", "scripts/pipeline/process_era5.py", "--start", iso,
             "--region", region],
            check=True, timeout=180, cwd=ROOT,
        )
        subprocess.run(
            ["uv", "run", "python", "scripts/pipeline/download_goes.py", "--start", iso,
             "--region", region, "--bands", *GOES_BANDS],
            check=True, timeout=900, cwd=ROOT,
        )
        detail = "ERA5 + GOES listos"
        if bucket:
            _s3_sync_up(day, region, bucket)
            detail += " y subidos a S3"
        return (iso, True, detail)
    except subprocess.TimeoutExpired:
        return (iso, False, "timeout (descarga lenta)")
    except subprocess.CalledProcessError as e:
        return (iso, False, f"falló: {e}")


def materialize(days: list[dt.date], region: str, workers: int, bucket: str = "") -> None:
    """Descarga y procesa los ``days`` en paralelo (``workers`` a la vez), subiendo a S3 si hay bucket."""
    where = f", guardando en s3://{bucket}" if bucket else " (solo local)"
    print(f"Materializando {len(days)} día(s) con {workers} en paralelo{where}…", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_materialize_day, d, region, bucket): d for d in days}
        for fut in as_completed(futures):
            iso, ok, detail = fut.result()
            mark = "✓" if ok else "✗"
            print(f"  {mark} {iso}: {detail}", flush=True)


def main() -> None:
    """Punto de entrada de la CLI."""
    p = argparse.ArgumentParser(description="Construye los datos del modelo: muestreo + descarga paralela.")
    p.add_argument("--plan", action="store_true", help="Solo construir y guardar el plan de muestreo")
    p.add_argument("--materialize", action="store_true", help="Descargar y procesar los días del plan")
    p.add_argument("--one-day", type=str, default="", help="Materializar SOLO este día (AAAA-MM-DD), para probar")
    p.add_argument("--workers", type=int, default=6, help="Descargas en paralelo (por defecto 6)")
    p.add_argument("--s3-bucket", default="", help="Bucket S3 donde guardar/cachear (ej. mesocyclonic-dev-data-...)")
    p.add_argument("--region", default="south-central-austral", help="Región de recorte")
    p.add_argument("--neighbor", type=int, default=3, help="Lado de la vecindad espacial (celdas)")
    p.add_argument("--hours", type=int, default=2, help="Ventana temporal ±horas")
    p.add_argument("--ratio", type=int, default=10, help="Negativos por positivo")
    p.add_argument("--negative-days", type=int, default=25, help="Días sin evento a muestrear")
    a = p.parse_args()

    cfg = SampleConfig(
        neighbor=a.neighbor, hours=a.hours, ratio=a.ratio, negative_days=a.negative_days
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Siempre se construye el plan (es barato) para saber qué días materializar.
    pos, neg_days, summary = build_plan(cfg)
    pos.to_parquet(OUT_DIR / "positives.parquet", index=False)
    neg_days.to_parquet(OUT_DIR / "negative_days.parquet", index=False)
    print("Plan de muestreo:")
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)
    print(f"Manifiesto guardado en {OUT_DIR}", flush=True)

    if a.plan and not a.materialize:
        return

    if a.materialize:
        if a.one_day:
            days = [dt.date.fromisoformat(a.one_day)]
        else:
            pos_days = set(pos["day"])
            neg = set(neg_days["day"])
            days = sorted(pos_days | neg)
        materialize(days, a.region, a.workers, a.s3_bucket)


if __name__ == "__main__":
    main()
