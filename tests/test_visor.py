"""Comprueba que la página descriptiva funciona sin recortes preparados."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from visor_app import datos  # noqa: E402


class VisorTest(unittest.TestCase):
    """Comprueba el acceso al proyecto con una región todavía vacía."""

    def test_proyecto_se_muestra_con_region_sin_dias(self) -> None:
        """Un directorio regional vacío no debe bloquear la descripción del proyecto."""
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / "scripts" / "visor.py")
        with (
            patch.object(datos, "regiones", return_value=["region-vacia"]),
            patch.object(datos, "dias", return_value={}),
        ):
            app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.title), 1)
        self.assertIn("Predicción de tormentas mesociclónicas", app.title[0].value)

    def test_proyecto_se_muestra_sin_regiones(self) -> None:
        """Sin ninguna región descargada, la página por defecto sigue siendo la descripción."""
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / "scripts" / "visor.py")
        with patch.object(datos, "regiones", return_value=[]):
            app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertIn("Predicción de tormentas mesociclónicas", app.title[0].value)


if __name__ == "__main__":
    unittest.main()
