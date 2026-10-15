"""Orquestador de punta a punta: del bucket del equipo a la tabla lista para el modelo.

Pensado para correr en una EC2 (idealmente en ``us-east-1``, misma región que el bucket, donde la
descarga de S3 va a varios GB/s). Encadena, en orden, los componentes que ya existen en el repo y
reemplaza la descarga lenta de NSF-NCAR por el **adaptador del bucket** (``sync_from_bucket``):

1. ``sync_from_bucket``   — baja ERA5 (Zarr) y GOES del bucket y los deja en el formato del proyecto
                            (``era5_indices`` + ``goes_latlon``), **en paralelo** (``--workers``).
2. ``build_table select`` — etiqueta Celdas_Hora (positivos del catálogo + no etiquetadas) → cells.
3. ``compose_rgb``        — recorta GOES y compone un PNG por celda (solo si ``--embeddings``).
4. ``encode_bedrock``     — convierte cada PNG en un embedding de Bedrock (solo si ``--embeddings``).
5. ``build_table build``  — une índices ERA5 (+ embeddings) en la tabla final del modelo.

Modos:
- ``--config physical``   (por defecto): solo ERA5 + features GOES físicas. Rápido y garantizado.
- ``--config embeddings`` : agrega los embeddings de Bedrock (implica ``--embeddings``). Más lento,
                            pero en EC2 intra-región + paralelo es viable (~minutos).

Los días se toman del catálogo (los que tienen evento y están en el bucket) más una muestra de días
sin evento. Lee el bucket con acceso anónimo; Bedrock necesita credenciales con permiso de
``bedrock:InvokeModel``.

Ejemplos:
    # Solo ERA5 (seguro, rápido)
    uv run python scripts/model/run_pipeline.py --bucket <bucket> --config physical --workers 10

    # Con embeddings de Bedrock
    uv run python scripts/model/run_pipeline.py --bucket <bucket> --config embeddings --workers 10
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import fsspec
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SYNC = ROOT / "scripts" / "model" / "sync_from_bucket.py"
CATALOG = ROOT / "data" / "tornados_chile.xlsx"
REGION = "south-central-austral"


def _run(cmd: list[str], timeout: int | None = None) -> int:
    """Ejecuta un comando mostrando la línea; devuelve el código de salida."""
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, timeout=timeout).returncode


def _catalog_event_days() -> set[dt.date]:
    """Días con evento (con hora UTC) del catálogo."""
    d = pd.read_excel(CATALOG, sheet_name="Final_Table")
    dates = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    hours = pd.to_numeric(
        d["Hour (UTC)"].astype(str).str.extract(r"(\d{1,2})", expand=False), errors="coerce"
    )
    return {dd for dd, hh in zip(dates, hours, strict=True) if pd.notna(dd) and pd.notna(hh)}


def _bucket_days(bucket: str) -> list[dt.date]:
    """Días con ERA5 en el store Zarr del bucket."""
    fs = fsspec.filesystem("s3", anon=True)
    out: list[dt.date] = []
    for p in fs.ls(f"{bucket}/era5_store", detail=False):
        n = p.rstrip("/").split("/")[-1]
        if n.startswith("era5_") and n.endswith(".zarr"):
            with contextlib.suppress(ValueError):
                out.append(dt.datetime.strptime(n[5:13], "%Y%m%d").date())
    return sorted(out)


def _sync_one(bucket: str, day: dt.date, with_goes: bool) -> tuple[str, int]:
    """Sincroniza un día del bucket (ERA5 y, si procede, GOES). Para el pool paralelo."""
    only = "both" if with_goes else "era5"
    code = subprocess.run(
        [
            sys.executable,
            str(SYNC),
            "--bucket",
            bucket,
            "--start",
            day.isoformat(),
            "--region",
            REGION,
            "--only",
            only,
        ],
        cwd=ROOT,
        timeout=1800,
    ).returncode
    return (day.isoformat(), code)


def sync_bucket(bucket: str, days: list[dt.date], with_goes: bool, workers: int) -> None:
    """Paso 1: baja y adapta los días del bucket en paralelo."""
    print(
        f"[1/5] Sync bucket: {len(days)} días, {workers} en paralelo, GOES={with_goes}", flush=True
    )
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_sync_one, bucket, d, with_goes): d for d in days}
        for f in as_completed(futs):
            iso, code = f.result()
            print(f"   {'OK' if code == 0 else 'FALLO'} {iso}", flush=True)


def main() -> None:
    """Punto de entrada del orquestador."""
    p = argparse.ArgumentParser(description="Pipeline de punta a punta desde el bucket del equipo.")
    p.add_argument("--bucket", required=True, help="Bucket S3 público (sin s3://)")
    p.add_argument("--config", choices=("physical", "embeddings"), default="physical")
    p.add_argument("--workers", type=int, default=10, help="Descargas/sync en paralelo")
    p.add_argument(
        "--ratio", type=int, default=50, help="No etiquetadas por positiva (build_table select)"
    )
    p.add_argument("--max-neg-days", type=int, default=15, help="Días sin evento a incluir")
    p.add_argument("--recipe", default="ir_wv", help="Receta RGB (compose_rgb)")
    p.add_argument("--model", default="titan", help="Modelo de embeddings (encode_bedrock)")
    p.add_argument("--skip-sync", action="store_true", help="Saltar el paso 1 (datos ya locales)")
    a = p.parse_args()

    with_goes = a.config == "embeddings"
    event_days = sorted(_catalog_event_days() & set(_bucket_days(a.bucket)))
    neg_days = [d for d in _bucket_days(a.bucket) if d not in _catalog_event_days()][
        : a.max_neg_days
    ]
    days = sorted(set(event_days) | set(neg_days))
    if not days:
        raise SystemExit("No hay días del catálogo disponibles en el bucket todavía.")
    start, end = days[0].isoformat(), days[-1].isoformat()
    print(
        f"Días: {len(days)} ({len(event_days)} con evento, {len(neg_days)} negativos)", flush=True
    )

    model = ["uv", "run", "python"]

    # 1) Bucket -> formato local
    if not a.skip_sync:
        sync_bucket(a.bucket, days, with_goes, a.workers)

    # 2) Selección de celdas
    print("[2/5] build_table --stage select", flush=True)
    _run(
        [
            *model,
            "scripts/model/build_table.py",
            "--stage",
            "select",
            "--ratio",
            str(a.ratio),
            "--seed",
            "0",
            "--start",
            start,
            "--end",
            end,
            "--region",
            REGION,
        ]
    )

    # 3-4) RGB + embeddings (solo config embeddings)
    if with_goes:
        cells = f"data/model/{REGION}/cells.parquet"
        print("[3/5] compose_rgb", flush=True)
        _run(
            [
                *model,
                "scripts/model/compose_rgb.py",
                "--cells",
                cells,
                "--recipe",
                a.recipe,
                "--recipe-version",
                "1",
                "--size",
                "224",
                "--window-km",
                "100",
                "--start",
                start,
                "--end",
                end,
                "--region",
                REGION,
                "--force",
            ]
        )
        print("[4/5] encode_bedrock", flush=True)
        _run(
            [
                *model,
                "scripts/model/encode_bedrock.py",
                "--model",
                a.model,
                "--cache",
                "local",
                "--start",
                start,
                "--end",
                end,
                "--region",
                REGION,
                "--force",
            ]
        )
    else:
        print("[3-4/5] (omitido: config physical, sin embeddings)", flush=True)

    # 5) Tabla final
    print("[5/5] build_table --stage build", flush=True)
    _run(
        [
            *model,
            "scripts/model/build_table.py",
            "--stage",
            "build",
            "--config",
            a.config,
            "--start",
            start,
            "--end",
            end,
            "--region",
            REGION,
        ]
    )

    print("\n=== PIPELINE COMPLETO ===", flush=True)
    print(f"Tabla del modelo en data/model/{REGION}/ (config {a.config})", flush=True)
    print("Siguiente: entrenar con scripts/model/train_xgboost.py o loeo.py", flush=True)


if __name__ == "__main__":
    main()
