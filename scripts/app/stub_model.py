"""Modelo_Sustituto: Índice_Favorabilidad heurístico cuando no hay artefactos del Modelo_Real.

Puntaje por fila = ``clip(cape / CAPE_REF, 0, 1) * clip(shear_06 / SHEAR_REF, 0, 1)``. Es monótono
no decreciente en CAPE y en cizalladura y siempre queda en [0, 1] (Req. 5.4, 5.8). Una fila con
NaN en CAPE o cizalladura vale 0 (Req. 5.7); los infinitos se recortan como cualquier otro valor
(``+inf`` → 1, ``-inf`` → 0) y los negativos quedan en 0.

``predict`` devuelve las mismas columnas, orden y formato que ``inference.predict_fn`` de Daniel
(``date`` como texto ``%Y-%m-%d``, ``hour_utc`` entero), con ``config = "sustituto/<config>"``.
Módulo puro: no importa ``xgboost`` ni ``inference.py`` para que el sustituto siga liviano.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CAPE_REF = 1000.0  # J/kg
SHEAR_REF = 25.0  # m/s (shear_06)
REQUIRED = ("cape", "shear_06")
# Copia de inference.OUTPUT_COLUMNS (scripts/model/sm_job/inference.py). No se importa para no
# arrastrar xgboost; tests/test_app_contracts.py y tests/test_app_stub_model.py vigilan que
# coincidan en contenido y orden.
OUTPUT_COLUMNS = ("probability", "date", "hour_utc", "latitude", "longitude", "config")
CONFIG_PREFIX = "sustituto/"


def _ratio(values: np.ndarray, ref: float) -> np.ndarray:
    """``values / ref`` recortado a [0, 1]; NaN se conserva para tratarlo aparte."""
    return np.clip(np.asarray(values, dtype=np.float64) / ref, 0.0, 1.0)


def score(cape: np.ndarray, shear: np.ndarray) -> np.ndarray:
    """clip(cape/CAPE_REF, 0, 1) * clip(shear/SHEAR_REF, 0, 1); NaN en cualquiera -> 0.

    Monótona no decreciente en ambos argumentos, valores en [0, 1].
    """
    c = _ratio(cape, CAPE_REF)
    s = _ratio(shear, SHEAR_REF)
    out = c * s
    # NaN en cualquiera de los dos factores (incluye 0 * NaN) → 0.
    return np.where(np.isnan(c) | np.isnan(s), 0.0, out)


def predict(df: pd.DataFrame, config: str) -> pd.DataFrame:
    """Mismas columnas y orden que inference.predict_fn (OUTPUT_COLUMNS), config = 'sustituto/<config>'.

    Supone que ``df`` ya trae las columnas clave y ``REQUIRED`` (lo valida ``infer.run``).
    """
    data = df.reset_index(drop=True)
    p = score(
        pd.to_numeric(data["cape"], errors="coerce").to_numpy(dtype=np.float64),
        pd.to_numeric(data["shear_06"], errors="coerce").to_numpy(dtype=np.float64),
    )
    return pd.DataFrame(
        {
            "probability": p,
            "date": pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d"),
            "hour_utc": data["hour_utc"].astype(int),
            "latitude": data["latitude"].astype(np.float64),
            "longitude": data["longitude"].astype(np.float64),
            "config": CONFIG_PREFIX + config,
        },
        columns=list(OUTPUT_COLUMNS),
    )
