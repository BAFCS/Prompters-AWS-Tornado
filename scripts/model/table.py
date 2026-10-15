"""Constructor_Tabla: etiquetado PU, muestreo, rezagos y tabla por Configuración_Experimento.

Lógica pura sobre ``pandas``/``numpy``: no lee archivos ni importa ``common``, ``xarray``,
``fsspec``, ``h5py`` o ``s3fs`` en tiempo de ejecución, para importarse igual desde
``build_table.py``, ``train_xgboost.py`` y el contenedor de SageMaker (que solo recibe
``scripts/model``). La región llega como un objeto con ``contains(lat, lon)`` (``common.Region``).

Las entradas son tablas en formato largo, una fila por Celda_Hora (``time``, ``latitude``,
``longitude``): índices ERA5 de todas las horas de los días procesados, Variables_GOES del
Extractor_GOES y embeddings por ``cell_id``. ``build`` las une, calcula los rezagos t-1/-2/-3 h
sin información del futuro y devuelve las columnas clave más ``config_columns(config)``, en orden
``(time, latitude, longitude)`` (determinista, Req. 6.13).

Identificadores (Data Models del diseño):

- ``cell_id``: ``AAAAMMDDHH_<lat:+06.2f>_<lon:+07.2f>`` (p. ej. ``2019053018_-37.25_-072.50``).
- ``event_id``: ``AAAAMMDD-<fila del Catálogo>``; vacío en las no etiquetadas.
- ``fold_group``: ``event_id`` en las positivas; en las no etiquetadas, uno de los Eventos del mismo
  día (o de todos si el día no tiene) elegido con sha256 de ``cell_id`` y la semilla.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from goes_features import GOES_FEATURES

if TYPE_CHECKING:
    import common

# Las 12 variables ERA5 de train_xgboost.py, con su signo físico austral (SRH y STP negativos).
ERA5_FEATURES = (
    "cape",
    "shear_01",
    "shear_03",
    "shear_06",
    "srh_01",
    "srh_03",
    "lcl",
    "gamma_03",
    "gamma_75",
    "vgp_01",
    "stp_lm",
    "sherbs3",
)
CONFIGS = ("baseline_era5", "physical", "embeddings")
LAGS = (1, 2, 3)
LAGGED = (*ERA5_FEATURES, *GOES_FEATURES)  # 16 variables con rezagos en physical/embeddings
POINT = ["time", "latitude", "longitude"]
KEY_COLUMNS = (
    "cell_id",
    "time",
    "date",
    "hour_utc",
    "latitude",
    "longitude",
    "label",
    "event_id",
    "fold_group",
)
INFER_KEY_COLUMNS = ("cell_id", "time", "date", "hour_utc", "latitude", "longitude")
CELL_COLUMNS = ("cell_id", "time", "latitude", "longitude", "label", "event_id", "fold_group")
POSITIVE_COLUMNS = ("cell_id", "time", "latitude", "longitude", "label", "event_id")
SKIPPED_COLUMNS = ("event_id", "reason")
MIN_RATIO, MAX_RATIO = 1, 1000
TIE_TOL = 1e-12  # distancias² que difieren menos que esto se consideran empate
SCAN_LOOKBACK = pd.Timedelta(minutes=60)

# Columnas de la hoja Final_Table del Catálogo.
CATALOG_DATE = "Date (Gregorian Calendar)"
CATALOG_LAT = "Latitude"
CATALOG_LON = "Longitude"
CATALOG_HOUR = "Hour (UTC)"
COLLISION = "colisión"


def utc(values: pd.Series | Sequence) -> pd.Series:
    """Tiempos como ``datetime64[ns, UTC]`` (los tiempos sin zona se toman como UTC)."""
    return pd.Series(pd.to_datetime(values, utc=True)).astype("datetime64[ns, UTC]")


def coordinate(value: object) -> float:
    """Convierte una coordenada del Catálogo (texto o número) a grados decimales con signo."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    s = str(value).strip().replace(",", ".")
    sign = -1.0 if any(c in s.upper() for c in ("S", "W", "O", "-")) else 1.0
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return sign * abs(float(digits))
    except ValueError:
        return float("nan")


def parse_hour(value: object) -> float:
    """Hora UTC decimal de la celda ``Hour (UTC)`` (``"18:30"`` → 18,5; ``"22-23:25"`` → 22).

    NaN si no hay hora o si es inválida (hora > 23 o minutos > 59).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?", str(value))
    if not m:
        return float("nan")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return float("nan")
    return h + mi / 60.0


def normalize_catalog(raw: pd.DataFrame) -> pd.DataFrame:
    """Agrega ``date``, ``lat``, ``lon`` y ``hour_utc`` a la hoja ``Final_Table`` del Catálogo.

    Conserva las columnas y el índice de ``raw`` (el índice de fila forma el ``event_id``).
    """
    d = raw.copy()
    dates = pd.to_datetime(raw[CATALOG_DATE], errors="coerce")
    d["date"] = [None if pd.isna(x) else x.date() for x in dates]
    d["lat"] = raw[CATALOG_LAT].map(coordinate).astype(float)
    d["lon"] = raw[CATALOG_LON].map(coordinate).astype(float)
    d["hour_utc"] = raw[CATALOG_HOUR].map(parse_hour).astype(float)
    return d


def make_cell_id(time: object, lat: float, lon: float) -> str:
    """Identificador ``AAAAMMDDHH_<lat:+06.2f>_<lon:+07.2f>`` de una Celda_Hora."""
    t = pd.Timestamp(time)  # type: ignore[arg-type]
    return f"{t:%Y%m%d%H}_{lat:+06.2f}_{lon:+07.2f}"


def make_event_id(day: dt.date, row: object) -> str:
    """Identificador ``AAAAMMDD-<fila>`` de un Evento del Catálogo."""
    return f"{day:%Y%m%d}-{row}"


def event_order(event_id: str) -> tuple[str, int, str]:
    """Clave de orden de ``event_id``: fecha y luego número de fila (``-9`` antes que ``-10``)."""
    day, _, row = event_id.partition("-")
    return day, int(row) if row.isdigit() else -1, event_id


def round_hour(day: dt.date, hour_utc: float) -> pd.Timestamp:
    """Hora UTC del Evento redondeada a la hora entera más cercana (``:30`` sube)."""
    t = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=float(hour_utc))
    return (t + pd.Timedelta(minutes=30)).floor("h")


def nearest_point(
    lat: np.ndarray, lon: np.ndarray, ev_lat: float, ev_lon: float
) -> tuple[float, float]:
    """Punto de la grilla (``lat`` × ``lon``) más cercano al Evento (Req. 6.2).

    Distancia en grados con la longitud escalada por ``cos(lat del Evento)``; los empates se
    resuelven por menor latitud y luego menor longitud.
    """
    la, lo = np.meshgrid(np.asarray(lat, float), np.asarray(lon, float), indexing="ij")
    k = math.cos(math.radians(ev_lat))
    d2 = (la - ev_lat) ** 2 + ((lo - ev_lon) * k) ** 2
    cand = d2 <= d2.min() + TIE_TOL
    la_c, lo_c = la[cand], lo[cand]
    i = int(np.lexsort((lo_c, la_c))[0])
    return float(la_c[i]), float(lo_c[i])


def _finite(x: object) -> bool:
    """``True`` si ``x`` es un número finito."""
    try:
        return math.isfinite(float(x))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def label_positives(
    catalog: pd.DataFrame,
    lat: np.ndarray,
    lon: np.ndarray,
    region: common.Region,
    times: Iterable | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Celdas_Hora positivas del Catálogo normalizado y Eventos omitidos con su motivo.

    Cada Evento con fecha, coordenadas y hora UTC dentro de ``region`` se asigna al punto ERA5 más
    cercano y a su hora redondeada. Si se dan ``times`` (horas ERA5 procesadas), los Eventos cuya
    hora no está se omiten. Si varios Eventos caen en la misma Celda_Hora, gana el ``event_id``
    menor (``event_order``) y los demás se omiten como colisión (Req. 6.10-6.12).
    """
    available = set(utc(list(times))) if times is not None else None
    rows: list[dict] = []
    skipped: list[dict] = []
    for idx, day, ev_lat, ev_lon, hour in zip(
        catalog.index.tolist(),
        catalog["date"].tolist(),
        catalog["lat"].tolist(),
        catalog["lon"].tolist(),
        catalog["hour_utc"].tolist(),
        strict=True,
    ):
        if day is None or pd.isna(day):
            skipped.append({"event_id": f"sin-fecha-{idx}", "reason": "sin fecha"})
            continue
        eid = make_event_id(day, idx)
        if not (_finite(ev_lat) and _finite(ev_lon)):
            skipped.append({"event_id": eid, "reason": "sin coordenadas"})
            continue
        if not _finite(hour):
            skipped.append({"event_id": eid, "reason": "sin hora UTC"})
            continue
        if not bool(region.contains(np.asarray(float(ev_lat)), np.asarray(float(ev_lon)))):
            skipped.append({"event_id": eid, "reason": "fuera de la región"})
            continue
        t = round_hour(day, float(hour))
        if available is not None and t not in available:
            skipped.append(
                {"event_id": eid, "reason": f"sin índices ERA5 para {t:%Y-%m-%d %H} UTC"}
            )
            continue
        la, lo = nearest_point(lat, lon, float(ev_lat), float(ev_lon))
        rows.append(
            {
                "cell_id": make_cell_id(t, la, lo),
                "time": t,
                "latitude": la,
                "longitude": lo,
                "label": 1,
                "event_id": eid,
            }
        )
    winners: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: event_order(r["event_id"])):
        if r["cell_id"] in winners:
            first = winners[r["cell_id"]]["event_id"]
            reason = f"{COLLISION}: misma Celda_Hora que {first}"
            skipped.append({"event_id": r["event_id"], "reason": reason})
        else:
            winners[r["cell_id"]] = r
    pos = pd.DataFrame(list(winners.values()), columns=list(POSITIVE_COLUMNS))
    pos["time"] = utc(pos["time"])
    pos["label"] = pos["label"].astype("int8")
    pos = pos.sort_values(POINT, kind="mergesort").reset_index(drop=True)
    return pos, pd.DataFrame(skipped, columns=list(SKIPPED_COLUMNS))


def candidate_cells(times: Iterable, lat: np.ndarray, lon: np.ndarray) -> pd.DataFrame:
    """Todas las Celdas_Hora (``times`` × ``lat`` × ``lon``) con su ``cell_id``, en orden canónico."""
    ts = utc(list(times)).drop_duplicates().sort_values().reset_index(drop=True)
    la = np.asarray(lat, dtype=np.float64)
    lo = np.asarray(lon, dtype=np.float64)
    idx = pd.MultiIndex.from_product([ts, la, lo], names=POINT)
    df = idx.to_frame(index=False)
    df["time"] = utc(df["time"])
    df.insert(
        0,
        "cell_id",
        [
            make_cell_id(t, y, x)
            for t, y, x in zip(
                df["time"], df["latitude"].tolist(), df["longitude"].tolist(), strict=True
            )
        ],
    )
    return df.sort_values(POINT, kind="mergesort").reset_index(drop=True)


def sample_unlabeled(
    candidates: pd.DataFrame, n_pos: int, ratio: int, seed: int, exclude: Iterable[str] = ()
) -> pd.DataFrame:
    """Muestra sin reemplazo de ``ratio × n_pos`` Celdas_Hora no etiquetadas (Req. 6.3).

    Excluye los ``cell_id`` de ``exclude`` (las positivas) y muestrea con
    ``np.random.default_rng(seed)`` sobre las candidatas en orden ``(time, latitude, longitude)``.
    Si hay menos candidatas que las pedidas, toma todas y avisa. ``ratio`` debe estar en 1..1000.
    """
    if isinstance(ratio, bool) or not isinstance(ratio, int) or not MIN_RATIO <= ratio <= MAX_RATIO:
        raise ValueError(f"ratio={ratio!r} fuera del rango permitido [{MIN_RATIO}, {MAX_RATIO}]")
    excluded = set(exclude)
    pool = candidates[~candidates["cell_id"].isin(excluded)].drop_duplicates("cell_id")
    pool = pool.sort_values(POINT, kind="mergesort").reset_index(drop=True)
    size = ratio * int(n_pos)
    if size > len(pool):
        print(
            f"  aviso: se pidieron {size} Celdas_Hora no etiquetadas y hay {len(pool)}; "
            "se toman todas",
            flush=True,
        )
        size = len(pool)
    if size == 0:
        return pool.iloc[:0].copy()
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(pool), size=size, replace=False))
    return pool.iloc[pick].reset_index(drop=True)


def fold_bucket(cell_id: str, seed: int, n: int) -> int:
    """Índice determinista en ``[0, n)`` a partir de sha256 de ``"<cell_id>|<seed>"``."""
    h = hashlib.sha256(f"{cell_id}|{seed}".encode()).hexdigest()
    return int(h[:16], 16) % n


def assign_fold_groups(table: pd.DataFrame, seed: int) -> pd.Series:
    """``fold_group`` de cada fila: el ``event_id`` en positivas; un Evento del día en las demás.

    Las no etiquetadas de un día con Eventos se reparten entre esos Eventos; las de días sin Evento,
    entre todos. Sin Eventos, el grupo queda vacío.
    """
    days = utc(table["time"]).dt.date.tolist()
    labels = table["label"].astype(int).tolist()
    ids = table["event_id"].fillna("").astype(str).tolist()
    by_day: dict[dt.date, set[str]] = {}
    for d, lab, eid in zip(days, labels, ids, strict=True):
        if lab == 1:
            by_day.setdefault(d, set()).add(eid)
    day_events = {d: sorted(v, key=event_order) for d, v in by_day.items()}
    all_events = sorted({e for v in by_day.values() for e in v}, key=event_order)
    out: list[str] = []
    for cid, d, lab, eid in zip(
        table["cell_id"].astype(str).tolist(), days, labels, ids, strict=True
    ):
        if lab == 1:
            out.append(eid)
            continue
        evs = day_events.get(d) or all_events
        out.append(evs[fold_bucket(cid, seed, len(evs))] if evs else "")
    return pd.Series(out, index=table.index, name="fold_group", dtype=object)


def select_cells(
    catalog: pd.DataFrame,
    times: Iterable,
    lat: np.ndarray,
    lon: np.ndarray,
    region: common.Region,
    ratio: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Etapa ``select``: positivas, muestra no etiquetada y ``fold_group`` (``cells.parquet``).

    Devuelve ``(cells, skipped)``; ``cells`` tiene ``CELL_COLUMNS`` en orden canónico.
    """
    times = list(times)
    pos, skipped = label_positives(catalog, lat, lon, region, times)
    cand = candidate_cells(times, lat, lon)
    unl = sample_unlabeled(cand, len(pos), ratio, seed, pos["cell_id"].tolist())
    unl = unl.assign(label=np.int8(0), event_id="")
    cells = pd.concat([pos, unl[list(POSITIVE_COLUMNS)]], ignore_index=True)
    cells["label"] = cells["label"].astype("int8")
    cells = cells.sort_values(POINT, kind="mergesort").reset_index(drop=True)
    cells["fold_group"] = assign_fold_groups(cells, seed)
    return cells[list(CELL_COLUMNS)], skipped


def add_lags(hourly: pd.DataFrame, cols: Sequence[str], lags: Sequence[int] = LAGS) -> pd.DataFrame:
    """Agrega ``<var>_lag{k}`` (valor en t - k h del mismo punto) y ``<var>_d{k}`` (t menos t - k).

    El rezago se busca por hora exacta (equivale a reindexar la serie horaria de cada punto sin
    huecos y desplazarla ``k`` horas): si la hora t - k no existe o vale NaN, el rezago y la
    diferencia son NaN. No elimina ni reordena filas (Req. 6.5-6.7). Falla si hay filas repetidas
    por ``(time, latitude, longitude)``.
    """
    df = hourly.reset_index(drop=True).copy()
    df["time"] = utc(df["time"])
    if df.duplicated(POINT).any():
        raise ValueError("hay filas repetidas por (time, latitude, longitude)")
    base = df[[*POINT, *cols]]
    out = df
    for k in lags:
        shifted = base.copy()
        shifted["time"] = shifted["time"] + pd.Timedelta(hours=k)
        shifted = shifted.rename(columns={c: f"{c}_lag{k}" for c in cols})
        out = out.merge(shifted, on=POINT, how="left", validate="one_to_one")
    for k in lags:
        for c in cols:
            out[f"{c}_d{k}"] = out[c] - out[f"{c}_lag{k}"]
    return out


def emb_columns(n_emb: int) -> list[str]:
    """``emb_0000`` ... ``emb_{n-1}``."""
    return [f"emb_{i:04d}" for i in range(n_emb)]


def config_columns(config: str, n_emb: int = 0) -> list[str]:
    """Columnas de variables (``X``) de la Configuración_Experimento, en orden fijo.

    ``baseline_era5``: las 12 ERA5 en t. ``physical``: las 16 variables (ERA5 + GOES) en t y, por
    cada una, ``_lag1..3`` y ``_d1..3`` (112). ``embeddings``: ``physical`` más ``emb_*`` crudos.
    """
    if config == "baseline_era5":
        return list(ERA5_FEATURES)
    if config not in CONFIGS:
        raise ValueError(f"configuración desconocida {config!r}; usa una de {list(CONFIGS)}")
    cols: list[str] = list(LAGGED)
    for c in LAGGED:
        cols += [f"{c}_lag{k}" for k in LAGS] + [f"{c}_d{k}" for k in LAGS]
    if config == "embeddings":
        if n_emb < 1:
            raise ValueError("la configuración embeddings necesita al menos una columna emb_*")
        cols += emb_columns(n_emb)
    return cols


def _point_frame(df: pd.DataFrame | None, cols: Sequence[str]) -> pd.DataFrame:
    """``df[POINT + cols]`` con tiempos en UTC y las columnas faltantes en NaN."""
    if df is None:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in [*POINT, *cols]}).assign(
            time=utc([])
        )
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    out = out[[*POINT, *cols]].copy()
    out["time"] = utc(out["time"])
    return out


def _goes_frame(goes: pd.DataFrame | None) -> pd.DataFrame:
    """Variables_GOES por Celda_Hora; NaN si el barrido no está en (t - 60 min, t] (Req. 6.6-6.9)."""
    g = _point_frame(goes, GOES_FEATURES)
    if goes is not None and "scan_start" in goes.columns:
        s = utc(goes["scan_start"].reset_index(drop=True))
        t = g["time"].reset_index(drop=True)
        bad = (~((s > t - SCAN_LOOKBACK) & (s <= t))).to_numpy()
        g = g.reset_index(drop=True)
        g.loc[bad, list(GOES_FEATURES)] = np.nan
    return g


def build(
    config: str,
    cells: pd.DataFrame,
    era5: pd.DataFrame,
    goes: pd.DataFrame | None = None,
    embeddings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Tabla de la Configuración_Experimento ``config``: una fila por Celda_Hora de ``cells``.

    ``cells`` trae ``cell_id, time, latitude, longitude`` y, en entrenamiento, ``label``,
    ``event_id`` y ``fold_group`` (sin ``label`` se arma una tabla de inferencia, solo con
    ``INFER_KEY_COLUMNS``). ``era5`` tiene los índices ERA5 por hora y punto (todas las horas
    disponibles, para los rezagos); ``goes``, las Variables_GOES (con ``scan_start`` opcional);
    ``embeddings``, ``cell_id`` y ``emb_*`` (solo ``embeddings``). Lo que falta queda en NaN.
    """
    if config not in CONFIGS:
        raise ValueError(f"configuración desconocida {config!r}; usa una de {list(CONFIGS)}")
    labeled = "label" in cells.columns
    keys = list(KEY_COLUMNS if labeled else INFER_KEY_COLUMNS)
    c = cells.copy()
    c["time"] = utc(c["time"])
    if "cell_id" not in c.columns:
        c["cell_id"] = [
            make_cell_id(t, y, x)
            for t, y, x in zip(
                c["time"], c["latitude"].tolist(), c["longitude"].tolist(), strict=True
            )
        ]
    if c["cell_id"].duplicated().any():
        raise ValueError("cells tiene cell_id repetidos")
    hourly = _point_frame(era5, ERA5_FEATURES)
    if hourly.duplicated(POINT).any():
        raise ValueError("los índices ERA5 tienen filas repetidas por (time, latitude, longitude)")
    n_emb = 0
    if config != "baseline_era5":
        g = _goes_frame(goes)
        if g.duplicated(POINT).any():
            raise ValueError(
                "las Variables_GOES tienen filas repetidas por (time, latitude, longitude)"
            )
        hourly = hourly.merge(g, on=POINT, how="outer")
        hourly = add_lags(hourly, LAGGED)
    base_cols = [
        k for k in ("cell_id", *POINT, "label", "event_id", "fold_group") if k in c.columns
    ]
    table = c[base_cols].merge(hourly, on=POINT, how="left", validate="one_to_one")
    if config == "embeddings":
        if embeddings is None:
            raise ValueError("la configuración embeddings necesita la tabla de embeddings")
        emb_cols = sorted(col for col in embeddings.columns if str(col).startswith("emb_"))
        n_emb = len(emb_cols)
        emb = embeddings[["cell_id", *emb_cols]].drop_duplicates("cell_id")
        table = table.merge(emb, on="cell_id", how="left", validate="one_to_one")
    table["date"] = table["time"].dt.date
    table["hour_utc"] = table["time"].dt.hour.astype("int8")
    if labeled:
        table["label"] = table["label"].astype("int8")
        for k in ("event_id", "fold_group"):
            if k not in table.columns:
                table[k] = ""
            table[k] = table[k].fillna("").astype(str)
    feats = config_columns(config, n_emb)
    for col in feats:
        if col not in table.columns:
            table[col] = np.nan
    table[feats] = table[feats].astype("float64")
    table = table.sort_values(POINT, kind="mergesort").reset_index(drop=True)
    return table[keys + feats]
