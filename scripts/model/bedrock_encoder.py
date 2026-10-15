"""Codificador_Bedrock: convierte los PNG del Compositor_RGB en embeddings de Amazon Bedrock.

Los clientes de Bedrock (``bedrock-runtime`` para ``InvokeModel`` y ``bedrock`` para el plano de
control) y la función de espera se inyectan, para probar todo con dobles sin red ni credenciales.
``boto3`` solo se importa dentro de ``make_clients``.

- ``preflight`` comprueba con ``get_foundation_model`` que el modelo existe en la región antes de
  enviar la primera imagen (Req. 4.4).
- El cuerpo de cada solicitud lleva solo la imagen en base64 y los parámetros del modelo, nada del
  Catálogo (Req. 4.9).
- ``ThrottlingException`` se reintenta tras esperar 1, 2, 4, 8 y 16 s; después, la imagen queda
  fallida (Req. 4.7). Otros errores y el tiempo agotado de 30 s dejan la imagen fallida con su tipo
  de error (Req. 4.10). Un vector de longitud distinta de ``dim`` o con valores no finitos también
  queda fallido (Req. 4.11). Las imágenes fallidas nunca entran en la caché.
- La caché se indexa con ``cache_key`` (sha256 del PNG, modelo, dimensión y receta, Req. 4.5).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

BACKOFF_S = (1, 2, 4, 8, 16)  # esperas ante ThrottlingException (Req. 4.7)
READ_TIMEOUT_S = 30  # tiempo máximo de una invocación (Req. 4.10)
THROTTLING = "ThrottlingException"
MISSING_KEY_CODES = ("NoSuchKey", "404", "NotFound")


@dataclass(frozen=True)
class ModelSpec:
    """Modelo de embeddings de Bedrock: identificador, dimensión por defecto y dimensiones válidas."""

    name: str  # nombre corto de la CLI (``titan``, ``cohere-v4``)
    model_id: str
    default_dim: int
    allowed_dims: tuple[int, ...]

    def request(self, png: bytes, dim: int) -> dict[str, Any]:
        """Cuerpo de ``InvokeModel``: solo la imagen en base64 y los parámetros del modelo."""
        image = base64.b64encode(png).decode("ascii")
        if self.name == "titan":
            return {"inputImage": image, "embeddingConfig": {"outputEmbeddingLength": dim}}
        return {
            "input_type": "search_document",
            "images": [f"data:image/png;base64,{image}"],
            "embedding_types": ["float"],
            "output_dimension": dim,
        }

    def parse(self, payload: dict[str, Any]) -> list[float]:
        """Vector de la respuesta (``embedding`` en Titan; ``embeddings.float[0]`` en Cohere)."""
        if self.name == "titan":
            return list(payload["embedding"])
        emb = payload["embeddings"]
        if isinstance(emb, dict):
            emb = emb["float"]
        return list(emb[0])


MODELS = {
    "titan": ModelSpec("titan", "amazon.titan-embed-image-v1", 1024, (256, 384, 1024)),
    "cohere-v4": ModelSpec("cohere-v4", "cohere.embed-v4:0", 1536, (256, 512, 1024, 1536)),
}
DEFAULT_MODEL = "titan"


def cache_key(png: bytes, model_id: str, dim: int, recipe_version: str) -> str:
    """Clave de caché: sha256 de ``"<sha256 del PNG>|<model_id>|<dim>|<receta>_v<versión>"``.

    Cambiar cualquiera de los cuatro componentes cambia la clave (Req. 4.5). ``model_id`` y
    ``recipe_version`` no pueden contener ``|``, para que la concatenación no sea ambigua.
    """
    for name, value in (("model_id", model_id), ("recipe_version", recipe_version)):
        if "|" in value:
            raise ValueError(f"{name} no puede contener '|': {value!r}")
    digest = hashlib.sha256(png).hexdigest()
    return hashlib.sha256(f"{digest}|{model_id}|{int(dim)}|{recipe_version}".encode()).hexdigest()


def error_code(e: BaseException) -> str:
    """Código de error de botocore (``e.response['Error']['Code']``) o el nombre de la excepción."""
    response = getattr(e, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(e).__name__


class BedrockRuntimeLike(Protocol):
    """Lo que el codificador usa del cliente ``bedrock-runtime``."""

    def invoke_model(
        self, *, modelId: str, body: str, contentType: str, accept: str
    ) -> dict[str, Any]:
        """Invoca el modelo con el cuerpo JSON ``body``."""
        ...


class BedrockControlLike(Protocol):
    """Lo que el codificador usa del cliente ``bedrock`` (plano de control)."""

    def get_foundation_model(self, *, modelIdentifier: str) -> dict[str, Any]:
        """Describe el modelo; falla si no existe en la región."""
        ...


class S3ClientLike(Protocol):
    """Lo que ``S3Cache`` usa del cliente ``s3``."""

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        """Lee un objeto."""
        ...

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, Any]:
        """Escribe un objeto."""
        ...


class EmbeddingCache(Protocol):
    """Caché de embeddings indexada por ``cache_key``."""

    def get(self, key: str) -> np.ndarray | None:
        """Vector guardado bajo ``key`` o ``None`` si no hay."""
        ...

    def put(self, key: str, vec: np.ndarray) -> None:
        """Guarda (o reemplaza) el vector de ``key``."""
        ...


def _npy_bytes(vec: np.ndarray) -> bytes:
    """Serializa ``vec`` como ``.npy`` (``float32``)."""
    buf = io.BytesIO()
    np.save(buf, np.asarray(vec, dtype=np.float32), allow_pickle=False)
    return buf.getvalue()


class LocalCache:
    """Caché en disco: ``<root>/<key>.npy`` escrito vía ``.tmp`` + ``os.replace`` (sin entradas a medias)."""

    def __init__(self, root: Path) -> None:
        """Caché bajo la carpeta ``root`` (se crea al escribir)."""
        self.root = root

    def path(self, key: str) -> Path:
        """Ruta del archivo de ``key``."""
        return self.root / f"{key}.npy"

    def get(self, key: str) -> np.ndarray | None:
        """Vector de ``key`` o ``None`` si no existe."""
        p = self.path(key)
        if not p.exists():
            return None
        return np.load(p, allow_pickle=False)

    def put(self, key: str, vec: np.ndarray) -> None:
        """Escribe el vector de ``key`` de forma atómica."""
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(_npy_bytes(vec))
        os.replace(tmp, p)


class S3Cache:
    """Caché en S3: ``s3://<bucket>/<prefix><key>.npy`` con ``put_object`` (atómico en S3)."""

    def __init__(
        self, client: S3ClientLike, bucket: str, prefix: str = "model/embeddings/cache/"
    ) -> None:
        """Caché con el cliente S3 ``client`` (inyectable) bajo ``bucket``/``prefix``."""
        self.client = client
        self.bucket = bucket
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"

    def object_key(self, key: str) -> str:
        """Clave S3 del vector ``key``."""
        return f"{self.prefix}{key}.npy"

    def get(self, key: str) -> np.ndarray | None:
        """Vector de ``key`` o ``None`` si el objeto no existe."""
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self.object_key(key))
        except Exception as e:
            if error_code(e) in MISSING_KEY_CODES:
                return None
            raise
        return np.load(io.BytesIO(obj["Body"].read()), allow_pickle=False)

    def put(self, key: str, vec: np.ndarray) -> None:
        """Sube el vector de ``key``."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.object_key(key),
            Body=_npy_bytes(vec),
            ContentType="application/octet-stream",
        )


@dataclass(frozen=True)
class ImageItem:
    """Una imagen a codificar: su Celda_Hora, los bytes del PNG y la receta (``<nombre>_v<versión>``)."""

    cell_id: str
    png: bytes
    recipe_version: str


@dataclass(frozen=True)
class EncodeResult:
    """Resultado de una imagen: ``status`` ∈ {``encoded``, ``cached``, ``failed``}."""

    status: str
    vector: np.ndarray | None = None
    error_type: str | None = None


@dataclass
class RunSummary:
    """Contabilidad de una corrida (Req. 4.8): ``encoded + cached + failed`` = imágenes de entrada."""

    encoded: int = 0
    cached: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    vectors: dict[str, np.ndarray] = field(default_factory=dict)  # cell_id → vector (no fallidas)

    @property
    def exit_code(self) -> int:
        """Código de salida de la CLI: distinto de cero si hubo imágenes fallidas."""
        return 1 if self.failed > 0 else 0

    def to_json(self, model_id: str, dim: int) -> dict[str, Any]:
        """Contenido de ``run_summary.json``."""
        return {
            "model_id": model_id,
            "dim": dim,
            "encoded": self.encoded,
            "cached": self.cached,
            "failed": self.failed,
            "failures": self.failures,
        }


def valid_vector(vec: object, dim: int) -> np.ndarray | None:
    """``vec`` como ``float32`` si tiene longitud ``dim`` y todos sus valores son finitos; si no, ``None``."""
    try:
        arr = np.asarray(vec, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1 or arr.shape[0] != dim or not np.isfinite(arr).all():
        return None
    return arr


class BedrockEncoder:
    """Codifica PNG con un Modelo_Embedding de Bedrock, con caché y reintentos ante limitación de tasa."""

    def __init__(
        self,
        client: BedrockRuntimeLike,
        control: BedrockControlLike,
        spec: ModelSpec,
        dim: int,
        cache: EmbeddingCache,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Codificador del modelo ``spec`` con dimensión de salida ``dim``.

        ``client`` es el cliente ``bedrock-runtime``, ``control`` el de ``bedrock``, ``cache`` la
        caché de embeddings y ``sleep`` la función de espera de los reintentos.
        """
        if dim not in spec.allowed_dims:
            raise ValueError(
                f"dimensión {dim} no válida para {spec.model_id}; usa una de {list(spec.allowed_dims)}"
            )
        self.client = client
        self.control = control
        self.spec = spec
        self.dim = dim
        self.cache = cache
        self.sleep = sleep

    def preflight(self, region: str) -> None:
        """Termina (``SystemExit``) si el modelo no se ofrece en ``region`` o no hay acceso (Req. 4.4).

        Se llama antes de la primera imagen y no toca la caché.
        """
        try:
            self.control.get_foundation_model(modelIdentifier=self.spec.model_id)
        except Exception as e:
            raise SystemExit(
                f"error: el modelo {self.spec.model_id} no está disponible en la región {region} "
                f"o la cuenta no tiene acceso ({error_code(e)}: {e!s:.200})"
            ) from e

    def _invoke(self, body: str) -> dict[str, Any]:
        """Una llamada a ``InvokeModel`` y su respuesta JSON."""
        resp = self.client.invoke_model(
            modelId=self.spec.model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        raw = resp["body"]
        data = raw.read() if hasattr(raw, "read") else raw
        return json.loads(data)

    def encode(self, png: bytes, recipe_version: str, force: bool) -> EncodeResult:
        """Embedding de ``png``: desde la caché (salvo ``force``) o invocando Bedrock."""
        key = cache_key(png, self.spec.model_id, self.dim, recipe_version)
        if not force:
            hit = self.cache.get(key)
            vec = valid_vector(hit, self.dim) if hit is not None else None
            if vec is not None:
                return EncodeResult("cached", vec)
        body = json.dumps(self.spec.request(png, self.dim))
        payload: dict[str, Any] | None = None
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                payload = self._invoke(body)
                break
            except Exception as e:
                code = error_code(e)
                if code == THROTTLING and attempt < len(BACKOFF_S):
                    self.sleep(BACKOFF_S[attempt])
                    continue
                return EncodeResult("failed", error_type=code)
        if payload is None:  # inalcanzable: el bucle termina con break o return
            return EncodeResult("failed", error_type=THROTTLING)
        try:
            raw_vec = self.spec.parse(payload)
        except (KeyError, IndexError, TypeError) as e:
            return EncodeResult("failed", error_type=f"InvalidResponse:{type(e).__name__}")
        vec = valid_vector(raw_vec, self.dim)
        if vec is None:
            return EncodeResult("failed", error_type="InvalidEmbedding")
        self.cache.put(key, vec)
        return EncodeResult("encoded", vec)

    def run(self, items: Iterable[ImageItem], force: bool) -> RunSummary:
        """Codifica todas las imágenes sin detenerse por una fallida y devuelve la contabilidad."""
        summary = RunSummary()
        for item in items:
            res = self.encode(item.png, item.recipe_version, force)
            if res.status == "failed":
                summary.failed += 1
                summary.failures.append(
                    {"cell_id": item.cell_id, "error_type": res.error_type or "Unknown"}
                )
                continue
            if res.status == "cached":
                summary.cached += 1
            else:
                summary.encoded += 1
            assert res.vector is not None
            summary.vectors[item.cell_id] = res.vector
        return summary


def make_clients(region: str) -> tuple[Any, Any]:
    """Clientes boto3 ``bedrock-runtime`` y ``bedrock`` de ``region``, sin reintentos de botocore.

    ``read_timeout=30`` hace que una invocación lenta falle como ``ReadTimeoutError`` (Req. 4.10) y
    ``max_attempts=0`` deja los reintentos solo en manos de ``BedrockEncoder``.
    """
    import boto3
    from botocore.config import Config

    cfg = Config(read_timeout=READ_TIMEOUT_S, retries={"max_attempts": 0})
    runtime = boto3.client("bedrock-runtime", region_name=region, config=cfg)
    control = boto3.client("bedrock", region_name=region, config=cfg)
    return runtime, control
