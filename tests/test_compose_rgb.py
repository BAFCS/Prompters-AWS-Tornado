"""Pruebas de la CLI del Compositor_RGB con NetCDF sintéticos en un directorio temporal."""

import contextlib
import datetime as dt
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compose_rgb  # noqa: E402
import rgb  # noqa: E402
import synthetic  # noqa: E402

REGION = "test-region"
H11 = dt.datetime(2019, 5, 30, 11)
H12 = dt.datetime(2019, 5, 30, 12)
WINDOW_KM = 20.0


def cells(*points: tuple[str, float, float]) -> pd.DataFrame:
    """Celdas_Hora de las 12 UTC en los puntos ``(cell_id, lat, lon)``."""
    return pd.DataFrame(
        {
            "cell_id": [p[0] for p in points],
            "time": pd.to_datetime([H12] * len(points)).tz_localize("UTC"),
            "latitude": [p[1] for p in points],
            "longitude": [p[2] for p in points],
        }
    )


A = ("2019053012_-35.00_-072.00", -35.0, -72.0)
B = ("2019053012_-35.25_-071.75", -35.25, -71.75)


class ComposeRgbTest(unittest.TestCase):
    """Validación de recetas, omisiones con motivo y contenido del manifiesto."""

    def setUp(self) -> None:
        """Directorio temporal con ``crops/`` y ``model/``."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.crops = self.root / "crops"
        self.out = self.root / "model"

    def tearDown(self) -> None:
        """Borra el directorio temporal."""
        self._tmp.cleanup()

    def write_goes(
        self, bands: tuple[str, ...] = ("C08", "C13"), hole: bool = False
    ) -> list[dt.datetime]:
        """Archivos GOES de las 11 y las 12 con BT uniformes; ``hole`` vacía la ventana de B."""
        fns = {
            "C08": lambda s: 230.0,
            "C10": lambda s: 240.0,
            "C12": lambda s: 250.0,
            "C13": lambda s: 260.0,
        }
        scans: list[dt.datetime] = []
        for h in (H11, H12):
            scans, data = synthetic.uniform_scans(h, {b: fns[b] for b in bands})
            if hole and h == H12:
                lat, lon = synthetic.goes_grid()
                data["C13"][0][np.ix_(lat < -35.1, lon > -71.9)] = np.nan
            synthetic.write_goes_latlon(self.crops, REGION, h, scans, data)
        return scans

    def compose(
        self, table: pd.DataFrame, recipe: rgb.Recipe, force: bool = False
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Llama a ``compose_cells`` sin imprimir."""
        with contextlib.redirect_stdout(io.StringIO()):
            return compose_rgb.compose_cells(
                table, REGION, recipe, 224, WINDOW_KM, self.crops, self.out, force
            )

    def test_unknown_recipe_or_version_exits_before_processing(self) -> None:
        """Receta o versión inexistente: termina antes de leer ``--cells`` y nombra el campo."""
        missing = str(self.root / "no-existe.parquet")
        for args, words in (
            (["--recipe", "nope"], ("nope", "name")),
            (["--recipe", "ir_wv", "--recipe-version", "9"], ("ir_wv", "version", "9")),
        ):
            with self.subTest(args=args), self.assertRaises(SystemExit) as cm:
                compose_rgb.main(["--start", "2019-05-30", "--cells", missing, *args])
            for w in words:
                self.assertIn(w, str(cm.exception.code))

    def test_lower_not_below_upper_is_rejected(self) -> None:
        """Un canal con límite inferior ≥ superior invalida la receta, nombrando receta y campo."""
        for lower, upper in ((300.0, 200.0), (250.0, 250.0)):
            bad = rgb.Recipe(
                "bad",
                1,
                (
                    rgb.Channel("C13", lower, upper, 0),
                    rgb.Channel("C08", 193.15, 263.15, 0),
                    rgb.Channel("C08-C13", -80.0, 10.0, 0),
                ),
            )
            with self.subTest(lower=lower, upper=upper), self.assertRaises(ValueError) as cm:
                rgb.validate_recipe("bad", 1, {("bad", 1): bad})
            self.assertIn("bad", str(cm.exception))
            self.assertIn("lower_k", str(cm.exception))

    def test_missing_band_is_skipped(self) -> None:
        """Sin C10/C12 la receta ``airmass`` omite la Celda_Hora y registra la banda."""
        self.write_goes(("C08", "C13"))
        man, skp = self.compose(cells(A), rgb.RECIPES[("airmass", 1)])
        self.assertEqual(len(man), 0)
        self.assertEqual(skp["cell_id"].tolist(), [A[0]])
        self.assertIn("C10", skp["reason"].iloc[0])
        self.assertIn("C12", skp["reason"].iloc[0])
        out_dir = self.out / REGION / "rgb" / "airmass_v1"
        self.assertEqual(list(out_dir.rglob("*.png")), [])
        self.assertTrue((out_dir / "skipped.parquet").exists())

    def test_low_valid_window_is_skipped(self) -> None:
        """Una ventana con < 50 % de C13 válidos se omite y las demás siguen."""
        self.write_goes(hole=True)
        man, skp = self.compose(cells(A, B), rgb.RECIPES[("ir_wv", 1)])
        self.assertEqual(man["cell_id"].tolist(), [A[0]])
        self.assertEqual(skp["cell_id"].tolist(), [B[0]])
        self.assertIn("50 %", skp["reason"].iloc[0])
        self.assertIn("C13", skp["reason"].iloc[0])

    def test_manifest_contents(self) -> None:
        """El manifiesto trae los campos del diseño y el sha256 del PNG escrito."""
        self.write_goes()
        man, skp = self.compose(cells(A), rgb.RECIPES[("ir_wv", 1)])
        self.assertEqual(len(skp), 0)
        self.assertEqual(list(man.columns), compose_rgb.MANIFEST_COLUMNS)
        row = man.iloc[0]
        out_dir = self.out / REGION / "rgb" / "ir_wv_v1"
        png = out_dir / row["png_path"]
        self.assertEqual(row["png_path"], f"20190530/{A[0]}.png")
        self.assertEqual(row["sha256"], hashlib.sha256(png.read_bytes()).hexdigest())
        self.assertEqual(row["recipe"], "ir_wv")
        self.assertEqual(row["recipe_version"], 1)
        self.assertEqual(row["scan_start"], pd.Timestamp(H12, tz="UTC"))
        self.assertEqual(row["window_km"], WINDOW_KM)
        self.assertEqual(row["size_px"], 224)
        self.assertGreater(row["scale_px_per_px"], 1.0)
        self.assertEqual(row["missing_frac"], 0.0)
        saved = pd.read_parquet(out_dir / "manifest.parquet")
        self.assertEqual(saved["cell_id"].tolist(), [A[0]])
        # Determinismo: rehacer con --force da el mismo PNG.
        again, _ = self.compose(cells(A), rgb.RECIPES[("ir_wv", 1)], force=True)
        self.assertEqual(again["sha256"].iloc[0], row["sha256"])


if __name__ == "__main__":
    unittest.main()
