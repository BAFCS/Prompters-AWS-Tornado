"""Pruebas del reporte comparativo (``scripts/model/compare_runs.py``)."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

import compare_runs  # noqa: E402

RESULTS = "s3://ml/model/results/R1"


def metrics_doc(config: str, pod: float, far: float, csi: float) -> dict:
    """``metrics.json`` mínimo de una configuración."""
    sel = {"pod": pod, "far": far, "csi": csi, "hits": 3, "misses": 1, "false_alarms": 2}
    return {
        "config": config,
        "selection": {**sel, "n_events": 4},
        "development_case": {**sel, "n_events": 2},
        "n_folds_skipped": 1,
        "informative": {"pr_auc_oof": 0.4, "best_csi_threshold": 0.3, "best_csi": 0.5},
    }


def store(csi: dict[str, float]) -> dict[str, bytes]:
    """Objetos de la corrida: ``metrics.json`` e ``importance.json`` de cada configuración."""
    objs: dict[str, bytes] = {}
    for c, v in csi.items():
        objs[f"{RESULTS}/{c}/metrics.json"] = json.dumps(metrics_doc(c, 0.5, 0.2, v)).encode()
        objs[f"{RESULTS}/{c}/importance.json"] = json.dumps({"cape": 0.1, "srh_01": 0.7}).encode()
    return objs


class CompareRunsTest(unittest.TestCase):
    """Fallos, selección y paridad con EC2."""

    def test_failed_config_keeps_the_others(self) -> None:
        """Una configuración fallida queda con su motivo y las demás se conservan."""
        objs = store({"baseline_era5": 0.3, "physical": 0.4, "embeddings": 0.6})
        statuses = {
            "physical": compare_runs.JobStatus("Failed", "AlgorithmError: sin memoria"),
            "embeddings": compare_runs.JobStatus("Completed", "", "s3://ml/a/model.tar.gz"),
        }
        doc = compare_runs.compare("R1", RESULTS, objs.get, statuses)
        self.assertEqual(
            doc["configs"]["physical"],
            {"status": "failed", "reason": "AlgorithmError: sin memoria"},
        )
        self.assertEqual(doc["configs"]["baseline_era5"]["status"], "ok")
        self.assertEqual(doc["configs"]["embeddings"]["selection"]["csi"], 0.6)
        self.assertEqual(doc["configs"]["embeddings"]["model_data"], "s3://ml/a/model.tar.gz")
        self.assertEqual(
            [i["variable"] for i in doc["configs"]["embeddings"]["importance"]], ["srh_01", "cape"]
        )
        self.assertIsNone(doc["selected"])
        self.assertIn("physical", doc["reason"])
        self.assertIn("sin memoria", doc["reason"])

    def test_missing_physical_or_embeddings_means_no_selection(self) -> None:
        """Sin ``metrics.json`` de ``physical`` o de ``embeddings`` no hay modelo seleccionado."""
        for missing in ("physical", "embeddings"):
            with self.subTest(missing=missing):
                csi = {"baseline_era5": 0.3, "physical": 0.4, "embeddings": 0.6}
                del csi[missing]
                doc = compare_runs.compare("R1", RESULTS, store(csi).get)
                self.assertIsNone(doc["selected"])
                self.assertEqual(doc["configs"][missing]["status"], "failed")
                self.assertIn(missing, doc["reason"])

    def test_tie_selects_physical(self) -> None:
        """Empate de CSI → ``physical``; CSI estrictamente mayor → ``embeddings``."""
        tie = store({"baseline_era5": 0.3, "physical": 0.45, "embeddings": 0.45})
        self.assertEqual(compare_runs.compare("R1", RESULTS, tie.get)["selected"], "physical")
        better = store({"baseline_era5": 0.3, "physical": 0.45, "embeddings": 0.46})
        self.assertEqual(compare_runs.compare("R1", RESULTS, better.get)["selected"], "embeddings")

    def test_ec2_parity(self) -> None:
        """|Δ| de POD, FAR y CSI de ``baseline_era5`` frente a EC2 y bandera ≤ 0,01."""
        objs = store({"baseline_era5": 0.40, "physical": 0.4, "embeddings": 0.4})
        near = {"pod": 0.505, "far": 0.195, "csi": 0.41}  # forma histórica (sin "selection")
        doc = compare_runs.compare("R1", RESULTS, objs.get, ec2_metrics=near)
        parity = doc["ec2_parity"]
        self.assertTrue(parity["within_tolerance"])
        self.assertAlmostEqual(parity["abs_delta"]["csi"], 0.01)
        far = {"selection": {"pod": 0.5, "far": 0.2, "csi": 0.42}}
        doc = compare_runs.compare("R1", RESULTS, objs.get, ec2_metrics=far)
        self.assertFalse(doc["ec2_parity"]["within_tolerance"])
        self.assertAlmostEqual(doc["ec2_parity"]["abs_delta"]["csi"], 0.02)

    def test_cli_writes_json_and_html(self) -> None:
        """La CLI escribe ``comparacion.json`` y ``comparacion.html`` en la carpeta local."""
        with tempfile.TemporaryDirectory() as d:
            results = Path(d) / "R7"
            for c in ("baseline_era5", "physical", "embeddings"):
                (results / c).mkdir(parents=True)
                doc = metrics_doc(c, 0.5, 0.2, 0.5 if c == "embeddings" else 0.4)
                (results / c / "metrics.json").write_text(json.dumps(doc), encoding="utf-8")
            status = Path(d) / "status.json"
            status.write_text(json.dumps({"baseline_era5": {"status": "Stopped"}}), "utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = compare_runs.main(["--results", str(results), "--status", str(status)])
            self.assertEqual(code, 0)
            out = json.loads((results / "comparacion.json").read_text(encoding="utf-8"))
            self.assertEqual(out["run_id"], "R7")
            self.assertEqual(out["selected"], "embeddings")
            self.assertEqual(out["configs"]["baseline_era5"]["status"], "failed")
            self.assertIn("Stopped", out["configs"]["baseline_era5"]["reason"])
            page = (results / "comparacion.html").read_text(encoding="utf-8")
            self.assertIn("embeddings", page)


if __name__ == "__main__":
    unittest.main()
