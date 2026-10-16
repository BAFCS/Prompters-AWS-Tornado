"""Pruebas de viewer_app/live_model.py sin red: grilla, hora disponible, ERA5 típico y modelo v2."""

import datetime as dt
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import live_model as lm  # noqa: E402


class LiveModelTests(unittest.TestCase):
    def test_grid_matches_region(self) -> None:
        lat, lon = lm.grid()
        self.assertEqual((lat[0], lat[-1], len(lat)), (-30.0, -56.0, 105))
        self.assertEqual((lon[0], lon[-1], len(lon)), (-76.0, -66.0, 41))

    def test_latest_hour_waits_for_latency(self) -> None:
        now = dt.datetime(2026, 10, 16, 3, 10, tzinfo=dt.UTC)
        self.assertEqual(lm.latest_hour(now), dt.datetime(2026, 10, 16, 2))
        now = dt.datetime(2026, 10, 16, 3, 40, tzinfo=dt.UTC)
        self.assertEqual(lm.latest_hour(now), dt.datetime(2026, 10, 16, 3))

    def test_typical_era5_covers_lags(self) -> None:
        lat, lon = lm.grid()
        t = dt.datetime(2026, 10, 13, 19)
        df, source = lm.era5_frame(t, lat[:3], lon[:2], "tipico")
        self.assertEqual(source, "tipico")
        self.assertEqual(df["time"].nunique(), 4)  # t-3..t
        self.assertEqual(len(df), 4 * 3 * 2)
        self.assertAlmostEqual(df["cape"].iloc[0], lm.typical_values()["cape"])

    def test_real_falls_back_to_typical_without_files(self) -> None:
        lat, lon = lm.grid()
        _, source = lm.era5_frame(dt.datetime(1999, 1, 1, 12), lat[:2], lon[:2], "real")
        self.assertEqual(source, "tipico")

    def test_v2_model_loads_and_is_physical(self) -> None:
        from sm_job import inference

        bundle = inference.model_fn(str(lm.MODEL_DIR))
        self.assertEqual(bundle.config, "physical")
        self.assertIsNone(bundle.reducer)
        self.assertFalse(any(c.startswith("emb") for c in bundle.model_columns))
        self.assertTrue(np.isfinite(len(bundle.model_columns)))


if __name__ == "__main__":
    unittest.main()
