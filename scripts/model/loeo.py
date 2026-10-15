"""Validación_LOEO: particiones por Evento, XGBoost con parada temprana interna y Métricas.

Lógica pura sobre ``numpy``/``pandas``/``xgboost``/``scikit-learn``: no importa ``common``,
``xarray``, ``fsspec``, ``h5py`` ni ``s3fs``, para correr igual en ``train_xgboost.py`` (local o
EC2) y dentro del contenedor de SageMaker (``sm_job/train_entry.py``), que solo recibe
``scripts/model``.

- ``compute_folds`` arma una partición por ``event_id`` positivo y marca como omitidas las que
  dejan el entrenamiento con una sola clase (Req. 7.2, 7.13). Se calcula una vez y se guarda en
  ``folds.json`` para que las tres configuraciones usen exactamente las mismas.
- En cada partición, prueba = ``fold_group == held`` y entrenamiento = el resto (sin fuga, Req.
  7.3). El Reductor (solo ``embeddings``) se ajusta con las filas de entrenamiento (Req. 5.2) y la
  parada temprana usa una validación interna agrupada por ``fold_group`` dentro del entrenamiento.
- Los NaN se pasan tal cual a XGBoost (sin imputación).
- POD, FAR y CSI se calculan con umbral 0,5 sobre los conteos acumulados; los Eventos del caso de
  desarrollo (30-31 de mayo de 2019) se informan aparte y no entran a la selección (Req. 7.8).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupShuffleSplit
from table import event_order

# Hiperparámetros compartidos por las tres configuraciones (Req. 7.1). ``random_state=seed`` y
# ``scale_pos_weight`` se agregan por partición con la misma regla.
XGB_PARAMS: dict[str, Any] = {
    "objective": "binary:logistic",
    "tree_method": "hist",
    "n_estimators": 1000,  # tope; el número real lo fija la parada temprana
    "early_stopping_rounds": 30,
    "eval_metric": ["logloss", "aucpr"],  # la última (aucpr) decide la parada temprana
    "max_depth": 4,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "learning_rate": 0.05,
}
INNER_VAL_FRACTION = 0.2
INNER_RETRIES = 10
FALLBACK_TREES = 300  # sin validación interna posible: árboles fijos, sin parada temprana
THRESHOLD = 0.5
DEV_DATES = (dt.date(2019, 5, 30), dt.date(2019, 5, 31))
PCA_PREFIX = "pca_"
EMB_PREFIX = "emb_"
SELECTION_RULE = "embeddings si CSI > CSI(physical)"
HISTORY_NOTE = (
    "Los resultados difieren de corridas históricas de la versión anterior de train_xgboost.py "
    "(300 árboles fijos sin parada temprana y prueba solo con la fila positiva de cada Evento): "
    "ahora cada partición prueba también con no etiquetadas retenidas y usa parada temprana "
    "interna agrupada."
)


class ReducerLike(Protocol):
    """Lo que la Validación_LOEO necesita de un Reductor (``reducer.Reducer``)."""

    n_components: int

    def fit(self, emb: np.ndarray) -> ReducerLike:
        """Ajusta con las filas de ``emb``."""
        ...

    def transform(self, emb: np.ndarray) -> np.ndarray:
        """Proyecta ``emb`` a ``n_components`` columnas."""
        ...

    def explained_variance(self) -> tuple[list[float], list[float]]:
        """Varianza explicada por componente y acumulada."""
        ...


ReducerFactory = Callable[[], ReducerLike]


@dataclass(frozen=True)
class Fold:
    """Partición de la Validación_LOEO: el Evento retenido y si se omite por tener una clase."""

    held: str
    date: str  # fecha del Evento (AAAA-MM-DD) o "" si no se puede leer del event_id
    dev: bool  # Evento del caso de desarrollo (DEV_DATES)
    skipped: bool


@dataclass(frozen=True)
class Failure:
    """Configuración cuyo trabajo de entrenamiento falló, con el motivo."""

    reason: str


@dataclass
class FitInfo:
    """Modelo ajustado por ``fit_xgb`` y lo que se registra de su entrenamiento."""

    model: xgb.XGBClassifier
    scale_pos_weight: float
    best_iteration: int
    early_stopping: bool
    inner: tuple[np.ndarray, np.ndarray] | None  # posiciones (entrenamiento, validación) internas


@dataclass
class FoldOutcome:
    """Resultado de una partición; los índices son posiciones de fila de la tabla."""

    held: str
    date: str
    dev: bool
    skipped: bool
    hits: int = 0
    misses: int = 0
    false_alarms: int = 0
    scale_pos_weight: float | None = None
    best_iteration: int | None = None
    early_stopping: bool | None = None
    test_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    y_test: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    p_test: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    inner_train_index: np.ndarray | None = None
    inner_val_index: np.ndarray | None = None
    reducer_ratio: list[float] | None = None
    reducer_cumulative: list[float] | None = None

    @property
    def detected(self) -> bool:
        """``True`` si el Evento retenido tuvo al menos un acierto."""
        return self.hits > 0


@dataclass
class FinalModel:
    """Modelo final entrenado con toda la tabla (más su Reductor en ``embeddings``)."""

    model: xgb.XGBClassifier
    reducer: ReducerLike | None
    input_columns: list[str]  # columnas de la tabla que necesita (config_columns)
    model_columns: list[str]  # columnas que ve XGBoost (emb_* reemplazadas por pca_*)
    emb_columns: list[str]
    importance: dict[str, float]
    fit: FitInfo


def event_date(event_id: str) -> dt.date | None:
    """Fecha ``AAAAMMDD`` del prefijo de ``event_id``; ``None`` si no se puede leer."""
    try:
        return dt.datetime.strptime(event_id[:8], "%Y%m%d").date()
    except ValueError:
        return None


def compute_folds(table: pd.DataFrame) -> list[Fold]:
    """Una partición por ``event_id`` positivo, en orden de ``event_order`` (Req. 7.2, 7.13).

    Solo usa ``label``, ``event_id`` y ``fold_group``, que son iguales en las tres
    configuraciones. Una partición se marca ``skipped`` si su entrenamiento tiene una sola clase.
    """
    labels = table["label"].astype(int).to_numpy()
    groups = table["fold_group"].fillna("").astype(str).to_numpy()
    events = table.loc[labels == 1, "event_id"].fillna("").astype(str)
    folds: list[Fold] = []
    for held in sorted(set(events) - {""}, key=event_order):
        train = groups != held
        day = event_date(held)
        folds.append(
            Fold(
                held=held,
                date=day.isoformat() if day else "",
                dev=day in DEV_DATES,
                skipped=len(set(labels[train].tolist())) < 2,
            )
        )
    return folds


def folds_to_json(folds: Sequence[Fold], seed: int) -> dict[str, Any]:
    """Contenido de ``folds.json`` (``seed``, ``folds`` y ``n_skipped``)."""
    return {
        "seed": int(seed),
        "folds": [dataclasses.asdict(f) for f in folds],
        "n_skipped": sum(f.skipped for f in folds),
    }


def folds_from_json(data: Mapping[str, Any]) -> list[Fold]:
    """Particiones leídas de ``folds.json``."""
    return [
        Fold(
            held=str(f["held"]),
            date=str(f.get("date", "")),
            dev=bool(f.get("dev", False)),
            skipped=bool(f.get("skipped", False)),
        )
        for f in data["folds"]
    ]


def split_fold(groups: np.ndarray, held: str) -> tuple[np.ndarray, np.ndarray]:
    """Posiciones de entrenamiento (``fold_group != held``) y de prueba (``== held``)."""
    test = groups == held
    return np.flatnonzero(~test), np.flatnonzero(test)


def scale_pos_weight(y: np.ndarray) -> float:
    """``n_negativas / n_positivas`` del conjunto de entrenamiento."""
    y = np.asarray(y).astype(int)
    n_pos = int((y == 1).sum())
    if n_pos == 0:
        raise ValueError("el conjunto de entrenamiento no tiene positivas")
    return float((y == 0).sum()) / n_pos


def _both_classes(y: np.ndarray) -> bool:
    """``True`` si ``y`` tiene positivas y no etiquetadas."""
    return bool((y == 1).any() and (y == 0).any())


def inner_split(
    groups: np.ndarray, y: np.ndarray, seed: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """Validación interna agrupada por ``fold_group`` dentro del entrenamiento de la partición.

    ``GroupShuffleSplit(test_size=INNER_VAL_FRACTION)`` con ``random_state = seed + i`` para
    ``i`` en ``0..INNER_RETRIES-1``, hasta que ambas partes tengan positivas y no etiquetadas.
    Devuelve posiciones dentro de ``groups``/``y``; ``None`` si no se logra.
    """
    groups = np.asarray(groups).astype(str)
    y = np.asarray(y).astype(int)
    for i in range(INNER_RETRIES):
        splitter = GroupShuffleSplit(
            n_splits=1, test_size=INNER_VAL_FRACTION, random_state=seed + i
        )
        try:
            tr, va = next(splitter.split(np.zeros(len(y)), y, groups))
        except ValueError:  # muy pocos grupos para separar
            return None
        if _both_classes(y[tr]) and _both_classes(y[va]):
            return np.asarray(tr, dtype=np.int64), np.asarray(va, dtype=np.int64)
    return None


def fit_xgb(
    X: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray,
    seed: int,
    xgb_overrides: Mapping[str, Any] | None = None,
) -> FitInfo:
    """Ajusta XGBoost con ``XGB_PARAMS``, ``random_state=seed`` y ``scale_pos_weight`` de ``y``.

    La parada temprana usa la validación interna de ``inner_split``; si no hay, entrena
    ``FALLBACK_TREES`` árboles sin parada temprana. ``xgb_overrides`` (solo pruebas) reemplaza
    parámetros, p. ej. ``{"n_estimators": 20}``.
    """
    y = np.asarray(y).astype(int)
    overrides = dict(xgb_overrides or {})
    spw = scale_pos_weight(y)
    split = inner_split(groups, y, seed)
    if split is not None:
        params = {**XGB_PARAMS, **overrides, "random_state": seed, "scale_pos_weight": spw}
        tr, va = split
        model = xgb.XGBClassifier(**params)
        model.fit(X.iloc[tr], y[tr], eval_set=[(X.iloc[va], y[va])], verbose=False)
        return FitInfo(model, spw, int(model.best_iteration), True, split)
    params = {
        **XGB_PARAMS,
        "n_estimators": FALLBACK_TREES,
        **overrides,
        "early_stopping_rounds": None,
        "random_state": seed,
        "scale_pos_weight": spw,
    }
    model = xgb.XGBClassifier(**params)
    model.fit(X, y, verbose=False)
    return FitInfo(model, spw, int(params["n_estimators"]) - 1, False, None)


def pca_columns(n: int) -> list[str]:
    """``pca_00`` ... ``pca_{n-1}``."""
    return [f"{PCA_PREFIX}{i:02d}" for i in range(n)]


def _design(
    table: pd.DataFrame,
    feats: Sequence[str],
    fit_idx: np.ndarray,
    other_idx: Sequence[np.ndarray],
    reducer_factory: ReducerFactory | None,
) -> tuple[pd.DataFrame, list[pd.DataFrame], ReducerLike | None, list[str]]:
    """Matrices de variables para ``fit_idx`` y cada ``other_idx``.

    Con ``reducer_factory``, las columnas ``emb_*`` se reemplazan por ``pca_*`` de un Reductor
    ajustado SOLO con las filas de ``fit_idx`` (Req. 5.2).
    """
    emb = [c for c in feats if c.startswith(EMB_PREFIX)] if reducer_factory else []
    base = [c for c in feats if c not in emb]
    x_fit = table.iloc[fit_idx][base].reset_index(drop=True)
    x_other = [table.iloc[idx][base].reset_index(drop=True) for idx in other_idx]
    if not emb or reducer_factory is None:
        return x_fit, x_other, None, base
    red = reducer_factory()
    red.fit(table.iloc[fit_idx][emb].to_numpy(dtype=np.float64))
    names = pca_columns(red.n_components)

    def project(x: pd.DataFrame, idx: np.ndarray) -> pd.DataFrame:
        proj = red.transform(table.iloc[idx][emb].to_numpy(dtype=np.float64))
        return pd.concat([x, pd.DataFrame(proj, columns=names)], axis=1)

    x_fit = project(x_fit, fit_idx)
    x_other = [project(x, idx) for x, idx in zip(x_other, other_idx, strict=True)]
    return x_fit, x_other, red, [*base, *names]


def counts(y: np.ndarray, p: np.ndarray, threshold: float = THRESHOLD) -> tuple[int, int, int]:
    """Aciertos, omisiones y falsas alarmas con positiva = ``p >= threshold`` (Req. 7.4)."""
    y = np.asarray(y).astype(int)
    pred = np.asarray(p, dtype=np.float64) >= threshold
    hits = int((pred & (y == 1)).sum())
    misses = int((~pred & (y == 1)).sum())
    false_alarms = int((pred & (y == 0)).sum())
    return hits, misses, false_alarms


def metrics(hits: int, misses: int, false_alarms: int) -> dict[str, float]:
    """POD, FAR y CSI; cada una vale 0 si su denominador es 0 (Req. 7.5)."""

    def ratio(num: int, den: int) -> float:
        return num / den if den else 0.0

    return {
        "pod": ratio(hits, hits + misses),
        "far": ratio(false_alarms, hits + false_alarms),
        "csi": ratio(hits, hits + misses + false_alarms),
    }


def best_csi_threshold(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Umbral (entre las probabilidades observadas) que maximiza el CSI y ese CSI (informativo).

    Ante empates gana el umbral menor. Sin predicciones devuelve ``(THRESHOLD, 0.0)``.
    """
    p = np.asarray(p, dtype=np.float64)
    if p.size == 0:
        return THRESHOLD, 0.0
    best_t, best = THRESHOLD, -1.0
    for t in np.unique(p):
        csi = metrics(*counts(y, p, float(t)))["csi"]
        if csi > best:
            best_t, best = float(t), csi
    return best_t, best


def pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    """Área bajo la curva precisión-exhaustividad (``average_precision_score``); 0 sin positivas."""
    y = np.asarray(y).astype(int)
    if y.size == 0 or not (y == 1).any():
        return 0.0
    return float(average_precision_score(y, np.asarray(p, dtype=np.float64)))


def summarize(outcomes: Sequence[FoldOutcome]) -> dict[str, Any]:
    """Conteos, Métricas y número de Eventos evaluados de las particiones no omitidas."""
    done = [o for o in outcomes if not o.skipped]
    hits = sum(o.hits for o in done)
    misses = sum(o.misses for o in done)
    false_alarms = sum(o.false_alarms for o in done)
    return {
        **metrics(hits, misses, false_alarms),
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "n_events": len(done),
    }


def aggregate(outcomes: Sequence[FoldOutcome]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Métricas de selección (sin el caso de desarrollo) y del caso de desarrollo (Req. 7.8)."""
    return (
        summarize([o for o in outcomes if not o.dev]),
        summarize([o for o in outcomes if o.dev]),
    )


@dataclass
class LoeoResult:
    """Resultados por partición de una Validación_LOEO."""

    outcomes: list[FoldOutcome]

    def oof(self) -> tuple[np.ndarray, np.ndarray]:
        """Etiquetas y probabilidades fuera de partición de las particiones de selección."""
        sel = [o for o in self.outcomes if not o.skipped and not o.dev]
        if not sel:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
        return np.concatenate([o.y_test for o in sel]), np.concatenate([o.p_test for o in sel])

    def to_metrics_json(self, config: str) -> dict[str, Any]:
        """Contenido de ``metrics.json`` de la configuración ``config`` (forma del diseño)."""
        selection, dev = aggregate(self.outcomes)
        y, p = self.oof()
        threshold, best = best_csi_threshold(y, p)
        out: dict[str, Any] = {
            "config": config,
            "selection": selection,
            "development_case": dev,
            "n_folds_skipped": sum(o.skipped for o in self.outcomes),
            "informative": {
                "pr_auc_oof": pr_auc(y, p),
                "best_csi_threshold": threshold,
                "best_csi": best,
            },
            "per_fold": [
                {
                    "held": o.held,
                    "date": o.date,
                    "dev": o.dev,
                    "skipped": o.skipped,
                    "scale_pos_weight": o.scale_pos_weight,
                    "best_iteration": o.best_iteration,
                    "early_stopping": o.early_stopping,
                    "hits": o.hits,
                    "misses": o.misses,
                    "false_alarms": o.false_alarms,
                }
                for o in self.outcomes
            ],
            "per_event": [
                {"event_id": o.held, "detectado": o.detected, "dev": o.dev}
                for o in self.outcomes
                if not o.skipped
            ],
        }
        reducer = [
            {"held": o.held, "ratio": o.reducer_ratio, "cumulative": o.reducer_cumulative}
            for o in self.outcomes
            if o.reducer_ratio is not None
        ]
        if reducer:
            out["reducer"] = {"per_fold": reducer}
        return out


def run_loeo(
    table: pd.DataFrame,
    feats: Sequence[str],
    folds: Sequence[Fold],
    seed: int,
    reducer_factory: ReducerFactory | None = None,
    xgb_overrides: Mapping[str, Any] | None = None,
) -> LoeoResult:
    """Validación_LOEO con las particiones ``folds`` (de ``folds.json``) sobre ``table``.

    En cada partición no omitida: entrenamiento = ``fold_group != held``, prueba = ``== held``;
    el Reductor (si hay ``reducer_factory``) y la validación interna solo ven el entrenamiento.
    """
    groups = table["fold_group"].fillna("").astype(str).to_numpy()
    y = table["label"].astype(int).to_numpy()
    outcomes: list[FoldOutcome] = []
    for f in folds:
        if f.skipped:
            outcomes.append(FoldOutcome(f.held, f.date, f.dev, True))
            continue
        tr, te = split_fold(groups, f.held)
        x_tr, (x_te,), red, _ = _design(table, feats, tr, [te], reducer_factory)
        fit = fit_xgb(x_tr, y[tr], groups[tr], seed, xgb_overrides)
        p = fit.model.predict_proba(x_te)[:, 1].astype(np.float64) if len(te) else np.zeros(0)
        hits, misses, false_alarms = counts(y[te], p)
        ratio, cumulative = red.explained_variance() if red is not None else (None, None)
        outcomes.append(
            FoldOutcome(
                held=f.held,
                date=f.date,
                dev=f.dev,
                skipped=False,
                hits=hits,
                misses=misses,
                false_alarms=false_alarms,
                scale_pos_weight=fit.scale_pos_weight,
                best_iteration=fit.best_iteration,
                early_stopping=fit.early_stopping,
                test_index=te,
                y_test=y[te],
                p_test=p,
                inner_train_index=tr[fit.inner[0]] if fit.inner else None,
                inner_val_index=tr[fit.inner[1]] if fit.inner else None,
                reducer_ratio=ratio,
                reducer_cumulative=cumulative,
            )
        )
    return LoeoResult(outcomes)


def _importance(model: xgb.XGBClassifier, columns: Sequence[str]) -> dict[str, float]:
    """Importancia de cada variable, de mayor a menor (0 si no es finita)."""
    values = [float(v) for v in model.feature_importances_]
    imp = {c: (v if math.isfinite(v) else 0.0) for c, v in zip(columns, values, strict=True)}
    return dict(sorted(imp.items(), key=lambda kv: kv[1], reverse=True))


def train_final(
    table: pd.DataFrame,
    feats: Sequence[str],
    seed: int,
    reducer_factory: ReducerFactory | None = None,
    xgb_overrides: Mapping[str, Any] | None = None,
) -> FinalModel:
    """Modelo final con toda la tabla, la misma validación interna y la misma parada temprana."""
    groups = table["fold_group"].fillna("").astype(str).to_numpy()
    y = table["label"].astype(int).to_numpy()
    idx = np.arange(len(table))
    x, _, red, cols = _design(table, feats, idx, [], reducer_factory)
    fit = fit_xgb(x, y, groups, seed, xgb_overrides)
    emb = [c for c in feats if c.startswith(EMB_PREFIX)] if red is not None else []
    return FinalModel(fit.model, red, list(feats), cols, emb, _importance(fit.model, cols), fit)


def select_model(results: Mapping[str, Mapping[str, Any] | Failure]) -> dict[str, Any]:
    """Modelo seleccionado según ``metrics.json`` por configuración (Req. 7.7, 7.11).

    ``embeddings`` solo si su CSI de selección es estrictamente mayor que el de ``physical``; si
    falta alguna de las dos (o falló), no hay selección y se indica el motivo.
    """
    failures = {c: r.reason for c, r in results.items() if isinstance(r, Failure)}
    missing = [
        c for c in ("physical", "embeddings") if c not in results or isinstance(results[c], Failure)
    ]
    if missing:
        detail = "; ".join(f"{c}: {failures.get(c, 'sin resultados')}" for c in missing)
        return {
            "selected": None,
            "rule": SELECTION_RULE,
            "reason": f"sin selección: falta {detail}",
            "failures": failures,
        }
    phys = results["physical"]
    emb = results["embeddings"]
    assert not isinstance(phys, Failure) and not isinstance(emb, Failure)
    csi_phys = float(phys["selection"]["csi"])
    csi_emb = float(emb["selection"]["csi"])
    return {
        "selected": "embeddings" if csi_emb > csi_phys else "physical",
        "rule": SELECTION_RULE,
        "reason": None,
        "failures": failures,
    }


def report_html(
    metrics_json: Mapping[str, Any], importance: Mapping[str, float], table: pd.DataFrame
) -> str:
    """Reporte HTML autocontenido de una configuración: Métricas, importancia y datos."""
    sel = metrics_json["selection"]
    dev = metrics_json["development_case"]
    info = metrics_json["informative"]
    config = html.escape(str(metrics_json.get("config", "")))
    top = max([*importance.values(), 0.0]) or 1.0
    bars = "".join(
        f'<tr><td>{html.escape(name)}</td><td><div class="bar" '
        f'style="width:{max(v / top * 100, 0.5):.1f}%"></div><span>{v:.3f}</span></td></tr>'
        for name, v in importance.items()
    )
    events = "".join(
        f"<li>{'✓' if e['detectado'] else '✗'} {html.escape(str(e['event_id']))}"
        f"{' (desarrollo)' if e.get('dev') else ''}</li>"
        for e in metrics_json["per_event"]
    )
    days = table["date"].nunique() if "date" in table else 0
    n_pos = int((table["label"] == 1).sum()) if "label" in table else 0
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resultados XGBoost ({config}) — entorno tornádico Chile</title>
<style>
 body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
   max-width:860px;margin:0 auto;padding:32px 24px;color:#182230;background:#f4f6fa}}
 h1{{font-size:22px}} h2{{font-size:17px;margin-top:32px;border-bottom:1px solid #ccd4e0;padding-bottom:6px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}}
 .card{{background:#fff;border:1px solid #ccd4e0;border-radius:12px;padding:16px 20px;flex:1;min-width:140px}}
 .card .n{{font-size:30px;font-weight:700;color:#b35500}} .card .l{{color:#5a6675;font-size:13px}}
 table{{width:100%;border-collapse:collapse}} td{{padding:5px 8px;vertical-align:middle}}
 .bar{{display:inline-block;height:12px;background:#ff9900;border-radius:3px;vertical-align:middle;margin-right:8px}}
 ul{{columns:2;font-size:13px;color:#5a6675}} .muted{{color:#5a6675;font-size:13px}}
 .note{{background:#fff8e6;border:1px solid #f0c36d;border-radius:8px;padding:10px 14px;font-size:13px}}
</style></head><body>
<h1>Resultados del modelo XGBoost — {config}</h1>
<p class="muted">Clasificador de entorno tornádico. Generado {now}.</p>
<p class="note">{html.escape(HISTORY_NOTE)}</p>

<h2>Métricas de selección (Validación_LOEO, umbral {THRESHOLD})</h2>
<div class="cards">
  <div class="card"><div class="n">{sel["pod"]:.2f}</div><div class="l">POD — prob. de detección</div></div>
  <div class="card"><div class="n">{sel["far"]:.2f}</div><div class="l">FAR — falsas alarmas</div></div>
  <div class="card"><div class="n">{sel["csi"]:.2f}</div><div class="l">CSI — índice crítico</div></div>
</div>
<p class="muted">Aciertos: {sel["hits"]} · Omisiones: {sel["misses"]} ·
  Falsas alarmas: {sel["false_alarms"]} · Eventos evaluados: {sel["n_events"]} ·
  Particiones omitidas (una sola clase): {metrics_json["n_folds_skipped"]}.
  No se usa exactitud: con &gt;99 % de celdas sin evento, siempre decir «no» acertaría casi todo.</p>

<h2>Caso de desarrollo (30-31 de mayo de 2019, fuera de la selección)</h2>
<p class="muted">POD {dev["pod"]:.2f} · FAR {dev["far"]:.2f} · CSI {dev["csi"]:.2f} ·
  Aciertos {dev["hits"]} · Omisiones {dev["misses"]} · Falsas alarmas {dev["false_alarms"]} ·
  Eventos {dev["n_events"]}.</p>

<h2>Información complementaria (no interviene en la selección)</h2>
<p class="muted">PR-AUC fuera de partición: {info["pr_auc_oof"]:.3f} ·
  Umbral de máximo CSI: {info["best_csi_threshold"]:.3f} (CSI {info["best_csi"]:.3f}).</p>

<h2>Importancia de las variables (modelo final)</h2>
<table>{bars}</table>
<p class="muted">La SRH y el STP se usan con su signo físico austral (negativo).</p>

<h2>Detección por evento</h2>
<ul>{events}</ul>

<h2>Datos</h2>
<p class="muted">Tabla PU: {len(table)} filas · {n_pos} positivos ·
  {len(table) - n_pos} no etiquetados · {days} días.
  «No etiquetado» no es «negativo»: el catálogo solo tiene positivos (sección 6.1 del documento).</p>
</body></html>"""
