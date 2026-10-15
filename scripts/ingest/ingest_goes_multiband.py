#!/usr/bin/env python3
"""Orquestador GOES MULTI-BANDA: baja varias bandas ABI del año, en paralelo, con sharding.

Para la "tanda completa" de GOES se bajan varias bandas (no solo C13). Cada combinación
(banda, día) es independiente, así que se paralelizan con un pool de procesos y se reparten entre
instancias con `--shard-index/--shard-total`. Cada tarea invoca `ingest_goes.py --date <día>
--band <N> --skip-existing`, que escribe a `goes_store/<fecha>/goes_YYYYMMDD_CNN.nc`.

Bandas recomendadas para mesociclones (orden de valor):
  C13 (IR ventana, ya ingerida), C08/C09 (vapor de agua alto/medio), C02 (visible alta resolución).

Uso::

    python ingest_goes_multiband.py --start 2025-10-15 --end 2026-10-14 \\
        --bands 8 9 2 --workers 8 --shard-index 0 --shard-total 1
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BUCKET = os.environ.get("DEST_BUCKET", "mesocyclonic-test-data-20261015013924290100000003")
AWS_REGION = "us-east-1"
SCRIPT = str(Path(__file__).resolve().parent / "ingest_goes.py")
PY = sys.executable


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Días entre ``start`` y ``end`` inclusive."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def run_task(day_iso: str, band: int) -> tuple[str, int, bool, float]:
    """Baja un (día, banda) invocando ingest_goes.py; devuelve (día, banda, ok, segundos)."""
    t0 = time.time()
    try:
        subprocess.run(
            [PY, SCRIPT, "--date", day_iso, "--band", str(band), "--skip-existing"],
            check=True, capture_output=True, text=True, timeout=3600,
        )
        return day_iso, band, True, time.time() - t0
    except Exception:  # noqa: BLE001
        return day_iso, band, False, time.time() - t0


def publish(payload: dict) -> None:
    """Sube progreso agregado a progreso_goes_mb.json (best-effort)."""
    try:
        import boto3

        boto3.client("s3", region_name=AWS_REGION).put_object(
            Bucket=BUCKET, Key="experimentos/progreso_goes_mb.json",
            Body=json.dumps(payload, ensure_ascii=False).encode(),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  aviso progreso: {e!s:.120}", flush=True)


def main() -> int:
    """Reparte (banda × día) en shards y corre --workers tareas en paralelo."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", help="primer día del rango (AAAA-MM-DD); alternativa a --days-file")
    p.add_argument("--end", help="último día del rango (AAAA-MM-DD, inclusive)")
    p.add_argument(
        "--days-file",
        help="JSON con lista de días AAAA-MM-DD (bloques alrededor de eventos); "
        "alternativa a --start/--end",
    )
    p.add_argument("--bands", nargs="+", type=int, required=True, help="bandas ABI, p.ej. 8 9 2")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-total", type=int, default=1)
    a = p.parse_args()

    if a.days_file:
        with open(a.days_file) as f:
            days = sorted(dt.date.fromisoformat(s) for s in json.load(f))
    elif a.start and a.end:
        days = date_range(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    else:
        print("ERROR: usa --start/--end o --days-file", file=sys.stderr)
        return 1
    # Todas las combinaciones (día, banda), repartidas por shard.
    tasks = [(d.isoformat(), b) for d in days for b in a.bands]
    tasks = [t for i, t in enumerate(tasks) if i % a.shard_total == a.shard_index]
    total = len(tasks)
    print(f"GOES multibanda | shard {a.shard_index}/{a.shard_total} | bandas {a.bands} | "
          f"{len(days)} días | {total} tareas | {a.workers} workers", flush=True)

    done = ok = 0
    t0 = time.time()
    publish({"fuente": "goes_mb", "hecho": 0, "total": total, "porcentaje": 0.0,
             "estado": "en curso", "bandas": a.bands})

    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_task, d, b): (d, b) for d, b in tasks}
        for fut in as_completed(futs):
            d, b, success, secs = fut.result()
            done += 1
            ok += 1 if success else 0
            pct = 100.0 * done / total
            el = time.time() - t0
            eta = (total - done) / (done / el) if done and el else 0
            print(f"[{done:4d}/{total}] {pct:5.1f}% | {d} C{b:02d} {'ok' if success else 'FALLO'} "
                  f"| ETA {eta/60:.0f} min | ok={ok}", flush=True)
            publish({"fuente": "goes_mb", "hecho": done, "total": total,
                     "porcentaje": round(pct, 1), "segundos": round(el, 1),
                     "estado": "en curso", "eta_segundos": round(eta, 1),
                     "ok": ok, "fallos": done - ok, "bandas": a.bands})

    el = time.time() - t0
    print(f"=== FIN GOES multibanda: {ok}/{total} tareas OK en {el/60:.1f} min ===", flush=True)
    publish({"fuente": "goes_mb", "hecho": total, "total": total, "porcentaje": 100.0,
             "segundos": round(el, 1), "estado": "completado", "ok": ok,
             "fallos": total - ok, "bandas": a.bands})
    return 0 if ok == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
