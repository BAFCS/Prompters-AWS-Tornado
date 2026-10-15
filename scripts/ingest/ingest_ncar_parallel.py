#!/usr/bin/env python3
"""Orquestador PARALELO de la ingesta ncar->Zarr: varios días a la vez (alta intensidad).

Diagnóstico que justifica este orquestador: la EC2 que ejecuta ``ingest_ncar_zarr.py`` para un día
queda a ~6% de CPU; el cuello de botella es la **red** (lectura cross-region us-west-2 -> us-east-1
del bucket ``nsf-ncar-era5``), no el procesador. Por eso conviene lanzar **muchos días en paralelo**
en la misma instancia: mientras unos esperan datos de red, otros avanzan, y así se aprovecha el
ancho de banda sin saturar la CPU.

Cada día es independiente (no comparten estado), así que el paralelismo es seguro. Este script
lanza hasta ``--workers`` procesos ``ingest_ncar_zarr.py --date <día>`` a la vez sobre el rango
pedido, y publica un progreso agregado a S3 (``progreso_ncar.json``) con el formato que lee el panel.

Uso::

    python ingest_ncar_parallel.py --start 2025-10-15 --end 2026-09-30 --workers 12 \\
        --shard-index 0 --shard-total 1

``--shard-index``/``--shard-total`` permiten repartir el rango entre VARIAS instancias (flota):
cada instancia procesa los días cuyo índice ``% shard_total == shard_index``. Así se combina el
paralelismo intra-instancia (workers) con el inter-instancia (shards), sin que dos instancias
procesen el mismo día.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
AWS_REGION = "us-east-1"
SCRIPT = str(Path(__file__).resolve().parent / "ingest_ncar_zarr.py")
PY = sys.executable  # el mismo intérprete (venv 3.12)


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Días entre ``start`` y ``end`` inclusive."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def run_one_day(day_iso: str) -> tuple[str, bool, float]:
    """Ejecuta la ingesta de un día en un subproceso; devuelve ``(día, ok, segundos)``."""
    t0 = time.time()
    try:
        subprocess.run(
            [PY, SCRIPT, "--date", day_iso],
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        return day_iso, True, time.time() - t0
    except Exception:  # noqa: BLE001
        return day_iso, False, time.time() - t0


def publish(payload: dict) -> None:
    """Sube el progreso agregado a ``progreso_ncar.json`` (best-effort)."""
    try:
        import boto3

        boto3.client("s3", region_name=AWS_REGION).put_object(
            Bucket=BUCKET,
            Key="experimentos/progreso_ncar.json",
            Body=json.dumps(payload, ensure_ascii=False).encode(),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  aviso progreso: {e!s:.120}", flush=True)


def main() -> int:
    """Punto de entrada: reparte el rango en shards y corre ``--workers`` días en paralelo."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="día inicial AAAA-MM-DD")
    p.add_argument("--end", required=True, help="día final AAAA-MM-DD inclusive")
    p.add_argument("--workers", type=int, default=12, help="días en paralelo (red es el cuello)")
    p.add_argument("--shard-index", type=int, default=0, help="índice de esta instancia (0..N-1)")
    p.add_argument("--shard-total", type=int, default=1, help="número de instancias de la flota")
    a = p.parse_args()

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    all_days = date_range(start, end)
    # Esta instancia toma solo los días de su shard.
    days = [d for i, d in enumerate(all_days) if i % a.shard_total == a.shard_index]
    total = len(days)
    print(
        f"ncar PARALELO | shard {a.shard_index}/{a.shard_total} | {total} días | "
        f"{a.workers} workers | {start}..{end}",
        flush=True,
    )

    done = 0
    ok = 0
    t0 = time.time()
    times: list[float] = []
    publish({"fuente": "ncar", "dia_actual": 0, "dia_total": total, "hecho": 0, "total": total,
             "porcentaje": 0.0, "mb": 0.0, "segundos": 0.0, "estado": "en curso (paralelo)",
             "eta_segundos": 0.0, "workers": a.workers})

    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one_day, d.isoformat()): d for d in days}
        for fut in as_completed(futs):
            day_iso, success, secs = fut.result()
            done += 1
            if success:
                ok += 1
                times.append(secs)
            pct = 100.0 * done / total
            elapsed = time.time() - t0
            # ETA por ritmo real agregado (días/seg) considerando el paralelismo.
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            avg = sum(times) / len(times) if times else 0
            print(
                f"[{done:3d}/{total}] {pct:5.1f}% | {day_iso} {'ok' if success else 'FALLO'} "
                f"| medio/dia {avg:.0f}s | ETA {eta/60:.0f} min | ok={ok}",
                flush=True,
            )
            publish({"fuente": "ncar", "dia_actual": done, "dia_total": total, "hecho": done,
                     "total": total, "porcentaje": round(pct, 1), "mb": 0.0,
                     "segundos": round(elapsed, 1), "estado": "en curso (paralelo)",
                     "eta_segundos": round(eta, 1), "workers": a.workers,
                     "tiempo_medio_dia_s": round(avg, 1), "ok": ok, "fallos": done - ok})

    elapsed = time.time() - t0
    print(f"=== FIN ncar paralelo: {ok}/{total} días OK en {elapsed/60:.1f} min ===", flush=True)
    publish({"fuente": "ncar", "dia_actual": total, "dia_total": total, "hecho": total,
             "total": total, "porcentaje": 100.0, "mb": 0.0, "segundos": round(elapsed, 1),
             "estado": "completado", "eta_segundos": 0.0, "workers": a.workers,
             "ok": ok, "fallos": total - ok})
    return 0 if ok == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
