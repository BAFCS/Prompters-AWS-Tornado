"""Lectura y validación de CSV_Predicciones y sus metadatos (compartido por sitio y alertas).

`load` solo lee archivos: el CSV `pred_AAAAMMDD.csv` y su `pred_AAAAMMDD.meta.json`. Ante cualquier
falla de esquema o de contenido lanza `InvalidPredictions` con un mensaje en castellano que nombra
el archivo y el motivo (Req. 6.10 y 7.13).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = ("probability", "date", "hour_utc", "latitude", "longitude", "config")
KEY = ("date", "hour_utc", "latitude", "longitude")
MODELOS = ("real", "sustituto")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Predictions:
    """CSV_Predicciones validado: tabla con columnas `SCHEMA`, metadatos y ruta de origen."""

    df: pd.DataFrame
    meta: dict
    path: Path


class InvalidPredictions(ValueError):
    """CSV_Predicciones o metadatos inválidos; el mensaje nombra el archivo y el motivo."""


def meta_path(csv: Path) -> Path:
    """Ruta de metadatos de un CSV: `pred_X.csv` -> `pred_X.meta.json`."""
    csv = Path(csv)
    return csv.with_name(f"{csv.stem}.meta.json")


def _fail(path: Path, reason: str) -> InvalidPredictions:
    return InvalidPredictions(f"{path}: {reason}")


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    """Columna convertida a float; valores no numéricos o vacíos quedan como NaN."""
    return pd.to_numeric(df[column].str.strip(), errors="coerce").astype(float)


def _valid_date(value: str) -> bool:
    """True si `value` es una fecha de calendario real con formato AAAA-MM-DD."""
    if not _DATE_RE.match(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _read_meta(csv: Path) -> dict:
    path = meta_path(csv)
    if not path.is_file():
        raise _fail(path, f"faltan los metadatos del CSV {csv.name}")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(path, f"metadatos ilegibles ({exc})") from exc
    if not isinstance(meta, dict):
        raise _fail(path, "los metadatos no son un objeto JSON")
    if "modelo" not in meta:
        raise _fail(path, "los metadatos no indican 'modelo'")
    if meta["modelo"] not in MODELOS:
        raise _fail(path, f"'modelo' inválido {meta['modelo']!r}; se esperaba 'real' o 'sustituto'")
    return meta


def load(csv: Path) -> Predictions:
    """Lee y valida un CSV_Predicciones y sus metadatos.

    Exige columnas exactas = `SCHEMA` (mismo orden); `probability` en [0, 1] y sin NaN;
    `hour_utc` entero 0..23; `date` AAAA-MM-DD válida; latitud y longitud numéricas; sin
    duplicados en (date, hour_utc, latitude, longitude); metadatos presentes con `modelo` en
    {'real', 'sustituto'}. Si algo falla, `InvalidPredictions`.
    """
    csv = Path(csv)
    if not csv.is_file():
        raise _fail(csv, "el CSV de predicciones no existe")
    try:
        raw = pd.read_csv(csv, dtype=str, keep_default_na=False)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise _fail(csv, f"CSV ilegible ({exc})") from exc

    columns = tuple(str(c) for c in raw.columns)
    if columns != SCHEMA:
        missing = [c for c in SCHEMA if c not in columns]
        extra = [c for c in columns if c not in SCHEMA]
        detail = []
        if missing:
            detail.append(f"faltan {missing}")
        if extra:
            detail.append(f"sobran {extra}")
        if not detail:
            detail.append(f"orden {list(columns)}")
        raise _fail(csv, f"columnas distintas del esquema {','.join(SCHEMA)}: {'; '.join(detail)}")

    prob = _numeric(raw, "probability")
    if prob.isna().any():
        raise _fail(csv, f"'probability' con NaN o no numérica en {int(prob.isna().sum())} filas")
    out_of_range = (prob < 0) | (prob > 1)
    if out_of_range.any():
        raise _fail(csv, f"'probability' fuera de [0, 1] en {int(out_of_range.sum())} filas")

    hour = _numeric(raw, "hour_utc")
    bad_hour = hour.isna() | (hour != np.floor(hour)) | (hour < 0) | (hour > 23)
    if bad_hour.any():
        first = raw["hour_utc"][bad_hour].iloc[0]
        raise _fail(csv, f"'hour_utc' fuera de 0–23 o no entera (p. ej. {first!r})")

    dates = raw["date"].str.strip()
    for value in dates.unique():
        if not _valid_date(value):
            raise _fail(csv, f"'date' no tiene formato AAAA-MM-DD: {value!r}")

    lat = _numeric(raw, "latitude")
    lon = _numeric(raw, "longitude")
    if lat.isna().any() or lon.isna().any():
        raise _fail(csv, "'latitude' o 'longitude' vacía o no numérica")

    df = pd.DataFrame(
        {
            "probability": prob,
            "date": dates,
            "hour_utc": hour.astype(int),
            "latitude": lat,
            "longitude": lon,
            "config": raw["config"],
        }
    )
    dup = df.duplicated(subset=list(KEY))
    if dup.any():
        raise _fail(
            csv, f"filas duplicadas en (date, hour_utc, latitude, longitude): {int(dup.sum())}"
        )

    return Predictions(df=df, meta=_read_meta(csv), path=csv)
