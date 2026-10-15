"""Pruebas de ``scripts/app/infer_grid.py`` con un XGBoost sintético y Bedrock simulado (sin red)."""

import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import infer_grid  # noqa: E402
import predictions  # noqa: E402
import prototype  # noqa: E402
import synthetic  # noqa: E402
import table as tb  # noqa: E402
from app_synthetic import NoNetworkMixin  # noqa: E402

REGION = "test-region"
DAY = dt.date(2019, 5, 30)
DIM = 256


def write_model(model_dir: Path) -> None:
    """XGBoost diminuto con las columnas de ``embeddings`` (sin Reductor) y sus artefactos."""
    cols = tb.config_columns("embeddings", DIM)
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(60, len(cols))), columns=cols)
    y = (x["cape"] > 0).astype(int)
    model = xgb.XGBClassifier(n_estimators=3, max_depth=2)
    model.fit(x, y)
    model_dir.mkdir(parents=True)
    model.save_model(str(model_dir / "model.json"))
    doc = {"required": cols, "model": cols, "embedding": []}
    (model_dir / "feature_columns.json").write_text(json.dumps(doc), "utf-8")
    (model_dir / "config.json").write_text(json.dumps({"config": "embeddings"}), "utf-8")


class FakeBedrock:
    """Dobles de ``bedrock-runtime`` y ``bedrock``: vector constante y cuenta de llamadas."""

    def __init__(self) -> None:
        """Sin llamadas todavía."""
        self.calls = 0

    def invoke_model(self, **_: object) -> dict:
        """Responde como Titan con un vector de ``DIM`` valores."""
        self.calls += 1
        return {"body": io.BytesIO(json.dumps({"embedding": [0.01] * DIM}).encode())}

    def get_foundation_model(self, **_: object) -> dict:
        """El modelo existe en la región."""
        return {}


class InferGridTest(NoNetworkMixin):
    """De la grilla al CSV_Predicciones con ``modelo: real``."""

    def setUp(self) -> None:
        """ERA5 de 19–21 UTC, GOES solo de las 19 (la hora 21 queda sin GOES) y el modelo."""
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.crops = self.root / "crops"
        rng = np.random.default_rng(1)
        shape = (3, 2, 2)
        values = {c: rng.normal(size=shape) for c in ("cape", "shear_06", "srh_01")}
        synthetic.write_era5_indices(self.crops, REGION, DAY, [19, 20, 21], values)
        h19 = dt.datetime(2019, 5, 30, 19)
        scans, bands = synthetic.uniform_scans(
            h19, {"C08": lambda s: 230.0, "C13": lambda s: 210.0}
        )
        synthetic.write_goes_latlon(self.crops, REGION, h19, scans, bands)
        self.model_dir = self.root / "model"
        write_model(self.model_dir)
        self.fake = FakeBedrock()

    def args(self, *extra: str) -> list[str]:
        """Argumentos comunes de la CLI hacia el directorio temporal."""
        return [
            "--day", DAY.isoformat(), "--hours", "19", "21", "--region", REGION,
            "--model-dir", str(self.model_dir), "--out", str(self.root / "pred"),
            "--work", str(self.root / "work"), "--window-km", "20", *extra,
        ]  # fmt: skip

    def run_cli(self, *extra: str) -> Path:
        """Corre ``infer_grid.run`` con Bedrock simulado y sin imprimir."""
        a = infer_grid.build_parser().parse_args(self.args(*extra))
        with contextlib.redirect_stdout(io.StringIO()):
            return infer_grid.run(
                a,
                crops_root=self.crops,
                client_factory=lambda region: (self.fake, self.fake),
                cache_root=self.root / "cache",
            )

    def test_csv_schema_meta_and_rows(self) -> None:
        """CSV válido para ``predictions.load``, meta real y filas = celdas × horas con GOES."""
        csv = self.run_cli("--stride", "1")
        loaded = predictions.load(csv)
        self.assertEqual(tuple(loaded.df.columns), predictions.SCHEMA)
        self.assertEqual(loaded.meta["modelo"], "real")
        self.assertEqual(loaded.meta["config"], "embeddings")
        self.assertEqual(loaded.meta["horas_sin_goes"], [21])
        self.assertEqual(loaded.meta["horas"], [19, 20])
        self.assertEqual(len(loaded.df), 4 * 2)
        self.assertEqual(loaded.meta["filas"], 8)
        self.assertEqual(sorted(loaded.df["hour_utc"].unique()), [19, 20])
        bedrock = loaded.meta["bedrock"]
        self.assertEqual(self.fake.calls, bedrock["llamadas_bedrock"])
        self.assertGreater(self.fake.calls, 0)
        encoded = bedrock["llamadas_bedrock"] + bedrock["desde_cache"]
        self.assertEqual(loaded.meta["nan"]["sin_embedding"], 8 - encoded)

    def test_stride_reduces_cells_and_reuses_cache(self) -> None:
        """``--stride 2`` deja 1 × 1 puntos; la segunda corrida sale toda de la caché."""
        csv = self.run_cli("--stride", "2")
        self.assertEqual(len(predictions.load(csv).df), 1 * 2)
        calls = self.fake.calls
        self.run_cli("--stride", "2")
        self.assertEqual(self.fake.calls, calls)

    def test_estimate_guard(self) -> None:
        """Sobre el límite termina antes de llamar a Bedrock salvo con ``--yes``."""
        with mock.patch.object(infer_grid, "MAX_IMAGES", 3):
            with self.assertRaises(SystemExit):
                self.run_cli("--stride", "1")
            self.assertEqual(self.fake.calls, 0)
            self.run_cli("--stride", "1", "--yes")
        self.assertEqual(infer_grid.estimate(53 * 21, 9), 10017)
        with self.assertRaises(SystemExit):
            infer_grid.check_estimate(15_001, yes=False)
        infer_grid.check_estimate(15_001, yes=True)

    def test_prototype_uses_real_predictions(self) -> None:
        """El prototipo toma el CSV real, con su insignia y el paso de la grilla de los datos."""
        csv = self.run_cli("--stride", "1")
        real = prototype.load_real(csv.parent, DAY.isoformat())
        assert real is not None
        df, meta = real
        payload = prototype.day_payload(df, "real", meta)
        # Sin train_summary.json no se sabe si el día es fuera de muestra: insignia sin sufijo.
        self.assertEqual(payload["badge"], prototype.BADGES["real"])
        self.assertIn("model_dir", payload["modelo_info"])
        self.assertIsNone(payload["modelo_info"]["en_entrenamiento"])
        self.assertEqual(payload["max"], round(df["probability"].max() * prototype.SCALE))
        meta_out = dict(meta, en_entrenamiento=False)
        self.assertIn("fuera de muestra", prototype.day_payload(df, "real", meta_out)["badge"])
        self.assertEqual(payload["step"], 0.25)
        self.assertTrue(prototype.is_real(csv))
        coarse = pd.DataFrame({"latitude": [-35.0, -35.5, -36.0]})
        self.assertEqual(prototype.grid_step(coarse["latitude"].to_numpy()), 0.5)


if __name__ == "__main__":
    unittest.main()
