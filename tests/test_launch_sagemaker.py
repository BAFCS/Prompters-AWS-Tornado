"""Pruebas de ``scripts/model/launch_sagemaker.py`` con un backend falso (sin AWS)."""

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "scripts" / "model"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(MODEL))  # como al correr un script de scripts/model: sys.path[0]

import launch_sagemaker as ls  # noqa: E402
import synthetic  # noqa: E402

BUCKET = "ml-bucket"
ROLE = "arn:aws:iam::123456789012:role/sagemaker-exec"
COMMON = ["--run-id", "R1", "--bucket", BUCKET, "--role-arn", ROLE, "--poll", "0"]


def metrics_doc(config: str, csi: float) -> dict:
    """``metrics.json`` mínimo que dejaría el trabajo de ``config``."""
    sel = {"pod": 0.5, "far": 0.2, "csi": csi, "hits": 1, "misses": 1, "false_alarms": 0}
    return {
        "config": config,
        "selection": {**sel, "n_events": 2},
        "development_case": {**sel, "n_events": 0},
        "n_folds_skipped": 0,
        "informative": {"pr_auc_oof": 0.5, "best_csi_threshold": 0.5, "best_csi": csi},
    }


class FakeBackend:
    """Backend en memoria que registra cada llamada; ``train`` simula los resultados del trabajo."""

    def __init__(self, transform_status: str = "Completed") -> None:
        """Sin objetos ni trabajos."""
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, tuple]] = []
        self.specs: list[ls.TrainingSpec] = []
        self.transform_status = transform_status

    def _log(self, name: str, *args: object) -> None:
        """Registra la llamada."""
        self.calls.append((name, args))

    def upload_file(self, path: Path, bucket: str, key: str) -> str:
        """Guarda el archivo."""
        self._log("upload_file", bucket, key)
        self.objects[(bucket, key)] = Path(path).read_bytes()
        return f"s3://{bucket}/{key}"

    def put_bytes(self, data: bytes, bucket: str, key: str, content_type: str) -> str:
        """Guarda los bytes."""
        self._log("put_bytes", bucket, key, content_type)
        self.objects[(bucket, key)] = data
        return f"s3://{bucket}/{key}"

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        """Lee un objeto."""
        self._log("get_bytes", bucket, key)
        return self.objects.get((bucket, key))

    def exists(self, bucket: str, prefix: str) -> bool:
        """Hay objetos bajo el prefijo."""
        self._log("exists", bucket, prefix)
        return any(b == bucket and k.startswith(prefix) for b, k in self.objects)

    def image_uri(self) -> str:
        """Imagen ficticia."""
        self._log("image_uri")
        return "xgboost:3.0-5"

    def train(self, spec: ls.TrainingSpec) -> str:
        """Registra el trabajo y deja su ``metrics.json`` en los resultados."""
        self._log("train", spec.config)
        self.specs.append(spec)
        bucket, prefix = ls.split_s3(spec.hyperparameters["results-uri"])
        csi = {"baseline_era5": 0.2, "physical": 0.3, "embeddings": 0.4}[spec.config]
        doc = json.dumps(metrics_doc(spec.config, csi)).encode()
        self.objects[(bucket, f"{prefix}/{spec.config}/metrics.json")] = doc
        return f"{spec.job_name}-001"

    def describe_training_job(self, name: str) -> dict[str, Any]:
        """Trabajo terminado con su ``model.tar.gz``."""
        self._log("describe_training_job", name)
        artifacts = f"s3://{BUCKET}/model/artifacts/R1/{name}/output/model.tar.gz"
        return {"TrainingJobStatus": "Completed", "ModelArtifacts": {"S3ModelArtifacts": artifacts}}

    def create_model(self, name: str, image: str, model_data: str, env: dict[str, str]) -> None:
        """Registra el modelo."""
        self._log("create_model", name, image, model_data, env)

    def create_transform_job(
        self, name: str, model_name: str, input_uri: str, output_uri: str
    ) -> None:
        """Registra el Batch Transform."""
        self._log("create_transform_job", name, model_name, input_uri, output_uri)

    def describe_transform_job(self, name: str) -> dict[str, Any]:
        """Estado programado del Batch Transform."""
        self._log("describe_transform_job", name)
        reason = "ClientError: fila inválida en date=2019-06-01/part-0.parquet"
        return {"TransformJobStatus": self.transform_status, "FailureReason": reason}

    def create_endpoint_config(self, name: str, model_name: str) -> None:
        """Registra la configuración."""
        self._log("create_endpoint_config", name, model_name)

    def create_endpoint(self, name: str, config_name: str) -> None:
        """Registra el endpoint."""
        self._log("create_endpoint", name, config_name)

    def delete_endpoint(self, name: str) -> None:
        """Registra el borrado."""
        self._log("delete_endpoint", name)

    def delete_endpoint_config(self, name: str) -> None:
        """Registra el borrado."""
        self._log("delete_endpoint_config", name)

    def delete_model(self, name: str) -> None:
        """Registra el borrado."""
        self._log("delete_model", name)

    def names(self) -> list[str]:
        """Métodos llamados, en orden."""
        return [n for n, _ in self.calls]


def write_tables(root: Path, tables: dict) -> Path:
    """Tablas por configuración en ``root/config=<c>/date=AAAA-MM-DD/part-0.parquet``."""
    for c, df in tables.items():
        part = root / f"config={c}" / f"date={synthetic.TABLE_DAY:%Y-%m-%d}" / "part-0.parquet"
        part.parent.mkdir(parents=True)
        df.to_parquet(part, index=False)
    return root


def comparacion(selected: str | None) -> bytes:
    """``comparacion.json`` con ``model_data`` de cada configuración."""
    configs = {
        c: {"status": "ok", "model_data": f"s3://{BUCKET}/model/artifacts/R1/{c}/model.tar.gz"}
        for c in ("baseline_era5", "physical", "embeddings")
    }
    return json.dumps({"run_id": "R1", "configs": configs, "selected": selected}).encode()


class TrainTest(unittest.TestCase):
    """Subcomando ``train``."""

    @classmethod
    def setUpClass(cls) -> None:
        """Tablas sintéticas de las tres configuraciones."""
        cls.tables = synthetic.model_tables()

    def train(self, tables: dict, fake: FakeBackend) -> int:
        """Corre ``train`` sobre ``tables`` escritas en un temporal."""
        with tempfile.TemporaryDirectory() as d:
            root = write_tables(Path(d), tables)
            with contextlib.redirect_stdout(io.StringIO()):
                return ls.run(["train", *COMMON, "--tables-root", str(root)], fake)

    def test_table_without_positives_stops_before_jobs(self) -> None:
        """Sin positivas en una configuración no se sube ni se crea ningún trabajo."""
        tables = dict(self.tables)
        tables["physical"] = tables["physical"].assign(label=0)
        fake = FakeBackend()
        with self.assertRaises(SystemExit) as cm:
            self.train(tables, fake)
        self.assertIn("physical", str(cm.exception))
        self.assertIn("positivas", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_missing_columns_stop_before_jobs(self) -> None:
        """Columnas faltantes (por nombre) detienen todo antes de crear trabajos."""
        for config, drop in (("physical", ["goes_bt13_min_d3"]), ("embeddings", None)):
            with self.subTest(config=config):
                tables = dict(self.tables)
                df = tables[config]
                cols = drop or [c for c in df.columns if c.startswith("emb_")]
                tables[config] = df.drop(columns=cols)
                fake = FakeBackend()
                with self.assertRaises(SystemExit) as cm:
                    self.train(tables, fake)
                self.assertIn(config, str(cm.exception))
                self.assertIn("goes_bt13_min_d3" if drop else "emb_", str(cm.exception))
                self.assertEqual(fake.calls, [])

    def test_three_jobs_share_hyperparameters_and_folds(self) -> None:
        """Tres trabajos con los mismos hiperparámetros (salvo config) y el mismo folds.json."""
        fake = FakeBackend()
        self.assertEqual(self.train(self.tables, fake), 0)
        self.assertEqual(
            [s.config for s in fake.specs], ["baseline_era5", "physical", "embeddings"]
        )
        shared = [{k: v for k, v in s.hyperparameters.items() if k != "config"} for s in fake.specs]
        self.assertEqual(shared[0], shared[1])
        self.assertEqual(shared[0], shared[2])
        self.assertEqual(
            [s.hyperparameters["config"] for s in fake.specs], [s.config for s in fake.specs]
        )
        folds_uri = f"s3://{BUCKET}/model/tables/R1/folds.json"
        self.assertEqual({s.inputs["folds"] for s in fake.specs}, {folds_uri})
        self.assertEqual(
            [s.inputs["train"] for s in fake.specs],
            [
                f"s3://{BUCKET}/model/tables/R1/{c}/"
                for c in ("baseline_era5", "physical", "embeddings")
            ],
        )
        self.assertEqual(
            [n for n, a in fake.calls if n == "put_bytes" and a[1].endswith("folds.json")],
            ["put_bytes"],
        )
        folds = json.loads(fake.objects[(BUCKET, "model/tables/R1/folds.json")])
        self.assertEqual(len(folds["folds"]), 3)
        for c in ("baseline_era5", "physical", "embeddings"):
            key = f"model/tables/R1/{c}/date={synthetic.TABLE_DAY:%Y-%m-%d}/part-0.parquet"
            self.assertIn((BUCKET, key), fake.objects)
        comp = json.loads(fake.objects[(BUCKET, "model/results/R1/comparacion.json")])
        self.assertEqual(comp["selected"], "embeddings")
        self.assertTrue(comp["configs"]["embeddings"]["model_data"].endswith("model.tar.gz"))
        self.assertIn((BUCKET, "model/results/R1/comparacion.html"), fake.objects)

    def test_rejects_other_region(self) -> None:
        """Una región ML distinta de us-east-1 se rechaza antes de todo."""
        with self.assertRaises(SystemExit) as cm:
            ls.run(["train", *COMMON, "--ml-region", "us-west-2"], FakeBackend())
        self.assertIn("us-east-1", str(cm.exception))


class TransformTest(unittest.TestCase):
    """Subcomando ``transform``."""

    def transform(self, fake: FakeBackend, *extra: str) -> tuple[int, list[str], str]:
        """Corre ``transform`` con una tabla de inferencia falsa; devuelve código, días y stderr."""
        seen: list[str] = []
        with tempfile.TemporaryDirectory() as d:

            def build(a: argparse.Namespace, config: str) -> list[Path]:
                seen.append(config)
                part = Path(d) / "date=2019-06-01" / "part-0.parquet"
                part.parent.mkdir(parents=True, exist_ok=True)
                synthetic.model_tables()[config].to_parquet(part, index=False)
                return [part]

            argv = ["transform", *COMMON, "--start", "2019-06-01", "--inference-id", "I1", *extra]
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = ls.run(argv, fake, build_inference=build)
        return code, seen, err.getvalue()

    def test_uses_selected_model_and_new_prefix(self) -> None:
        """El modelo es el seleccionado en comparacion.json y todo va a model/inference/I1/."""
        fake = FakeBackend()
        fake.objects[(BUCKET, "model/results/R1/comparacion.json")] = comparacion("physical")
        code, seen, _ = self.transform(fake)
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["physical"])
        (_, (name, image, model_data, env)) = next(c for c in fake.calls if c[0] == "create_model")
        self.assertEqual(model_data, f"s3://{BUCKET}/model/artifacts/R1/physical/model.tar.gz")
        self.assertEqual(env["SAGEMAKER_PROGRAM"], "inference.py")
        self.assertEqual(
            env["SAGEMAKER_SUBMIT_DIRECTORY"],
            f"s3://{BUCKET}/model/inference/I1/code/sourcedir.tar.gz",
        )
        (_, (_, model_name, inp, out)) = next(
            c for c in fake.calls if c[0] == "create_transform_job"
        )
        self.assertEqual(model_name, name)
        self.assertEqual(inp, f"s3://{BUCKET}/model/inference/I1/input/")
        self.assertEqual(out, f"s3://{BUCKET}/model/inference/I1/output/")
        written = [k for (_, k) in fake.objects if k.startswith("model/inference/")]
        self.assertTrue(all(k.startswith("model/inference/I1/") for k in written))

    def test_existing_prefix_is_not_touched(self) -> None:
        """Si el prefijo de la corrida ya existe, termina sin crear nada ni sobrescribir."""
        fake = FakeBackend()
        fake.objects[(BUCKET, "model/results/R1/comparacion.json")] = comparacion("physical")
        fake.objects[(BUCKET, "model/inference/I1/output/part-0.parquet.out")] = b"previa"
        with self.assertRaises(SystemExit):
            self.transform(fake)
        self.assertNotIn("create_model", fake.names())
        self.assertEqual(
            fake.objects[(BUCKET, "model/inference/I1/output/part-0.parquet.out")], b"previa"
        )

    def test_failure_reports_cause_and_files(self) -> None:
        """Un Batch Transform fallido informa la causa y los archivos de entrada."""
        fake = FakeBackend(transform_status="Failed")
        fake.objects[(BUCKET, "model/results/R1/comparacion.json")] = comparacion("embeddings")
        previous = {(BUCKET, "model/inference/I0/output/x.out"): b"anterior"}
        fake.objects.update(previous)
        code, seen, err = self.transform(fake)
        self.assertEqual(code, 1)
        self.assertEqual(seen, ["embeddings"])
        self.assertIn("fila inválida", err)
        self.assertIn("model/inference/I1/input/date=2019-06-01/part-0.parquet", err)
        self.assertEqual(fake.objects[(BUCKET, "model/inference/I0/output/x.out")], b"anterior")

    def test_no_selected_model(self) -> None:
        """Sin modelo seleccionado no se crea nada."""
        fake = FakeBackend()
        fake.objects[(BUCKET, "model/results/R1/comparacion.json")] = comparacion(None)
        with self.assertRaises(SystemExit):
            self.transform(fake)
        self.assertNotIn("create_model", fake.names())


class EndpointTest(unittest.TestCase):
    """Subcomando ``endpoint``: privado, sin acceso público."""

    def test_deploy_is_private(self) -> None:
        """Solo crea modelo, configuración y endpoint de SageMaker: nada público."""
        fake = FakeBackend()
        fake.objects[(BUCKET, "model/results/R1/comparacion.json")] = comparacion("physical")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ls.run(["endpoint", "deploy", *COMMON], fake), 0)
        self.assertEqual(
            [n for n in fake.names() if n.startswith("create")],
            ["create_model", "create_endpoint_config", "create_endpoint"],
        )
        self.assertLessEqual(
            set(fake.names()),
            {
                "get_bytes",
                "upload_file",
                "image_uri",
                "create_model",
                "create_endpoint_config",
                "create_endpoint",
            },
        )
        self.assertIn("SigV4", out.getvalue())
        public = [
            m for m in dir(ls.Backend) if re.search(r"api|url|policy|public|permission", m, re.I)
        ]
        self.assertEqual(public, [])

    def test_delete(self) -> None:
        """El borrado elimina endpoint, configuración y modelo con el mismo nombre."""
        fake = FakeBackend()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ls.run(["endpoint", "delete", "--run-id", "R1"], fake), 0)
        self.assertEqual(
            fake.calls,
            [
                ("delete_endpoint", ("tornado-ep-R1",)),
                ("delete_endpoint_config", ("tornado-ep-R1",)),
                ("delete_model", ("tornado-ep-R1",)),
            ],
        )


class PackagingTest(unittest.TestCase):
    """SDK real sin tapar y paquete de inferencia."""

    def test_real_sdk_is_not_shadowed(self) -> None:
        """Con scripts/model en sys.path[0], ``sagemaker`` es el SDK del entorno virtual."""
        self.assertFalse((MODEL / "sagemaker").exists())
        prefix = Path(sys.prefix).resolve()
        self.assertTrue(Path(ls.sagemaker.__file__).resolve().is_relative_to(prefix))
        code = "import sys; sys.path.insert(0, sys.argv[1]); import sagemaker; print(sagemaker.__file__)"
        out = subprocess.run(
            [sys.executable, "-c", code, str(MODEL)], capture_output=True, text=True, check=True
        )
        sdk = Path(out.stdout.strip().splitlines()[-1]).resolve()
        self.assertTrue(sdk.is_relative_to(prefix), sdk)
        self.assertFalse(sdk.is_relative_to(MODEL), sdk)
        ls.assert_real_sdk()

    def test_guard_detects_local_package(self) -> None:
        """``assert_real_sdk`` termina si ``sagemaker`` resolviera dentro de scripts/model."""
        real = ls.sagemaker.__file__
        try:
            ls.sagemaker.__file__ = str(MODEL / "sagemaker" / "__init__.py")
            with self.assertRaises(SystemExit):
                ls.assert_real_sdk()
        finally:
            ls.sagemaker.__file__ = real

    def test_sourcedir_has_inference_at_root(self) -> None:
        """``sourcedir.tar.gz`` trae ``inference.py`` en la raíz y los módulos que usa."""
        with tempfile.TemporaryDirectory() as d:
            tar_path = ls.build_inference_sourcedir(Path(d))
            with tarfile.open(tar_path) as tar:
                names = set(tar.getnames())
        self.assertEqual(
            names,
            {"inference.py", "reducer.py", "table.py", "goes_features.py", "requirements.txt"},
        )


if __name__ == "__main__":
    unittest.main()
