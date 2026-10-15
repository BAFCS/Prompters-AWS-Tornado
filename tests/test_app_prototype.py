"""Prueba sintética del prototipo (``scripts/app/prototype.py``): índices → sitio y alertas, sin red."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import predictions  # noqa: E402
import prototype  # noqa: E402
from app_synthetic import NoNetworkMixin  # noqa: E402


def _idx(path: Path) -> None:
    """``era5_idx`` sintético 2 horas × 3 × 3 con una celda muy favorable en Biobío."""
    lat = np.array([-36.5, -37.0, -37.5])
    lon = np.array([-73.0, -72.5, -72.0])
    time = pd.to_datetime(["2019-05-30T19:00", "2019-05-30T20:00"])
    cape = np.full((2, 3, 3), 100.0)
    shear = np.full((2, 3, 3), 5.0)
    cape[1, 1, 1], shear[1, 1, 1] = 2000.0, 30.0
    xr.Dataset(
        {"cape": (("time", "latitude", "longitude"), cape),
         "shear_06": (("time", "latitude", "longitude"), shear)},
        coords={"time": time, "latitude": lat, "longitude": lon},
    ).to_netcdf(path, engine="h5netcdf")  # fmt: skip


class PrototypeTest(NoNetworkMixin):
    """Recorre predicción, CSV válido, JSON del sitio y alertas."""

    def test_end_to_end(self) -> None:
        """La celda favorable da 100 %, el CSV pasa ``predictions.load`` y hay una alerta."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = root / "era5_idx_20190530.nc"
            _idx(f)
            pred = prototype.predict_day(f)
            self.assertEqual(len(pred), 18)
            self.assertAlmostEqual(float(pred["probability"].max()), 1.0)
            csv = prototype.write_predictions(pred, root / "pred", "2019-05-30")
            loaded = predictions.load(csv)
            self.assertEqual(loaded.meta["modelo"], "sustituto")

            payload = prototype.day_payload(pred, "sustituto")
            self.assertEqual(sorted(payload["hours"]), ["19", "20"])
            self.assertIn(prototype.SCALE, payload["hours"]["20"])
            prototype.build_site([payload], None, root / "site")
            index = json.loads((root / "site" / "days" / "index.json").read_text("utf-8"))
            self.assertEqual(index["default"], "2019-05-30")
            self.assertIn(prototype.DISCLAIMER, (root / "site" / "index.html").read_text("utf-8"))

            alerts = prototype.alerts(pred, "sustituto")
            biobio = [a for a in alerts if a["zona"] == "Biobío"]
            self.assertEqual([a["hora_utc"] for a in biobio], [20])
            self.assertEqual(biobio[0]["indice_max"], 100.0)
            self.assertTrue(all(a["hora_utc"] == 20 for a in alerts))


if __name__ == "__main__":
    unittest.main()
