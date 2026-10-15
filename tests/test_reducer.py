"""Pruebas de propiedades del Reductor (``scripts/model/reducer.py``)."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from sklearn.decomposition import PCA

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

import reducer  # noqa: E402

FLOATS = st.floats(-1e3, 1e3, allow_nan=False, allow_infinity=False, width=64)
MODEL_IDS = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=30
)


@st.composite
def fitted_case(draw: st.DrawFn) -> tuple[int, np.ndarray]:
    """``(n_components, matriz de ajuste)`` con al menos ``n_components`` filas y columnas."""
    n = draw(st.integers(reducer.MIN_COMPONENTS, reducer.MAX_COMPONENTS))
    dim = draw(st.integers(n, n + 6))
    rows = draw(st.integers(n, n + 12))
    x = draw(arrays(np.float64, (rows, dim), elements=FLOATS))
    return n, x


def with_nan_rows(draw: st.DrawFn, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Copia de ``x`` con NaN en filas aleatorias y la máscara de esas filas."""
    bad = draw(arrays(np.bool_, (x.shape[0],)))
    y = x.copy()
    y[bad, draw(st.integers(0, x.shape[1] - 1))] = np.nan
    return y, bad


class ReducerTest(unittest.TestCase):
    """Propiedades 11, 12, 13 y 14 y los errores de dimensión y filas."""

    # Feature: multimodal-tornado-predictor, Property 11: Forma de la proyección del Reductor
    @settings(max_examples=100, deadline=None)
    @given(case=fitted_case(), data=st.data())
    def test_projection_shape(self, case: tuple[int, np.ndarray], data: st.DataObject) -> None:
        """N filas en el mismo orden, ``n_components`` columnas y NaN en las filas inválidas."""
        n, x = case
        r = reducer.Reducer(n, "titan").fit(x)
        n_rows = data.draw(st.integers(1, 20))
        new = data.draw(arrays(np.float64, (n_rows, x.shape[1]), elements=FLOATS))
        new, bad = with_nan_rows(data.draw, new)
        out = r.transform(new)
        self.assertEqual(out.shape, (n_rows, n))
        self.assertTrue(np.isnan(out[bad]).all())
        self.assertTrue(np.isfinite(out[~bad]).all())
        # Mismo orden: cada fila válida coincide con su proyección individual.
        for i in np.flatnonzero(~bad):
            np.testing.assert_allclose(out[i], r.transform(new[i : i + 1])[0], atol=1e-6)

    # Feature: multimodal-tornado-predictor, Property 12: Varianza explicada acotada
    @settings(max_examples=100, deadline=None)
    @given(case=fitted_case())
    def test_explained_variance_bounded(self, case: tuple[int, np.ndarray]) -> None:
        """Fracciones en [0, 1], acumulada no decreciente y ≤ 1, igual a scikit-learn."""
        n, x = case
        # Varianza total no despreciable frente a la magnitud de los datos (evita cancelación).
        total = float(((x - x.mean(axis=0)) ** 2).sum())
        assume(total > 1e-8 * max(1.0, float((x**2).sum())))
        r = reducer.Reducer(n, "titan").fit(x)
        ratio, cumulative = r.explained_variance()
        self.assertEqual(len(ratio), n)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in ratio))
        self.assertTrue(all(b >= a for a, b in zip(cumulative, cumulative[1:], strict=False)))
        self.assertLessEqual(cumulative[-1], 1.0)
        ref = PCA(n_components=n, svd_solver="full").fit(x)
        np.testing.assert_allclose(ratio, ref.explained_variance_ratio_, atol=1e-7)

    # Feature: multimodal-tornado-predictor, Property 13: Ida y vuelta de guardar y cargar el Reductor
    @settings(max_examples=100, deadline=None)
    @given(case=fitted_case(), model_id=MODEL_IDS, data=st.data())
    def test_save_load_round_trip(
        self, case: tuple[int, np.ndarray], model_id: str, data: st.DataObject
    ) -> None:
        """Cargar lo guardado da las mismas proyecciones, componentes y modelo."""
        n, x = case
        r = reducer.Reducer(n, model_id).fit(x)
        new, _ = with_nan_rows(data.draw, x)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reducer.npz"
            r.save(path)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["reducer.npz"])
            loaded = reducer.Reducer.load(path)
        self.assertEqual(loaded.n_components, n)
        self.assertEqual(loaded.model_id, model_id)
        self.assertEqual(loaded.input_dim, x.shape[1])
        np.testing.assert_array_equal(loaded.transform(new), r.transform(new))
        self.assertEqual(loaded.explained_variance(), r.explained_variance())

    # Feature: multimodal-tornado-predictor, Property 14: Número de componentes fuera de rango
    @settings(max_examples=100, deadline=None)
    @given(n=st.one_of(st.integers(max_value=7), st.integers(min_value=17)))
    def test_out_of_range_components(self, n: int) -> None:
        """Fuera de [8, 16] falla con el valor y el rango, sin escribir archivos."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as cm:
                reducer.Reducer(n, "titan")
            self.assertEqual(list(Path(tmp).iterdir()), [])
        msg = str(cm.exception)
        self.assertIn(str(n), msg)
        self.assertIn("[8, 16]", msg)

    def test_non_integer_components(self) -> None:
        """Un número no entero de componentes también se rechaza."""
        for bad in (8.5, "8", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reducer.Reducer(bad, "titan")  # type: ignore[arg-type]

    def test_different_dimension_is_rejected(self) -> None:
        """Proyectar con otra dimensión falla con la esperada y la recibida."""
        x = np.random.default_rng(0).standard_normal((20, 12))
        r = reducer.Reducer(8, "titan").fit(x)
        with self.assertRaises(ValueError) as cm:
            r.transform(np.zeros((3, 13)))
        self.assertIn("12", str(cm.exception))
        self.assertIn("13", str(cm.exception))

    def test_too_few_valid_rows(self) -> None:
        """Menos filas válidas que componentes: error con las esperadas y las recibidas."""
        x = np.random.default_rng(0).standard_normal((10, 12))
        x[3:, 0] = np.nan  # quedan 3 filas válidas
        with self.assertRaises(ValueError) as cm:
            reducer.Reducer(8, "titan").fit(x)
        self.assertIn("8", str(cm.exception))
        self.assertIn("3", str(cm.exception))

    def test_nan_rows_excluded_from_fit(self) -> None:
        """Las filas con NaN no influyen en el ajuste."""
        rng = np.random.default_rng(1)
        x = rng.standard_normal((30, 10))
        dirty = np.vstack([x, np.full((5, 10), np.nan)])
        a = reducer.Reducer(8, "m").fit(x)
        b = reducer.Reducer(8, "m").fit(dirty)
        np.testing.assert_allclose(a.transform(x), b.transform(x))


if __name__ == "__main__":
    unittest.main()
