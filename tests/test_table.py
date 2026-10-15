"""Pruebas del Constructor_Tabla (``scripts/model/table.py`` y ``build_table.py``)."""

import contextlib
import datetime as dt
import io
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import table  # noqa: E402

import common  # noqa: E402

DAY = dt.date(2019, 5, 30)
WORLD = common.Region("world", 90, -90, -180, 180)
T0 = pd.Timestamp("2019-05-30 00:00", tz="UTC")


def catalog_frame(events: list[dict], index: list[int] | None = None) -> pd.DataFrame:
    """Catálogo normalizado (``date``, ``lat``, ``lon``, ``hour_utc``) con el índice de fila dado."""
    df = pd.DataFrame(events, columns=["date", "lat", "lon", "hour_utc"])
    if index is not None:
        df.index = pd.Index(index)
    return df


@st.composite
def grid(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray]:
    """Grilla regular de 0,25° (latitudes descendentes como ERA5), de 1 a 5 puntos por eje."""
    lat0 = draw(st.integers(-200, -100)) * 0.25
    lon0 = draw(st.integers(-300, -260)) * 0.25
    ny, nx = draw(st.integers(1, 5)), draw(st.integers(1, 5))
    lat = lat0 - 0.25 * np.arange(ny)
    lon = lon0 + 0.25 * np.arange(nx)
    return lat, lon


def coord_in(draw: st.DrawFn, axis: np.ndarray) -> float:
    """Coordenada cerca de ``axis``: continua o en un múltiplo de 0,125° (fuerza empates)."""
    lo, hi = float(axis.min()) - 0.3, float(axis.max()) + 0.3
    return draw(
        st.one_of(
            st.floats(lo, hi, allow_nan=False),
            st.integers(math.ceil(lo / 0.125), math.floor(hi / 0.125)).map(lambda i: i * 0.125),
        )
    )


def reference_cell(
    lat: np.ndarray, lon: np.ndarray, ev_lat: float, ev_lon: float, hour: int, minute: int
) -> tuple[pd.Timestamp, float, float]:
    """Búsqueda exhaustiva: punto de menor distancia (empates: menor lat, menor lon) y hora."""
    k = math.cos(math.radians(ev_lat))
    pts = [(float(y), float(x)) for y in lat for x in lon]
    d2 = [(y - ev_lat) ** 2 + ((x - ev_lon) * k) ** 2 for y, x in pts]
    best = min(d2)
    y, x = min(p for p, d in zip(pts, d2, strict=True) if d <= best + 1e-12)
    t = pd.Timestamp(dt.datetime.combine(DAY, dt.time(hour)), tz="UTC")
    if minute >= 30:
        t += pd.Timedelta(hours=1)
    return t, y, x


def era5_frame(
    times: list[pd.Timestamp], lat: np.ndarray, lon: np.ndarray, seed: int
) -> pd.DataFrame:
    """Índices ERA5 sintéticos en formato largo; SRH y STP negativos (signo austral)."""
    rng = np.random.default_rng(seed)
    idx = pd.MultiIndex.from_product([times, lat, lon], names=table.POINT).to_frame(index=False)
    for c in table.ERA5_FEATURES:
        idx[c] = rng.normal(size=len(idx))
    for c in ("srh_01", "srh_03", "stp_lm"):
        idx[c] = -np.abs(idx[c]) - 0.1
    return idx


def goes_frame(
    times: list[pd.Timestamp], lat: np.ndarray, lon: np.ndarray, seed: int
) -> pd.DataFrame:
    """Variables_GOES sintéticas con ``scan_start`` 10 min antes de cada hora."""
    rng = np.random.default_rng(seed + 1)
    g = pd.MultiIndex.from_product([times, lat, lon], names=table.POINT).to_frame(index=False)
    g["scan_start"] = g["time"] - pd.Timedelta(minutes=10)
    for c in table.GOES_FEATURES:
        g[c] = rng.normal(size=len(g))
    return g


@st.composite
def inputs(draw: st.DrawFn) -> dict:
    """Entradas sintéticas: horas (con huecos), grilla, ERA5, GOES, embeddings y Celdas_Hora."""
    lat = np.array([-35.0, -35.25])[: draw(st.integers(1, 2))]
    lon = np.array([-72.0, -71.75])[: draw(st.integers(1, 2))]
    hours = draw(st.lists(st.integers(0, 8), min_size=1, max_size=9, unique=True))
    times = [T0 + pd.Timedelta(hours=h) for h in sorted(hours)]
    seed = draw(st.integers(0, 2**16))
    era5 = era5_frame(times, lat, lon, seed)
    nan_mask = draw(st.lists(st.booleans(), min_size=len(era5), max_size=len(era5)))
    era5.loc[np.array(nan_mask), "cape"] = np.nan
    goes = goes_frame(times, lat, lon, seed)
    cand = table.candidate_cells(times, lat, lon)
    pick = draw(st.lists(st.integers(0, len(cand) - 1), min_size=1, unique=True))
    cells = cand.iloc[sorted(pick)].reset_index(drop=True)
    n_pos = draw(st.integers(0, len(cells)))
    cells["label"] = np.int8(0)
    cells.loc[: n_pos - 1, "label"] = np.int8(1)
    cells["event_id"] = [f"20190530-{i}" if lab else "" for i, lab in enumerate(cells["label"])]
    cells["fold_group"] = table.assign_fold_groups(cells, seed)
    emb = pd.DataFrame(
        np.random.default_rng(seed + 2).normal(size=(len(cells), 3)),
        columns=table.emb_columns(3),
    )
    emb.insert(0, "cell_id", cells["cell_id"].tolist())
    emb = emb.iloc[: draw(st.integers(0, len(emb)))]  # algunas Celdas_Hora sin embedding
    return {"cells": cells, "era5": era5, "goes": goes, "embeddings": emb}


def build(config: str, d: dict) -> pd.DataFrame:
    """``table.build`` con las entradas de ``inputs``."""
    return table.build(config, d["cells"], d["era5"], d["goes"], d["embeddings"])


class LabelingTest(unittest.TestCase):
    """Propiedades 16, 17 y 18."""

    # Feature: multimodal-tornado-predictor, Property 16: Etiquetado del punto y hora más cercanos
    @settings(max_examples=100, deadline=None)
    @given(g=grid(), data=st.data(), hour=st.integers(0, 23), minute=st.integers(0, 59))
    def test_nearest_point_and_hour(
        self, g: tuple[np.ndarray, np.ndarray], data: st.DataObject, hour: int, minute: int
    ) -> None:
        """La Celda_Hora positiva coincide con la búsqueda exhaustiva de referencia."""
        lat, lon = g
        ev_lat, ev_lon = coord_in(data.draw, lat), coord_in(data.draw, lon)
        cat = catalog_frame(
            [{"date": DAY, "lat": ev_lat, "lon": ev_lon, "hour_utc": hour + minute / 60}]
        )
        pos, skipped = table.label_positives(cat, lat, lon, WORLD)
        self.assertEqual(len(skipped), 0)
        t, y, x = reference_cell(lat, lon, ev_lat, ev_lon, hour, minute)
        self.assertEqual(len(pos), 1)
        row = pos.iloc[0]
        self.assertEqual((row["time"], row["latitude"], row["longitude"]), (t, y, x))
        self.assertEqual(row["cell_id"], table.make_cell_id(t, y, x))
        self.assertEqual(row["event_id"], "20190530-0")

    # Feature: multimodal-tornado-predictor, Property 17: Un Evento por positivo
    @settings(max_examples=100, deadline=None)
    @given(
        events=st.lists(
            st.tuples(
                st.sampled_from([DAY, dt.date(2019, 5, 31), None]),
                st.sampled_from([-35.0, -35.1, -35.25, -36.5, float("nan")]),
                st.sampled_from([-72.0, -71.9, -71.75]),
                st.sampled_from([12.0, 12.25, 12.75, 13.0, float("nan")]),
            ),
            max_size=12,
        ),
        rows=st.lists(st.integers(0, 200), min_size=12, max_size=12, unique=True),
    )
    def test_one_event_per_positive(self, events: list[tuple], rows: list[int]) -> None:
        """Cada positiva tiene un Evento y cada Evento incluido una positiva; gana el menor."""
        lat, lon = np.array([-35.0, -35.25]), np.array([-72.0, -71.75])
        region = common.Region("r", -34.8, -35.5, -72.2, -71.5)
        cat = catalog_frame(
            [{"date": d, "lat": y, "lon": x, "hour_utc": h} for d, y, x, h in events],
            rows[: len(events)],
        )
        pos, skipped = table.label_positives(cat, lat, lon, region)
        self.assertFalse(pos["cell_id"].duplicated().any())
        self.assertFalse(pos["event_id"].duplicated().any())
        self.assertTrue((pos["label"] == 1).all())
        # Referencia: la Celda_Hora de cada Evento por separado; el menor event_id de cada una gana.
        cell_of: dict[str, str] = {}
        for i in range(len(cat)):
            one, _ = table.label_positives(cat.iloc[[i]], lat, lon, region)
            if len(one):
                cell_of[one["event_id"].iloc[0]] = one["cell_id"].iloc[0]
        winners = {}
        for eid in sorted(cell_of, key=table.event_order):
            winners.setdefault(cell_of[eid], eid)
        self.assertEqual(dict(zip(pos["cell_id"], pos["event_id"], strict=True)), winners)
        collided = set(skipped.loc[skipped["reason"].str.startswith(table.COLLISION), "event_id"])
        self.assertEqual(collided, set(cell_of) - set(winners.values()))
        self.assertEqual(len(pos) + len(skipped), len(cat))

    # Feature: multimodal-tornado-predictor, Property 18: Muestreo de no etiquetadas
    @settings(max_examples=100, deadline=None)
    @given(
        n_hours=st.integers(1, 6),
        n_pos=st.integers(0, 6),
        ratio=st.integers(1, 1000),
        seed=st.integers(0, 2**32 - 1),
        data=st.data(),
    )
    def test_unlabeled_sample(
        self, n_hours: int, n_pos: int, ratio: int, seed: int, data: st.DataObject
    ) -> None:
        """Sin repetidos, sin positivas y de tamaño ``min(ratio × positivas, disponibles)``."""
        times = [T0 + pd.Timedelta(hours=h) for h in range(n_hours)]
        cand = table.candidate_cells(times, np.array([-35.0, -35.25]), np.array([-72.0, -71.75]))
        n_pos = min(n_pos, len(cand))
        positives = data.draw(st.permutations(cand["cell_id"].tolist()))[:n_pos]
        with contextlib.redirect_stdout(io.StringIO()):
            s = table.sample_unlabeled(cand, n_pos, ratio, seed, positives)
            again = table.sample_unlabeled(cand, n_pos, ratio, seed, positives)
        self.assertFalse(s["cell_id"].duplicated().any())
        self.assertFalse(set(s["cell_id"]) & set(positives))
        self.assertEqual(len(s), min(ratio * n_pos, len(cand) - n_pos))
        pd.testing.assert_frame_equal(s, again)

    def test_ratio_out_of_range(self) -> None:
        """Una razón fuera de 1..1000 se rechaza."""
        cand = table.candidate_cells([T0], np.array([-35.0]), np.array([-72.0]))
        for bad in (0, 1001):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                table.sample_unlabeled(cand, 1, bad, 0)

    def test_skipped_events_are_reported(self) -> None:
        """Eventos sin fecha, coordenadas u hora, o fuera de la región, se omiten con motivo."""
        region = common.Region("r", -34.8, -35.5, -72.2, -71.5)
        cat = catalog_frame(
            [
                {"date": None, "lat": -35.0, "lon": -72.0, "hour_utc": 12.0},
                {"date": DAY, "lat": float("nan"), "lon": -72.0, "hour_utc": 12.0},
                {"date": DAY, "lat": -35.0, "lon": -72.0, "hour_utc": float("nan")},
                {"date": DAY, "lat": -40.0, "lon": -72.0, "hour_utc": 12.0},
                {"date": DAY, "lat": -35.0, "lon": -72.0, "hour_utc": 12.0},
            ]
        )
        pos, skipped = table.label_positives(
            cat, np.array([-35.0]), np.array([-72.0]), region, [T0 + pd.Timedelta(hours=11)]
        )
        self.assertEqual(len(pos), 0)
        self.assertEqual(
            skipped["reason"].str.split(" ").str[0].tolist(),
            ["sin", "sin", "sin", "fuera", "sin"],
        )
        self.assertIn("ERA5", skipped["reason"].iloc[-1])

    def test_normalize_catalog(self) -> None:
        """Coordenadas en texto, hora ``HH:MM`` y fechas inválidas."""
        raw = pd.DataFrame(
            {
                table.CATALOG_DATE: ["2019-05-30", "no es fecha"],
                table.CATALOG_LAT: ["35,5 S", -36.0],
                table.CATALOG_LON: ["72.25 O", -71.0],
                table.CATALOG_HOUR: ["18:30", "25"],
            }
        )
        cat = table.normalize_catalog(raw)
        self.assertEqual(cat["date"].tolist(), [DAY, None])
        self.assertEqual(cat["lat"].tolist(), [-35.5, -36.0])
        self.assertEqual(cat["lon"].tolist(), [-72.25, -71.0])
        self.assertEqual(cat["hour_utc"].iloc[0], 18.5)
        self.assertTrue(math.isnan(cat["hour_utc"].iloc[1]))

    def test_fold_groups(self) -> None:
        """Positivas: su ``event_id``; no etiquetadas: un Evento del día, estable entre corridas."""
        cells = pd.DataFrame(
            {
                "cell_id": ["a", "b", "c", "d"],
                "time": utc_list(
                    ["2019-05-30 12:00", "2019-05-30 13:00", "2019-05-30 14:00", "2019-06-02 00:00"]
                ),
                "label": [1, 1, 0, 0],
                "event_id": ["20190530-9", "20190530-10", "", ""],
            }
        )
        g = table.assign_fold_groups(cells, 0)
        self.assertEqual(g.tolist()[:2], ["20190530-9", "20190530-10"])
        self.assertIn(g.iloc[2], {"20190530-9", "20190530-10"})
        self.assertIn(g.iloc[3], {"20190530-9", "20190530-10"})
        pd.testing.assert_series_equal(g, table.assign_fold_groups(cells, 0))
        self.assertEqual(table.fold_bucket("c", 0, 2), table.fold_bucket("c", 0, 2))


def utc_list(values: list[str]) -> pd.Series:
    """Serie de tiempos UTC."""
    return table.utc(values)


class LagsAndBuildTest(unittest.TestCase):
    """Propiedades 19, 20, 22 y 23."""

    # Feature: multimodal-tornado-predictor, Property 19: Rezagos y diferencias correctos
    @settings(max_examples=100, deadline=None)
    @given(
        series=st.lists(
            st.tuples(
                st.sampled_from([(-35.0, -72.0), (-35.25, -72.0)]),
                st.integers(0, 10),
                st.one_of(st.floats(-1e3, 1e3), st.just(float("nan"))),
            ),
            min_size=1,
            max_size=25,
            unique_by=lambda r: (r[0], r[1]),
        )
    )
    def test_lags(self, series: list[tuple]) -> None:
        """``_lag{k}`` es el valor en t - k h (NaN si falta) y ``_d{k}`` la diferencia."""
        hourly = pd.DataFrame(
            {
                "time": [T0 + pd.Timedelta(hours=h) for _, h, _ in series],
                "latitude": [p[0] for p, _, _ in series],
                "longitude": [p[1] for p, _, _ in series],
                "v": [v for _, _, v in series],
            }
        )
        out = table.add_lags(hourly, ["v"])
        self.assertEqual(len(out), len(hourly))
        np.testing.assert_array_equal(out["v"].to_numpy(), hourly["v"].to_numpy())
        lookup = {(p, h): v for p, h, v in series}
        for i, (p, h, v) in enumerate(series):
            for k in table.LAGS:
                ref = lookup.get((p, h - k), float("nan"))
                got = out[f"v_lag{k}"].iloc[i]
                self.assertTrue(got == ref or (math.isnan(got) and math.isnan(ref)))
                d = out[f"v_d{k}"].iloc[i]
                exp = v - ref
                self.assertTrue(d == exp or (math.isnan(d) and math.isnan(exp)))

    # Feature: multimodal-tornado-predictor, Property 20: Sin información del futuro
    @settings(max_examples=100, deadline=None)
    @given(d=inputs(), data=st.data(), config=st.sampled_from(table.CONFIGS))
    def test_no_future_information(self, d: dict, data: st.DataObject, config: str) -> None:
        """Alterar ERA5/GOES posteriores a t (o barridos con s > t) no cambia las filas de t."""
        t = data.draw(st.sampled_from(sorted(set(d["cells"]["time"]))))
        before = build(config, d)
        rng = np.random.default_rng(data.draw(st.integers(0, 2**16)))
        era5, goes = d["era5"].copy(), d["goes"].copy()
        later = era5["time"] > t
        era5.loc[later, list(table.ERA5_FEATURES)] = rng.normal(size=(int(later.sum()), 12))
        glater = goes["time"] > t
        goes.loc[glater, list(table.GOES_FEATURES)] = rng.normal(size=(int(glater.sum()), 4))
        # Barridos futuros en la hora t: se ignoran aunque traigan valores.
        at_t = goes["time"] == t
        goes.loc[at_t, "scan_start"] = goes.loc[at_t, "time"] + pd.Timedelta(minutes=5)
        goes.loc[at_t, list(table.GOES_FEATURES)] = 1e6
        after = table.build(config, d["cells"], era5, goes, d["embeddings"])
        b = before[before["time"] == t].reset_index(drop=True)
        a = after[after["time"] == t].reset_index(drop=True)
        cur = [c for c in table.GOES_FEATURES if c in a.columns]
        if cur:
            # Sin barrido válido en (t - 60, t] las Variables_GOES de t quedan en NaN.
            self.assertTrue(a[cur].isna().all().all())
            b = b.drop(columns=cur)
            a = a.drop(columns=cur)
            dcols = [
                c for c in a.columns if any(c.startswith(f"{g}_d") for g in table.GOES_FEATURES)
            ]
            b, a = b.drop(columns=dcols), a.drop(columns=dcols)
        pd.testing.assert_frame_equal(b, a)

    # Feature: multimodal-tornado-predictor, Property 22: Esquema por configuración y signo austral conservado
    @settings(max_examples=100, deadline=None)
    @given(d=inputs(), config=st.sampled_from(table.CONFIGS))
    def test_schema_and_southern_sign(self, d: dict, config: str) -> None:
        """Una fila por Celda_Hora, columnas clave + ``config_columns`` y SRH/STP idénticos."""
        out = build(config, d)
        n_emb = 3 if config == "embeddings" else 0
        self.assertEqual(
            list(out.columns), list(table.KEY_COLUMNS) + table.config_columns(config, n_emb)
        )
        self.assertEqual(sorted(out["cell_id"]), sorted(d["cells"]["cell_id"]))
        if config == "physical":
            self.assertEqual(len(table.config_columns(config)), 112)
        if config == "baseline_era5":
            self.assertEqual(len(table.config_columns(config)), 12)
        ref = d["era5"].copy()
        ref["time"] = table.utc(ref["time"])
        merged = out[table.POINT + ["srh_01", "srh_03", "stp_lm"]].merge(
            ref[table.POINT + ["srh_01", "srh_03", "stp_lm"]], on=table.POINT, suffixes=("", "_in")
        )
        self.assertEqual(len(merged), len(out))
        for c in ("srh_01", "srh_03", "stp_lm"):
            np.testing.assert_array_equal(merged[c].to_numpy(), merged[f"{c}_in"].to_numpy())
            self.assertTrue((merged[c] < 0).all())

    # Feature: multimodal-tornado-predictor, Property 23: Tabla determinista
    @settings(max_examples=100, deadline=None)
    @given(d=inputs(), config=st.sampled_from(table.CONFIGS))
    def test_deterministic(self, d: dict, config: str) -> None:
        """Dos construcciones con las mismas entradas dan la misma tabla (NaN igual a NaN)."""
        first = build(config, d)
        second = table.build(
            config,
            d["cells"].sample(frac=1.0, random_state=1),
            d["era5"].sample(frac=1.0, random_state=2),
            d["goes"],
            d["embeddings"],
        )
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(first, build(config, d))

    def test_missing_scan_and_embedding_are_nan(self) -> None:
        """Sin barrido en (t - 60, t] ni embedding: NaN y la fila se conserva."""
        lat, lon = np.array([-35.0]), np.array([-72.0])
        times = [T0, T0 + pd.Timedelta(hours=1)]
        cells = table.candidate_cells(times, lat, lon).assign(label=0, event_id="", fold_group="")
        goes = goes_frame(times, lat, lon, 0)
        goes.loc[1, "scan_start"] = goes.loc[1, "time"] - pd.Timedelta(minutes=60)
        emb = pd.DataFrame({"cell_id": [cells["cell_id"].iloc[0]], "emb_0000": [1.0]})
        out = table.build("embeddings", cells, era5_frame(times, lat, lon, 0), goes, emb)
        self.assertEqual(len(out), 2)
        self.assertTrue(out.loc[1, list(table.GOES_FEATURES)].isna().all())
        self.assertFalse(out.loc[0, list(table.GOES_FEATURES)].isna().any())
        self.assertEqual(out["emb_0000"].isna().tolist(), [False, True])

    def test_inference_table_has_no_labels(self) -> None:
        """Sin ``label`` en ``cells`` la tabla solo lleva las columnas clave de inferencia."""
        lat, lon = np.array([-35.0]), np.array([-72.0])
        cells = table.candidate_cells([T0], lat, lon)
        out = table.build("physical", cells, era5_frame([T0], lat, lon, 0))
        self.assertEqual(list(out.columns[:6]), list(table.INFER_KEY_COLUMNS))
        self.assertNotIn("label", out.columns)


class BuildTableCliTest(unittest.TestCase):
    """Prueba de humo de ``build_table.py`` con ERA5 y Catálogo ``.xlsx`` sintéticos."""

    BBOX = ["--region", "test-region", "--bbox", "-34.9", "-35.4", "-72.1", "-71.6"]

    def setUp(self) -> None:
        """Índices ERA5 de 10 a 14 UTC del 30 de mayo y un Catálogo con cuatro Eventos."""
        import synthetic

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.crops = self.root / "crops"
        self.model = self.root / "model"
        hours = list(range(10, 15))
        lat, lon = synthetic.era5_grid()
        shape = (len(hours), len(lat), len(lon))
        values = {c: np.full(shape, float(i + 1)) for i, c in enumerate(table.ERA5_FEATURES)}
        values["srh_01"] = -np.arange(np.prod(shape), dtype=float).reshape(shape) - 1.0
        synthetic.write_era5_indices(self.crops, "test-region", DAY, hours, values)
        catalog = pd.DataFrame(
            {
                table.CATALOG_DATE: ["2019-05-30"] * 4,
                table.CATALOG_LAT: ["-35.02", "-35,01", "-35.0", "-40.0"],
                table.CATALOG_LON: ["-71.98", "-71.99", "-72.0", "-72.0"],
                table.CATALOG_HOUR: ["12:10", "11:50", None, "12:00"],
            }
        )
        self.catalog = self.root / "tornados_chile.xlsx"
        catalog.to_excel(self.catalog, sheet_name="Final_Table", index=False, engine="openpyxl")

    def tearDown(self) -> None:
        """Borra el directorio temporal."""
        self._tmp.cleanup()

    def run_stage(self, *args: str) -> str:
        """Ejecuta ``build_table.run`` y devuelve lo impreso."""
        import build_table

        argv = ["--start", "2019-05-30", *self.BBOX, "--catalog", str(self.catalog), *args]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = build_table.run(
                build_table.build_parser().parse_args(argv), self.crops, self.model
            )
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_select_build_infer(self) -> None:
        """``select`` → ``cells.parquet``; ``build`` e ``infer`` → tablas por día."""
        log = self.run_stage("--stage", "select", "--ratio", "2", "--seed", "0")
        cells = pd.read_parquet(self.model / "test-region" / "cells.parquet")
        self.assertEqual(list(cells.columns), list(table.CELL_COLUMNS))
        self.assertEqual(cells["label"].tolist().count(1), 1)
        self.assertEqual(len(cells), 3)
        pos = cells[cells["label"] == 1].iloc[0]
        self.assertEqual(pos["cell_id"], "2019053012_-35.00_-072.00")
        self.assertEqual(pos["event_id"], "20190530-0")
        self.assertIn("20190530-1: colisión", log)
        self.assertIn("20190530-2: sin hora UTC", log)
        self.assertIn("20190530-3: fuera de la región", log)
        self.assertEqual(set(cells["fold_group"]), {"20190530-0"})

        log = self.run_stage("--stage", "build", "--config", "physical")
        self.assertIn("sin Variables_GOES", log)
        part = self.model / "test-region" / "tables" / "config=physical" / "date=2019-05-30"
        df = pd.read_parquet(part / "part-0.parquet")
        self.assertEqual(len(df), 3)
        self.assertEqual(
            list(df.columns), list(table.KEY_COLUMNS) + table.config_columns("physical")
        )
        self.assertTrue(df["goes_bt13_min"].isna().all())
        self.assertTrue((df["srh_01"] < 0).all())
        row = df[df["label"] == 1].iloc[0]
        self.assertEqual(row["srh_01_lag1"], row["srh_01"] + 4.0)  # misma celda, una hora antes
        self.assertIn("ya existe", self.run_stage("--stage", "build", "--config", "physical"))
        self.assertNotIn(
            "ya existe", self.run_stage("--stage", "build", "--config", "physical", "--force")
        )

        self.run_stage("--stage", "build", "--config", "baseline_era5")
        base = self.model / "test-region" / "tables" / "config=baseline_era5" / "date=2019-05-30"
        df = pd.read_parquet(base / "part-0.parquet")
        self.assertEqual(list(df.columns), list(table.KEY_COLUMNS) + list(table.ERA5_FEATURES))

        self.run_stage("--stage", "infer", "--config", "physical")
        inf = self.model / "test-region" / "inference" / "config=physical" / "date=2019-05-30"
        df = pd.read_parquet(inf / "part-0.parquet")
        self.assertEqual(len(df), 5 * 4)
        self.assertNotIn("label", df.columns)


if __name__ == "__main__":
    unittest.main()
