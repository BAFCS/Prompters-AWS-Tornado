"""Orquesta el entrenamiento en la nube: genera índices ERA5 de los días con evento y entrena.

Pensado para correr en la EC2 de entrenamiento (us-west-2, cerca de ERA5). Para cada día del
catálogo con un evento en la era de GOES-16 (desde dic-2017) y una muestra de días sin evento:

1. Descarga ERA5 (``download_era5.py``) y calcula los índices (``process_era5.py``). Cada script
   salta lo que ya existe, así que es seguro reintentar.
2. Llama a ``train_xgboost.py`` con la carpeta de índices y sube los resultados al prefijo S3.

Opciones para acotar el costo (ERA5 son ~12 GB de tráfico por día): ``--max-event-days`` limita
cuántos días con evento se procesan, y ``--unlabeled-days`` cuántos días sin evento se añaden como
no etiquetados.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import subprocess
import sys
from pathlib import Path

import fsspec
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

GOES16_START = dt.date(2017, 12, 1)  # inicio operacional de GOES-16 sobre Chile


def _read_catalog_days(catalog: str) -> list[dt.date]:
    """Días (ordenados, únicos) con evento en la era de GOES-16, leídos del catálogo en S3 o local."""
    with fsspec.open(catalog, "rb") as f:  # type: ignore[union-attr]
        raw = f.read()
    d = pd.read_excel(io.BytesIO(raw), sheet_name="Final_Table")
    dates = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date.dropna()
    days = sorted({x for x in dates if x >= GOES16_START})
    return days


def _run(cmd: list[str]) -> None:
    """Ejecuta un comando y aborta si falla."""
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def _generate_indices(day: dt.date, region: str) -> None:
    """Descarga ERA5 y calcula los índices de un día (salta lo ya hecho)."""
    iso = day.isoformat()
    _run(["uv", "run", "python", "scripts/pipeline/download_era5.py", "--start", iso, "--region", region])
    _run(["uv", "run", "python", "scripts/pipeline/process_era5.py", "--start", iso, "--region", region])


def main() -> None:
    """Punto de entrada: genera índices y entrena, todo en la nube."""
    p = argparse.ArgumentParser(description="Entrenamiento en la nube de XGBoost (índices + modelo).")
    p.add_argument("--catalog", required=True, help="Ruta o s3:// del tornados_chile.xlsx")
    p.add_argument("--out", required=True, help="Prefijo s3:// donde dejar los resultados")
    p.add_argument("--region", default="south-central-austral", help="Región de recorte")
    p.add_argument("--max-event-days", type=int, default=0, help="Límite de días con evento (0 = todos)")
    p.add_argument(
        "--unlabeled-days",
        type=int,
        default=0,
        help="Días extra SIN evento como no etiquetados (0 = ninguno; usa el muestreo interno)",
    )
    a = p.parse_args()

    event_days = _read_catalog_days(a.catalog)
    if a.max_event_days:
        event_days = event_days[: a.max_event_days]
    print(f"Días con evento a procesar: {len(event_days)}", flush=True)

    # Días sin evento, intercalados, para enriquecer los no etiquetados del PU learning.
    extra: list[dt.date] = []
    if a.unlabeled_days and event_days:
        step = max((event_days[-1] - event_days[0]).days // (a.unlabeled_days + 1), 1)
        cur = event_days[0]
        while len(extra) < a.unlabeled_days:
            cur = cur + dt.timedelta(days=step)
            if cur not in event_days and cur < dt.date.today():
                extra.append(cur)

    for day in [*event_days, *extra]:
        try:
            _generate_indices(day, a.region)
        except subprocess.CalledProcessError as e:
            print(f"  aviso: falló el día {day} ({e}); se omite", flush=True)

    indices_dir = str(common.folder(a.region, "era5_indices"))
    print(f"Entrenando con índices en {indices_dir}", flush=True)
    _run([
        "uv", "run", "python", "scripts/model/train_xgboost.py",
        "--indices", indices_dir,
        "--catalog", a.catalog,
        "--out", a.out,
    ])
    print("Entrenamiento en la nube completo.", flush=True)


if __name__ == "__main__":
    main()
