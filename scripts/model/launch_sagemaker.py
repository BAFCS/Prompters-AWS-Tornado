#!/usr/bin/env python3
"""Entrenamiento, inferencia por lotes y endpoint privado del predictor en SageMaker (us-east-1).

Subcomandos:

- train: valida las tablas de cada configuracion (positivos y columnas requeridas) ANTES de crear
  trabajos, calcula folds.json una sola vez, sube tablas y particiones a
  s3://<bucket>/model/tables/<run_id>/, crea un trabajo por configuracion con
  sagemaker.train.ModelTrainer (mismos hiperparametros, imagen de XGBoost 3.0-5,
  source_dir=scripts/model, entry_script=sm_job/train_entry.py), espera y escribe
  comparacion.json/html en s3://<bucket>/model/results/<run_id>/ con compare_runs.py.
- transform: arma la tabla de inferencia de --start/--end/--region (build_table.py --stage infer),
  la sube a un prefijo NUEVO s3://<bucket>/model/inference/<inference_id>/ y lanza Batch Transform
  con el model.tar.gz del modelo seleccionado en comparacion.json. Si falla, informa la causa y
  los archivos de entrada; las corridas anteriores no se tocan.
- endpoint deploy|delete: endpoint en tiempo real privado, invocable solo con
  sagemaker-runtime InvokeEndpoint firmado con SigV4 (sin API Gateway ni URL publica), y su borrado.

El SDK de SageMaker y boto3 quedan detras de un Backend inyectable (pruebas sin AWS). Al importar
se verifica que "import sagemaker" resuelve al SDK instalado y no a un paquete de scripts/model.

Uso::

    uv run python scripts/model/launch_sagemaker.py train --run-id R1 --bucket <ml> --role-arn <arn>
    uv run python scripts/model/launch_sagemaker.py transform --run-id R1 --bucket <ml> \\
        --role-arn <arn> --start 2019-06-01 --end 2019-06-02 --region south-central-austral
    uv run python scripts/model/launch_sagemaker.py endpoint deploy --run-id R1 --bucket <ml> \\
        --role-arn <arn>
    uv run python scripts/model/launch_sagemaker.py endpoint delete --run-id R1
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import sagemaker

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def assert_real_sdk() -> None:
    """Termina si ``import sagemaker`` no resolvió al SDK instalado (p. ej. un paquete local)."""
    sdk_file = getattr(sagemaker, "__file__", None)
    if sdk_file is None:
        raise SystemExit("error: 'sagemaker' no es el SDK de SageMaker (paquete sin __file__)")
    path = Path(sdk_file).resolve()
    if path.is_relative_to(HERE):
        raise SystemExit(
            f"error: 'import sagemaker' resolvió a {path}, dentro de scripts/model: un paquete "
            "local tapa al SDK. Renómbralo (el del trabajo se llama sm_job/)."
        )


assert_real_sdk()

sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import compare_runs  # noqa: E402
import loeo  # noqa: E402
import table as tb  # noqa: E402

import common  # noqa: E402

# us-east-1: la cuenta solo permite esa región y ahí está el bucket de datos. Los trabajos leen las
# tablas ya armadas del bucket ML, no nsf-ncar-era5 (us-west-2), así que no cruzan regiones.
ML_REGION = "us-east-1"
SOURCE_DIR = "scripts/model"
ENTRY_SCRIPT = "sm_job/train_entry.py"
REQUIREMENTS = "sm_job/requirements.txt"
INSTANCE_TYPE = "ml.m5.xlarge"
XGB_IMAGE_VERSION = "3.0-5"
PARQUET = "application/x-parquet"
CSV = "text/csv"
TERMINAL = ("Completed", "Failed", "Stopped")
POLL_S = 30.0
INFERENCE_MODULES = ("reducer.py", "table.py", "goes_features.py")
MAX_NAME = 63


@dataclass
class TrainingSpec:
    """Un trabajo de entrenamiento: configuración, hiperparámetros y canales S3."""

    config: str
    job_name: str
    hyperparameters: dict[str, str]
    inputs: dict[str, str]  # canal → URI s3://
    output_uri: str


class Backend(Protocol):
    """Operaciones de S3 y SageMaker que usa la CLI (todas pasan por aquí)."""

    def upload_file(self, path: Path, bucket: str, key: str) -> str:
        """Sube un archivo y devuelve su URI ``s3://``."""
        ...

    def put_bytes(self, data: bytes, bucket: str, key: str, content_type: str) -> str:
        """Sube ``data`` con su Content-Type y devuelve la URI."""
        ...

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        """Contenido del objeto o ``None`` si no existe."""
        ...

    def exists(self, bucket: str, prefix: str) -> bool:
        """``True`` si hay al menos un objeto bajo ``prefix``."""
        ...

    def image_uri(self) -> str:
        """URI de la imagen de XGBoost de SageMaker en la región ML."""
        ...

    def train(self, spec: TrainingSpec) -> str:
        """Crea el trabajo de entrenamiento (sin esperar) y devuelve su nombre."""
        ...

    def describe_training_job(self, name: str) -> dict[str, Any]:
        """``DescribeTrainingJob``."""
        ...

    def create_model(self, name: str, image: str, model_data: str, env: dict[str, str]) -> None:
        """``CreateModel`` con el rol de ejecución."""
        ...

    def create_transform_job(
        self, name: str, model_name: str, input_uri: str, output_uri: str
    ) -> None:
        """``CreateTransformJob`` (Parquet de entrada, CSV de salida)."""
        ...

    def describe_transform_job(self, name: str) -> dict[str, Any]:
        """``DescribeTransformJob``."""
        ...

    def create_endpoint_config(self, name: str, model_name: str) -> None:
        """``CreateEndpointConfig`` con una variante."""
        ...

    def create_endpoint(self, name: str, config_name: str) -> None:
        """``CreateEndpoint``."""
        ...

    def delete_endpoint(self, name: str) -> None:
        """``DeleteEndpoint``."""
        ...

    def delete_endpoint_config(self, name: str) -> None:
        """``DeleteEndpointConfig``."""
        ...

    def delete_model(self, name: str) -> None:
        """``DeleteModel``."""
        ...


class DefaultBackend:
    """Backend real: SDK v3 de SageMaker (``ModelTrainer``) y clientes boto3 en ``region``."""

    def __init__(self, region: str, role_arn: str | None) -> None:
        """Clientes de S3 y SageMaker y sesión del SDK en ``region``."""
        import boto3
        from sagemaker.core.helper.session_helper import Session

        self.region = region
        self.role_arn = role_arn
        self.boto = boto3.Session(region_name=region)
        self.s3: Any = self.boto.client("s3")
        self.sm: Any = self.boto.client("sagemaker")
        self.session = Session(boto_session=self.boto)

    def upload_file(self, path: Path, bucket: str, key: str) -> str:
        """Sube un archivo."""
        self.s3.upload_file(str(path), bucket, key)
        return f"s3://{bucket}/{key}"

    def put_bytes(self, data: bytes, bucket: str, key: str, content_type: str) -> str:
        """Sube bytes con Content-Type."""
        self.s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{bucket}/{key}"

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        """Lee un objeto (``None`` si no existe)."""
        from botocore.exceptions import ClientError

        try:
            return self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    def exists(self, bucket: str, prefix: str) -> bool:
        """``True`` si hay objetos bajo ``prefix``."""
        resp = self.s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        return int(resp.get("KeyCount", 0)) > 0

    def image_uri(self) -> str:
        """Imagen de XGBoost de SageMaker (``image_uris.retrieve``)."""
        from sagemaker.core import image_uris

        return image_uris.retrieve(
            "xgboost", region=self.region, version=XGB_IMAGE_VERSION, sagemaker_session=self.session
        )

    def train(self, spec: TrainingSpec) -> str:
        """``ModelTrainer`` con ``SourceCode(source_dir="scripts/model", ...)``; no espera."""
        from sagemaker.train.configs import Compute, InputData, OutputDataConfig, SourceCode
        from sagemaker.train.model_trainer import ModelTrainer

        trainer = ModelTrainer(
            sagemaker_session=self.session,
            role=self.role_arn,
            base_job_name=spec.job_name,
            training_image=self.image_uri(),
            source_code=SourceCode(
                source_dir=str(ROOT / SOURCE_DIR),
                entry_script=ENTRY_SCRIPT,
                requirements=REQUIREMENTS,
            ),
            compute=Compute(instance_type=INSTANCE_TYPE, instance_count=1),
            hyperparameters=dict(spec.hyperparameters),
            output_data_config=OutputDataConfig(s3_output_path=spec.output_uri),
        )
        channels: list[Any] = [
            InputData(channel_name=k, data_source=v) for k, v in spec.inputs.items()
        ]
        trainer.train(input_data_config=channels, wait=False, logs=False)
        job = trainer._latest_training_job
        if job is None:
            raise RuntimeError(f"SageMaker no devolvió el trabajo de {spec.config}")
        return str(job.training_job_name)

    def describe_training_job(self, name: str) -> dict[str, Any]:
        """Estado del trabajo."""
        return self.sm.describe_training_job(TrainingJobName=name)

    def create_model(self, name: str, image: str, model_data: str, env: dict[str, str]) -> None:
        """Modelo de SageMaker con el contenedor de XGBoost en modo script."""
        self.sm.create_model(
            ModelName=name,
            ExecutionRoleArn=self.role_arn,
            PrimaryContainer={"Image": image, "ModelDataUrl": model_data, "Environment": env},
        )

    def create_transform_job(
        self, name: str, model_name: str, input_uri: str, output_uri: str
    ) -> None:
        """Batch Transform de un archivo Parquet por solicitud y salida CSV."""
        self.sm.create_transform_job(
            TransformJobName=name,
            ModelName=model_name,
            TransformInput={
                "DataSource": {"S3DataSource": {"S3DataType": "S3Prefix", "S3Uri": input_uri}},
                "ContentType": PARQUET,
                "SplitType": "None",
            },
            TransformOutput={"S3OutputPath": output_uri, "Accept": CSV, "AssembleWith": "None"},
            TransformResources={"InstanceType": INSTANCE_TYPE, "InstanceCount": 1},
        )

    def describe_transform_job(self, name: str) -> dict[str, Any]:
        """Estado del Batch Transform."""
        return self.sm.describe_transform_job(TransformJobName=name)

    def create_endpoint_config(self, name: str, model_name: str) -> None:
        """Configuración de endpoint con una instancia."""
        self.sm.create_endpoint_config(
            EndpointConfigName=name,
            ProductionVariants=[
                {
                    "VariantName": "AllTraffic",
                    "ModelName": model_name,
                    "InstanceType": INSTANCE_TYPE,
                    "InitialInstanceCount": 1,
                }
            ],
        )

    def create_endpoint(self, name: str, config_name: str) -> None:
        """Endpoint privado (solo ``InvokeEndpoint`` firmado con SigV4)."""
        self.sm.create_endpoint(EndpointName=name, EndpointConfigName=config_name)

    def delete_endpoint(self, name: str) -> None:
        """Borra el endpoint."""
        self.sm.delete_endpoint(EndpointName=name)

    def delete_endpoint_config(self, name: str) -> None:
        """Borra la configuración del endpoint."""
        self.sm.delete_endpoint_config(EndpointConfigName=name)

    def delete_model(self, name: str) -> None:
        """Borra el modelo."""
        self.sm.delete_model(ModelName=name)


BuildInference = Callable[[argparse.Namespace, str], list[Path]]


def resource_name(*parts: str, max_len: int = MAX_NAME) -> str:
    """Nombre válido para SageMaker (letras, dígitos y guiones; ``max_len`` caracteres)."""
    raw = "-".join(parts)
    return re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9-]", "-", raw)).strip("-")[:max_len].strip("-")


def s3_uri(bucket: str, key: str) -> str:
    """``s3://bucket/key``."""
    return f"s3://{bucket}/{key}"


def split_s3(uri: str) -> tuple[str, str]:
    """``s3://bucket/key`` → ``(bucket, key)``."""
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def table_files(config_dir: Path) -> list[Path]:
    """Parquet de una tabla (``date=AAAA-MM-DD/part-0.parquet``)."""
    return sorted(config_dir.rglob("*.parquet")) if config_dir.is_dir() else []


def read_table(config_dir: Path) -> pd.DataFrame | None:
    """Tabla completa de una configuración o ``None`` si no hay archivos."""
    files = table_files(config_dir)
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def validate_table(config: str, df: pd.DataFrame | None, where: Path) -> str | None:
    """Motivo por el que ``config`` no se puede entrenar (Req. 7.12) o ``None``."""
    if df is None:
        return f"{config}: no hay tablas en {where}"
    n_emb = sum(str(c).startswith(loeo.EMB_PREFIX) for c in df.columns)
    if config == "embeddings" and n_emb == 0:
        return f"{config}: faltan columnas emb_* (embeddings de Bedrock)"
    required = [*tb.KEY_COLUMNS, *tb.config_columns(config, n_emb)]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return f"{config}: faltan columnas {', '.join(missing)}"
    if not (df["label"] == 1).any():
        return f"{config}: la tabla no tiene Celdas_Hora positivas"
    return None


def build_inference_sourcedir(dest: Path) -> Path:
    """``sourcedir.tar.gz`` de inferencia: ``inference.py`` en la raíz, módulos y requirements."""
    out = dest / "sourcedir.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(HERE / "sm_job" / "inference.py", arcname="inference.py")
        for name in INFERENCE_MODULES:
            tar.add(HERE / name, arcname=name)
        tar.add(HERE / "sm_job" / "requirements.txt", arcname="requirements.txt")
    return out


def wait_training(
    backend: Backend, names: Mapping[str, str], sleep: Callable[[float], None], poll: float
) -> dict[str, compare_runs.JobStatus]:
    """Espera a que los trabajos terminen y devuelve su estado por configuración."""
    pending = dict(names)
    out: dict[str, compare_runs.JobStatus] = {}
    while pending:
        for config, name in list(pending.items()):
            d = backend.describe_training_job(name)
            status = str(d.get("TrainingJobStatus", ""))
            if status in TERMINAL:
                artifacts = d.get("ModelArtifacts") or {}
                out[config] = compare_runs.JobStatus(
                    status,
                    str(d.get("FailureReason", "")),
                    str(artifacts.get("S3ModelArtifacts", "")),
                )
                del pending[config]
                print(f"  {config}: {name} terminó con estado {status}", flush=True)
        if pending:
            sleep(poll)
    return out


def _require(a: argparse.Namespace, *names: str) -> None:
    """Termina si falta alguna de las opciones ``names``."""
    missing = [f"--{n.replace('_', '-')}" for n in names if not getattr(a, n, None)]
    if missing:
        raise SystemExit(f"error: {a.command} requiere {', '.join(missing)}")


def cmd_train(
    a: argparse.Namespace, get_backend: Callable[[], Backend], sleep: Callable[[float], None]
) -> int:
    """Subcomando ``train``."""
    _require(a, "bucket", "role_arn")
    root = a.tables_root or common.DATA / "model" / a.region / "tables"
    tables = {c: read_table(root / f"config={c}") for c in a.configs}
    errors = [
        msg
        for c in a.configs
        if (msg := validate_table(c, tables[c], root / f"config={c}")) is not None
    ]
    if errors:
        raise SystemExit("error: no se lanza ningún trabajo:\n  " + "\n  ".join(errors))
    valid = {c: t for c, t in tables.items() if t is not None}
    folds = loeo.compute_folds(valid[a.configs[0]])
    for c, t in valid.items():
        if loeo.compute_folds(t) != folds:
            raise SystemExit(f"error: {c} no tiene las mismas particiones que {a.configs[0]}")
    backend = get_backend()
    base = f"model/tables/{a.run_id}"
    folds_uri = backend.put_bytes(
        json.dumps(loeo.folds_to_json(folds, a.seed), indent=2).encode(),
        a.bucket,
        f"{base}/folds.json",
        "application/json",
    )
    results_uri = s3_uri(a.bucket, f"model/results/{a.run_id}")
    shared = {"seed": str(a.seed), "n-components": str(a.n_components), "results-uri": results_uri}
    names: dict[str, str] = {}
    for c in a.configs:
        cdir = root / f"config={c}"
        for f in table_files(cdir):
            backend.upload_file(f, a.bucket, f"{base}/{c}/{f.relative_to(cdir).as_posix()}")
        spec = TrainingSpec(
            config=c,
            job_name=resource_name("tornado", c, a.run_id, max_len=38),
            hyperparameters={"config": c, **shared},
            inputs={"train": s3_uri(a.bucket, f"{base}/{c}/"), "folds": folds_uri},
            output_uri=s3_uri(a.bucket, f"model/artifacts/{a.run_id}/"),
        )
        names[c] = backend.train(spec)
        print(f"{c}: trabajo {names[c]} creado", flush=True)
    statuses = wait_training(backend, names, sleep, a.poll)

    def reader(uri: str) -> bytes | None:
        return backend.get_bytes(*split_s3(uri))

    def writer(uri: str, data: bytes, content_type: str) -> None:
        backend.put_bytes(data, *split_s3(uri), content_type)

    doc = compare_runs.compare(a.run_id, results_uri, reader, statuses)
    compare_runs.write_outputs(doc, results_uri, writer)
    print(f"Modelo seleccionado: {doc['selected'] or 'ninguno'} ({results_uri}/)", flush=True)
    return 0 if all(s.status == "Completed" for s in statuses.values()) else 1


def selected_model(backend: Backend, bucket: str, run_id: str) -> tuple[str, str]:
    """Configuración seleccionada en ``comparacion.json`` y su ``model.tar.gz`` (Req. 8.6)."""
    key = f"model/results/{run_id}/comparacion.json"
    raw = backend.get_bytes(bucket, key)
    if raw is None:
        raise SystemExit(f"error: no existe {s3_uri(bucket, key)}; corre antes train")
    doc = json.loads(raw)
    config = doc.get("selected")
    if not config:
        raise SystemExit(
            f"error: la corrida {run_id} no tiene modelo seleccionado: {doc.get('reason')}"
        )
    model_data = doc["configs"].get(config, {}).get("model_data")
    if not model_data:
        raise SystemExit(f"error: comparacion.json no trae model_data de {config}")
    return config, str(model_data)


def default_build_inference(a: argparse.Namespace, config: str) -> list[Path]:
    """Tabla de inferencia con ``build_table.py --stage infer``; devuelve sus Parquet por día."""
    import build_table

    argv = ["--stage", "infer", "--config", config, "--start", a.start.isoformat()]
    argv += ["--region", a.region]
    if a.end:
        argv += ["--end", a.end.isoformat()]
    if a.bbox:
        argv += ["--bbox", *(str(v) for v in a.bbox)]
    if a.force:
        argv.append("--force")
    if a.embeddings:
        argv += ["--embeddings", str(a.embeddings)]
    ns = build_table.build_parser().parse_args(argv)
    build_table.run(ns, common.CROPS, build_table.MODEL_DATA)
    out = build_table.MODEL_DATA / common.region_of(ns).name / "inference" / f"config={config}"
    files = [out / f"date={d:%Y-%m-%d}" / "part-0.parquet" for d in common.days(ns)]
    return [f for f in files if f.is_file()]


def upload_sourcedir(backend: Backend, bucket: str, key: str) -> str:
    """Arma y sube ``sourcedir.tar.gz``; devuelve su URI."""
    with tempfile.TemporaryDirectory() as d:
        return backend.upload_file(build_inference_sourcedir(Path(d)), bucket, key)


def inference_env(sourcedir_uri: str) -> dict[str, str]:
    """Variables del contenedor de XGBoost en modo script para ``inference.py``."""
    return {"SAGEMAKER_PROGRAM": "inference.py", "SAGEMAKER_SUBMIT_DIRECTORY": sourcedir_uri}


def cmd_transform(
    a: argparse.Namespace,
    get_backend: Callable[[], Backend],
    sleep: Callable[[float], None],
    build_inference: BuildInference,
) -> int:
    """Subcomando ``transform`` (Batch Transform en un prefijo nuevo)."""
    _require(a, "bucket", "role_arn")
    backend = get_backend()
    config, model_data = selected_model(backend, a.bucket, a.run_id)
    inference_id = a.inference_id or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"model/inference/{inference_id}/"
    if backend.exists(a.bucket, prefix):
        raise SystemExit(
            f"error: {s3_uri(a.bucket, prefix)} ya existe; usa otro --inference-id "
            "(no se sobrescriben corridas anteriores)"
        )
    files = build_inference(a, config)
    if not files:
        raise SystemExit("error: no se generó ninguna tabla de inferencia para el rango pedido")
    inputs = []
    for f in files:
        inputs.append(backend.upload_file(f, a.bucket, f"{prefix}input/{f.parent.name}/{f.name}"))
    code = upload_sourcedir(backend, a.bucket, f"{prefix}code/sourcedir.tar.gz")
    model_name = resource_name("tornado", config, inference_id)
    backend.create_model(model_name, backend.image_uri(), model_data, inference_env(code))
    job = resource_name("tornado-bt", inference_id)
    output_uri = s3_uri(a.bucket, f"{prefix}output/")
    backend.create_transform_job(job, model_name, s3_uri(a.bucket, f"{prefix}input/"), output_uri)
    print(f"Batch Transform {job} ({config}) creado; salida en {output_uri}", flush=True)
    while True:
        d = backend.describe_transform_job(job)
        status = str(d.get("TransformJobStatus", ""))
        if status in TERMINAL:
            break
        sleep(a.poll)
    if status != "Completed":
        reason = d.get("FailureReason") or f"estado {status}"
        print(f"error: el Batch Transform {job} falló: {reason}", file=sys.stderr, flush=True)
        print("  archivos de entrada:", file=sys.stderr, flush=True)
        for uri in inputs:
            print(f"    {uri}", file=sys.stderr, flush=True)
        return 1
    print(f"Listo: probabilidades en {output_uri}", flush=True)
    return 0


def cmd_endpoint(a: argparse.Namespace, get_backend: Callable[[], Backend]) -> int:
    """Subcomando ``endpoint deploy|delete`` (endpoint privado, solo SigV4)."""
    name = a.endpoint_name or resource_name("tornado-ep", a.run_id)
    backend = get_backend()
    if a.action == "delete":
        backend.delete_endpoint(name)
        backend.delete_endpoint_config(name)
        backend.delete_model(name)
        print(f"Endpoint {name}, su configuración y su modelo borrados", flush=True)
        return 0
    _require(a, "bucket", "role_arn")
    config, model_data = selected_model(backend, a.bucket, a.run_id)
    code = upload_sourcedir(backend, a.bucket, f"model/endpoint/{a.run_id}/code/sourcedir.tar.gz")
    backend.create_model(name, backend.image_uri(), model_data, inference_env(code))
    backend.create_endpoint_config(name, name)
    backend.create_endpoint(name, name)
    print(
        f"Endpoint privado {name} ({config}) en creación. Se invoca solo con "
        "sagemaker-runtime InvokeEndpoint firmado con SigV4; no se crea URL pública. "
        f"Bórralo con: endpoint delete --run-id {a.run_id}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Parser con los subcomandos ``train``, ``transform`` y ``endpoint``."""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--run-id", required=True, help="identificador de la corrida de entrenamiento"
    )
    shared.add_argument(
        "--ml-region", default=ML_REGION, help=f"región de SageMaker (solo {ML_REGION})"
    )
    shared.add_argument("--bucket", help="bucket ML (salida ml_bucket de Terraform)")
    shared.add_argument("--role-arn", help="rol de ejecución (sagemaker_execution_role_arn)")
    shared.add_argument("--poll", type=float, default=POLL_S, help="segundos entre consultas")

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)

    tr = sub.add_parser("train", parents=[shared], help="entrena las tres configuraciones")
    tr.add_argument(
        "--region", default="south-central-austral", help="región de las tablas (data/model/...)"
    )
    tr.add_argument(
        "--tables-root",
        type=Path,
        help="carpeta con config=<config>/ (por defecto data/model/<region>/tables)",
    )
    tr.add_argument("--seed", type=int, default=0, help="semilla (por defecto 0)")
    tr.add_argument("--n-components", type=int, default=8, help="componentes del Reductor (8-16)")
    tr.add_argument(
        "--configs", nargs="+", choices=tb.CONFIGS, default=list(tb.CONFIGS), help="configuraciones"
    )

    tf = sub.add_parser("transform", parents=[shared], help="inferencia por lotes")
    tf.add_argument(
        "--start", type=dt.date.fromisoformat, required=True, help="primer día, AAAA-MM-DD"
    )
    tf.add_argument("--end", type=dt.date.fromisoformat, help="último día (inclusive)")
    tf.add_argument("--region", default="south-central-austral", help="región de trabajo")
    tf.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("NORTH", "SOUTH", "WEST", "EAST"),
        help="región a medida",
    )
    tf.add_argument("--force", action="store_true", help="rehace las tablas de inferencia")
    tf.add_argument(
        "--inference-id", help="prefijo nuevo model/inference/<id>/ (por defecto la hora UTC)"
    )
    tf.add_argument(
        "--embeddings", type=Path, help="parquet de embeddings (si se eligió embeddings)"
    )

    ep = sub.add_parser("endpoint", parents=[shared], help="endpoint privado (SigV4)")
    ep.add_argument("action", choices=("deploy", "delete"), help="desplegar o borrar")
    ep.add_argument("--endpoint-name", help="nombre (por defecto tornado-ep-<run_id>)")
    return p


def run(
    argv: Sequence[str] | None = None,
    backend: Backend | None = None,
    sleep: Callable[[float], None] = time.sleep,
    build_inference: BuildInference = default_build_inference,
) -> int:
    """Ejecuta la CLI con un ``backend`` inyectable (por defecto ``DefaultBackend``)."""
    a = build_parser().parse_args(argv)
    if a.ml_region != ML_REGION:
        raise SystemExit(
            f"error: SageMaker y Bedrock deben ir en {ML_REGION} (región de la cuenta y del bucket de datos); "
            f"se recibió --ml-region {a.ml_region}"
        )

    def get_backend() -> Backend:
        return backend if backend is not None else DefaultBackend(a.ml_region, a.role_arn)

    if a.command == "train":
        return cmd_train(a, get_backend, sleep)
    if a.command == "transform":
        return cmd_transform(a, get_backend, sleep, build_inference)
    return cmd_endpoint(a, get_backend)


def main() -> None:
    """Punto de entrada de la CLI."""
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
