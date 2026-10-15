"""Entrena un clasificador XGBoost de entorno tornádico con los índices ERA5 y el catálogo.

Flujo (todo pensado para correr en la nube, en la EC2 de entrenamiento, o en local):

1. Lee los índices ERA5 ya calculados (``era5_indices/era5_idx_AAAAMMDD.nc``) y el catálogo de
   tornados (``tornados_chile.xlsx``). Las rutas pueden ser locales o ``s3://`` (vía s3fs).
2. Arma la tabla *positive-unlabeled* (PU) de la configuración ``baseline_era5`` con ``table.py``
   (el mismo código que usa ``build_table.py``): positivos = la celda ERA5 y la hora más cercanas
   a cada evento del catálogo; no etiquetados = una muestra con semilla del resto de celdas-horas.
   No hay negativos confiables (sección 6.1 del documento), así que "no etiquetado" no es
   "negativo".
3. Evalúa con la Validación_LOEO de ``loeo.py`` (el mismo código que el trabajo de SageMaker):
   una partición por evento, con su ``fold_group`` completo en prueba (sin fuga, sección 6.3) y
   parada temprana con validación interna agrupada.
4. Informa POD, FAR y CSI (sección 6.2), no exactitud, más PR-AUC y el umbral de máximo CSI como
   información complementaria. Los resultados difieren de corridas históricas de la versión
   anterior de este script (300 árboles fijos y prueba solo con la fila positiva).
5. Escribe ``model.json`` (XGBoost), ``metrics.json``, ``importance.json`` y ``reporte.html`` y los
   sube al prefijo de resultados (local o ``s3://``).

Convenciones de dominio respetadas: la SRH y el STP tornádicos son **negativos** en el hemisferio
sur (rama *left-mover*); las features se usan con su signo físico, tal como las escribe
``process_era5.py``. Los NaN se pasan tal cual a XGBoost (sin imputación).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO, cast

import fsspec
import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import loeo  # noqa: E402
import table as tb  # noqa: E402

import common  # noqa: E402

CONFIG = "baseline_era5"
# Las 12 variables ERA5 del modelo (base física, sección 5), con su signo austral.
FEATURES = list(tb.ERA5_FEATURES)

# Por cada positivo, cuántas celdas-hora no etiquetadas se muestrean.
UNLABELED_PER_POSITIVE = 200
ERA5_STEP_DEG = 0.25


def _open_dataset(path: str) -> xr.Dataset:
    """Abre un NetCDF local o en S3 (acceso anónimo si es un bucket público)."""
    if path.startswith("s3://"):
        with fsspec.open(path, "rb").open() as f:  # type: ignore[union-attr]
            return xr.load_dataset(io.BytesIO(f.read()))
    return xr.load_dataset(path)


def _read_catalog(path: str) -> pd.DataFrame:
    """Lee ``Final_Table`` del catálogo (local o ``s3://``) y lo normaliza con ``table.py``."""
    with fsspec.open(path, "rb") as f:  # type: ignore[union-attr]
        raw = cast(BinaryIO, f).read()
    return tb.normalize_catalog(pd.read_excel(io.BytesIO(raw), sheet_name="Final_Table"))


def _day_of(path: str) -> dt.date | None:
    """Extrae la fecha AAAAMMDD del nombre ``era5_idx_AAAAMMDD.nc``."""
    stem = path.rstrip("/").split("/")[-1]
    for token in stem.replace(".", "_").split("_"):
        if len(token) == 8 and token.isdigit():
            try:
                return dt.datetime.strptime(token, "%Y%m%d").date()
            except ValueError:
                return None
    return None


def read_indices(indices_paths: list[str]) -> pd.DataFrame:
    """Índices ERA5 de ``indices_paths`` en formato largo (``time``, ``latitude``, ``longitude``)."""
    parts: list[pd.DataFrame] = []
    for path in indices_paths:
        if _day_of(path) is None:
            continue
        ds = _open_dataset(path)
        present = [f for f in FEATURES if f in ds.data_vars]
        missing = [f for f in FEATURES if f not in ds.data_vars]
        if missing:
            print(f"  aviso: faltan features {missing} en {path}", flush=True)
        parts.append(ds[present].to_dataframe(dim_order=list(tb.POINT)).reset_index())
        ds.close()
    if not parts:
        return pd.DataFrame(columns=list(tb.POINT))
    era5 = pd.concat(parts, ignore_index=True)
    era5["time"] = tb.utc(era5["time"])
    return era5


def grid_region(lat: np.ndarray, lon: np.ndarray) -> common.Region:
    """Rectángulo de la grilla ERA5 más media celda: los eventos fuera de él no se etiquetan."""
    half = ERA5_STEP_DEG / 2
    return common.Region(
        "indices",
        float(np.max(lat)) + half,
        float(np.min(lat)) - half,
        float(np.min(lon)) - half,
        float(np.max(lon)) + half,
    )


def build_table(indices_paths: list[str], catalog: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Tabla PU ``baseline_era5`` de los días con índices, con ``table.select_cells`` y ``build``.

    Solo se etiquetan los eventos de los días de ``indices_paths``; se informa cuántos se omiten.
    """
    era5 = read_indices(indices_paths)
    if era5.empty:
        raise SystemExit("No hay índices ERA5 legibles (era5_idx_AAAAMMDD.nc).")
    days = sorted({d for d in (_day_of(p) for p in indices_paths) if d is not None})
    lat = era5["latitude"].drop_duplicates().to_numpy()
    lon = era5["longitude"].drop_duplicates().to_numpy()
    events = catalog[catalog["date"].isin(days)]
    cells, skipped = tb.select_cells(
        events,
        sorted(set(era5["time"])),
        lat,
        lon,
        grid_region(lat, lon),
        UNLABELED_PER_POSITIVE,
        seed,
    )
    if len(skipped):
        print(
            f"  {len(skipped)} eventos omitidos (sin hora, fuera de la grilla o colisión)",
            flush=True,
        )
    return tb.build(CONFIG, cells, era5)


def _write(path: str, data: bytes) -> None:
    """Escribe ``data`` en una ruta local o ``s3://`` con el Content-Type correcto por extensión.

    Sin Content-Type, S3 guarda los objetos como ``binary/octet-stream`` y el navegador descarga el
    HTML en vez de mostrarlo. Se fija ``text/html`` para ``.html`` y ``application/json`` para JSON.
    """
    content_type = (
        "text/html; charset=utf-8"
        if path.endswith(".html")
        else "application/json"
        if path.endswith(".json")
        else "application/octet-stream"
    )
    if path.startswith("s3://"):
        fs = fsspec.filesystem("s3")
        with fs.open(path, "wb", content_type=content_type) as f:
            f.write(data)
    else:
        with fsspec.open(path, "wb") as f:  # type: ignore[union-attr]
            cast(BinaryIO, f).write(data)


def _list_indices(indices_arg: str) -> list[str]:
    """Lista los NetCDF de índices en una carpeta local o un prefijo ``s3://``."""
    fs, _, _ = fsspec.get_fs_token_paths(indices_arg.rstrip("/") + "/*.nc")
    found = fs.glob(indices_arg.rstrip("/") + "/*.nc")
    prefix = "s3://" if indices_arg.startswith("s3://") else ""
    return sorted(prefix + p for p in found)


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada de la CLI."""
    p = argparse.ArgumentParser(
        description="Entrena XGBoost de entorno tornádico (ERA5 + catálogo)."
    )
    p.add_argument("--indices", required=True, help="Carpeta o prefijo s3:// con era5_idx_*.nc")
    p.add_argument("--catalog", required=True, help="Ruta o s3:// del tornados_chile.xlsx")
    p.add_argument(
        "--out", required=True, help="Carpeta o prefijo s3:// donde dejar los resultados"
    )
    p.add_argument(
        "--seed", type=int, default=0, help="Semilla del muestreo, las particiones y XGBoost"
    )
    a = p.parse_args(argv)

    print("Listando índices ERA5...", flush=True)
    indices = _list_indices(a.indices)
    print(f"  {len(indices)} archivos de índices", flush=True)
    if not indices:
        raise SystemExit(f"No hay índices en {a.indices}. Genera era5_indices primero.")

    print("Leyendo catálogo...", flush=True)
    catalog = _read_catalog(a.catalog)

    print("Construyendo tabla PU...", flush=True)
    table = build_table(indices, catalog, a.seed)
    n_pos = int((table["label"] == 1).sum())
    print(f"  {len(table)} filas, {n_pos} positivos", flush=True)
    if n_pos == 0:
        raise SystemExit("No hay positivos: revisa que los días de los índices tengan eventos.")

    print("Validación dejar-un-evento-afuera...", flush=True)
    folds = loeo.compute_folds(table)
    metrics = loeo.run_loeo(table, FEATURES, folds, a.seed).to_metrics_json(CONFIG)
    sel = metrics["selection"]
    print(f"  POD={sel['pod']:.3f} FAR={sel['far']:.3f} CSI={sel['csi']:.3f}", flush=True)

    print("Entrenando modelo final...", flush=True)
    final = loeo.train_final(table, FEATURES, a.seed)

    out = a.out.rstrip("/")
    print(f"Subiendo resultados a {out}...", flush=True)
    # XGBoost serializa a un archivo; se escribe en un temporal y se sube su contenido.
    with tempfile.TemporaryDirectory() as tmp:
        model_file = Path(tmp) / "model.json"
        final.model.save_model(str(model_file))
        _write(f"{out}/model.json", model_file.read_bytes())
    _write(f"{out}/metrics.json", json.dumps(metrics, indent=2, ensure_ascii=False).encode())
    _write(
        f"{out}/importance.json",
        json.dumps(final.importance, indent=2, ensure_ascii=False).encode(),
    )
    _write(f"{out}/reporte.html", loeo.report_html(metrics, final.importance, table).encode())
    print("Listo.", flush=True)


if __name__ == "__main__":
    main()
