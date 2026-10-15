#!/usr/bin/env python3
"""Inferencia del Modelo_Real (XGBoost híbrido ERA5 + imágenes GOES) sobre la grilla de un día.

Arma las Celdas_Hora de ``--day`` en la ventana ``--hours`` (por defecto 15–23 UTC) sobre la
grilla ERA5 submuestreada cada ``--stride`` puntos (2 → 0,5°, para acotar las llamadas a Bedrock)
y reutiliza el código del modelo de Daniel sin reimplementarlo:

1. Variables_GOES del día con ``extract_goes_features.process_day`` (carpeta de trabajo propia);
2. en ``embeddings``: PNG por Celda_Hora con ``compose_rgb.compose_cells`` y embeddings de Titan
   con ``bedrock_encoder.BedrockEncoder`` (caché local compartida ``data/model/embeddings/cache``);
3. tabla de inferencia con ``table.build`` (rezagos t-1..t-3 con los índices del día y el anterior);
4. ``inference.model_fn`` + ``inference.predict_fn`` (paridad exacta con SageMaker).

Escribe ``<out>/pred_AAAAMMDD.csv`` (esquema de ``predictions.py``) y ``pred_AAAAMMDD.meta.json``
con ``modelo: "real"``. Las celdas fuera de la ventana o del submuestreo no aparecen (el sitio las
deja vacías). Las horas sin archivos GOES (ni en t ni en t-1) se omiten y quedan en los metadatos.
Antes de llamar a Bedrock imprime la estimación de imágenes y se niega a pasar de 15000 sin
``--yes``.

Uso::

    uv run --no-sync python scripts/app/infer_grid.py --day 2019-05-30
    uv run --no-sync python scripts/app/infer_grid.py --day 2019-05-30 --hours 19 23 --stride 1 --yes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[2]
for _p in ("scripts", "scripts/model", "scripts/app"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

import atomic  # noqa: E402
import bedrock_encoder as be  # noqa: E402
import build_table  # noqa: E402
import compose_rgb  # noqa: E402
import encode_bedrock  # noqa: E402
import extract_goes_features as egf  # noqa: E402
import rgb  # noqa: E402
import table as tb  # noqa: E402
from sm_job import inference  # noqa: E402

import common  # noqa: E402

MODEL_DATA = common.DATA / "model"
DEFAULT_MODEL_DIR = MODEL_DATA / "hibrido"
DEFAULT_OUT = common.DATA / "app" / "predictions"
DEFAULT_WORK = common.DATA / "app" / "infer_work"
CACHE_ROOT = MODEL_DATA / "embeddings" / "cache"  # la misma caché local de encode_bedrock.py
MAX_IMAGES = 15_000
GRID_STEP = 0.25  # paso de la grilla ERA5 en grados
GOES_WINDOW_DEG = 0.25  # Ventana_GOES por defecto de extract_goes_features.py
CHUNK = 100  # imágenes por tarea de los hilos de Bedrock

ClientFactory = Callable[[str], tuple[Any, Any]]


def grid(idx_file: Path, stride: int) -> tuple[np.ndarray, np.ndarray]:
    """Latitudes y longitudes de la grilla ERA5 de ``idx_file`` tomando un punto cada ``stride``."""
    with xr.open_dataset(idx_file, engine="h5netcdf") as ds:
        lat = np.asarray(ds["latitude"].values, dtype=np.float64)
        lon = np.asarray(ds["longitude"].values, dtype=np.float64)
    return lat[::stride], lon[::stride]


def hours_with_goes(
    crops_root: Path, region: str, times: list[pd.Timestamp]
) -> tuple[list[pd.Timestamp], list[int]]:
    """Horas con algún archivo GOES en t o t-1 (donde busca el barrido) y las horas sin él."""
    ok: list[pd.Timestamp] = []
    missing: list[int] = []
    for t in times:
        naive = t.tz_convert(None).to_pydatetime()
        files = [egf.goes_path(crops_root, region, naive - dt.timedelta(hours=k)) for k in (0, 1)]
        if any(f.exists() for f in files):
            ok.append(t)
        else:
            missing.append(int(t.hour))
    return ok, missing


def estimate(n_points: int, n_hours: int) -> int:
    """Imágenes (y como máximo llamadas a Bedrock) de ``n_points`` puntos × ``n_hours`` horas."""
    return int(n_points) * int(n_hours)


def check_estimate(n_images: int, yes: bool, limit: int | None = None) -> None:
    """Termina (``SystemExit``) si ``n_images`` supera ``limit`` (``MAX_IMAGES``) sin ``--yes``."""
    limit = MAX_IMAGES if limit is None else limit
    if n_images > limit and not yes:
        raise SystemExit(
            f"error: {n_images} imágenes superan el límite de {limit}; "
            "sube --stride, acota --hours o confirma con --yes"
        )


def needs_embeddings(bundle: inference.Bundle) -> bool:
    """``True`` si el modelo trae columnas ``emb_*`` (configuración ``embeddings``)."""
    return any(c.startswith("emb_") for c in bundle.input_columns)


def embedding_dim(bundle: inference.Bundle) -> int:
    """Dimensión de los embeddings que espera el modelo (columnas ``emb_*`` requeridas)."""
    return sum(c.startswith("emb_") for c in bundle.input_columns)


def encode_parallel(
    encoder: be.BedrockEncoder, items: list[be.ImageItem], workers: int
) -> be.RunSummary:
    """``encoder.run`` en ``workers`` hilos por tandas de ``CHUNK``; une las contabilidades."""
    chunks = [items[i : i + CHUNK] for i in range(0, len(items), CHUNK)]
    total = be.RunSummary()
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(encoder.run, c, False) for c in chunks]
        for fut in as_completed(futures):
            s = fut.result()
            total.encoded += s.encoded
            total.cached += s.cached
            total.failed += s.failed
            total.failures.extend(s.failures)
            total.vectors.update(s.vectors)
            done += s.encoded + s.cached + s.failed
            print(
                f"  embeddings {done}/{len(items)} (Bedrock {total.encoded}, "
                f"caché {total.cached}, fallidas {total.failed})",
                flush=True,
            )
    return total


def embed_cells(
    cells: pd.DataFrame,
    day: dt.date,
    region: str,
    crops_root: Path,
    work_root: Path,
    recipe: rgb.Recipe,
    size: int,
    window_km: float,
    dim: int,
    ml_region: str,
    workers: int,
    client_factory: ClientFactory,
    cache_root: Path,
) -> tuple[pd.DataFrame, dict]:
    """PNG (``compose_rgb``) y embeddings Titan (``bedrock_encoder``) de las Celdas_Hora.

    Devuelve la tabla ``cell_id, model_id, dim, emb_*`` y la contabilidad para los metadatos.
    """
    _, skp = compose_rgb.compose_cells(
        cells, region, recipe, size, window_km, crops_root, work_root, False
    )
    manifest = work_root / region / "rgb" / recipe.tag / "manifest.parquet"
    items, _ = encode_bedrock.read_items(manifest, [day])
    spec = be.MODELS["titan"]
    runtime, control = client_factory(ml_region)
    encoder = be.BedrockEncoder(runtime, control, spec, dim, be.LocalCache(cache_root))
    encoder.preflight(ml_region)
    print(f"{spec.model_id} ({dim}) en {ml_region}: {len(items)} imágenes", flush=True)
    summary = encode_parallel(encoder, items, workers)
    stats = {
        "modelo_embedding": spec.model_id,
        "dim": dim,
        "receta": recipe.tag,
        "size_px": size,
        "window_km": window_km,
        "imagenes": len(items),
        "llamadas_bedrock": summary.encoded,
        "desde_cache": summary.cached,
        "fallidas": summary.failed,
        "rgb_omitidas": len(skp),
        "rgb_omitidas_motivos": {str(k): int(v) for k, v in skp["reason"].value_counts().items()},
    }
    for f in summary.failures[:20]:
        print(f"  fallida: {f['cell_id']} ({f['error_type']})", flush=True)
    return encode_bedrock.embeddings_frame(summary, spec.model_id, dim), stats


def goes_frame(day: dt.date, region: str, crops_root: Path, work_root: Path) -> pd.DataFrame | None:
    """Variables_GOES del día (``extract_goes_features.process_day`` en la carpeta de trabajo).

    Se recalculan en cada corrida para no usar una tabla de antes de que terminara la descarga GOES.
    """
    egf.process_day(day, region, crops_root, work_root, GOES_WINDOW_DEG, True)
    return build_table.read_goes(work_root, region, [day])


def evaluation(model_dir: Path, day: dt.date) -> dict[str, Any]:
    """Si ``day`` se usó para entrenar el modelo (según ``train_summary.json`` de ``model_dir``)."""
    summary = Path(model_dir) / "train_summary.json"
    try:
        s = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"evaluacion": "desconocida (sin train_summary.json)", "en_entrenamiento": None}
    used = {*s.get("event_days", []), *s.get("negative_days", [])}
    inside = day.isoformat() in used
    return {
        "evaluacion": "en muestra (día usado en el entrenamiento)"
        if inside
        else "fuera de muestra (día retenido, no usado en el entrenamiento)",
        "en_entrenamiento": inside,
        "dias_entrenamiento": len(used),
        "excluidos": list(s.get("args", {}).get("exclude_days", [])),
    }


def nan_counts(df: pd.DataFrame, bundle: inference.Bundle) -> dict[str, int]:
    """Filas con NaN por grupo de variables de la tabla de inferencia."""
    emb = [c for c in bundle.input_columns if c.startswith("emb_")]
    era5 = [c for c in tb.ERA5_FEATURES if c in df.columns]
    goes = [c for c in tb.GOES_FEATURES if c in df.columns]
    out = {
        "filas_con_algun_nan": int(df[bundle.input_columns].isna().any(axis=1).sum()),
        "era5_t_con_nan": int(df[era5].isna().any(axis=1).sum()) if era5 else 0,
        "goes_t_con_nan": int(df[goes].isna().any(axis=1).sum()) if goes else 0,
    }
    if emb:
        out["sin_embedding"] = int(df[emb].isna().all(axis=1).sum())
    return out


def run(
    a: argparse.Namespace,
    crops_root: Path = common.CROPS,
    client_factory: ClientFactory = be.make_clients,
    cache_root: Path = CACHE_ROOT,
) -> Path:
    """Corre la inferencia de ``a`` y devuelve la ruta del CSV escrito."""
    if a.stride < 1:
        raise SystemExit("error: --stride debe ser >= 1")
    h0, h1 = a.hours
    if not 0 <= h0 <= h1 <= 23:
        raise SystemExit("error: --hours espera INICIO FIN con 0 <= INICIO <= FIN <= 23")
    day: dt.date = a.day
    region = a.region
    idx_file = crops_root / region / "era5_indices" / f"era5_idx_{day:%Y%m%d}.nc"
    if not idx_file.exists():
        raise SystemExit(f"error: falta {idx_file}; corre sync_from_bucket.py --only era5")
    bundle = inference.model_fn(str(a.model_dir))
    lat, lon = grid(idx_file, a.stride)
    t0 = pd.Timestamp(day, tz="UTC")
    times = [t0 + pd.Timedelta(hours=h) for h in range(h0, h1 + 1)]
    use_goes = bundle.config != "baseline_era5"
    missing_hours: list[int] = []
    if use_goes:
        times, missing_hours = hours_with_goes(crops_root, region, times)
        for h in missing_hours:
            print(f"  aviso: {day} {h:02d} UTC sin archivos GOES; se omite la hora", flush=True)
    if not times:
        raise SystemExit(f"error: {day}: ninguna hora de {h0}-{h1} UTC tiene GOES")
    n_points = len(lat) * len(lon)
    use_emb = needs_embeddings(bundle)
    n_images = estimate(n_points, len(times)) if use_emb else 0
    print(
        f"{day}: {len(lat)}×{len(lon)} puntos (paso {GRID_STEP * a.stride:g}°) × {len(times)} "
        f"horas = {n_points * len(times)} celdas; estimación {n_images} imágenes para Bedrock "
        "(las que ya estén en caché no se cobran)",
        flush=True,
    )
    check_estimate(n_images, a.yes)
    if a.dry_run:
        raise SystemExit(0)

    cells = tb.candidate_cells(times, lat, lon)
    era5 = build_table.read_era5(crops_root, region, [day], build_table.previous_day([day]))
    goes = goes_frame(day, region, crops_root, a.work) if use_goes else None
    emb = None
    emb_stats: dict = {}
    if use_emb:
        if a.profile and client_factory is be.make_clients:
            os.environ["AWS_PROFILE"] = a.profile
        recipe = rgb.validate_recipe(a.recipe, a.recipe_version)
        emb, emb_stats = embed_cells(
            cells,
            day,
            region,
            crops_root,
            a.work,
            recipe,
            a.size,
            a.window_km,
            embedding_dim(bundle),
            a.ml_region,
            a.workers,
            client_factory,
            cache_root,
        )
    df = tb.build(bundle.config, cells, era5, goes, emb)
    pred = inference.predict_fn(df, bundle)
    if pred["probability"].isna().any():
        raise SystemExit("error: el modelo devolvió probabilidades NaN")

    csv = Path(a.out) / f"pred_{day:%Y%m%d}.csv"
    atomic.write_text(csv, pred.to_csv(index=False))
    peak = pred.groupby("hour_utc")["probability"].max()
    meta = {
        "modelo": "real",
        "config": bundle.config,
        "model_dir": str(a.model_dir),
        "generado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "filas": len(pred),
        "celdas": n_points,
        "horas": [int(t.hour) for t in times],
        "horas_sin_goes": missing_hours,
        "stride": a.stride,
        "paso_grados": GRID_STEP * a.stride,
        "nan": nan_counts(df, bundle),
        "max_por_hora": {str(h): round(float(v), 4) for h, v in peak.items()},
        "bedrock": emb_stats,
        **evaluation(a.model_dir, day),
    }
    atomic.write_json(csv.with_name(f"{csv.stem}.meta.json"), meta)
    print(f"{csv}: {len(pred)} filas, máx {pred['probability'].max() * 100:.1f} %", flush=True)
    return csv


def build_parser() -> argparse.ArgumentParser:
    """Parser de la CLI."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--day", type=dt.date.fromisoformat, required=True, help="día AAAA-MM-DD")
    p.add_argument(
        "--hours",
        type=int,
        nargs=2,
        default=(15, 23),
        metavar=("INICIO", "FIN"),
        help="ventana de horas UTC inclusive (por defecto 15 23)",
    )
    p.add_argument(
        "--stride", type=int, default=2, help="un punto ERA5 cada N (por defecto 2 → 0,5°)"
    )
    p.add_argument("--region", default="south-central-austral")
    p.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="artefactos")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="carpeta del CSV_Predicciones")
    p.add_argument("--work", type=Path, default=DEFAULT_WORK, help="carpeta de trabajo")
    p.add_argument("--recipe", default="ir_wv", help="receta RGB (por defecto ir_wv)")
    p.add_argument("--recipe-version", type=int, default=1)
    p.add_argument("--size", type=int, default=rgb.DEFAULT_SIZE, help="lado del PNG en píxeles")
    p.add_argument("--window-km", type=float, default=100.0, help="ventana RGB en km")
    p.add_argument("--profile", default="gpu", help="perfil AWS para Bedrock (por defecto gpu)")
    p.add_argument("--ml-region", default="us-east-1", help="región de Bedrock")
    p.add_argument("--workers", type=int, default=8, help="hilos de llamadas a Bedrock")
    p.add_argument("--yes", action="store_true", help=f"permite más de {MAX_IMAGES} imágenes")
    p.add_argument("--dry-run", action="store_true", help="solo imprime la estimación")
    return p


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada de la CLI."""
    run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
