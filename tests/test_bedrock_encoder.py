"""Pruebas del Codificador_Bedrock con dobles de prueba (sin red ni credenciales de AWS)."""

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

import bedrock_encoder as be  # noqa: E402
import encode_bedrock  # noqa: E402

KINDS = ("ok", "short", "nan", "throttle", "error", "timeout")
RECIPE = "ir_wv_v1"


class FakeClientError(Exception):
    """Error con la forma de ``botocore.exceptions.ClientError`` (``response['Error']['Code']``)."""

    def __init__(self, code: str) -> None:
        """Error con código ``code``."""
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class ReadTimeoutError(Exception):
    """Doble del ``ReadTimeoutError`` de botocore (invocación de más de 30 s)."""


def vector_for(png: bytes, dim: int) -> list[float]:
    """Vector determinista y finito derivado de los bytes de ``png``."""
    rng = np.random.default_rng(int.from_bytes(png[:8].ljust(8, b"\0"), "little") + len(png))
    return rng.standard_normal(dim).tolist()


def image_of(body: dict[str, Any]) -> bytes:
    """Bytes de la imagen enviada en un cuerpo de Titan o de Cohere."""
    if "inputImage" in body:
        return base64.b64decode(body["inputImage"])
    return base64.b64decode(body["images"][0].split(",", 1)[1])


class FakeBedrockRuntime:
    """Doble de ``bedrock-runtime`` con respuestas programables por imagen.

    ``plan`` asocia los bytes de cada PNG a una secuencia de respuestas (``KINDS``); la última se
    repite. Sin plan, la imagen responde ``ok``. Registra cada cuerpo enviado en ``calls``.
    """

    def __init__(self, dim: int, plan: dict[bytes, list[str]] | None = None) -> None:
        """Doble que devuelve vectores de longitud ``dim``."""
        self.dim = dim
        self.plan = {k: list(v) for k, v in (plan or {}).items()}
        self.calls: list[dict[str, Any]] = []

    def invoke_model(
        self, *, modelId: str, body: str, contentType: str, accept: str
    ) -> dict[str, Any]:
        """Simula ``InvokeModel`` según el plan de la imagen."""
        payload_in = json.loads(body)
        self.calls.append({"modelId": modelId, "body": payload_in})
        png = image_of(payload_in)
        seq = self.plan.get(png, ["ok"])
        kind = seq.pop(0) if len(seq) > 1 else seq[0]
        if kind == "throttle":
            raise FakeClientError("ThrottlingException")
        if kind == "error":
            raise FakeClientError("ValidationException")
        if kind == "timeout":
            raise ReadTimeoutError("read timeout")
        vec = vector_for(png, self.dim)
        if kind == "short":
            vec = vec[:-1]
        elif kind == "nan":
            vec[0] = float("nan")
        if "inputImage" in payload_in:
            payload: dict[str, Any] = {"embedding": vec, "inputTextTokenCount": 0}
        else:
            payload = {"embeddings": {"float": [vec]}, "response_type": "embeddings_by_type"}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class FakeBedrockControl:
    """Doble del plano de control ``bedrock``: el modelo existe o no."""

    def __init__(self, available: bool = True) -> None:
        """Doble con el modelo disponible o no."""
        self.available = available
        self.calls: list[str] = []

    def get_foundation_model(self, *, modelIdentifier: str) -> dict[str, Any]:
        """Simula ``GetFoundationModel``."""
        self.calls.append(modelIdentifier)
        if not self.available:
            raise FakeClientError("ResourceNotFoundException")
        return {"modelDetails": {"modelId": modelIdentifier}}


class MemoryCache:
    """Caché en memoria que cuenta las escrituras."""

    def __init__(self) -> None:
        """Caché vacía."""
        self.data: dict[str, np.ndarray] = {}
        self.puts = 0

    def get(self, key: str) -> np.ndarray | None:
        """Vector de ``key`` o ``None``."""
        return self.data.get(key)

    def put(self, key: str, vec: np.ndarray) -> None:
        """Guarda una copia de ``vec``."""
        self.puts += 1
        self.data[key] = np.array(vec, copy=True)


class FakeS3:
    """Doble mínimo de un cliente S3 (``get_object``/``put_object``)."""

    def __init__(self) -> None:
        """Bucket vacío."""
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        """Objeto o ``NoSuchKey``."""
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict:
        """Guarda el objeto."""
        self.objects[(Bucket, Key)] = Body
        return {}


def encoder(
    model: str = "titan",
    dim: int | None = None,
    plan: dict[bytes, list[str]] | None = None,
    available: bool = True,
) -> tuple[be.BedrockEncoder, FakeBedrockRuntime, MemoryCache, list[float]]:
    """Codificador con dobles; devuelve también el doble, la caché y las esperas registradas."""
    spec = be.MODELS[model]
    d = dim or spec.default_dim
    runtime = FakeBedrockRuntime(d, plan)
    cache = MemoryCache()
    waits: list[float] = []
    enc = be.BedrockEncoder(runtime, FakeBedrockControl(available), spec, d, cache, waits.append)
    return enc, runtime, cache, waits


def items_of(pngs: list[bytes]) -> list[be.ImageItem]:
    """Una ImageItem por PNG, con ``cell_id`` correlativo."""
    return [be.ImageItem(f"2019053012_{i:04d}", p, RECIPE) for i, p in enumerate(pngs)]


NO_PIPE = st.text(alphabet=st.characters(blacklist_characters="|"), max_size=20)
COMPONENTS = (st.binary(max_size=32), NO_PIPE, st.integers(1, 4096), NO_PIPE)


class CacheKeyTest(unittest.TestCase):
    """Propiedad 8."""

    # Feature: multimodal-tornado-predictor, Property 8: La clave de caché distingue sus cuatro componentes
    @settings(max_examples=100, deadline=None)
    @given(data=st.data(), which=st.sampled_from([None, 0, 1, 2, 3]))
    def test_key_distinguishes_components(self, data: st.DataObject, which: int | None) -> None:
        """Misma clave si y solo si las cuatro componentes son iguales."""
        a = [data.draw(s) for s in COMPONENTS]
        b = list(a)
        if which is not None:
            b[which] = data.draw(COMPONENTS[which])
        ka = be.cache_key(a[0], a[1], a[2], a[3])
        kb = be.cache_key(b[0], b[1], b[2], b[3])
        self.assertEqual(ka == kb, a == b)
        self.assertEqual(len(ka), 64)

    def test_pipe_is_rejected(self) -> None:
        """Un ``|`` en el modelo o la receta haría ambigua la clave: se rechaza."""
        with self.assertRaises(ValueError):
            be.cache_key(b"x", "a|b", 8, RECIPE)
        with self.assertRaises(ValueError):
            be.cache_key(b"x", "m", 8, "r|1")


class EncoderPropertiesTest(unittest.TestCase):
    """Propiedades 9 y 10."""

    # Feature: multimodal-tornado-predictor, Property 9: Idempotencia de la caché
    @settings(max_examples=100, deadline=None)
    @given(pngs=st.lists(st.binary(min_size=1, max_size=24), unique=True, max_size=6))
    def test_cache_idempotence(self, pngs: list[bytes]) -> None:
        """La segunda corrida no invoca Bedrock y devuelve los mismos vectores."""
        enc, runtime, _, _ = encoder(dim=256)
        first = enc.run(items_of(pngs), force=False)
        n_calls = len(runtime.calls)
        second = enc.run(items_of(pngs), force=False)
        self.assertEqual(n_calls, len(pngs))
        self.assertEqual(len(runtime.calls), n_calls)
        self.assertEqual((second.cached, second.encoded, second.failed), (len(pngs), 0, 0))
        self.assertEqual(sorted(first.vectors), sorted(second.vectors))
        for k, v in first.vectors.items():
            np.testing.assert_array_equal(v, second.vectors[k])

    # Feature: multimodal-tornado-predictor, Property 10: Contabilidad de la corrida de codificación
    @settings(max_examples=100, deadline=None)
    @given(
        cases=st.lists(
            st.tuples(st.binary(min_size=1, max_size=24), st.sampled_from(KINDS)),
            unique_by=lambda c: c[0],
            max_size=8,
        ),
        model=st.sampled_from(sorted(be.MODELS)),
        data=st.data(),
    )
    def test_run_accounting(
        self, cases: list[tuple[bytes, str]], model: str, data: st.DataObject
    ) -> None:
        """Las cuentas suman, la caché solo tiene vectores válidos y las solicitudes solo la imagen."""
        spec = be.MODELS[model]
        dim = data.draw(st.sampled_from(spec.allowed_dims))
        plan = {png: [kind] for png, kind in cases}
        enc, runtime, cache, _ = encoder(model, dim, plan)
        pngs = [png for png, _ in cases]
        summary = enc.run(items_of(pngs), force=False)
        n_bad = sum(kind != "ok" for _, kind in cases)
        self.assertEqual(summary.encoded + summary.cached + summary.failed, len(cases))
        self.assertEqual(summary.failed, n_bad)
        self.assertEqual(len(summary.failures), n_bad)
        self.assertEqual(summary.exit_code != 0, summary.failed > 0)
        self.assertEqual(len(cache.data), len(cases) - n_bad)
        for vec in cache.data.values():
            self.assertEqual(vec.shape, (dim,))
            self.assertTrue(np.isfinite(vec).all())
        expected_keys = (
            {"inputImage", "embeddingConfig"}
            if model == "titan"
            else {"input_type", "images", "embedding_types", "output_dimension"}
        )
        for call in runtime.calls:
            body = call["body"]
            self.assertEqual(call["modelId"], spec.model_id)
            self.assertEqual(set(body), expected_keys)
            self.assertIn(image_of(body), pngs)
            if model == "titan":
                self.assertEqual(body["embeddingConfig"], {"outputEmbeddingLength": dim})
            else:
                self.assertEqual(body["output_dimension"], dim)
                self.assertEqual(len(body["images"]), 1)


class EncoderUnitTest(unittest.TestCase):
    """Pruebas obligatorias del Codificador_Bedrock (5.5)."""

    def test_vector_dimension(self) -> None:
        """El vector devuelto tiene la dimensión configurada (Titan 1024 por defecto, Cohere)."""
        for model, dim in (
            ("titan", None),
            ("titan", 256),
            ("cohere-v4", None),
            ("cohere-v4", 512),
        ):
            enc, _, _, _ = encoder(model, dim)
            res = enc.encode(b"png", RECIPE, force=False)
            expected = dim or be.MODELS[model].default_dim
            with self.subTest(model=model, dim=dim):
                self.assertEqual(res.status, "encoded")
                assert res.vector is not None
                self.assertEqual(res.vector.shape, (expected,))
        self.assertEqual(be.MODELS["titan"].default_dim, 1024)

    def test_invalid_dim_is_rejected(self) -> None:
        """Una dimensión que el modelo no ofrece se rechaza al crear el codificador."""
        with self.assertRaises(ValueError):
            encoder("titan", 512)

    def test_cache_reuse_without_calling_double(self) -> None:
        """Con la entrada en caché no se llama al doble."""
        enc, runtime, cache, _ = encoder(dim=256)
        enc.encode(b"a", RECIPE, force=False)
        self.assertEqual(len(runtime.calls), 1)
        res = enc.encode(b"a", RECIPE, force=False)
        self.assertEqual(res.status, "cached")
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(cache.puts, 1)

    def test_throttling_waits(self) -> None:
        """Limitación persistente: esperas 1, 2, 4, 8 y 16 s, luego fallida sin caché."""
        enc, runtime, cache, waits = encoder(dim=256, plan={b"a": ["throttle"]})
        res = enc.encode(b"a", RECIPE, force=False)
        self.assertEqual(waits, [1, 2, 4, 8, 16])
        self.assertEqual(len(runtime.calls), 6)
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.error_type, "ThrottlingException")
        self.assertEqual(cache.puts, 0)

    def test_throttling_then_success(self) -> None:
        """Dos limitaciones y luego éxito: esperas 1 y 2 s, imagen codificada."""
        enc, _, cache, waits = encoder(dim=256, plan={b"a": ["throttle", "throttle", "ok"]})
        res = enc.encode(b"a", RECIPE, force=False)
        self.assertEqual(waits, [1, 2])
        self.assertEqual(res.status, "encoded")
        self.assertEqual(cache.puts, 1)

    def test_other_errors_fail_with_type(self) -> None:
        """Otro error o tiempo agotado: fallida con el tipo de error, sin reintentos ni caché."""
        for kind, code in (("error", "ValidationException"), ("timeout", "ReadTimeoutError")):
            enc, runtime, cache, waits = encoder(dim=256, plan={b"a": [kind]})
            res = enc.encode(b"a", RECIPE, force=False)
            with self.subTest(kind=kind):
                self.assertEqual((res.status, res.error_type), ("failed", code))
                self.assertEqual(len(runtime.calls), 1)
                self.assertEqual(waits, [])
                self.assertEqual(cache.puts, 0)

    def test_invalid_vectors_fail_without_cache(self) -> None:
        """Vector de longitud errónea o con NaN: fallida y sin caché."""
        for kind in ("short", "nan"):
            enc, _, cache, _ = encoder(dim=256, plan={b"a": [kind]})
            res = enc.encode(b"a", RECIPE, force=False)
            with self.subTest(kind=kind):
                self.assertEqual(res.status, "failed")
                self.assertEqual(cache.puts, 0)

    def test_preflight_unavailable_model_exits_without_cache(self) -> None:
        """Modelo no disponible: ``SystemExit`` con modelo y región, sin tocar la caché."""
        enc, runtime, cache, _ = encoder(available=False)
        with self.assertRaises(SystemExit) as cm:
            enc.preflight("us-west-2")
        msg = str(cm.exception.code)
        self.assertIn("amazon.titan-embed-image-v1", msg)
        self.assertIn("us-west-2", msg)
        self.assertEqual(runtime.calls, [])
        self.assertEqual((cache.puts, cache.data), (0, {}))

    def test_force_replaces_cache(self) -> None:
        """Con ``force`` se invoca Bedrock aunque haya caché y se reemplaza la entrada."""
        enc, runtime, cache, _ = encoder(dim=256)
        key = be.cache_key(b"a", be.MODELS["titan"].model_id, 256, RECIPE)
        cache.put(key, np.zeros(256, dtype=np.float32))
        res = enc.encode(b"a", RECIPE, force=False)
        self.assertEqual((res.status, len(runtime.calls)), ("cached", 0))
        res = enc.encode(b"a", RECIPE, force=True)
        self.assertEqual((res.status, len(runtime.calls)), ("encoded", 1))
        expected = np.asarray(vector_for(b"a", 256), dtype=np.float32)
        np.testing.assert_array_equal(cache.data[key], expected)

    def test_local_and_s3_caches(self) -> None:
        """``LocalCache`` (sin ``.tmp`` sobrantes) y ``S3Cache`` guardan y devuelven el vector."""
        vec = np.arange(4, dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            local = be.LocalCache(Path(tmp) / "cache")
            self.assertIsNone(local.get("k"))
            local.put("k", vec)
            np.testing.assert_array_equal(local.get("k"), vec)
            self.assertEqual([p.name for p in (Path(tmp) / "cache").iterdir()], ["k.npy"])
        s3 = be.S3Cache(FakeS3(), "bucket", "model/embeddings/cache")
        self.assertIsNone(s3.get("k"))
        s3.put("k", vec)
        np.testing.assert_array_equal(s3.get("k"), vec)
        self.assertEqual(s3.object_key("k"), "model/embeddings/cache/k.npy")


class EncodeCliTest(unittest.TestCase):
    """CLI ``encode_bedrock.py`` con fábrica de clientes falsa."""

    def setUp(self) -> None:
        """Manifiesto con tres PNG (dos del 30 de mayo, uno del 31) en un directorio temporal."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rgb_dir = self.root / "rgb" / "ir_wv_v1"
        rows = []
        for cell_id in ("2019053012_a", "2019053013_b", "2019053112_c"):
            rel = f"{cell_id[:8]}/{cell_id}.png"
            png = self.rgb_dir / rel
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(f"png-{cell_id}".encode())
            rows.append(
                {"cell_id": cell_id, "png_path": rel, "recipe": "ir_wv", "recipe_version": 1}
            )
        self.manifest = self.rgb_dir / "manifest.parquet"
        pd.DataFrame(rows).to_parquet(self.manifest, index=False)
        self.model_root = self.root / "model"
        self.runtime: FakeBedrockRuntime | None = None
        self.regions: list[str] = []
        self.dim = 1024

    def tearDown(self) -> None:
        """Borra el directorio temporal."""
        self._tmp.cleanup()

    def factory(
        self, plan: dict[bytes, list[str]] | None = None, available: bool = True
    ) -> encode_bedrock.ClientFactory:
        """Fábrica falsa que registra la región y crea el doble con la dimensión ``self.dim``."""

        def make(region: str) -> tuple[Any, Any]:
            """Dobles de ``bedrock-runtime`` y ``bedrock``."""
            self.regions.append(region)
            self.runtime = FakeBedrockRuntime(self.dim, plan)
            return self.runtime, FakeBedrockControl(available)

        return make

    def run_cli(self, *args: str, plan: dict | None = None, available: bool = True) -> int:
        """Ejecuta la CLI sobre el 30 de mayo sin imprimir."""
        argv = ["--start", "2019-05-30", "--manifest", str(self.manifest), *args]
        with contextlib.redirect_stdout(io.StringIO()):
            return encode_bedrock.run_cli(argv, self.factory(plan, available), self.model_root)

    def out_dir(self) -> Path:
        """Carpeta de embeddings de la región por defecto."""
        return self.model_root / "south-central-austral" / "embeddings"

    def test_titan_by_default(self) -> None:
        """Sin ``--model`` usa Titan (1024), escribe la tabla y el resumen y sale con 0."""
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.regions, ["us-west-2"])
        df = pd.read_parquet(self.out_dir() / "titan_1024_ir_wv_v1.parquet")
        self.assertEqual(df["cell_id"].tolist(), ["2019053012_a", "2019053013_b"])
        self.assertEqual(list(df.columns[:4]), ["cell_id", "model_id", "dim", "emb_0000"])
        self.assertEqual(df.shape[1], 3 + 1024)
        self.assertEqual(set(df["model_id"]), {"amazon.titan-embed-image-v1"})
        summary = json.loads((self.out_dir() / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["model_id"], "amazon.titan-embed-image-v1")
        self.assertEqual((summary["encoded"], summary["cached"], summary["failed"]), (2, 0, 0))
        self.assertEqual(len(list((self.model_root / "embeddings" / "cache").glob("*.npy"))), 2)
        # Segunda corrida: todo desde caché.
        self.assertEqual(self.run_cli(), 0)
        assert self.runtime is not None
        self.assertEqual(self.runtime.calls, [])

    def test_cohere_selectable(self) -> None:
        """``--model cohere-v4`` usa Cohere Embed v4 y registra su identificador."""
        self.dim = 512
        self.assertEqual(self.run_cli("--model", "cohere-v4", "--dim", "512"), 0)
        assert self.runtime is not None
        self.assertEqual({c["modelId"] for c in self.runtime.calls}, {"cohere.embed-v4:0"})
        df = pd.read_parquet(self.out_dir() / "cohere-v4_512_ir_wv_v1.parquet")
        self.assertEqual(df.shape, (2, 3 + 512))
        summary = json.loads((self.out_dir() / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["model_id"], "cohere.embed-v4:0")

    def test_exit_code_with_failures(self) -> None:
        """Una imagen fallida deja código 1 y queda en el resumen con su tipo de error."""
        code = self.run_cli(plan={b"png-2019053013_b": ["error"]})
        self.assertEqual(code, 1)
        summary = json.loads((self.out_dir() / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(
            summary["failures"], [{"cell_id": "2019053013_b", "error_type": "ValidationException"}]
        )

    def test_preflight_failure_exits_before_encoding(self) -> None:
        """Modelo no disponible: código 1, sin invocaciones, sin caché ni tabla."""
        self.assertEqual(self.run_cli(available=False), 1)
        assert self.runtime is not None
        self.assertEqual(self.runtime.calls, [])
        self.assertFalse((self.model_root / "embeddings" / "cache").exists())
        self.assertFalse(self.out_dir().exists())

    def test_invalid_dim_exits_with_error(self) -> None:
        """Una ``--dim`` que el modelo no ofrece termina con código distinto de cero."""
        self.assertNotEqual(self.run_cli("--dim", "512"), 0)

    def test_s3_cache(self) -> None:
        """``--cache s3`` guarda en el bucket indicado con el cliente inyectado."""
        s3 = FakeS3()
        argv = ["--start", "2019-05-30", "--manifest", str(self.manifest)]
        argv += ["--cache", "s3", "--cache-bucket", "ml-bucket"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = encode_bedrock.run_cli(
                argv, self.factory(), self.model_root, s3_client_factory=lambda r: s3
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(s3.objects), 2)
        self.assertTrue(all(k.startswith("model/embeddings/cache/") for _, k in s3.objects))


if __name__ == "__main__":
    unittest.main()
