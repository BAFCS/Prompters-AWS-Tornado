"""Pruebas del Servicio_Inferencia (``scripts/model/sm_job/inference.py``)."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(ROOT / "scripts" / "model" / "sm_job"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inference  # noqa: E402
import synthetic  # noqa: E402
import train_entry  # noqa: E402

CONFIGS = ("physical", "embeddings")


def input_frame(bundle: inference.Bundle, n: int, seed: int, nan_frac: float) -> pd.DataFrame:
    """Entrada con todas las columnas requeridas (en orden aleatorio) y NaN en ``nan_frac``."""
    rng = np.random.default_rng(seed)
    data = rng.normal(size=(n, len(bundle.input_columns)))
    data[rng.random(data.shape) < nan_frac] = np.nan
    df = pd.DataFrame(data, columns=bundle.input_columns)
    df["date"] = pd.to_datetime("2020-01-01") + pd.to_timedelta(rng.integers(0, 60, n), "D")
    df["date"] = df["date"].dt.date
    df["hour_utc"] = rng.integers(0, 24, n).astype("int8")
    df["latitude"] = rng.uniform(-56, -30, n)
    df["longitude"] = rng.uniform(-76, -66, n)
    df["cell_id"] = [f"c{i}" for i in range(n)]
    return df[list(rng.permutation(df.columns))]


class InferenceTest(unittest.TestCase):
    """Propiedades 29 y 30 con modelos diminutos entrenados por ``train_entry``."""

    tmp: tempfile.TemporaryDirectory
    bundles: dict[str, inference.Bundle]

    @classmethod
    def setUpClass(cls) -> None:
        """Entrena ``physical`` y ``embeddings`` con la tabla sintética y carga sus modelos."""
        tables = synthetic.model_tables()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bundles = {}
        for config in CONFIGS:
            root = Path(cls.tmp.name) / config
            inp = synthetic.write_channels(root, tables[config], tables["physical"])
            with contextlib.redirect_stdout(io.StringIO()):
                train_entry.main(["--config", config], inp, root / "model")
            cls.bundles[config] = inference.model_fn(str(root / "model"))

    @classmethod
    def tearDownClass(cls) -> None:
        """Borra los modelos temporales."""
        cls.tmp.cleanup()

    # Feature: multimodal-tornado-predictor, Property 29: Salida de inferencia
    @settings(max_examples=100, deadline=None)
    @given(
        config=st.sampled_from(CONFIGS),
        n=st.integers(1, 30),
        seed=st.integers(0, 2**16),
        nan_frac=st.sampled_from([0.0, 0.1, 0.5, 1.0]),
    )
    def test_output(self, config: str, n: int, seed: int, nan_frac: float) -> None:
        """Una probabilidad en [0, 1] por fila, en el orden de entrada, con NaN tolerados."""
        bundle = self.bundles[config]
        df = input_frame(bundle, n, seed, nan_frac)
        out = inference.predict_fn(df, bundle)
        self.assertEqual(list(out.columns), list(inference.OUTPUT_COLUMNS))
        self.assertEqual(len(out), n)
        p = out["probability"].to_numpy()
        self.assertTrue(np.isfinite(p).all())
        self.assertTrue(((p >= 0) & (p <= 1)).all())
        np.testing.assert_array_equal(out["latitude"], df["latitude"].to_numpy())
        np.testing.assert_array_equal(out["longitude"], df["longitude"].to_numpy())
        np.testing.assert_array_equal(out["hour_utc"], df["hour_utc"].astype(int).to_numpy())
        self.assertEqual(out["date"].tolist(), [d.isoformat() for d in df["date"]])
        self.assertTrue((out["config"] == config).all())

    # Feature: multimodal-tornado-predictor, Property 30: Rechazo por columnas faltantes
    @settings(max_examples=100, deadline=None)
    @given(config=st.sampled_from(CONFIGS), data=st.data())
    def test_missing_columns(self, config: str, data: st.DataObject) -> None:
        """Quitar columnas requeridas lanza ``MissingColumnsError`` que nombra exactamente esas."""
        bundle = self.bundles[config]
        dropped = data.draw(st.lists(st.sampled_from(bundle.required), min_size=1, unique=True))
        df = input_frame(bundle, 5, 0, 0.1).drop(columns=dropped)
        with self.assertRaises(inference.MissingColumnsError) as cm:
            inference.predict_fn(df, bundle)
        expected = [c for c in bundle.required if c in dropped]
        self.assertEqual(cm.exception.missing, expected)
        self.assertEqual(
            str(cm.exception), "faltan columnas requeridas por el modelo: " + ", ".join(expected)
        )

    def test_parquet_in_csv_out(self) -> None:
        """``input_fn`` lee Parquet; ``output_fn`` escribe CSV; otros tipos se rechazan."""
        bundle = self.bundles["physical"]
        df = input_frame(bundle, 4, 1, 0.2)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        parsed = inference.input_fn(buf.getvalue(), "application/x-parquet")
        body = inference.output_fn(inference.predict_fn(parsed, bundle), "text/csv")
        csv = pd.read_csv(io.BytesIO(body))
        self.assertEqual(list(csv.columns), list(inference.OUTPUT_COLUMNS))
        self.assertEqual(len(csv), 4)
        with self.assertRaises(ValueError):
            inference.input_fn(b"", "application/json")
        with self.assertRaises(ValueError):
            inference.output_fn(csv, "application/json")
        self.assertIsNotNone(self.bundles["embeddings"].reducer)
        self.assertIsNone(bundle.reducer)


if __name__ == "__main__":
    unittest.main()
