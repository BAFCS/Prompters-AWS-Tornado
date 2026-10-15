"""Monitor del avance: revisa S3 cada N segundos y avisa qué archivos nuevos se subieron.

Sirve para vigilar la materialización desde otra terminal: muestra cada índice ERA5 y recorte GOES
que cae en el bucket, y avisa si pasa mucho tiempo sin novedades (posible atasco).

Uso:
    AWS_PROFILE=gpu uv run python data_pipeline/watch_s3.py --bucket mesocyclonic-model-905418466452
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import fsspec


def _list(fs: fsspec.AbstractFileSystem, bucket: str) -> dict[str, int]:
    """Mapa {clave: tamaño} de los archivos relevantes ya subidos (índices + GOES)."""
    out: dict[str, int] = {}
    for prefix in (f"{bucket}/era5_indices/", f"{bucket}/data/crops/"):
        try:
            for info in fs.find(prefix, detail=True).values():
                if info["name"].endswith(".nc"):
                    out[info["name"]] = info.get("size", 0)
        except FileNotFoundError:
            pass
    return out


def main() -> None:
    """Vigila el bucket e informa cada archivo nuevo; alerta si hay silencio prolongado."""
    p = argparse.ArgumentParser(description="Monitor de subida a S3 de la materialización.")
    p.add_argument("--bucket", required=True, help="Bucket S3 a vigilar (sin s3://)")
    p.add_argument("--every", type=int, default=30, help="Cada cuántos segundos revisar")
    p.add_argument("--stall", type=int, default=600, help="Segundos sin novedad para alertar atasco")
    a = p.parse_args()

    fs = fsspec.filesystem("s3")
    seen = _list(fs, a.bucket)
    print(f"[{_now()}] Vigilando s3://{a.bucket} — {len(seen)} archivos ya presentes.", flush=True)
    last_change = time.time()

    while True:
        time.sleep(a.every)
        current = _list(fs, a.bucket)
        new = {k: v for k, v in current.items() if k not in seen}
        if new:
            for key, size in sorted(new.items()):
                short = key.split("/", 1)[1] if "/" in key else key
                print(f"[{_now()}] ⬆️  SUBIDO  {short}  ({size / 1e6:.1f} MB)", flush=True)
            print(f"[{_now()}] total: {len(current)} archivos en S3", flush=True)
            seen = current
            last_change = time.time()
        else:
            idle = int(time.time() - last_change)
            if idle >= a.stall:
                print(f"[{_now()}] ⚠️  SIN NOVEDAD hace {idle // 60} min — posible atasco", flush=True)
            else:
                print(f"[{_now()}] … sin cambios ({idle}s desde el último; {len(current)} archivos)", flush=True)


def _now() -> str:
    """Hora local HH:MM:SS para los mensajes."""
    return dt.datetime.now().strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
