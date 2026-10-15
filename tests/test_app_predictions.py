"""Pruebas de la lectura y validación de CSV_Predicciones (``scripts/app/predictions.py``)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))

import predictions  # noqa: E402

HEADER = "probability,date,hour_utc,latitude,longitude,config"
ROWS = [
    "0.4123,2019-05-30,21,-36.75,-73.0,sustituto/baseline_era5",
    "0.0,2019-05-30,0,-36.5,-73.0,sustituto/baseline_era5",
    "1.0,2019-05-30,23,-36.75,-72.75,sustituto/baseline_era5",
]
META = {"modelo": "sustituto", "generado": "2026-10-20T14:03:11Z", "filas": 3}


class LoadTest(unittest.TestCase):
    """Acepta un CSV válido y rechaza cada tipo de falla con un motivo que la nombra."""

    def setUp(self) -> None:
        """Crea un directorio temporal por prueba."""
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.csv = self.dir / "pred_20190530.csv"

    def tearDown(self) -> None:
        """Borra el directorio temporal."""
        self._tmp.cleanup()

    def write(
        self, header: str = HEADER, rows: list[str] | None = None, meta: object = META
    ) -> None:
        """Escribe el CSV y, salvo `meta=None`, sus metadatos."""
        lines = [header, *(ROWS if rows is None else rows)]
        self.csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if meta is not None:
            predictions.meta_path(self.csv).write_text(json.dumps(meta), encoding="utf-8")

    def assert_invalid(self, *fragments: str) -> None:
        """`load` falla y el mensaje nombra el archivo y cada fragmento."""
        with self.assertRaises(predictions.InvalidPredictions) as ctx:
            predictions.load(self.csv)
        message = str(ctx.exception)
        self.assertIn("pred_20190530", message)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_meta_path(self) -> None:
        """pred_X.csv -> pred_X.meta.json en el mismo directorio."""
        self.assertEqual(
            predictions.meta_path(Path("a/pred_20190530.csv")), Path("a/pred_20190530.meta.json")
        )

    def test_valid(self) -> None:
        """Un CSV válido se carga con columnas SCHEMA, tipos numéricos y metadatos."""
        self.write()
        pred = predictions.load(self.csv)
        self.assertEqual(tuple(pred.df.columns), predictions.SCHEMA)
        self.assertEqual(len(pred.df), 3)
        self.assertEqual(pred.df["hour_utc"].tolist(), [21, 0, 23])
        self.assertAlmostEqual(float(pred.df["probability"].iloc[0]), 0.4123)
        self.assertEqual(pred.df["date"].iloc[0], "2019-05-30")
        self.assertEqual(pred.meta["modelo"], "sustituto")
        self.assertEqual(pred.path, self.csv)

    def test_valid_real_and_empty(self) -> None:
        """Solo cabecera y modelo 'real' también es válido."""
        self.write(rows=[], meta={"modelo": "real"})
        pred = predictions.load(self.csv)
        self.assertEqual(len(pred.df), 0)
        self.assertEqual(pred.meta["modelo"], "real")

    def test_missing_column(self) -> None:
        """Columna ausente."""
        self.write(
            header="probability,date,hour_utc,latitude,longitude",
            rows=[r.rsplit(",", 1)[0] for r in ROWS],
        )
        self.assert_invalid("columnas", "faltan", "config")

    def test_extra_column(self) -> None:
        """Columna sobrante."""
        self.write(header=HEADER + ",extra", rows=[r + ",x" for r in ROWS])
        self.assert_invalid("columnas", "sobran", "extra")

    def test_renamed_column(self) -> None:
        """Columna renombrada."""
        self.write(header=HEADER.replace("probability", "prob"))
        self.assert_invalid("columnas", "probability", "prob")

    def test_probability_out_of_range(self) -> None:
        """probability > 1 y < 0."""
        for value in ("1.5", "-0.1"):
            with self.subTest(value=value):
                self.write(rows=[ROWS[0].replace("0.4123", value)])
                self.assert_invalid("probability", "[0, 1]")

    def test_probability_nan(self) -> None:
        """probability NaN o vacía."""
        for value in ("nan", ""):
            with self.subTest(value=value):
                self.write(rows=[ROWS[0].replace("0.4123", value)])
                self.assert_invalid("probability", "NaN")

    def test_hour_24(self) -> None:
        """hour_utc fuera de 0–23."""
        self.write(rows=[ROWS[0].replace(",21,", ",24,")])
        self.assert_invalid("hour_utc", "0–23")

    def test_bad_date(self) -> None:
        """Fecha con formato distinto o inexistente."""
        for value in ("30/05/2019", "2019-02-30", "20190530"):
            with self.subTest(value=value):
                self.write(rows=[ROWS[0].replace("2019-05-30", value)])
                self.assert_invalid("date", "AAAA-MM-DD")

    def test_duplicate_key(self) -> None:
        """Dos filas con la misma (date, hour_utc, latitude, longitude)."""
        self.write(rows=[ROWS[0], ROWS[0].replace("0.4123", "0.9")])
        self.assert_invalid("duplicadas")

    def test_missing_meta(self) -> None:
        """Sin archivo de metadatos."""
        self.write(meta=None)
        self.assert_invalid("metadatos", "pred_20190530.meta.json")

    def test_meta_without_modelo(self) -> None:
        """Metadatos sin 'modelo'."""
        self.write(meta={"generado": "2026-10-20T14:03:11Z"})
        self.assert_invalid("modelo")

    def test_meta_bad_modelo(self) -> None:
        """'modelo' con valor no reconocido."""
        self.write(meta={"modelo": "otro"})
        self.assert_invalid("modelo", "otro")

    def test_missing_csv(self) -> None:
        """CSV inexistente."""
        self.assert_invalid("no existe")


if __name__ == "__main__":
    unittest.main()
