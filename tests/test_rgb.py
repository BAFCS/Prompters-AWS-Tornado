"""Pruebas de propiedades del Compositor_RGB (``scripts/model/rgb.py``)."""

import dataclasses
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

import rgb  # noqa: E402

RECIPE_KEYS = sorted(rgb.RECIPES)


@st.composite
def window(draw: st.DrawFn) -> tuple[rgb.Recipe, dict[str, np.ndarray]]:
    """Receta de ``RECIPES`` con rellenos aleatorios y una ventana con ≥ 50 % válidos por banda."""
    recipe = rgb.RECIPES[draw(st.sampled_from(RECIPE_KEYS))]
    fills = draw(st.lists(st.integers(0, 255), min_size=3, max_size=3))
    r, g, b = (
        dataclasses.replace(ch, fill=f) for ch, f in zip(recipe.channels, fills, strict=True)
    )
    recipe = dataclasses.replace(recipe, channels=(r, g, b))
    h = draw(st.integers(1, 16))
    w = draw(st.integers(1, 16))
    n = h * w
    bands: dict[str, np.ndarray] = {}
    for b in recipe.bands:
        bt = draw(arrays(np.float64, (h, w), elements=st.floats(150.0, 320.0)))
        n_bad = draw(st.integers(0, n // 2))
        bad = draw(st.permutations(range(n)))[:n_bad]
        flat = bt.ravel()
        flat[list(bad)] = np.nan
        bands[b] = flat.reshape(h, w)
    return recipe, bands


class RgbTest(unittest.TestCase):
    """Propiedades 5, 6 y 7 del diseño."""

    # Feature: multimodal-tornado-predictor, Property 5: Forma de la imagen RGB y relleno de píxeles sin dato
    @settings(max_examples=100, deadline=None)
    @given(window(), st.integers(rgb.MIN_SIZE, rgb.MAX_SIZE))
    def test_property_5_shape_and_fill(
        self, win: tuple[rgb.Recipe, dict[str, np.ndarray]], size: int
    ) -> None:
        """``uint8`` (size, size, 3); relleno por canal donde falta dato; fracción sin dato real."""
        recipe, bands = win
        res = rgb.compose(bands, recipe, size)
        self.assertEqual(res.rgb.dtype, np.uint8)
        self.assertEqual(res.rgb.shape, (size, size, 3))
        any_missing = np.zeros(next(iter(bands.values())).shape, dtype=bool)
        for c, ch in enumerate(recipe.channels):
            vals = rgb.channel_values(bands, ch)
            miss = ~np.isfinite(vals)
            any_missing |= miss
            self.assertTrue(np.all(res.normalized[..., c][miss] == ch.fill), ch.expr)
        self.assertEqual(res.missing_frac, float(any_missing.mean()))

    # Feature: multimodal-tornado-predictor, Property 6: Ida y vuelta de la normalización
    @settings(max_examples=100, deadline=None)
    @given(
        st.floats(-100.0, 300.0),
        st.floats(1.0, 200.0),
        st.data(),
    )
    def test_property_6_round_trip(self, lower: float, width: float, data: st.DataObject) -> None:
        """Error ≤ (upper − lower) / 255 dentro del rango y el límite exacto fuera de él."""
        upper = lower + width
        ch = rgb.Channel("C13", lower, upper, 0)
        bt = data.draw(
            arrays(np.float64, st.integers(1, 64), elements=st.floats(lower - 50, upper + 50))
        )
        back = rgb.denormalize(rgb.normalize(bt, ch), ch)
        step = (upper - lower) / 255.0
        inside = (bt >= lower) & (bt <= upper)
        self.assertTrue(np.all(np.abs(back[inside] - bt[inside]) <= step))
        self.assertTrue(np.all(back[bt < lower] == lower))
        self.assertTrue(np.all(back[bt > upper] == upper))

    # Feature: multimodal-tornado-predictor, Property 7: Composición determinista
    @settings(max_examples=100, deadline=None)
    @given(window(), st.integers(rgb.MIN_SIZE, 512))
    def test_property_7_deterministic(
        self, win: tuple[rgb.Recipe, dict[str, np.ndarray]], size: int
    ) -> None:
        """Componer y codificar dos veces da PNG idénticos byte a byte."""
        recipe, bands = win
        a = rgb.to_png_bytes(rgb.compose(bands, recipe, size).rgb)
        b = rgb.to_png_bytes(rgb.compose({k: v.copy() for k, v in bands.items()}, recipe, size).rgb)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
