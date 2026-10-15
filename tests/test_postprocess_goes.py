"""Comprueba la lógica pura del post-proceso GOES con una grilla sintética, sin red ni datos.

Arma un ``goes_store`` en memoria (una banda ``int16`` en grilla fija del ABI con ``lat``/``lon`` 2D,
varios barridos) y verifica que ``postprocess_goes_store`` reproyecta a lat/lon regular por vecino
más cercano sin inventar valores, agrupa los barridos por hora y conserva la codificación entera.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "pipeline"))

import postprocess_goes_store as pp  # noqa: E402
import process_goes as pg  # noqa: E402

import common  # noqa: E402

SCALE = 0.05
OFFSET = 180.0
FILL = -1


def synthetic_store(n_scan: int, ny: int = 8, nx: int = 6) -> xr.Dataset:
    """Una banda ``C13`` sintética en grilla ABI (``time``, ``y``, ``x``) con ``lat``/``lon`` 2D.

    Los enteros crecen con el índice del píxel para que cada valor sea distinto y rastreable; un
    píxel se marca con ``_FillValue`` para comprobar que se propaga como NaN. ``lat``/``lon`` caen
    dentro de una región chica para que todos los puntos de la grilla regular tengan vecino.
    """
    lat2d, lon2d = np.meshgrid(
        np.linspace(-34.0, -37.0, ny), np.linspace(-73.0, -71.0, nx), indexing="ij"
    )
    raw = np.arange(ny * nx, dtype="int16").reshape(1, ny, nx).repeat(n_scan, axis=0)
    raw = raw.copy()
    raw[:, 0, 0] = FILL  # un píxel sin dato en todos los barridos
    times = np.array(
        [np.datetime64("2019-04-03T00:00:00") + np.timedelta64(10 * k, "m") for k in range(n_scan)]
    )
    da = xr.DataArray(
        raw,
        dims=("time", "y", "x"),
        attrs={"scale_factor": SCALE, "add_offset": OFFSET, "_FillValue": FILL, "units": "K"},
    )
    return xr.Dataset(
        {"C13": da},
        coords={
            "time": times,
            "lat": (("y", "x"), lat2d),
            "lon": (("y", "x"), lon2d),
        },
    )


class PostprocessGoesTest(unittest.TestCase):
    """Verifica reproyección, agrupación horaria y codificación con datos en memoria."""

    def setUp(self) -> None:
        """Región chica, grilla regular de paso grueso y el índice del vecino más cercano."""
        self.reg = common.Region("test", -34.0, -37.0, -73.0, -71.0)
        self.lat, self.lon = pg.grid(self.reg, 0.5)
        self.store = synthetic_store(n_scan=9)
        src = self.store
        self.idx, self.valid = pg.nearest_index(
            src["lat"].values, src["lon"].values, self.lat, self.lon, radius=1.0
        )

    def test_reproject_shape_and_grid(self) -> None:
        """La salida tiene forma (time, latitude, longitude) sobre la grilla regular pedida."""
        out = pp.reproject_scans(
            {"C13": self.store}, ["C13"], self.idx, self.valid, self.lat, self.lon, slice(0, 3)
        )
        self.assertEqual(out["C13"].dims, ("time", "latitude", "longitude"))
        self.assertEqual(out.sizes["time"], 3)
        self.assertEqual(out.sizes["latitude"], len(self.lat))
        self.assertEqual(out.sizes["longitude"], len(self.lon))
        np.testing.assert_array_equal(out["latitude"].values, self.lat)
        np.testing.assert_array_equal(out["longitude"].values, self.lon)

    def test_nearest_neighbor_does_not_invent_values(self) -> None:
        """Cada valor reproyectado existe en el origen decodificado (vecino más cercano puro)."""
        out = pp.reproject_scans(
            {"C13": self.store}, ["C13"], self.idx, self.valid, self.lat, self.lon, slice(0, 1)
        )
        raw = self.store["C13"].values[0]
        # El script decodifica y guarda en float32; se compara en la misma precisión para que la
        # verificación de "no inventa valores" no falle por diferencias en el último decimal.
        src_bt = np.where(raw == FILL, np.nan, raw * SCALE + OFFSET).astype("f4")
        src_values = set(np.round(src_bt[np.isfinite(src_bt)], 4).tolist())
        out_bt = out["C13"].values[0]
        out_values = set(np.round(out_bt[np.isfinite(out_bt)], 4).tolist())
        self.assertTrue(out_values.issubset(src_values))

    def test_fill_propagates_as_nan(self) -> None:
        """El píxel marcado con _FillValue en el origen no produce un valor físico en la salida."""
        out = pp.reproject_scans(
            {"C13": self.store}, ["C13"], self.idx, self.valid, self.lat, self.lon, slice(0, 1)
        )
        bt = out["C13"].values[0]
        # El valor del píxel de relleno (0,0) no debe aparecer como un valor válido inventado.
        self.assertTrue(np.isfinite(bt).any())  # hay datos válidos
        self.assertTrue(np.isnan(bt).any())  # y el relleno quedó como NaN en su vecindad

    def test_group_by_hour(self) -> None:
        """Los 9 barridos de 10 min caen en las horas 0 y 1 en orden ascendente."""
        groups = pp.group_by_hour(self.store["time"].values)
        self.assertEqual(sorted(groups), [0, 1])
        self.assertEqual(groups[0], list(range(6)))  # 6 barridos en la hora 0
        self.assertEqual(groups[1], [6, 7, 8])  # 3 en la hora 1
        all_idx = [k for h in sorted(groups) for k in groups[h]]
        self.assertEqual(all_idx, list(range(9)))  # cada barrido una sola vez

    def test_encoding_preserved(self) -> None:
        """La codificación int16 (escala, desfase, relleno) sale igual que en el origen."""
        enc = pp.encodings({"C13": self.store}, ["C13"])
        self.assertEqual(enc["C13"]["dtype"], "int16")
        self.assertAlmostEqual(enc["C13"]["scale_factor"], SCALE)
        self.assertAlmostEqual(enc["C13"]["add_offset"], OFFSET)
        self.assertEqual(enc["C13"]["_FillValue"], FILL)

    def test_coding_attrs_removed_from_variable(self) -> None:
        """Los atributos de codificación no quedan en los attrs de la variable (irían al encoding)."""
        out = pp.reproject_scans(
            {"C13": self.store}, ["C13"], self.idx, self.valid, self.lat, self.lon, slice(0, 2)
        )
        for key in pp.CODING_ATTRS:
            self.assertNotIn(key, out["C13"].attrs)
        self.assertIn("units", out["C13"].attrs)  # los descriptivos sí se conservan

    def test_store_key_format(self) -> None:
        """La ruta de origen sigue el patrón goes_store/<AAAA-MM-DD>/goes_<AAAAMMDD>_<banda>.nc."""
        key = pp.store_key(dt.date(2019, 4, 3), "C13")
        self.assertTrue(key.endswith("goes_store/2019-04-03/goes_20190403_C13.nc"))


if __name__ == "__main__":
    unittest.main()
