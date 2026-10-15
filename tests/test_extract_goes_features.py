"""Pruebas de la CLI del Extractor_GOES con NetCDF sintéticos en un directorio temporal."""

import contextlib
import datetime as dt
import io
import math
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

import extract_goes_features as egf  # noqa: E402
import synthetic  # noqa: E402

REGION = "test-region"
DAY = dt.date(2019, 5, 30)
H11 = dt.datetime(2019, 5, 30, 11)
H12 = dt.datetime(2019, 5, 30, 12)
H13 = dt.datetime(2019, 5, 30, 13)


def bt13(s: dt.datetime) -> float:
    """BT de C13 que baja 0,5 K por minuto desde las 11:00 (tope que se enfría)."""
    return 280.0 - 0.5 * (s - H11).total_seconds() / 60.0


def bt08(s: dt.datetime) -> float:
    """BT de C08, 10 K por debajo de C13."""
    return bt13(s) - 10.0


def run(crops: Path, out: Path, force: bool = False, day: dt.date = DAY) -> tuple[Path | None, str]:
    """Llama a ``process_day`` y devuelve su resultado y lo impreso."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = egf.process_day(day, REGION, crops, out, 0.25, force)
    return res, buf.getvalue()


class ExtractGoesFeaturesTest(unittest.TestCase):
    """Columnas, avisos, días sin archivos y salto de lo existente."""

    def setUp(self) -> None:
        """Directorio temporal con ``crops/`` y ``model/``."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.crops = self.root / "crops"
        self.out = self.root / "model"

    def tearDown(self) -> None:
        """Borra el directorio temporal."""
        self._tmp.cleanup()

    def write_hours(self, *hours: dt.datetime, bands: tuple[str, ...] = ("C08", "C13")) -> None:
        """Escribe un archivo GOES por hora con seis barridos uniformes."""
        fns = {"C08": bt08, "C13": bt13}
        for h in hours:
            scans, data = synthetic.uniform_scans(h, {b: fns[b] for b in bands})
            synthetic.write_goes_latlon(self.crops, REGION, h, scans, data)

    def test_output_columns_and_values(self) -> None:
        """Una fila por Celda_Hora, barrido en (t − 60, t], tasa de enfriamiento y NaN sin barrido."""
        synthetic.write_era5_indices(self.crops, REGION, DAY, [12, 13, 16])
        self.write_hours(H11)
        # Ventana del punto (−35,25; −71,75) sin datos en el barrido de las 12:00.
        lat, lon = synthetic.goes_grid()
        scans, data = synthetic.uniform_scans(H12, {"C08": bt08, "C13": bt13})
        hole = np.ix_(lat < -35.125, lon > -71.875)
        data["C13"][0][hole] = np.nan
        synthetic.write_goes_latlon(self.crops, REGION, H12, scans, data)

        res, _ = run(self.crops, self.out)
        assert res is not None
        df = pd.read_parquet(res)
        self.assertEqual(list(df.columns), egf.COLUMNS)
        self.assertEqual(len(df), 3 * 2 * 2)
        self.assertEqual(str(df["time"].dtype), "datetime64[ns, UTC]")

        at12 = df[df["time"] == pd.Timestamp(H12, tz="UTC")]
        ok12 = at12[(at12["latitude"] == -35.0)]
        self.assertTrue((ok12["scan_start"] == pd.Timestamp(H12, tz="UTC")).all())
        # Sin futuro: los barridos 12:10–12:50, más fríos, no entran en la hora 12.
        np.testing.assert_allclose(ok12["goes_bt13_min"], bt13(H12), atol=0.01)
        np.testing.assert_allclose(ok12["goes_wv_ir_max"], -10.0, atol=0.01)
        np.testing.assert_allclose(ok12["goes_cold_frac"], 0.0)
        # Par 11:40 → 12:00 (Δt = 20 min): (260 − 250) × 15 / 20 = 7,5 K/15 min.
        np.testing.assert_allclose(ok12["goes_cooling_rate"], 7.5, atol=0.01)

        hole_row = at12[(at12["latitude"] == -35.25) & (at12["longitude"] == -71.75)].iloc[0]
        for c in egf.gf.GOES_FEATURES:
            self.assertTrue(math.isnan(hole_row[c]), c)
        self.assertLess(hole_row["valid_frac_c13"], 0.5)

        at13 = df[df["time"] == pd.Timestamp(H13, tz="UTC")]
        late = pd.Timestamp(H12 + dt.timedelta(minutes=50), tz="UTC")
        self.assertTrue((at13["scan_start"] == late).all())

        at16 = df[df["time"] == pd.Timestamp(dt.datetime(2019, 5, 30, 16), tz="UTC")]
        self.assertEqual(len(at16), 4)
        self.assertTrue(at16["scan_start"].isna().all())
        self.assertTrue(at16[list(egf.gf.GOES_FEATURES)].isna().all().all())

    def test_missing_band_warns_and_continues(self) -> None:
        """Un archivo sin C08 se omite con aviso (archivo y banda) y la hora usa el anterior."""
        synthetic.write_era5_indices(self.crops, REGION, DAY, [13])
        self.write_hours(H12)
        self.write_hours(H13, bands=("C13",))
        res, out = run(self.crops, self.out)
        self.assertIn(f"goes_{H13:%Y%m%d%H}.nc", out)
        self.assertIn("C08", out)
        assert res is not None
        df = pd.read_parquet(res)
        late = pd.Timestamp(H12 + dt.timedelta(minutes=50), tz="UTC")
        self.assertTrue((df["scan_start"] == late).all())

    def test_day_without_files(self) -> None:
        """Un día sin archivos GOES no escribe tabla y avisa con la fecha."""
        other = DAY + dt.timedelta(days=1)
        synthetic.write_era5_indices(self.crops, REGION, other, [12])
        res, out = run(self.crops, self.out, day=other)
        self.assertIsNone(res)
        self.assertIn(str(other), out)
        self.assertFalse((self.out / REGION / "goes_features").exists())

    def test_skip_existing_and_force(self) -> None:
        """Sin ``--force`` se salta la tabla existente; con ``--force`` se rehace."""
        synthetic.write_era5_indices(self.crops, REGION, DAY, [12])
        self.write_hours(H11, H12)
        first, _ = run(self.crops, self.out)
        assert first is not None
        stamp = first.stat().st_mtime_ns
        again, out = run(self.crops, self.out)
        self.assertIsNone(again)
        self.assertIn("ya existe", out)
        self.assertEqual(first.stat().st_mtime_ns, stamp)
        forced, _ = run(self.crops, self.out, force=True)
        self.assertEqual(forced, first)
        self.assertFalse(first.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
