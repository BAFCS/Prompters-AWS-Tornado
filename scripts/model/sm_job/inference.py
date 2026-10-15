"""Servicio_Inferencia: funciones de SageMaker para Batch Transform y el endpoint opcional.

El contenedor de XGBoost de SageMaker (modo script, ``SAGEMAKER_PROGRAM=inference.py``) llama a
``model_fn`` con la carpeta del ``model.tar.gz`` que dejó ``sm_job/train_entry.py`` y luego, por
cada solicitud, a ``input_fn`` → ``predict_fn`` → ``output_fn``:

- entrada: Parquet (``application/x-parquet``) con la tabla de inferencia de ``build_table.py
  --stage infer`` (columnas clave más las de la Configuración_Experimento);
- ``predict_fn`` valida el esquema con ``validate_schema``: si falta alguna columna requerida lanza
  ``MissingColumnsError`` con todas las faltantes y no devuelve probabilidades (Req. 8.3). Los NaN
  de columnas presentes se pasan tal cual a XGBoost (Req. 8.7). En ``embeddings`` aplica el
  ``reducer.npz`` a las columnas ``emb_*``;
- salida: CSV (``text/csv``) con ``probability, date, hour_utc, latitude, longitude, config``, una
  fila por fila de entrada y en el mismo orden (Req. 8.1, 8.2).

En el ``sourcedir.tar.gz`` de inferencia este archivo va en la raíz junto a ``reducer.py``; en el
repositorio vive en ``scripts/model/sm_job/``. Por eso se agregan al ``sys.path`` su carpeta y la
superior, y ``reducer`` se importa igual en ambos casos. No importa ``common`` ni ``xarray``.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE.parent, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xgboost as xgb  # noqa: E402
from reducer import Reducer  # noqa: E402

PARQUET = "application/x-parquet"
CSV = "text/csv"
KEY_INPUT = ("date", "hour_utc", "latitude", "longitude")
OUTPUT_COLUMNS = ("probability", "date", "hour_utc", "latitude", "longitude", "config")
PCA_PREFIX = "pca_"


@dataclass
class Bundle:
    """Modelo cargado con sus columnas y, en ``embeddings``, su Reductor."""

    model: xgb.XGBClassifier
    config: str
    input_columns: list[str]  # variables que debe traer la tabla (config_columns)
    model_columns: list[str]  # columnas que ve XGBoost (emb_* reemplazadas por pca_*)
    emb_columns: list[str]
    reducer: Reducer | None = None

    @property
    def required(self) -> list[str]:
        """Columnas que debe traer la entrada: las de salida más las variables del modelo."""
        return [*KEY_INPUT, *self.input_columns]


class MissingColumnsError(ValueError):
    """La entrada no trae columnas requeridas por el modelo; nombra todas las faltantes."""

    def __init__(self, missing: list[str]) -> None:
        """Error con la lista ``missing`` (en el orden de las columnas requeridas)."""
        self.missing = list(missing)
        super().__init__("faltan columnas requeridas por el modelo: " + ", ".join(self.missing))


def validate_schema(df: pd.DataFrame, required: list[str]) -> None:
    """Lanza ``MissingColumnsError`` si a ``df`` le falta alguna columna de ``required``."""
    present = set(df.columns)
    missing = [c for c in required if c not in present]
    if missing:
        raise MissingColumnsError(missing)


def model_fn(model_dir: str) -> Bundle:
    """Carga ``model.json``, ``feature_columns.json``, ``config.json`` y ``reducer.npz``."""
    root = Path(model_dir)
    cols = json.loads((root / "feature_columns.json").read_text(encoding="utf-8"))
    conf = json.loads((root / "config.json").read_text(encoding="utf-8"))
    model = xgb.XGBClassifier()
    model.load_model(str(root / "model.json"))
    red_file = root / "reducer.npz"
    return Bundle(
        model=model,
        config=str(conf["config"]),
        input_columns=list(cols["required"]),
        model_columns=list(cols["model"]),
        emb_columns=list(cols.get("embedding", [])),
        reducer=Reducer.load(red_file) if red_file.is_file() else None,
    )


def _mime(value: str) -> str:
    """Tipo MIME sin parámetros (``text/csv; charset=utf-8`` → ``text/csv``)."""
    return value.split(";")[0].strip().lower()


def input_fn(body: bytes, content_type: str) -> pd.DataFrame:
    """Tabla de entrada desde Parquet; otro tipo de contenido se rechaza."""
    if _mime(content_type) != PARQUET:
        raise ValueError(f"tipo de contenido no admitido {content_type!r}; se espera {PARQUET}")
    return pd.read_parquet(io.BytesIO(body))


def predict_fn(df: pd.DataFrame, bundle: Bundle) -> pd.DataFrame:
    """Probabilidad por fila, en el orden de entrada, con las columnas de ``OUTPUT_COLUMNS``."""
    validate_schema(df, bundle.required)
    data = df.reset_index(drop=True)
    base = [c for c in bundle.model_columns if not c.startswith(PCA_PREFIX)]
    x = data[base].astype(np.float64)
    if bundle.reducer is not None:
        proj = bundle.reducer.transform(data[bundle.emb_columns].to_numpy(dtype=np.float64))
        names = [c for c in bundle.model_columns if c.startswith(PCA_PREFIX)]
        x = pd.concat([x, pd.DataFrame(proj, columns=names)], axis=1)
    p = bundle.model.predict_proba(x[bundle.model_columns])[:, 1] if len(x) else np.zeros(0)
    return pd.DataFrame(
        {
            "probability": np.asarray(p, dtype=np.float64),
            "date": pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d"),
            "hour_utc": data["hour_utc"].astype(int),
            "latitude": data["latitude"].astype(np.float64),
            "longitude": data["longitude"].astype(np.float64),
            "config": bundle.config,
        },
        columns=list(OUTPUT_COLUMNS),
    )


def output_fn(prediction: pd.DataFrame, accept: str) -> bytes:
    """CSV con encabezado y las columnas de ``OUTPUT_COLUMNS``."""
    if _mime(accept) not in (CSV, "*/*", ""):
        raise ValueError(f"tipo de salida no admitido {accept!r}; se espera {CSV}")
    return prediction[list(OUTPUT_COLUMNS)].to_csv(index=False).encode()
