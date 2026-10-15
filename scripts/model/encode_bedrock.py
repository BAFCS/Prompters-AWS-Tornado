#!/usr/bin/env python3
"""Codifica con Amazon Bedrock los PNG del Compositor_RGB y escribe sus embeddings.

Lee ``--manifest`` (``manifest.parquet`` de ``compose_rgb.py``), toma las imágenes de las
Celdas_Hora de ``--start``-``--end`` y las envía al Modelo_Embedding ``--model`` (``titan`` por
defecto, Titan Multimodal Embeddings G1; ``cohere-v4`` para Cohere Embed v4) con la dimensión
``--dim``. Antes de la primera imagen comprueba que el modelo se ofrece en ``--ml-region``. Reutiliza
la caché (local o S3) salvo ``--force``, que vuelve a invocar Bedrock y reemplaza las entradas.

Salida::

    data/model/<region>/embeddings/<model>_<dim>_<recipe>_v<version>.parquet   (cell_id, model_id, dim, emb_0000...)
    data/model/<region>/embeddings/run_summary.json                           (encoded, cached, failed, model_id)
    data/model/embeddings/cache/<clave>.npy                                    (--cache local)

Termina con código distinto de cero si alguna imagen falla o si el modelo no está disponible.

Uso::

    uv run python scripts/model/encode_bedrock.py --start 2019-05-30 --manifest data/model/south-central-austral/rgb/ir_wv_v1/manifest.parquet
    uv run python scripts/model/encode_bedrock.py --start 2019-05-30 --manifest manifest.parquet --model cohere-v4 --dim 512
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bedrock_encoder as be  # noqa: E402

import common  # noqa: E402

MODEL_DATA = common.DATA / "model"
DEFAULT_ML_REGION = "us-east-1"
MANIFEST_COLUMNS = ("cell_id", "png_path", "recipe", "recipe_version")

ClientFactory = Callable[[str], tuple[Any, Any]]


def emb_columns(dim: int) -> list[str]:
    """Nombres ``emb_0000`` ... ``emb_{dim-1}``."""
    return [f"emb_{i:04d}" for i in range(dim)]


def read_items(manifest: Path, days: list[dt.date]) -> tuple[list[be.ImageItem], str]:
    """Imágenes del manifiesto cuyas Celdas_Hora caen en ``days`` y la receta (``<nombre>_v<versión>``).

    ``png_path`` es relativo a la carpeta del manifiesto. Todas las filas deben tener la misma receta.
    """
    man = pd.read_parquet(manifest)
    missing = [c for c in MANIFEST_COLUMNS if c not in man.columns]
    if missing:
        raise SystemExit(f"error: {manifest}: faltan las columnas {missing}")
    tags = sorted(
        {f"{r}_v{int(v)}" for r, v in zip(man["recipe"], man["recipe_version"], strict=True)}
    )
    if len(tags) > 1:
        raise SystemExit(f"error: {manifest} mezcla recetas {tags}; usa un manifiesto por receta")
    tag = tags[0] if tags else ""
    wanted = {f"{d:%Y%m%d}" for d in days}
    items: list[be.ImageItem] = []
    for cell_id, rel in zip(
        man["cell_id"].astype(str).tolist(), man["png_path"].astype(str).tolist(), strict=True
    ):
        if cell_id[:8] not in wanted:
            continue
        items.append(be.ImageItem(cell_id, (manifest.parent / rel).read_bytes(), tag))
    items.sort(key=lambda it: it.cell_id)
    return items, tag


def embeddings_frame(summary: be.RunSummary, model_id: str, dim: int) -> pd.DataFrame:
    """Tabla ``cell_id, model_id, dim, emb_*`` con los vectores codificados o reutilizados."""
    ids = sorted(summary.vectors)
    mat = (
        np.stack([summary.vectors[i] for i in ids]).astype(np.float32)
        if ids
        else np.zeros((0, dim), dtype=np.float32)
    )
    df = pd.DataFrame(mat, columns=emb_columns(dim))
    df.insert(0, "dim", np.full(len(ids), dim, dtype=np.int32))
    df.insert(0, "model_id", [model_id] * len(ids))
    df.insert(0, "cell_id", ids)
    return df


def _write_bytes(data: bytes, out_file: Path) -> None:
    """Escribe ``data`` en ``out_file`` pasando por un ``.tmp``."""
    tmp = out_file.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(out_file)


def build_parser() -> argparse.ArgumentParser:
    """Parser de la CLI (opciones de ``common`` más las del Codificador_Bedrock)."""
    p = common.parser(__doc__, "las imágenes ya codificadas (ignora la caché)")
    p.add_argument(
        "--manifest", type=Path, required=True, help="manifest.parquet de compose_rgb.py"
    )
    p.add_argument(
        "--model",
        choices=sorted(be.MODELS),
        default=be.DEFAULT_MODEL,
        help="Modelo_Embedding (por defecto titan)",
    )
    p.add_argument(
        "--dim",
        type=int,
        help="dimensión de salida (por defecto 1024 en titan y 1536 en cohere-v4)",
    )
    p.add_argument(
        "--cache", choices=("local", "s3"), default="local", help="dónde guardar la caché"
    )
    p.add_argument("--cache-bucket", help="bucket S3 de la caché (requerido con --cache s3)")
    p.add_argument(
        "--ml-region",
        default=DEFAULT_ML_REGION,
        help=f"región de Bedrock (por defecto {DEFAULT_ML_REGION})",
    )
    return p


def run_cli(
    argv: list[str] | None,
    client_factory: ClientFactory = be.make_clients,
    model_root: Path = MODEL_DATA,
    s3_client_factory: Callable[[str], Any] | None = None,
) -> int:
    """Ejecuta la CLI y devuelve el código de salida (``0`` sin fallidas).

    ``client_factory(region)`` devuelve ``(bedrock_runtime, bedrock)``; las pruebas pasan dobles.
    ``s3_client_factory`` crea el cliente S3 de ``--cache s3`` (por defecto boto3).
    """
    a = build_parser().parse_args(argv)
    spec = be.MODELS[a.model]
    dim = a.dim if a.dim is not None else spec.default_dim
    if dim not in spec.allowed_dims:
        print(f"error: --dim {dim} no válida para {a.model}; usa {list(spec.allowed_dims)}")
        return 2
    reg = common.region_of(a)
    if a.cache == "s3":
        if not a.cache_bucket:
            print("error: --cache s3 requiere --cache-bucket")
            return 2
        client: Any
        if s3_client_factory is None:
            import boto3

            client = boto3.client("s3", region_name=a.ml_region)
        else:
            client = s3_client_factory(a.ml_region)
        cache: be.EmbeddingCache = be.S3Cache(client, a.cache_bucket)
    else:
        cache = be.LocalCache(model_root / "embeddings" / "cache")
    items, tag = read_items(a.manifest, common.days(a))
    runtime, control = client_factory(a.ml_region)
    encoder = be.BedrockEncoder(runtime, control, spec, dim, cache)
    try:
        encoder.preflight(a.ml_region)
    except SystemExit as e:
        print(e.code, flush=True)
        return 1
    print(f"{spec.model_id} ({dim}): {len(items)} imágenes", flush=True)
    summary = encoder.run(items, a.force)
    out_dir = model_root / reg.name / "embeddings"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{a.model}_{dim}_{tag}.parquet"
    tmp = out_file.with_suffix(".tmp")
    embeddings_frame(summary, spec.model_id, dim).to_parquet(tmp, index=False)
    tmp.replace(out_file)
    report = summary.to_json(spec.model_id, dim)
    _write_bytes(
        json.dumps(report, indent=2, ensure_ascii=False).encode(), out_dir / "run_summary.json"
    )
    print(
        f"codificadas {summary.encoded}, desde caché {summary.cached}, fallidas {summary.failed}",
        flush=True,
    )
    for f in summary.failures:
        print(f"  fallida: {f['cell_id']} ({f['error_type']})", flush=True)
    return summary.exit_code


def main() -> None:
    """Punto de entrada de la CLI."""
    sys.exit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
