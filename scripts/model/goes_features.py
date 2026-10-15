"""Variables GOES diseñadas a mano por Celda_Hora (lógica pura del Extractor_GOES).

Solo usa NumPy y la biblioteca estándar: no lee archivos ni importa ``common``, para poder probarse
con datos sintéticos e importarse dentro del contenedor de SageMaker. Las funciones reciben
temperaturas de brillo (BT) en kelvin ya decodificadas con ``decode`` y devuelven ``float`` (NaN
cuando no hay datos suficientes).

Variables_GOES (``GOES_FEATURES``):

- ``goes_bt13_min``: BT mínima de la banda 13 (ventana IR limpia, 10,3 µm) en la Ventana_GOES.
- ``goes_cold_frac``: fracción de píxeles válidos de C13 bajo 213,15 K (−60 °C).
- ``goes_wv_ir_max``: máxima diferencia C08 − C13 (vapor de agua − IR), con píxeles válidos en
  ambas bandas; valores cercanos a 0 o positivos indican topes que alcanzan la tropopausa.
- ``goes_cooling_rate``: enfriamiento del tope en K/15 min entre dos barridos separados 15–30 min
  (positivo = el tope se enfría).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np

FILL_VALUE = -1  # _FillValue de los NetCDF de goes_latlon
COLD_THRESHOLD_K = 213.15  # −60 °C
MIN_VALID_FRACTION = 0.5  # bajo esta fracción de C13 válidos, todas las variables son NaN
GOES_FEATURES = ("goes_bt13_min", "goes_cold_frac", "goes_wv_ir_max", "goes_cooling_rate")

SCAN_LOOKBACK = dt.timedelta(minutes=60)  # el barrido de la hora t debe estar en (t − 60 min, t]
PAIR_MIN_MINUTES = 15.0  # separación mínima entre los dos barridos de la tasa de enfriamiento
PAIR_MAX_MINUTES = 30.0  # separación máxima


def decode(raw: np.ndarray, scale: float, offset: float, fill: int = FILL_VALUE) -> np.ndarray:
    """Decodifica enteros crudos a BT en kelvin (``float64``).

    Los valores iguales a ``fill`` se marcan como NaN antes de aplicar ``raw × scale + offset``,
    para que el relleno nunca se convierta en una temperatura plausible (Req. 2.5).
    """
    r = np.asarray(raw)
    return np.where(r == fill, np.nan, r.astype(np.float64) * scale + offset)


def valid_mask(bt: np.ndarray) -> np.ndarray:
    """Máscara de píxeles válidos: valor decodificado finito (el relleno ya es NaN)."""
    return np.isfinite(np.asarray(bt, dtype=np.float64))


def window_features(bt13: np.ndarray, bt08: np.ndarray) -> dict[str, float]:
    """BT mínima de C13, fracción bajo 213,15 K y máx. C08 − C13 de una Ventana_GOES decodificada.

    Devuelve también ``valid_frac_c13`` (fracción de píxeles válidos de C13 sobre el total de la
    ventana). Si esa fracción es menor que ``MIN_VALID_FRACTION``, las tres variables son NaN
    (Req. 2.6). ``goes_wv_ir_max`` usa solo píxeles válidos en ambas bandas y es NaN si no hay
    ninguno. ``bt13`` y ``bt08`` deben tener la misma forma.
    """
    b13 = np.asarray(bt13, dtype=np.float64)
    b08 = np.asarray(bt08, dtype=np.float64)
    if b13.shape != b08.shape:
        raise ValueError(f"C13 y C08 deben tener la misma forma: {b13.shape} != {b08.shape}")
    v13 = valid_mask(b13)
    total = b13.size
    valid_frac = float(v13.sum() / total) if total else 0.0
    nan = float("nan")
    out = {"goes_bt13_min": nan, "goes_cold_frac": nan, "goes_wv_ir_max": nan}
    if total == 0 or valid_frac < MIN_VALID_FRACTION:
        return out | {"valid_frac_c13": valid_frac}
    good = b13[v13]
    out["goes_bt13_min"] = float(good.min())
    out["goes_cold_frac"] = float(np.count_nonzero(good < COLD_THRESHOLD_K) / good.size)
    both = v13 & valid_mask(b08)
    if both.any():
        out["goes_wv_ir_max"] = float((b08[both] - b13[both]).max())
    return out | {"valid_frac_c13": valid_frac}


def cooling_rate(bt_min_early: float, bt_min_late: float, dt_min: float) -> float:
    """Tasa de enfriamiento ``(early − late) × 15 / dt_min`` en K/15 min (positiva si se enfría).

    Es NaN si ``dt_min`` no está en [15, 30] minutos (ambos inclusive) o si alguna BT mínima no es
    finita (Req. 2.4, 2.10).
    """
    early, late, d = float(bt_min_early), float(bt_min_late), float(dt_min)
    if not (np.isfinite(early) and np.isfinite(late) and np.isfinite(d)):
        return float("nan")
    if not PAIR_MIN_MINUTES <= d <= PAIR_MAX_MINUTES:
        return float("nan")
    return (early - late) * 15.0 / d


def select_scan(scan_times: Sequence[dt.datetime], t: dt.datetime) -> int | None:
    """Índice del barrido más reciente con inicio ``s`` en (t − 60 min, t]; ``None`` si no hay.

    Nunca elige barridos con ``s > t`` (sin información del futuro, Req. 6.6, 6.8, 6.9). Con sellos
    repetidos devuelve el primer índice del máximo.
    """
    best: int | None = None
    for i, s in enumerate(scan_times):
        if t - SCAN_LOOKBACK < s <= t and (best is None or s > scan_times[best]):
            best = i
    return best


def select_pair(scan_times: Sequence[dt.datetime], late: int) -> int | None:
    """Índice del barrido anterior a ``late`` separado entre 15 y 30 min (ambos inclusive).

    Prefiere la separación más cercana a 15 min; a igual separación, el primer índice. ``None``
    si no hay ninguno (la tasa de enfriamiento queda en NaN).
    """
    s_late = scan_times[late]
    best: int | None = None
    best_gap = float("inf")
    for i, s in enumerate(scan_times):
        gap = (s_late - s).total_seconds() / 60.0
        if PAIR_MIN_MINUTES <= gap <= PAIR_MAX_MINUTES and gap - PAIR_MIN_MINUTES < best_gap:
            best, best_gap = i, gap - PAIR_MIN_MINUTES
    return best


def window_slice(axis: np.ndarray, center: float, half: float) -> slice:
    """Rebanada contigua de ``axis`` (1D, monótono) con ``|axis − center| ≤ half``.

    Se usa para recortar la Ventana_GOES alrededor de un punto ERA5; si ningún valor cae en el
    rango devuelve una rebanada vacía.
    """
    idx = np.flatnonzero(np.abs(np.asarray(axis, dtype=np.float64) - center) <= half + 1e-9)
    if idx.size == 0:
        return slice(0, 0)
    return slice(int(idx.min()), int(idx.max()) + 1)
