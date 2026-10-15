"""Pruebas de propiedades de las Variables_GOES (``scripts/model/goes_features.py``)."""

import datetime as dt
import math
import sys
import unittest
from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

import goes_features as gf  # noqa: E402

FEATS = ("goes_bt13_min", "goes_cold_frac", "goes_wv_ir_max")


@st.composite
def goes_window(
    draw: st.DrawFn, min_valid: float = 0.0, max_valid: float = 1.0, strict_max: bool = False
) -> tuple[np.ndarray, np.ndarray, float, float, float, float]:
    """Ventana sintética ``int16`` de C13 y C08 con relleno (−1) en posiciones aleatorias.

    La fracción de píxeles válidos de C13 queda en [``min_valid``, ``max_valid``] (o
    [``min_valid``, ``max_valid``) con ``strict_max``). C08 lleva relleno independiente.
    """
    h = draw(st.integers(1, 12))
    w = draw(st.integers(1, 12))
    n = h * w
    lo = math.ceil(min_valid * n)
    hi = math.ceil(max_valid * n) - 1 if strict_max else math.floor(max_valid * n)
    n_valid = draw(st.integers(lo, hi))
    raw13 = draw(arrays(np.int16, (h, w), elements=st.integers(0, 4095)))
    raw08 = draw(arrays(np.int16, (h, w), elements=st.integers(0, 4095)))
    perm = draw(st.permutations(range(n)))
    flat13 = raw13.ravel()
    flat13[list(perm[n_valid:])] = gf.FILL_VALUE
    fill08 = draw(arrays(np.bool_, (h, w)))
    raw08[fill08] = gf.FILL_VALUE
    scale13 = draw(st.floats(0.01, 0.1))
    offset13 = draw(st.floats(100.0, 220.0))
    scale08 = draw(st.floats(0.01, 0.1))
    offset08 = draw(st.floats(100.0, 220.0))
    return flat13.reshape(h, w), raw08, scale13, offset13, scale08, offset08


def reference(
    raw13: np.ndarray, raw08: np.ndarray, s13: float, o13: float, s08: float, o08: float
) -> dict[str, float]:
    """Implementación de referencia con máscaras explícitas, píxel a píxel."""
    bt13: list[float] = []
    diffs: list[float] = []
    for r13, r08 in zip(raw13.ravel().tolist(), raw08.ravel().tolist(), strict=True):
        b13 = None if r13 == -1 else float(r13) * s13 + o13
        b08 = None if r08 == -1 else float(r08) * s08 + o08
        if b13 is not None:
            bt13.append(b13)
            if b08 is not None:
                diffs.append(b08 - b13)
    nan = float("nan")
    if len(bt13) < 0.5 * raw13.size:
        return {"goes_bt13_min": nan, "goes_cold_frac": nan, "goes_wv_ir_max": nan}
    return {
        "goes_bt13_min": min(bt13),
        "goes_cold_frac": sum(b < 213.15 for b in bt13) / len(bt13),
        "goes_wv_ir_max": max(diffs) if diffs else nan,
    }


def features(
    raw13: np.ndarray, raw08: np.ndarray, s13: float, o13: float, s08: float, o08: float
) -> dict[str, float]:
    """``window_features`` sobre la ventana decodificada con ``decode``."""
    return gf.window_features(gf.decode(raw13, s13, o13), gf.decode(raw08, s08, o08))


def same(a: float, b: float) -> bool:
    """Igualdad exacta que considera NaN igual a NaN."""
    return (math.isnan(a) and math.isnan(b)) or a == b


class GoesFeaturesTest(unittest.TestCase):
    """Propiedades 1, 2, 3, 4 y 21 del diseño."""

    # Feature: multimodal-tornado-predictor, Property 1: Variables_GOES coinciden con el modelo de referencia
    @settings(max_examples=100, deadline=None)
    @given(goes_window(min_valid=0.5))
    def test_property_1_reference_model(
        self, win: tuple[np.ndarray, np.ndarray, float, float, float, float]
    ) -> None:
        """Con ≥ 50 % de C13 válidos, las variables coinciden con la referencia y sus cotas."""
        got = features(*win)
        ref = reference(*win)
        for name in FEATS:
            self.assertTrue(same(got[name], ref[name]), f"{name}: {got[name]} != {ref[name]}")
        bt13 = gf.decode(win[0], win[2], win[3])
        valid = bt13[np.isfinite(bt13)]
        self.assertTrue(np.all(got["goes_bt13_min"] <= valid))
        self.assertGreaterEqual(got["goes_cold_frac"], 0.0)
        self.assertLessEqual(got["goes_cold_frac"], 1.0)

    # Feature: multimodal-tornado-predictor, Property 2: Invariancia ante permutación de píxeles
    @settings(max_examples=100, deadline=None)
    @given(goes_window(), st.data())
    def test_property_2_permutation(
        self, win: tuple[np.ndarray, np.ndarray, float, float, float, float], data: st.DataObject
    ) -> None:
        """Permutar los píxeles por igual en C08 y C13 no cambia ninguna variable."""
        raw13, raw08, *coefs = win
        perm = np.array(data.draw(st.permutations(range(raw13.size))), dtype=np.intp)
        p13 = raw13.ravel()[perm].reshape(raw13.shape)
        p08 = raw08.ravel()[perm].reshape(raw08.shape)
        a = features(raw13, raw08, *coefs)
        b = features(p13, p08, *coefs)
        for name in FEATS:
            self.assertTrue(same(a[name], b[name]), f"{name}: {a[name]} != {b[name]}")

    # Feature: multimodal-tornado-predictor, Property 3: Ventanas con pocos píxeles válidos dan NaN
    @settings(max_examples=100, deadline=None)
    @given(goes_window(max_valid=0.5, strict_max=True))
    def test_property_3_low_valid_is_nan(
        self, win: tuple[np.ndarray, np.ndarray, float, float, float, float]
    ) -> None:
        """Con menos de 50 % de C13 válidos, todas las variables son NaN."""
        got = features(*win)
        for name in FEATS:
            self.assertTrue(math.isnan(got[name]), name)
        self.assertLess(got["valid_frac_c13"], gf.MIN_VALID_FRACTION)

    def test_property_3_boundaries(self) -> None:
        """Casos límite de 100 píxeles: 0 % y 49 % válidos dan NaN; 50 % ya calcula."""
        raw08 = np.full((10, 10), 1000, dtype=np.int16)
        for n_valid, expect_nan in ((0, True), (49, True), (50, False)):
            with self.subTest(valid=n_valid):
                raw13 = np.full(100, gf.FILL_VALUE, dtype=np.int16)
                raw13[:n_valid] = 1500
                got = features(raw13.reshape(10, 10), raw08, 0.1, 100.0, 0.1, 100.0)
                for name in FEATS:
                    self.assertEqual(math.isnan(got[name]), expect_nan, name)
                self.assertAlmostEqual(got["valid_frac_c13"], n_valid / 100)

    # Feature: multimodal-tornado-predictor, Property 4: Tasa de enfriamiento
    @settings(max_examples=100, deadline=None)
    @given(
        st.one_of(st.floats(150.0, 330.0), st.just(float("nan")), st.just(float("inf"))),
        st.one_of(st.floats(150.0, 330.0), st.just(float("nan")), st.just(float("-inf"))),
        st.one_of(
            st.floats(0.0, 60.0),
            st.sampled_from([15.0, 30.0, 14.999, 30.001]),
            st.just(float("nan")),
        ),
    )
    def test_property_4_cooling_rate(self, early: float, late: float, dt_min: float) -> None:
        """Fórmula exacta dentro de [15, 30] min con BT finitas, positiva al enfriarse; NaN si no."""
        got = gf.cooling_rate(early, late, dt_min)
        ok = math.isfinite(early) and math.isfinite(late) and 15.0 <= dt_min <= 30.0
        if not ok:
            self.assertTrue(math.isnan(got))
            return
        self.assertEqual(got, (early - late) * 15.0 / dt_min)
        if early > late:
            self.assertGreater(got, 0.0)

    # Feature: multimodal-tornado-predictor, Property 21: Selección del barrido GOES
    @settings(max_examples=100, deadline=None)
    @given(
        st.lists(st.integers(-180, 180), max_size=12),
        st.integers(-120, 120),
    )
    def test_property_21_scan_selection(self, minutes: list[int], t_min: int) -> None:
        """``select_scan`` devuelve el sello máximo en (t − 60 min, t] o ``None``."""
        base = dt.datetime(2019, 5, 30, 18)
        scans = [base + dt.timedelta(minutes=m) for m in minutes]
        t = base + dt.timedelta(minutes=t_min)
        inside = [s for s in scans if t - dt.timedelta(minutes=60) < s <= t]
        idx = gf.select_scan(scans, t)
        if not inside:
            self.assertIsNone(idx)
            return
        assert idx is not None
        self.assertEqual(scans[idx], max(inside))
        self.assertLessEqual(scans[idx], t)

    def test_property_21_boundaries(self) -> None:
        """Un barrido justo en t − 60 min queda fuera y uno justo en t, dentro."""
        t = dt.datetime(2019, 5, 30, 18)
        self.assertIsNone(gf.select_scan([t - dt.timedelta(minutes=60)], t))
        self.assertEqual(gf.select_scan([t - dt.timedelta(minutes=60), t], t), 1)
        self.assertIsNone(gf.select_scan([t + dt.timedelta(minutes=1)], t))


if __name__ == "__main__":
    unittest.main()
