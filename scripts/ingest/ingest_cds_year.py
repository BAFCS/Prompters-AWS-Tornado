#!/usr/bin/env python3
"""Ingesta de una VENTANA DE UN AÑO de ERA5 recortado a Chile vía Copernicus CDS, con progreso.

Escala el experimento ``ingest_cds.py`` a un rango largo (por defecto un año). CDS impone un
límite de "costo" por petición: pedir un mes entero de una vez devuelve ``403 cost limits
exceeded``. Por eso se itera **por día** (una petición de niveles de presión + una de superficie
por día), que es lo que ya se validó que entra dentro del límite (~5,8 MB/día).

Salidas de AVANCE (lo que se pidió para seguir el progreso):

* Por ``stdout``: una línea por paso con el porcentaje acumulado, los MB bajados y el tiempo, por
  ejemplo ``[ 10/730]   1.4% | 2019-01-05 sfc | +1.1 MB | total 28.4 MB | 95 s``.
* Un ``progreso.json`` que se **sube a S3 tras cada paso** (``--progress-s3``), para consultar el
  avance en vivo desde fuera sin entrar a la instancia:
  ``{"hecho": 10, "total": 730, "porcentaje": 1.4, "mb": 28.4, "segundos": 95, "estado": "en curso"}``.

Es idempotente: si el archivo de un día ya está en S3, lo salta (``--skip-existing``, por defecto).
Si una petición falla, registra el error y sigue con el resto en vez de abortar todo.

Uso::

    python ingest_cds_year.py --year 2019
    python ingest_cds_year.py --start 2019-01 --end 2019-12 --progress-s3 s3://<bucket>/experimentos/progreso.json
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import sys
import time
from pathlib import Path

# Reutiliza la configuración del script de un día (área Chile, variables, niveles, bucket).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest_cds as one  # noqa: E402


def days_in_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Lista de días entre ``start`` y ``end`` inclusive."""
    n = (end - start).days
    return [start + dt.timedelta(days=i) for i in range(n + 1)]


def publish_progress(progress_s3: str, bucket: str, payload: dict) -> None:
    """Sube ``payload`` como ``progreso.json`` a S3 (ignora fallos para no romper la ingesta)."""
    if not progress_s3:
        return
    try:
        import boto3

        key = progress_s3.split(f"{bucket}/", 1)[1]
        boto3.client("s3", region_name=one.AWS_REGION).put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode(),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no se pudo subir progreso.json ({e!s:.120})", flush=True)


def key_exists(bucket: str, key: str) -> bool:
    """Devuelve si ``key`` ya existe en ``bucket`` (para saltar meses ya ingeridos)."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        try:
            boto3.client("s3", region_name=one.AWS_REGION).head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    """Punto de entrada: ingesta un año de ERA5 por meses, con progreso en stdout y en S3."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--year", type=int, help="año completo a ingestar, p. ej. 2019")
    p.add_argument("--start", help="mes inicial AAAA-MM (alternativa a --year)")
    p.add_argument("--end", help="mes final AAAA-MM inclusive (alternativa a --year)")
    p.add_argument("--bucket", default=one.BUCKET, help="bucket de destino")
    p.add_argument(
        "--prefix", default="era5_cds_year", help="prefijo S3 de salida (por defecto era5_cds_year)"
    )
    p.add_argument(
        "--progress-s3",
        default="",
        help="ruta s3:// del progreso.json (por defecto s3://<bucket>/experimentos/progreso.json)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="salta los meses cuyo archivo ya está en S3 (por defecto activado)",
    )
    p.add_argument("--output-dir", type=Path, default=Path("/tmp/era5_cds_year"))
    a = p.parse_args()

    if a.year:
        start = dt.date(a.year, 1, 1)
        end = dt.date(a.year, 12, 31)
    elif a.start and a.end:
        start = dt.date.fromisoformat(a.start + "-01")
        _ey, _em = int(a.end[:4]), int(a.end[5:7])
        end = dt.date(_ey, _em, calendar.monthrange(_ey, _em)[1])
    else:
        print("ERROR: usa --year AAAA o --start AAAA-MM --end AAAA-MM", file=sys.stderr)
        return 1

    progress_s3 = a.progress_s3 or f"s3://{a.bucket}/experimentos/progreso.json"

    try:
        import cdsapi

        client = cdsapi.Client()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: cliente CDS; revisa ~/.cdsapirc. {e!s:.200}", file=sys.stderr)
        return 1

    import boto3

    s3 = boto3.client("s3", region_name=one.AWS_REGION)

    day_list = days_in_range(start, end)
    # Cada día son 2 pasos (pl + sfc): así el porcentaje avanza más granular.
    steps = [(d, kind) for d in day_list for kind in ("pl", "sfc")]
    total = len(steps)
    done = 0
    total_mb = 0.0
    errors: list[str] = []
    t0 = time.time()

    print(
        f"Ingesta CDS de {start} a {end} | {len(day_list)} días | {total} pasos "
        f"(pl+sfc, por día para no exceder el cost limit del CDS) | área Chile {one.AREA_CHILE}",
        flush=True,
    )
    publish_progress(
        progress_s3,
        a.bucket,
        {
            "hecho": 0,
            "total": total,
            "porcentaje": 0.0,
            "mb": 0.0,
            "segundos": 0,
            "estado": "iniciando",
        },
    )

    for day, kind in steps:
        done += 1
        pct = 100.0 * done / total
        name = f"era5_{kind}_{day:%Y%m%d}.nc"
        key = f"{a.prefix}/{day:%Y}/{day:%m}/{name}"
        out_file = a.output_dir / f"{day:%Y}" / f"{day:%m}" / name

        if a.skip_existing and key_exists(a.bucket, key):
            elapsed = int(time.time() - t0)
            print(
                f"[{done:4d}/{total}] {pct:5.1f}% | {day} {kind} | ya existe, saltado "
                f"| total {total_mb:.1f} MB | {elapsed} s",
                flush=True,
            )
            publish_progress(
                progress_s3,
                a.bucket,
                {
                    "hecho": done,
                    "total": total,
                    "porcentaje": round(pct, 1),
                    "mb": round(total_mb, 1),
                    "segundos": elapsed,
                    "estado": "en curso",
                    "ultimo": f"{day} {kind} (saltado)",
                },
            )
            continue

        request = one.build_pl_request(day) if kind == "pl" else one.build_sfc_request(day)
        dataset = (
            "reanalysis-era5-pressure-levels" if kind == "pl" else "reanalysis-era5-single-levels"
        )
        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            seconds, mb = one.download_one(client, dataset, request, out_file)
            s3.upload_file(str(out_file), a.bucket, key)
            out_file.unlink(missing_ok=True)  # libera disco tras subir
            total_mb += mb
            elapsed = int(time.time() - t0)
            print(
                f"[{done:4d}/{total}] {pct:5.1f}% | {day} {kind} | +{mb:.1f} MB en {seconds:.0f}s "
                f"| total {total_mb:.1f} MB | {elapsed} s",
                flush=True,
            )
            publish_progress(
                progress_s3,
                a.bucket,
                {
                    "hecho": done,
                    "total": total,
                    "porcentaje": round(pct, 1),
                    "mb": round(total_mb, 1),
                    "segundos": elapsed,
                    "estado": "en curso",
                    "ultimo": f"{day} {kind}",
                    "errores": len(errors),
                },
            )
        except Exception as e:  # noqa: BLE001
            msg = f"{day} {kind}: {e!s:.160}"
            errors.append(msg)
            print(f"[{done:4d}/{total}] {pct:5.1f}% | ERROR {msg}", file=sys.stderr, flush=True)
            publish_progress(
                progress_s3,
                a.bucket,
                {
                    "hecho": done,
                    "total": total,
                    "porcentaje": round(pct, 1),
                    "mb": round(total_mb, 1),
                    "segundos": int(time.time() - t0),
                    "estado": "en curso con errores",
                    "errores": len(errors),
                    "ultimo_error": msg,
                },
            )

    elapsed = int(time.time() - t0)
    estado = "completo" if not errors else f"completo con {len(errors)} errores"
    print(
        f"\n=== FIN: {done}/{total} pasos | {total_mb:.1f} MB | {elapsed} s | {estado} ===",
        flush=True,
    )
    if errors:
        print("Errores:", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
    publish_progress(
        progress_s3,
        a.bucket,
        {
            "hecho": done,
            "total": total,
            "porcentaje": 100.0,
            "mb": round(total_mb, 1),
            "segundos": elapsed,
            "estado": estado,
            "errores": len(errors),
        },
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
