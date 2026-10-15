"""Punto de entrada del trabajo de entrenamiento de SageMaker (una Configuración_Experimento).

SageMaker copia ``scripts/model`` al contenedor (``SourceCode(source_dir="scripts/model")``) y
ejecuta este archivo con los hiperparámetros como opciones de línea de comandos::

    python sm_job/train_entry.py --config physical --seed 0 --n-components 8 \\
        --results-uri s3://<ml>/model/results/<run_id>

Lee los canales ``/opt/ml/input/data/train`` (Parquet de la tabla) y ``/opt/ml/input/data/folds``
(``folds.json``, el mismo para las tres configuraciones), ejecuta la Validación_LOEO de ``loeo.py``
(con un Reductor por partición en ``embeddings``), entrena el modelo final con la misma parada
temprana y escribe:

- en ``/opt/ml/model/`` (SageMaker lo empaqueta en ``model.tar.gz``): ``model.json``,
  ``feature_columns.json``, ``config.json`` y ``reducer.npz`` (solo ``embeddings``);
- en ``<results-uri>/<config>/``: ``model.json``, ``metrics.json``, ``importance.json`` y
  ``reporte.html`` con su Content-Type (Req. 7.9).

Solo usa numpy/pandas/xgboost/scikit-learn/pyarrow: no importa ``common`` ni ``xarray``, que no
están en el contenedor. Rutas y cliente S3 son inyectables para probar sin red.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from pathlib import Path
from typing import Any, Protocol, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loeo  # noqa: E402
import pandas as pd  # noqa: E402
import reducer  # noqa: E402
import table as tb  # noqa: E402

INPUT_DIR = Path("/opt/ml/input/data")
MODEL_DIR = Path("/opt/ml/model")
RESULT_FILES = ("model.json", "metrics.json", "importance.json", "reporte.html")
DEFAULT_MODEL_ID = "amazon.titan-embed-image-v1"


class S3Like(Protocol):
    """Lo que se usa de un cliente S3 de boto3."""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object:
        """Sube un objeto."""
        ...


def content_type(name: str) -> str:
    """Content-Type por extensión (sin él, S3 sirve el HTML como descarga)."""
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def json_bytes(obj: object) -> bytes:
    """``obj`` como JSON UTF-8 legible."""
    return json.dumps(obj, indent=2, ensure_ascii=False).encode()


def split_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/prefijo`` → ``(bucket, prefijo)`` sin barras finales."""
    if not uri.startswith("s3://"):
        raise ValueError(f"se esperaba una URI s3://; se recibió {uri!r}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key.strip("/")


def read_train(channel: Path) -> pd.DataFrame:
    """Tabla del canal ``train`` (todos los Parquet), en orden ``(time, latitude, longitude)``."""
    files = sorted(channel.rglob("*.parquet"))
    if not files:
        raise SystemExit(f"error: no hay archivos Parquet en el canal train ({channel})")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["time"] = tb.utc(df["time"])
    return df.sort_values(tb.POINT, kind="mergesort").reset_index(drop=True)


def read_folds(channel: Path) -> list[loeo.Fold]:
    """Particiones del canal ``folds`` (``folds.json``)."""
    path = channel / "folds.json"
    if not path.is_file():
        found = sorted(channel.rglob("*.json"))
        if not found:
            raise SystemExit(f"error: falta folds.json en el canal folds ({channel})")
        path = found[0]
    return loeo.folds_from_json(json.loads(path.read_text(encoding="utf-8")))


def feature_columns(config: str, df: pd.DataFrame) -> list[str]:
    """``config_columns`` de la configuración; termina si falta alguna en la tabla."""
    n_emb = sum(str(c).startswith(loeo.EMB_PREFIX) for c in df.columns)
    try:
        feats = tb.config_columns(config, n_emb)
    except ValueError as e:
        raise SystemExit(f"error: {config}: {e}") from e
    missing = [c for c in [*tb.KEY_COLUMNS, *feats] if c not in df.columns]
    if missing:
        raise SystemExit(f"error: {config}: faltan columnas {missing}")
    return feats


def upload(results_uri: str, config: str, files: dict[str, bytes], s3: S3Like | None) -> None:
    """Sube ``files`` a ``<results_uri>/<config>/`` (S3) o los escribe si es una carpeta local."""
    if not results_uri.startswith("s3://"):
        out = Path(results_uri) / config
        out.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (out / name).write_bytes(data)
        return
    if s3 is None:
        import boto3

        client = cast(S3Like, boto3.client("s3"))
    else:
        client = s3
    bucket, prefix = split_s3_uri(results_uri)
    for name, data in files.items():
        key = f"{prefix}/{config}/{name}" if prefix else f"{config}/{name}"
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type(name))


def build_parser() -> argparse.ArgumentParser:
    """Hiperparámetros del trabajo (SageMaker los pasa como ``--clave valor``)."""
    p = argparse.ArgumentParser(description="Entrenamiento LOEO de una configuración.")
    p.add_argument("--config", choices=tb.CONFIGS, required=True, help="Configuración_Experimento")
    p.add_argument("--seed", type=int, default=0, help="semilla de XGBoost y la validación interna")
    p.add_argument(
        "--n-components",
        type=int,
        default=reducer.DEFAULT_COMPONENTS,
        help="componentes del Reductor (solo embeddings, 8-16)",
    )
    p.add_argument("--results-uri", help="s3://<ml>/model/results/<run_id> (o carpeta local)")
    p.add_argument("--model-id", default=DEFAULT_MODEL_ID, help="Modelo_Embedding (informativo)")
    return p


def main(
    argv: list[str] | None = None,
    input_dir: Path = INPUT_DIR,
    model_dir: Path = MODEL_DIR,
    s3_client: S3Like | None = None,
    results_uri: str | None = None,
) -> int:
    """Ejecuta el trabajo; devuelve 0 si termina bien."""
    a = build_parser().parse_args(argv)
    results_uri = results_uri or a.results_uri
    df = read_train(input_dir / "train")
    folds = read_folds(input_dir / "folds")
    feats = feature_columns(a.config, df)
    if not (df["label"] == 1).any():
        raise SystemExit(f"error: {a.config}: la tabla no tiene Celdas_Hora positivas")
    factory = None
    if a.config == "embeddings":
        reducer.Reducer(a.n_components, a.model_id)  # valida 8-16 antes de entrenar
        factory = functools.partial(reducer.Reducer, a.n_components, a.model_id)
    print(f"{a.config}: {len(df)} filas, {len(folds)} particiones", flush=True)
    metrics = loeo.run_loeo(df, feats, folds, a.seed, factory).to_metrics_json(a.config)
    sel = metrics["selection"]
    print(f"  POD={sel['pod']:.3f} FAR={sel['far']:.3f} CSI={sel['csi']:.3f}", flush=True)
    final = loeo.train_final(df, feats, a.seed, factory)

    model_dir.mkdir(parents=True, exist_ok=True)
    final.model.save_model(str(model_dir / "model.json"))
    columns: dict[str, Any] = {
        "required": final.input_columns,
        "model": final.model_columns,
        "embedding": final.emb_columns,
    }
    (model_dir / "feature_columns.json").write_text(json.dumps(columns, indent=2), "utf-8")
    config: dict[str, Any] = {
        "config": a.config,
        "seed": a.seed,
        "xgb_params": loeo.XGB_PARAMS,
        "scale_pos_weight": final.fit.scale_pos_weight,
        "best_iteration": final.fit.best_iteration,
        "early_stopping": final.fit.early_stopping,
    }
    if isinstance(final.reducer, reducer.Reducer):
        final.reducer.save(model_dir / "reducer.npz")
        config.update(n_components=final.reducer.n_components, model_id=final.reducer.model_id)
    (model_dir / "config.json").write_text(json.dumps(config, indent=2), "utf-8")

    if results_uri:
        files = {
            "model.json": (model_dir / "model.json").read_bytes(),
            "metrics.json": json_bytes(metrics),
            "importance.json": json_bytes(final.importance),
            "reporte.html": loeo.report_html(metrics, final.importance, df).encode(),
        }
        upload(results_uri, a.config, files, s3_client)
        print(f"  resultados en {results_uri.rstrip('/')}/{a.config}/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
