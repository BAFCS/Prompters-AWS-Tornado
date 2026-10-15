"""Pruebas de la Validación_LOEO (``scripts/model/loeo.py``) con XGBoost real y pocas filas."""

import datetime as dt
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

import loeo  # noqa: E402
import reducer  # noqa: E402
import table  # noqa: E402

# Pocos árboles y un hilo: las propiedades entrenan XGBoost real en cada ejemplo.
FAST = {"n_estimators": 20, "n_jobs": 1}
DAYS = [dt.date(2019, 5, 30), dt.date(2019, 5, 31), dt.date(2020, 1, 5), dt.date(2021, 6, 12)]
FEATS = ["f0", "f1", "f2"]


@st.composite
def loeo_tables(draw: st.DrawFn, n_emb: int = 0, min_unl: int = 2) -> pd.DataFrame:
    """Tabla sintética: por Evento una positiva y no etiquetadas con su ``fold_group``.

    Con un solo Evento, su partición queda con una sola clase (omitida). ``n_emb`` agrega
    columnas ``emb_*`` sin NaN; las variables ``f*`` tienen NaN en posiciones aleatorias.
    """
    n_events = draw(st.integers(1, 4))
    days = draw(st.lists(st.sampled_from(DAYS), min_size=n_events, max_size=n_events))
    seed = draw(st.integers(0, 2**16))
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for i, day in enumerate(days):
        eid = f"{day:%Y%m%d}-{i}"
        rows.append({"label": 1, "event_id": eid, "fold_group": eid, "day": day})
        for _ in range(draw(st.integers(min_unl, min_unl + 4))):
            rows.append({"label": 0, "event_id": "", "fold_group": eid, "day": day})
    df = pd.DataFrame(rows)
    order = rng.permutation(len(df))  # las filas de un Evento no quedan contiguas
    df = df.iloc[order].reset_index(drop=True)
    df["label"] = df["label"].astype("int8")
    for c in FEATS:
        df[c] = rng.normal(size=len(df)) + 1.5 * df["label"]
        df.loc[rng.random(len(df)) < 0.15, c] = np.nan
    for c in table.emb_columns(n_emb):
        df[c] = rng.normal(size=len(df))
    return df


class SpyReducer:
    """Reductor real que registra las filas con que se ajusta."""

    fitted: list[np.ndarray] = []

    def __init__(self) -> None:
        """Envuelve un ``reducer.Reducer`` de 8 componentes."""
        self.inner = reducer.Reducer(8, "spy")
        self.n_components = 8

    def fit(self, emb: np.ndarray) -> "SpyReducer":
        """Registra ``emb`` y ajusta."""
        SpyReducer.fitted.append(np.array(emb, copy=True))
        self.inner.fit(emb)
        return self

    def transform(self, emb: np.ndarray) -> np.ndarray:
        """Proyección del Reductor real."""
        return self.inner.transform(emb)

    def explained_variance(self) -> tuple[list[float], list[float]]:
        """Varianza explicada del Reductor real."""
        return self.inner.explained_variance()


def era5_long(
    times: list[pd.Timestamp], lat: np.ndarray, lon: np.ndarray, seed: int
) -> pd.DataFrame:
    """Índices ERA5 sintéticos en formato largo."""
    rng = np.random.default_rng(seed)
    df = pd.MultiIndex.from_product([times, lat, lon], names=table.POINT).to_frame(index=False)
    for c in table.ERA5_FEATURES:
        df[c] = rng.normal(size=len(df))
    return df


def goes_long(
    times: list[pd.Timestamp], lat: np.ndarray, lon: np.ndarray, seed: int
) -> pd.DataFrame:
    """Variables_GOES sintéticas con barrido 10 min antes de cada hora."""
    rng = np.random.default_rng(seed + 1)
    df = pd.MultiIndex.from_product([times, lat, lon], names=table.POINT).to_frame(index=False)
    df["scan_start"] = df["time"] - pd.Timedelta(minutes=10)
    for c in table.GOES_FEATURES:
        df[c] = rng.normal(size=len(df))
    return df


class FoldsTest(unittest.TestCase):
    """Propiedades 24, 25 y 31 y casos de las particiones."""

    # Feature: multimodal-tornado-predictor, Property 24: Particiones idénticas entre configuraciones
    @settings(max_examples=100, deadline=None)
    @given(
        day=st.sampled_from([dt.date(2019, 5, 30), dt.date(2020, 1, 5)]),
        n_hours=st.integers(2, 4),
        data=st.data(),
        seed=st.integers(0, 2**16),
    )
    def test_same_folds_across_configs(
        self, day: dt.date, n_hours: int, data: st.DataObject, seed: int
    ) -> None:
        """Las tres tablas dan las mismas particiones y las mismas filas de prueba."""
        t0 = pd.Timestamp(day, tz="UTC")
        times = [t0 + pd.Timedelta(hours=h) for h in range(n_hours)]
        lat, lon = np.array([-35.0, -35.25]), np.array([-72.0, -71.75])
        cells = table.candidate_cells(times, lat, lon)
        pos = data.draw(
            st.lists(st.integers(0, len(cells) - 1), min_size=1, max_size=3, unique=True)
        )
        cells["label"] = np.int8(0)
        cells.loc[pos, "label"] = np.int8(1)
        cells["event_id"] = [
            f"{day:%Y%m%d}-{i}" if lab else "" for i, lab in enumerate(cells["label"])
        ]
        cells["fold_group"] = table.assign_fold_groups(cells, seed)
        era5, goes = era5_long(times, lat, lon, seed), goes_long(times, lat, lon, seed)
        emb = pd.DataFrame(
            np.random.default_rng(seed).normal(size=(len(cells), 8)), columns=table.emb_columns(8)
        )
        emb.insert(0, "cell_id", cells["cell_id"].tolist())
        tables = {c: table.build(c, cells, era5, goes, emb) for c in table.CONFIGS}
        folds = {c: loeo.compute_folds(t) for c, t in tables.items()}
        self.assertEqual(folds["baseline_era5"], folds["physical"])
        self.assertEqual(folds["baseline_era5"], folds["embeddings"])
        events = sorted(set(cells["event_id"]) - {""}, key=table.event_order)
        self.assertEqual([f.held for f in folds["physical"]], events)
        for f in folds["physical"]:
            ref = loeo.split_fold(tables["physical"]["fold_group"].to_numpy(), f.held)
            for t in tables.values():
                got = loeo.split_fold(t["fold_group"].to_numpy(), f.held)
                np.testing.assert_array_equal(got[1], ref[1])

    def test_same_outcomes_across_configs(self) -> None:
        """Con XGBoost real, las tres configuraciones evalúan las mismas particiones y filas.

        Ejemplo fijo (no propiedad): construir tres tablas y entrenar tres veces por ejemplo
        tarda demasiado para 100 ejemplos; la Propiedad 24 cubre ``compute_folds``.
        """
        times = [pd.Timestamp("2020-01-05", tz="UTC") + pd.Timedelta(hours=h) for h in range(4)]
        lat, lon = np.array([-35.0, -35.25, -35.5]), np.array([-72.0, -71.75, -71.5])
        cells = table.candidate_cells(times, lat, lon)
        cells["label"] = np.int8(0)
        cells.loc[[3, 17, 30], "label"] = np.int8(1)
        cells["event_id"] = [f"20200105-{i}" if lab else "" for i, lab in enumerate(cells["label"])]
        cells["fold_group"] = table.assign_fold_groups(cells, 0)
        era5, goes = era5_long(times, lat, lon, 0), goes_long(times, lat, lon, 0)
        emb = pd.DataFrame(
            np.random.default_rng(0).normal(size=(len(cells), 8)), columns=table.emb_columns(8)
        )
        emb.insert(0, "cell_id", cells["cell_id"].tolist())
        tables = {c: table.build(c, cells, era5, goes, emb) for c in table.CONFIGS}
        folds = loeo.compute_folds(tables["baseline_era5"])
        self.assertEqual(len(folds), 3)
        results = {
            c: loeo.run_loeo(
                t,
                table.config_columns(c, 8 if c == "embeddings" else 0),
                folds,
                0,
                (lambda: reducer.Reducer(8, "m")) if c == "embeddings" else None,
                FAST,
            )
            for c, t in tables.items()
        }
        ref = results["physical"].outcomes
        for c in table.CONFIGS:
            out = results[c].outcomes
            self.assertEqual([(o.held, o.skipped) for o in out], [(o.held, o.skipped) for o in ref])
            for a, b in zip(out, ref, strict=True):
                np.testing.assert_array_equal(a.test_index, b.test_index)

    # Feature: multimodal-tornado-predictor, Property 25: Sin fuga en la Validación_LOEO
    @settings(max_examples=100, deadline=None)
    @given(df=loeo_tables(), seed=st.integers(0, 2**16))
    def test_no_leakage(self, df: pd.DataFrame, seed: int) -> None:
        """Entrenamiento y prueba no comparten ``fold_group`` ni ``event_id``."""
        folds = loeo.compute_folds(df)
        result = loeo.run_loeo(df, FEATS, folds, seed, xgb_overrides=FAST)
        groups = df["fold_group"].to_numpy()
        eids = df["event_id"].to_numpy()
        for o in result.outcomes:
            if o.skipped:
                continue
            test = np.zeros(len(df), dtype=bool)
            test[o.test_index] = True
            self.assertEqual(set(groups[test]), {o.held})
            self.assertNotIn(o.held, set(groups[~test]))
            self.assertFalse((set(eids[test]) - {""}) & (set(eids[~test]) - {""}))
            self.assertTrue(test[eids == o.held].all())

    # Feature: multimodal-tornado-predictor, Property 31: Validación interna sin fuga y peso de clase por partición
    @settings(max_examples=100, deadline=None)
    @given(df=loeo_tables(), seed=st.integers(0, 2**16))
    def test_inner_split_and_class_weight(self, df: pd.DataFrame, seed: int) -> None:
        """La validación interna usa solo entrenamiento, con grupos disjuntos y sin el retenido."""
        result = loeo.run_loeo(df, FEATS, loeo.compute_folds(df), seed, xgb_overrides=FAST)
        groups = df["fold_group"].to_numpy()
        y = df["label"].to_numpy()
        for o in result.outcomes:
            if o.skipped:
                continue
            train = np.setdiff1d(np.arange(len(df)), o.test_index)
            n_pos, n_neg = int((y[train] == 1).sum()), int((y[train] == 0).sum())
            self.assertAlmostEqual(o.scale_pos_weight, n_neg / n_pos)
            if o.inner_train_index is None or o.inner_val_index is None:
                self.assertFalse(o.early_stopping)
                continue
            self.assertTrue(o.early_stopping)
            self.assertTrue(set(o.inner_train_index) <= set(train))
            self.assertTrue(set(o.inner_val_index) <= set(train))
            g_tr, g_va = set(groups[o.inner_train_index]), set(groups[o.inner_val_index])
            self.assertFalse(g_tr & g_va)
            self.assertNotIn(o.held, g_tr | g_va)

    def test_single_class_fold_is_skipped(self) -> None:
        """Con un solo Evento, el entrenamiento solo tiene no etiquetadas y la partición se omite."""
        df = pd.DataFrame(
            {
                "label": [1, 0, 0],
                "event_id": ["20200105-1", "", ""],
                "fold_group": ["20200105-1"] * 3,
            }
        )
        folds = loeo.compute_folds(df)
        self.assertEqual(folds, [loeo.Fold("20200105-1", "2020-01-05", False, True)])
        doc = loeo.folds_to_json(folds, 7)
        self.assertEqual(doc["n_skipped"], 1)
        self.assertEqual(loeo.folds_from_json(doc), folds)

    def test_xgb_params(self) -> None:
        """Hiperparámetros exactos del diseño."""
        self.assertEqual(
            loeo.XGB_PARAMS,
            {
                "objective": "binary:logistic",
                "tree_method": "hist",
                "n_estimators": 1000,
                "early_stopping_rounds": 30,
                "eval_metric": ["logloss", "aucpr"],
                "max_depth": 4,
                "min_child_weight": 5,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_lambda": 1.0,
                "learning_rate": 0.05,
            },
        )

    def test_fallback_without_inner_validation(self) -> None:
        """Sin validación interna posible (un solo grupo) se entrenan 300 árboles sin parada."""
        rng = np.random.default_rng(0)
        X = pd.DataFrame({"f0": rng.normal(size=12)})
        y = np.array([1, 0] * 6)
        fit = loeo.fit_xgb(X, y, np.array(["g"] * 12), 0, {"n_jobs": 1})
        self.assertFalse(fit.early_stopping)
        self.assertIsNone(fit.inner)
        self.assertEqual(fit.best_iteration, loeo.FALLBACK_TREES - 1)
        self.assertEqual(fit.model.get_booster().num_boosted_rounds(), loeo.FALLBACK_TREES)


class MetricsTest(unittest.TestCase):
    """Propiedades 26, 27 y 28."""

    # Feature: multimodal-tornado-predictor, Property 26: Cálculo y cotas de las Métricas
    @settings(max_examples=100, deadline=None)
    @given(
        pairs=st.lists(st.tuples(st.integers(0, 1), st.floats(0, 1)), max_size=40),
        c=st.tuples(st.integers(0, 50), st.integers(0, 50), st.integers(0, 50)),
    )
    def test_metrics(self, pairs: list[tuple[int, float]], c: tuple[int, int, int]) -> None:
        """Conteos con umbral ≥ 0,5 iguales a la referencia; POD, FAR, CSI en [0, 1]."""
        y = np.array([a for a, _ in pairs], dtype=int)
        p = np.array([b for _, b in pairs], dtype=float)
        ref = [0, 0, 0]
        for yi, pi in pairs:
            if pi >= 0.5 and yi == 1:
                ref[0] += 1
            elif yi == 1:
                ref[1] += 1
            elif pi >= 0.5:
                ref[2] += 1
        self.assertEqual(loeo.counts(y, p), tuple(ref))
        hits, misses, fa = c
        m = loeo.metrics(hits, misses, fa)
        for v in m.values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)
        if hits + misses == 0:
            self.assertEqual(m["pod"], 0.0)
        if hits + fa == 0:
            self.assertEqual(m["far"], 0.0)
        if hits + misses + fa == 0:
            self.assertEqual(m["csi"], 0.0)
        else:
            self.assertAlmostEqual(m["csi"], hits / (hits + misses + fa))

    # Feature: multimodal-tornado-predictor, Property 27: Exclusión del caso de desarrollo
    @settings(max_examples=100, deadline=None)
    @given(
        folds=st.lists(
            st.tuples(
                st.sampled_from(DAYS),
                st.booleans(),
                st.tuples(st.integers(0, 5), st.integers(0, 5), st.integers(0, 5)),
                st.tuples(st.integers(0, 5), st.integers(0, 5), st.integers(0, 5)),
            ),
            max_size=12,
        )
    )
    def test_development_case_excluded(self, folds: list[tuple]) -> None:
        """Alterar las particiones de 30-31/05/2019 no cambia las Métricas de selección."""

        def outcomes(alter: bool) -> list[loeo.FoldOutcome]:
            out = []
            for i, (day, skipped, a, b) in enumerate(folds):
                dev = day in loeo.DEV_DATES
                h, m, f = b if (alter and dev) else a
                out.append(
                    loeo.FoldOutcome(f"{day:%Y%m%d}-{i}", day.isoformat(), dev, skipped, h, m, f)
                )
            return out

        sel_a, dev_a = loeo.aggregate(outcomes(False))
        sel_b, _ = loeo.aggregate(outcomes(True))
        self.assertEqual(sel_a, sel_b)
        n_dev = sum(1 for d, s, _, _ in folds if d in loeo.DEV_DATES and not s)
        n_sel = sum(1 for d, s, _, _ in folds if d not in loeo.DEV_DATES and not s)
        self.assertEqual(dev_a["n_events"], n_dev)
        self.assertEqual(sel_a["n_events"], n_sel)
        doc = loeo.LoeoResult(outcomes(False)).to_metrics_json("physical")
        self.assertEqual(doc["selection"], sel_a)
        self.assertEqual(doc["development_case"], dev_a)

    # Feature: multimodal-tornado-predictor, Property 28: Regla de selección del modelo
    @settings(max_examples=100, deadline=None)
    @given(
        csi_p=st.floats(0, 1),
        csi_e=st.one_of(st.floats(0, 1), st.just(-1.0)),
        failed=st.sets(st.sampled_from(table.CONFIGS)),
    )
    def test_selection_rule(self, csi_p: float, csi_e: float, failed: set[str]) -> None:
        """``embeddings`` si y solo si su CSI es estrictamente mayor; sin selección si falta."""
        csi_e = csi_p if csi_e < 0 else csi_e  # fuerza empates
        csi = {"baseline_era5": 0.1, "physical": csi_p, "embeddings": csi_e}
        results: dict = {
            c: loeo.Failure(f"motivo {c}") if c in failed else {"selection": {"csi": csi[c]}}
            for c in table.CONFIGS
        }
        sel = loeo.select_model(results)
        if failed & {"physical", "embeddings"}:
            self.assertIsNone(sel["selected"])
            for c in failed & {"physical", "embeddings"}:
                self.assertIn(f"motivo {c}", sel["reason"])
        else:
            self.assertEqual(sel["selected"], "embeddings" if csi_e > csi_p else "physical")
        self.assertEqual(sel["failures"], {c: f"motivo {c}" for c in failed})


class ReducerFoldTest(unittest.TestCase):
    """Propiedad 15."""

    # Feature: multimodal-tornado-predictor, Property 15: El Reductor no ve el Evento retenido
    @settings(max_examples=100, deadline=None)
    @given(df=loeo_tables(n_emb=10, min_unl=8), seed=st.integers(0, 2**16))
    def test_reducer_never_sees_held_event(self, df: pd.DataFrame, seed: int) -> None:
        """Cada Reductor se ajusta exactamente con las filas de entrenamiento de su partición."""
        SpyReducer.fitted = []
        feats = [*FEATS, *table.emb_columns(10)]
        result = loeo.run_loeo(
            df, feats, loeo.compute_folds(df), seed, reducer_factory=SpyReducer, xgb_overrides=FAST
        )
        done = [o for o in result.outcomes if not o.skipped]
        self.assertEqual(len(SpyReducer.fitted), len(done))
        emb = df[table.emb_columns(10)].to_numpy()
        groups = df["fold_group"].to_numpy()
        for o, fitted in zip(done, SpyReducer.fitted, strict=True):
            held_rows = {tuple(r) for r in emb[groups == o.held]}
            self.assertFalse(held_rows & {tuple(r) for r in fitted})
            np.testing.assert_array_equal(fitted, emb[groups != o.held])
            self.assertIsNotNone(o.reducer_ratio)


class FinalModelTest(unittest.TestCase):
    """Modelo final y ``metrics.json``."""

    def test_train_final_and_metrics_json(self) -> None:
        """El modelo final reemplaza ``emb_*`` por ``pca_*`` y ``metrics.json`` tiene su forma."""
        rng = np.random.default_rng(3)
        rows = []
        for i, day in enumerate(DAYS):
            eid = f"{day:%Y%m%d}-{i}"
            rows += [{"label": 1, "event_id": eid, "fold_group": eid}]
            rows += [{"label": 0, "event_id": "", "fold_group": eid}] * 6
        df = pd.DataFrame(rows)
        for c in [*FEATS, *table.emb_columns(10)]:
            df[c] = rng.normal(size=len(df)) + df["label"]
        feats = [*FEATS, *table.emb_columns(10)]

        def factory() -> reducer.Reducer:
            return reducer.Reducer(8, "m")

        final = loeo.train_final(df, feats, 0, factory, FAST)
        self.assertEqual(final.model_columns, [*FEATS, *loeo.pca_columns(8)])
        self.assertEqual(final.emb_columns, table.emb_columns(10))
        self.assertEqual(
            list(final.importance), sorted(final.importance, key=final.importance.get, reverse=True)
        )
        doc = loeo.run_loeo(df, feats, loeo.compute_folds(df), 0, factory, FAST).to_metrics_json(
            "embeddings"
        )
        self.assertEqual(
            set(doc),
            {
                "config",
                "selection",
                "development_case",
                "n_folds_skipped",
                "informative",
                "per_fold",
                "per_event",
                "reducer",
            },
        )
        self.assertEqual(doc["selection"]["n_events"], 2)
        self.assertEqual(doc["development_case"]["n_events"], 2)
        self.assertLessEqual(
            {"scale_pos_weight", "best_iteration", "early_stopping"}, set(doc["per_fold"][0])
        )


if __name__ == "__main__":
    unittest.main()
