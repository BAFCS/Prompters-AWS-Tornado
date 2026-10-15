"""Pruebas del punto de entrada de entrenamiento de SageMaker (``scripts/model/sm_job/``)."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(ROOT / "scripts" / "model" / "sm_job"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import loeo  # noqa: E402
import synthetic  # noqa: E402
import train_entry  # noqa: E402

RESULTS = "s3://ml-bucket/model/results/R1"


class RecordingS3:
    """S3 falso que registra cada ``put_object``."""

    def __init__(self) -> None:
        """Sin objetos."""
        self.puts: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict:
        """Guarda el objeto y su Content-Type."""
        self.puts[(Bucket, Key)] = (Body, ContentType)
        return {}


class TrainEntryTest(unittest.TestCase):
    """``train_entry.main`` con directorios temporales y S3 falso."""

    @classmethod
    def setUpClass(cls) -> None:
        """Tablas sintéticas de las tres configuraciones."""
        cls.tables = synthetic.model_tables()

    def run_job(self, config: str, root: Path, s3: RecordingS3) -> Path:
        """Ejecuta el trabajo de ``config`` y devuelve la carpeta del modelo."""
        inp = synthetic.write_channels(root, self.tables[config], self.tables["physical"])
        model_dir = root / "model"
        argv = ["--config", config, "--seed", "0", "--n-components", "8", "--results-uri", RESULTS]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(train_entry.main(argv, inp, model_dir, s3), 0)
        return model_dir

    def test_baseline_outputs_and_uploads(self) -> None:
        """Escribe el modelo y sube los cuatro resultados con su Content-Type."""
        s3 = RecordingS3()
        with tempfile.TemporaryDirectory() as d:
            model_dir = self.run_job("baseline_era5", Path(d), s3)
            names = {p.name for p in model_dir.iterdir()}
            self.assertEqual(names, {"model.json", "feature_columns.json", "config.json"})
            conf = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(conf["config"], "baseline_era5")
        expected = {
            "model.json": "application/json",
            "metrics.json": "application/json",
            "importance.json": "application/json",
            "reporte.html": "text/html; charset=utf-8",
        }
        self.assertEqual(
            {k: ct for (_, k), (_, ct) in s3.puts.items()},
            {f"model/results/R1/baseline_era5/{n}": ct for n, ct in expected.items()},
        )
        self.assertEqual({b for b, _ in s3.puts}, {"ml-bucket"})
        metrics = json.loads(
            s3.puts[("ml-bucket", "model/results/R1/baseline_era5/metrics.json")][0]
        )
        self.assertEqual(metrics["config"], "baseline_era5")
        self.assertEqual(metrics["development_case"]["n_events"], 0)
        self.assertEqual(metrics["selection"]["n_events"], 3)

    def test_embeddings_writes_reducer(self) -> None:
        """En ``embeddings`` se guarda ``reducer.npz`` y el modelo usa ``pca_*``."""
        s3 = RecordingS3()
        with tempfile.TemporaryDirectory() as d:
            model_dir = self.run_job("embeddings", Path(d), s3)
            self.assertTrue((model_dir / "reducer.npz").is_file())
            cols = json.loads((model_dir / "feature_columns.json").read_text(encoding="utf-8"))
            self.assertEqual(cols["model"][-8:], loeo.pca_columns(8))
            self.assertFalse([c for c in cols["model"] if c.startswith("emb_")])
            self.assertEqual(len(cols["embedding"]), 10)
        metrics = json.loads(s3.puts[("ml-bucket", "model/results/R1/embeddings/metrics.json")][0])
        self.assertEqual(len(metrics["reducer"]["per_fold"]), 3)

    def test_missing_columns_stop_the_job(self) -> None:
        """Una tabla sin una columna de la configuración termina con un mensaje que la nombra."""
        df = self.tables["physical"].drop(columns=["cape_lag2"])
        with tempfile.TemporaryDirectory() as d:
            inp = synthetic.write_channels(Path(d), df, self.tables["physical"])
            with self.assertRaises(SystemExit) as cm:
                train_entry.main(["--config", "physical"], inp, Path(d) / "model", RecordingS3())
        self.assertIn("cape_lag2", str(cm.exception))

    def test_container_imports(self) -> None:
        """``train_entry`` e ``inference`` no cargan common, xarray ni bibliotecas de E/S de S3."""
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import train_entry, inference; "
            "print([m for m in ('common', 'xarray', 'fsspec', 's3fs', 'h5py') if m in sys.modules])"
        )
        out = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "scripts" / "model" / "sm_job")],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(out.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
