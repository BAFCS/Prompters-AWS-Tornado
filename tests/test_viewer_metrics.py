"""Pruebas sin red del stamp de métricas v2 y de la escala logarítmica del mapa de Predecir."""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import model_metrics as mm  # noqa: E402
from viewer_app import p_predict  # noqa: E402

# Cifras de .agents/tasks/hibrido/v2_metricas_clasificacion.txt (v2 physical y baseline ERA5).
SOURCE = {
    "roc_auc": 0.893,
    "pr_auc": 0.429,
    "brier": 0.024,
    "chance": 0.031,
    "at_050": {"f1": 0.472, "precision": 0.486, "recall": 0.459, "mcc": 0.456, "csi": 0.309},
    "at_028": {"f1": 0.568, "precision": 0.490, "recall": 0.676, "mcc": 0.560},
    "holdout": {"f1": 0.556, "pr_auc": 0.512, "csi": 0.385},
    "baseline_era5": {"roc_auc": 0.816, "f1": 0.427},
}

LINES = [
    "ROC-AUC 0,893 · PR-AUC 0,429 (IC95 0,32–0,60; azar 0,031) · Brier 0,024",
    "Umbral 0,50: F1 0,47 (IC95 0,34–0,58) · Precisión 0,49 · Recall 0,46 · MCC 0,46 · CSI 0,31",
    "Umbral 0,28 (F1 óptimo): F1 0,57 · Precisión 0,49 · Recall 0,68 · MCC 0,56",
    "Holdout sin 30–31/05/2019: F1 0,56 · PR-AUC 0,51 · CSI 0,39",
    "Baseline solo ERA5: ROC-AUC 0,816 · F1 0,43",
]


class MetricsTest(unittest.TestCase):
    """La constante y el texto del stamp coinciden con la fuente."""

    def test_values_match_source(self) -> None:
        """Cada cifra redondeada queda a lo sumo media centésima (0,005) de la del archivo fuente."""
        for key, val in SOURCE.items():
            if isinstance(val, dict):
                for sub, x in val.items():
                    with self.subTest(key=key, sub=sub):
                        self.assertAlmostEqual(mm.V2_PHYSICAL[key][sub], x, delta=0.0051)
            else:
                with self.subTest(key=key):
                    self.assertAlmostEqual(mm.V2_PHYSICAL[key], val, delta=0.0051)
        self.assertEqual(mm.V2_PHYSICAL["pr_auc_ci"], (0.32, 0.60))
        self.assertEqual(mm.V2_PHYSICAL["at_050"]["f1_ci"], (0.34, 0.58))

    def test_summary_lines(self) -> None:
        """El texto del stamp es exactamente el acordado y no reporta Accuracy."""
        self.assertEqual(mm.summary_lines(), LINES)
        self.assertFalse(any("Accuracy" in line for line in mm.summary_lines()))
        self.assertIn("Accuracy no se reporta", mm.V2_PHYSICAL["note"])

    def test_stamp_renders(self) -> None:
        """El stamp se dibuja sin excepciones y muestra las cifras."""
        app = AppTest.from_string("from viewer_app import model_metrics\nmodel_metrics.stamp('t')")
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        text = " ".join(m.value for m in app.markdown)
        self.assertIn("ROC-AUC 0,893", text)
        self.assertIn("Umbral 0,28", text)

    def test_forecast_page(self) -> None:
        """«Mapa del modelo» muestra el stamp y ya no habla del híbrido con Bedrock."""
        app = AppTest.from_string("from viewer_app import p_forecast\np_forecast.page()")
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Mapa del modelo")
        text = " ".join(m.value for m in app.markdown)
        self.assertIn("ROC-AUC 0,893", text)
        self.assertNotIn("Bedrock Titan", text)

    def test_predict_page(self) -> None:
        """«Predecir» muestra el stamp (sin red: sin días publicados)."""
        app = AppTest.from_string(
            "from unittest.mock import patch\nfrom viewer_app import p_predict\n"
            "with patch.object(p_predict, '_model_days', return_value=[]):\n    p_predict.page()"
        )
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Predecir")
        self.assertIn("ROC-AUC 0,893", " ".join(m.value for m in app.markdown))


class LogScaleTest(unittest.TestCase):
    """Escala logarítmica del mapa Leaflet de Predecir."""

    def test_color_index(self) -> None:
        """Tramos lineales de 20 % y log10 con piso 0,001."""
        lin = {0: 0, 19.9: 0, 20: 1, 100: 4}
        log = {0.05: 0, 0.1: 0, 1: 1, 10: 3, 100: 4}
        for pct, idx in lin.items():
            self.assertEqual(p_predict.score_color_index(pct, False), idx, pct)
        for pct, idx in log.items():
            self.assertEqual(p_predict.score_color_index(pct, True), idx, pct)

    def test_map_html(self) -> None:
        """El HTML trae el control, los ticks log y el estado inicial (lineal por defecto)."""
        args = (b"x", np.array([[0.0005, 0.5]]), np.array([-30.0]), np.array([-76.0, -75.75]))
        html = p_predict._map_html(*args, False)
        for s in ('id="logscale"', "Escala logarítmica", '"0.001"', '"0.01"', '"0.1"', '"1"'):
            self.assertIn(s, html)
        data = json.loads(html.split("const D=")[1].split(";\n")[0])
        self.assertIs(data["log"], False)
        self.assertEqual(data["prob"], [0.05, 50.0])
        log_html = p_predict._map_html(*args, False, log=True)
        self.assertIs(json.loads(log_html.split("const D=")[1].split(";\n")[0])["log"], True)


if __name__ == "__main__":
    unittest.main()
