"""Prueba sintética del prototipo (``scripts/app/prototype.py``): índices → sitio y alertas, sin red."""

import html
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


EXPECTED_LINES = [
    'Modelo: XGBoost v2 "physical" (ERA5 + GOES físicos), 2026-10-15',
    "ROC-AUC 0,893 · PR-AUC 0,429 (IC95 0,32–0,60; azar 0,031) · Brier 0,024",
    "Umbral 0,50: F1 0,47 (IC95 0,34–0,58) · Precisión 0,49 · Recall 0,46 · MCC 0,46 · CSI 0,31",
    "Umbral 0,28 (F1 óptimo): F1 0,57 · Precisión 0,49 · Recall 0,68 · MCC 0,56",
    "Holdout sin 30–31/05/2019: F1 0,56 · PR-AUC 0,51 · CSI 0,39",
    "Baseline solo ERA5: ROC-AUC 0,816 · F1 0,43",
]
NOTE = (
    "Puntaje = índice relativo de favorabilidad, no probabilidad calibrada. "
    "Accuracy no se reporta por el desbalance 1:30."
)


def _payload() -> dict:
    """Payload mínimo de un día (1 celda, 1 hora) del modelo v2 physical."""
    pred = pd.DataFrame(
        {
            "date": ["2019-05-30"],
            "hour_utc": [20],
            "latitude": [-37.0],
            "longitude": [-72.5],
            "probability": [0.5],
        }
    )
    return prototype.day_payload(pred, "real", {"config": "physical", "version": "v2"})


class SiteMetricsTest(NoNetworkMixin):
    """Stamp de métricas del v2 y control de escala logarítmica en la página."""

    def test_metric_lines(self) -> None:
        """Las líneas formateadas coinciden con las cifras de la validación del v2."""
        metrics = prototype.load_metrics()
        assert metrics is not None
        lines = prototype.metric_lines(metrics)
        self.assertEqual(lines[: len(EXPECTED_LINES)], EXPECTED_LINES)
        self.assertIn("Validación LOEO", lines[-1])
        self.assertEqual(metrics["nota"], NOTE)

    def test_stamp_in_site(self) -> None:
        """``build_site`` inyecta el stamp y escribe ``metricas.json``."""
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            prototype.build_site([_payload()], None, site)
            page = (site / "index.html").read_text("utf-8")
            self.assertIn('id="stamp"', page)
            self.assertIn('data-config="physical"', page)
            self.assertIn('data-version="v2"', page)
            self.assertNotIn("__STAMP__", page)
            for line in [*EXPECTED_LINES, NOTE]:
                self.assertIn(html.escape(line), page)
            saved = json.loads((site / "metricas.json").read_text("utf-8"))
            self.assertEqual(saved, prototype.load_metrics())

    def test_no_stamp_without_metrics(self) -> None:
        """Sin métricas no hay stamp ni ``metricas.json``."""
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            prototype.write_index(site, None)
            page = (site / "index.html").read_text("utf-8")
            self.assertNotIn('id="stamp"', page)
            self.assertNotIn("__STAMP__", page)
            self.assertFalse((site / "metricas.json").exists())

    def test_log_toggle(self) -> None:
        """El toggle log existe, arranca en lineal y la leyenda log usa ticks 0,001…1."""
        page = prototype.INDEX_HTML
        self.assertIn('<input id="log" type="checkbox">', page)
        self.assertIn("FLOOR=1e-3", page)
        self.assertIn('["0,001","0,01","0,1","1"]', page)


if __name__ == "__main__":
    unittest.main()
