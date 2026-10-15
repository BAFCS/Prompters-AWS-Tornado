"""Diseño de la submuestra de entrenamiento: positivos (con vecindad que sigue al tornado) y
negativos estratificados, SIN descargar ni procesar nada.

Separa el *qué* del *cómo*: aquí solo se decide qué celdas-hora componen la muestra y se escribe un
manifiesto (una tabla). La descarga y el cálculo de variables (lo costoso) ocurren después, solo
sobre los días que el manifiesto pide. Así se puede iterar el diseño del muestreo gratis.

Decisiones de muestreo (configurables):

- **Positivos.** Un tornado no es un punto fijo: se desplaza y su entorno favorable es de mesoescala.
  Por eso cada evento aporta una **vecindad espacial** (``neighbor`` celdas ERA5 alrededor, por
  defecto 3×3) a lo largo de una **ventana temporal** (``hours`` horas alrededor de la hora UTC, por
  defecto ±2 h). Esa vecindad cubre la trayectoria del tornado durante la ventana.
- **Negativos.** Días SIN evento, estratificados por estación (primavera/verano/otoño, cuando hay
  convección en el centro-sur) para dar varianza. Se respeta una **zona de exclusión**: ningún
  negativo cae a menos de ``exclusion_km`` / ``exclusion_h`` de un tornado conocido, para no
  etiquetar como negativo algo que estaba junto a un evento (el catálogo solo tiene positivos).
- **Proporción.** ``ratio`` negativos por positivo (por defecto 10:1).
- **Split temporal.** Columna ``split``: los eventos más recientes (desde ``test_from``) van a
  *test*; el resto a *train*. Mide si el modelo generaliza a eventos futuros que no vio.

El manifiesto NO fija aún las celdas negativas exactas (eso necesita la grilla real de cada día);
fija los **días** negativos y cuántas celdas-hora tomar de cada uno. La materialización elige las
celdas concretas respetando la exclusión.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

GOES16_START = dt.date(2017, 12, 1)  # GOES-16 operacional sobre Chile; antes no hay imagen


@dataclass(frozen=True)
class SampleConfig:
    """Parámetros del muestreo. Los valores por defecto son los acordados con el equipo."""

    neighbor: int = 3  # lado de la vecindad espacial en celdas ERA5 (3 → 3×3 alrededor del evento)
    hours: int = 2  # ventana temporal ±hours alrededor de la hora del evento
    ratio: int = 10  # negativos por cada positivo
    exclusion_km: float = 100.0  # ningún negativo a menos de esta distancia de un tornado
    exclusion_h: int = 3  # ni a menos de estas horas
    negative_days: int = 25  # días SIN evento a muestrear, estratificados por estación
    test_from: dt.date = field(default_factory=lambda: dt.date(2023, 1, 1))  # split temporal
    seed: int = 0


def _season(d: dt.date) -> str:
    """Estación del hemisferio sur para la fecha ``d`` (para estratificar los negativos)."""
    m = d.month
    if m in (12, 1, 2):
        return "verano"
    if m in (3, 4, 5):
        return "otonio"
    if m in (6, 7, 8):
        return "invierno"
    return "primavera"


def event_days(catalog: pd.DataFrame) -> pd.DataFrame:
    """Eventos del catálogo en la era de GOES-16 con fecha, hora UTC y coordenadas válidas.

    Espera un catálogo ya normalizado (columnas ``date``, ``lat``, ``lon``, ``hour_utc``).
    """
    d = catalog.copy()
    d = d[d["date"].notna() & (d["date"] >= GOES16_START)]
    d = d[d["lat"].notna() & d["lon"].notna() & d["hour_utc"].notna()]
    return d.reset_index(drop=True)


def positive_rows(events: pd.DataFrame, cfg: SampleConfig) -> pd.DataFrame:
    """Filas positivas amplificadas: vecindad ``neighbor``×``neighbor`` × ventana ±``hours``.

    Para cada evento genera una fila por (desplazamiento de celda, hora de la ventana). Los
    desplazamientos de celda se expresan como pasos relativos (``di``, ``dj``) sobre la grilla ERA5;
    la materialización los convierte en índices reales. La ventana cubre el movimiento del tornado.
    """
    half = cfg.neighbor // 2
    offsets = [(di, dj) for di in range(-half, half + 1) for dj in range(-half, half + 1)]
    hour_shifts = list(range(-cfg.hours, cfg.hours + 1))

    rows: list[dict] = []
    for _, ev in events.iterrows():
        event_id = f"{ev['date']:%Y%m%d}-{int(ev['hour_utc']):02d}-{ev.name}"
        split = "test" if ev["date"] >= cfg.test_from else "train"
        for dh in hour_shifts:
            hour = (int(ev["hour_utc"]) + dh) % 24
            for di, dj in offsets:
                rows.append({
                    "event_id": event_id,
                    "day": ev["date"],
                    "lat": ev["lat"],
                    "lon": ev["lon"],
                    "di": di,  # paso de celda en latitud respecto a la del evento
                    "dj": dj,  # paso de celda en longitud
                    "hour": hour,
                    "label": 1,
                    "season": _season(ev["date"]),
                    "split": split,
                    "kind": "tornado" if ev.get("Tornado", 0) == 1 else "tromba",
                })
    return pd.DataFrame(rows)


def negative_days_plan(events: pd.DataFrame, cfg: SampleConfig) -> pd.DataFrame:
    """Elige días SIN evento, estratificados por estación, lejos de cualquier día con tornado.

    Devuelve una tabla de días negativos con su estación y el split temporal. Las celdas concretas
    de cada día las elige la materialización (necesita la grilla real y la zona de exclusión).
    """
    rng = np.random.default_rng(cfg.seed)
    event_dates = set(events["date"])
    # Rango temporal: desde GOES-16 hasta hoy.
    start, end = GOES16_START, dt.date.today()
    all_days = [start + dt.timedelta(days=k) for k in range((end - start).days)]

    # Excluir días con evento y días a ±exclusion_h/24 de uno (aprox., día completo por simplicidad).
    forbidden = set()
    for ed in event_dates:
        for off in range(-1, 2):  # el día del evento y los adyacentes
            forbidden.add(ed + dt.timedelta(days=off))
    candidates = [d for d in all_days if d not in forbidden]

    # Estratificar: repartir los negative_days entre las estaciones con convección.
    by_season: dict[str, list[dt.date]] = {"primavera": [], "verano": [], "otonio": []}
    for d in candidates:
        s = _season(d)
        if s in by_season:
            by_season[s].append(d)

    per = max(cfg.negative_days // len(by_season), 1)
    picked: list[dt.date] = []
    for pool in by_season.values():
        if pool:
            idx = rng.choice(len(pool), size=min(per, len(pool)), replace=False)
            picked.extend(pool[i] for i in idx)

    picked = sorted(picked)[: cfg.negative_days]
    return pd.DataFrame({
        "day": picked,
        "season": [_season(d) for d in picked],
        "split": ["test" if d >= cfg.test_from else "train" for d in picked],
    })


def summarize(positives: pd.DataFrame, neg_days: pd.DataFrame, cfg: SampleConfig) -> dict:
    """Resumen del plan de muestreo (para registrar y revisar antes de descargar)."""
    n_events = positives["event_id"].nunique() if len(positives) else 0
    target_neg = len(positives) * cfg.ratio
    per_neg_day = int(np.ceil(target_neg / max(len(neg_days), 1)))
    return {
        "eventos": n_events,
        "filas_positivas": len(positives),
        "dias_negativos": len(neg_days),
        "filas_negativas_objetivo": target_neg,
        "celdas_por_dia_negativo": per_neg_day,
        "proporcion": f"{cfg.ratio}:1",
        "ventana": f"{cfg.neighbor}x{cfg.neighbor} celdas, ±{cfg.hours} h",
        "split_test_desde": str(cfg.test_from),
        "train_positivos": int((positives["split"] == "train").sum()),
        "test_positivos": int((positives["split"] == "test").sum()),
    }
