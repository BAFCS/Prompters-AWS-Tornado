#!/usr/bin/env python3
"""Descarga ERA5 recortado a Chile desde el Climate Data Store (CDS) y lo sube a S3.

Este script es un experimento de ingesta alternativo a ``scripts/pipeline/download_era5.py``: en
vez de leer el bucket Open Data ``s3://nsf-ncar-era5/`` y recortar bloques globales en memoria,
usa el servicio CDS de Copernicus (paquete ``cdsapi``), que entrega el recuadro ya recortado en
el servidor. El recorte se limita a Chile con ``area=[Norte, Oeste, Sur, Este]`` (el orden que
exige CDS), es decir ``[-30, -76, -56, -66]``, equivalente a la región ``south-central-austral``
del proyecto.

Para un día dado (``--date AAAA-MM-DD``) baja dos archivos NetCDF:

* ``reanalysis-era5-pressure-levels``: ``u``, ``v``, ``t`` y ``z`` (geopotencial) en los niveles
  1000, 925, 850, 700, 500 y 300 hPa, las 24 horas.
* ``reanalysis-era5-single-levels``: ``10u``, ``10v``, ``2t``, ``2d``, ``sp`` y ``cape``, las
  24 horas.

Mide y reporta por ``stdout`` el tiempo de cada descarga, los MB de cada archivo y el tiempo
total; después sube ambos ``.nc`` a
``s3://mesocyclonic-test-data-20261015013924290100000003/era5_cds/<date>/`` con boto3.

Supuestos:

* ``~/.cdsapirc`` ya existe con la URL y la clave del CDS (no se gestionan credenciales aquí).
* Las credenciales de AWS están disponibles para boto3 (rol de instancia, perfil o variables de
  entorno); la cuenta solo permite ``us-east-1``.

Uso::

    python scripts/ingest/ingest_cds.py --date 2019-05-30
    python scripts/ingest/ingest_cds.py --date 2019-05-30 --output-dir /tmp/era5 --no-upload

No descarga automáticamente al importarse: todo ocurre bajo ``main()``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

# Región Chile del proyecto (south-central-austral). CDS exige el orden Norte, Oeste, Sur, Este.
AREA_CHILE: list[float] = [-30.0, -76.0, -56.0, -66.0]

# Niveles de presión en hPa que usa el modelo de mesociclones.
PRESSURE_LEVELS: list[str] = ["1000", "925", "850", "700", "500", "300"]

# Variables de niveles de presión (nombres largos del CDS).
PL_VARIABLES: list[str] = [
    "u_component_of_wind",
    "v_component_of_wind",
    "temperature",
    "geopotential",
]

# Variables de superficie (nombres largos del CDS) equivalentes a 10u, 10v, 2t, 2d, sp y cape.
SFC_VARIABLES: list[str] = [
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "2m_temperature",
    "2m_dewpoint_temperature",
    "surface_pressure",
    "convective_available_potential_energy",
]

# Las 24 horas en formato "HH:00".
HOURS: list[str] = [f"{h:02d}:00" for h in range(24)]

# Bucket de destino en AWS (cuenta 822870558093, solo us-east-1).
BUCKET: str = "mesocyclonic-test-data-20261015013924290100000003"
S3_PREFIX: str = "era5_cds"
AWS_REGION: str = "us-east-1"


def parse_args() -> argparse.Namespace:
    """Interpreta los argumentos de la línea de comandos."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        required=True,
        help="día a descargar en formato AAAA-MM-DD (UTC)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/era5_cds"),
        help="carpeta local donde se dejan los .nc (por defecto data/era5_cds)",
    )
    p.add_argument(
        "--bucket",
        default=BUCKET,
        help="bucket de destino en S3 (por defecto el del experimento)",
    )
    p.add_argument(
        "--no-upload",
        action="store_true",
        help="no sube a S3; solo descarga y reporta localmente",
    )
    return p.parse_args()


def megabytes(path: Path) -> float:
    """Tamaño de ``path`` en megabytes (base 1024)."""
    return path.stat().st_size / (1024 * 1024)


def build_pl_request(date: dt.date) -> dict[str, object]:
    """Arma el cuerpo de la petición de niveles de presión para ``date``."""
    return {
        "product_type": ["reanalysis"],
        "variable": PL_VARIABLES,
        "pressure_level": PRESSURE_LEVELS,
        "year": [f"{date:%Y}"],
        "month": [f"{date:%m}"],
        "day": [f"{date:%d}"],
        "time": HOURS,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA_CHILE,
    }


def build_sfc_request(date: dt.date) -> dict[str, object]:
    """Arma el cuerpo de la petición de niveles de superficie para ``date``."""
    return {
        "product_type": ["reanalysis"],
        "variable": SFC_VARIABLES,
        "year": [f"{date:%Y}"],
        "month": [f"{date:%m}"],
        "day": [f"{date:%d}"],
        "time": HOURS,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA_CHILE,
    }


def download_one(
    client: object, dataset: str, request: dict[str, object], out_file: Path
) -> tuple[float, float]:
    """Descarga ``dataset`` con ``request`` del CDS y lo escribe en ``out_file``.

    Devuelve ``(segundos, megabytes)`` del archivo bajado. Traduce los errores habituales del
    servicio (403 por licencia no aceptada o credenciales inválidas, y las esperas de cola) en
    mensajes claros, re-lanzando la excepción para que ``main`` termine con código distinto de 0.
    """
    out_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"CDS: pidiendo {dataset} -> {out_file.name}", flush=True)
    t0 = time.time()
    try:
        # ``retrieve`` encola la solicitud, espera a que el CDS la complete y descarga el archivo.
        client.retrieve(dataset, request, str(out_file))  # type: ignore[attr-defined]
    except Exception as e:  # cdsapi envuelve los errores HTTP en su propia jerarquía
        msg = str(e).lower()
        if "403" in msg or "forbidden" in msg or "required licence" in msg or "licence" in msg:
            print(
                f"ERROR 403 en {dataset}: credenciales inválidas en ~/.cdsapirc o licencia del "
                f"producto sin aceptar en el portal del CDS. Detalle: {e!s:.200}",
                file=sys.stderr,
                flush=True,
            )
        elif "queue" in msg or "queued" in msg or "timeout" in msg or "408" in msg:
            print(
                f"ERROR de cola/espera en {dataset}: la solicitud quedó encolada o expiró en el "
                f"CDS; reintenta más tarde. Detalle: {e!s:.200}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"ERROR descargando {dataset}: {e!s:.200}", file=sys.stderr, flush=True)
        raise
    seconds = time.time() - t0
    mb = megabytes(out_file)
    print(f"CDS: {out_file.name} listo en {seconds:.0f} s, {mb:.1f} MB", flush=True)
    return seconds, mb


def upload_to_s3(files: list[Path], bucket: str, date: dt.date) -> None:
    """Sube ``files`` a ``s3://<bucket>/era5_cds/<date>/`` con boto3.

    Traduce el 403 de S3 (sin permiso de ``PutObject`` o bucket en otra región) en un mensaje
    claro y re-lanza la excepción.
    """
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=AWS_REGION)
    for f in files:
        key = f"{S3_PREFIX}/{date:%Y-%m-%d}/{f.name}"
        print(f"S3: subiendo {f.name} -> s3://{bucket}/{key}", flush=True)
        try:
            s3.upload_file(str(f), bucket, key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "403", "Forbidden"}:
                print(
                    f"ERROR 403 subiendo {f.name}: el rol no tiene permiso de PutObject sobre "
                    f"s3://{bucket}/ o el bucket está en otra región. Detalle: {e!s:.200}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print(f"ERROR subiendo {f.name}: {e!s:.200}", file=sys.stderr, flush=True)
            raise
        print(f"S3: {f.name} subido", flush=True)


def main() -> int:
    """Punto de entrada: descarga los dos archivos del día, mide tiempos/MB y sube a S3."""
    args = parse_args()
    date: dt.date = args.date

    try:
        import cdsapi
    except ImportError:
        print(
            "ERROR: falta el paquete cdsapi. Instálalo con 'uv add cdsapi' o 'pip install cdsapi'.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    try:
        # El cliente lee la URL y la clave de ~/.cdsapirc; se asume que ya existe.
        client = cdsapi.Client()
    except Exception as e:  # falta ~/.cdsapirc o está mal formado
        print(
            f"ERROR: no se pudo crear el cliente CDS; revisa ~/.cdsapirc. Detalle: {e!s:.200}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    out_dir = args.output_dir / f"{date:%Y-%m-%d}"
    pl_file = out_dir / f"era5_pl_{date:%Y%m%d}.nc"
    sfc_file = out_dir / f"era5_sfc_{date:%Y%m%d}.nc"

    jobs = (
        ("reanalysis-era5-pressure-levels", build_pl_request(date), pl_file),
        ("reanalysis-era5-single-levels", build_sfc_request(date), sfc_file),
    )

    print(f"Ingesta CDS para {date:%Y-%m-%d}, área Chile {AREA_CHILE} (N,O,S,E)", flush=True)
    t_total = time.time()
    total_mb = 0.0
    files: list[Path] = []
    try:
        for dataset, request, out_file in jobs:
            _, mb = download_one(client, dataset, request, out_file)
            total_mb += mb
            files.append(out_file)
    except Exception:
        print("Ingesta abortada por un error en la descarga.", file=sys.stderr, flush=True)
        return 2

    elapsed = time.time() - t_total
    print(
        f"Descarga completa: {len(files)} archivos, {total_mb:.1f} MB en {elapsed:.0f} s "
        f"({total_mb / elapsed:.2f} MB/s)",
        flush=True,
    )

    if args.no_upload:
        print("Subida a S3 omitida (--no-upload).", flush=True)
        return 0

    try:
        upload_to_s3(files, args.bucket, date)
    except Exception:
        print("La subida a S3 falló; los .nc quedan en disco.", file=sys.stderr, flush=True)
        return 3

    print(
        f"Listo. Archivos en s3://{args.bucket}/{S3_PREFIX}/{date:%Y-%m-%d}/ y en {out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
