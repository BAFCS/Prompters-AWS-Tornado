"""Comprueba el fondo de los paneles de Mapas: PNG precoloreado, orientación y trazas de la grilla."""

import base64
import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from viewer_app import charts, layers  # noqa: E402


def _decode(uri: str) -> np.ndarray:
    """Píxeles RGBA de un PNG en data-URI."""
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))))


class Background(unittest.TestCase):
    """``charts._png`` y ``charts.background``."""

    def test_png_nan_transparent_and_constant(self) -> None:
        """NaN queda transparente y un campo constante (``lo == hi``) no avisa de división por cero."""
        z = np.array([[np.nan, 1.0], [1.0, 1.0]])
        with np.errstate(all="raise"):
            px = _decode(charts._png(z, "Viridis", 1.0, 1.0))
        self.assertEqual(px.shape, (2, 2, 4))
        self.assertEqual(px[0, 0, 3], 0)
        self.assertTrue((px[1, :, 3] == 255).all())

    def test_traces_and_orientation(self) -> None:
        """Campo: imagen, grilla, grilla sin dato y barra; RGB: imagen y grilla; la imagen parte al sur."""
        lat, lon = np.array([-30.0, -30.25, -30.5]), np.array([-72.0, -71.75])
        z = np.array([[1.0, 2.0], [np.nan, 3.0], [4.0, 5.0]])
        field = layers.Layer(z, lat, lon, "campo", kind="sequential", color_range=(0.0, 5.0))
        image, grid, empty, _bar = charts.background(field)
        self.assertEqual(image.y0, -30.5)
        self.assertGreater(image.dy, 0)
        self.assertEqual(len(grid.x), 5)
        self.assertEqual(len(empty.x), 1)
        self.assertEqual(_decode(image.source)[1, 0, 3], 0)
        rgb = layers.Layer(np.zeros((3, 2, 3), np.uint8), lat, lon, "rgb")
        self.assertEqual(len(charts.background(rgb)), 2)


if __name__ == "__main__":
    unittest.main()
