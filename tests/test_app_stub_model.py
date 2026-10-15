"""Ejemplos del Modelo_Sustituto (Req. 5.4, 5.7, 5.8). Sin red ni xgboost."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))

import contracts  # noqa: E402
import stub_model  # noqa: E402

INFERENCE_PY = ROOT / "scripts" / "model" / "sm_job" / "inference.py"


def _table(cape: list[float], shear: list[float]) -> pd.DataFrame:
    """Tabla mínima con clave y las columnas de ``REQUIRED``."""
    n = len(cape)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-15"] * n),
            "hour_utc": np.arange(n, dtype=np.int64) % 24,
            "latitude": np.linspace(-56.0, -30.0, n),
            "longitude": np.full(n, -70.0),
            "cape": cape,
            "shear_06": shear,
        }
    )


class ScoreTest(unittest.TestCase):
    """``score``: rango, monotonía y NaN."""

    def test_reference_values(self) -> None:
        """Ejemplos a mano: 0, mitad, saturación y producto."""
        cape = np.array([0.0, 500.0, 1000.0, 5000.0, 500.0])
        shear = np.array([25.0, 25.0, 25.0, 100.0, 12.5])
        np.testing.assert_allclose(stub_model.score(cape, shear), [0.0, 0.5, 1.0, 1.0, 0.25])

    def test_nan_gives_zero(self) -> None:
        """NaN en CAPE, en cizalladura o en ambos → 0 (Req. 5.7)."""
        out = stub_model.score(np.array([np.nan, 2000.0, np.nan]), np.array([30.0, np.nan, np.nan]))
        np.testing.assert_array_equal(out, [0.0, 0.0, 0.0])

    def test_inf_and_negative_clipped(self) -> None:
        """``±inf`` y negativos se recortan; el resultado sigue en [0, 1] y sin NaN (Req. 5.4)."""
        cape = np.array([np.inf, -np.inf, -100.0, np.inf, 1000.0])
        shear = np.array([np.inf, 25.0, 25.0, -5.0, -np.inf])
        out = stub_model.score(cape, shear)
        np.testing.assert_array_equal(out, [1.0, 0.0, 0.0, 0.0, 0.0])
        self.assertFalse(np.isnan(out).any())

    def test_monotonic_examples(self) -> None:
        """Más CAPE y más cizalladura nunca bajan el puntaje (Req. 5.8)."""
        cape = np.array([0.0, 200.0, 200.0, 800.0, 1500.0, 1500.0])
        shear = np.array([5.0, 5.0, 10.0, 10.0, 20.0, 40.0])
        out = stub_model.score(cape, shear)
        self.assertTrue((np.diff(out) >= 0).all(), out)


class PredictTest(unittest.TestCase):
    """``predict``: columnas, formato y ``config``."""

    def test_columns_match_inference(self) -> None:
        """``OUTPUT_COLUMNS`` es igual al de ``inference.py`` en contenido y orden."""
        source = INFERENCE_PY.read_text(encoding="utf-8")
        self.assertEqual(
            contracts.tuple_constant(source, "OUTPUT_COLUMNS"), stub_model.OUTPUT_COLUMNS
        )

    def test_output_format(self) -> None:
        """Columnas en orden, fecha como texto, hora entera y ``config`` con prefijo."""
        df = _table([0.0, 1000.0, np.nan], [25.0, 25.0, 25.0])
        out = stub_model.predict(df, "baseline_era5")
        self.assertEqual(tuple(out.columns), stub_model.OUTPUT_COLUMNS)
        self.assertEqual(len(out), 3)
        self.assertEqual(out["date"].tolist(), ["2026-08-15"] * 3)
        self.assertTrue(pd.api.types.is_integer_dtype(out["hour_utc"]))
        self.assertEqual(out["hour_utc"].tolist(), [0, 1, 2])
        self.assertEqual(set(out["config"]), {"sustituto/baseline_era5"})
        np.testing.assert_allclose(out["probability"], [0.0, 1.0, 0.0])
        np.testing.assert_allclose(out["latitude"], df["latitude"])

    def test_keeps_input_order_with_custom_index(self) -> None:
        """Un índice desordenado no reordena ni desalinea las filas."""
        df = _table([1000.0, 0.0], [25.0, 25.0]).set_index(pd.Index([7, 3]))
        out = stub_model.predict(df, "physical")
        np.testing.assert_allclose(out["probability"], [1.0, 0.0])
        self.assertEqual(out.index.tolist(), [0, 1])

    def test_empty_table(self) -> None:
        """Tabla vacía → salida vacía con las mismas columnas."""
        out = stub_model.predict(_table([], []), "baseline_era5")
        self.assertEqual(tuple(out.columns), stub_model.OUTPUT_COLUMNS)
        self.assertEqual(len(out), 0)


if __name__ == "__main__":
    unittest.main()
