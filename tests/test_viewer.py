"""Comprueba que la página descriptiva funciona sin recortes preparados."""

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import charts, data, variables  # noqa: E402


class ViewerTest(unittest.TestCase):
    """Comprueba el acceso al proyecto con una región todavía vacía."""

    def test_project_shows_with_region_without_days(self) -> None:
        """Un directorio regional vacío no debe bloquear la descripción del proyecto."""
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "scripts" / "viewer" / "viewer.py"
        )
        with (
            patch.object(data, "regions", return_value=["empty-region"]),
            patch.object(data, "days", return_value={}),
        ):
            app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.title), 1)
        self.assertIn("Predicción de tormentas mesociclónicas", app.title[0].value)

    def test_project_without_regions_links_each_section(self) -> None:
        """Sin regiones, la página por defecto es Problema y su índice enlaza anclas que existen."""
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "scripts" / "viewer" / "viewer.py"
        )
        with patch.object(data, "regions", return_value=[]):
            app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(len(app.selectbox), 0)  # sin_datos cortó antes de la barra de región y día
        self.assertIn("Predicción de tormentas mesociclónicas", app.title[0].value)
        anchors = {h.proto.anchor for h in [*app.title, *app.header, *app.subheader]} - {""}
        indices = [m.value for m in app.markdown if "class='toc'" in m.value]
        self.assertEqual(len(indices), 2)  # el lateral y el del desplegable
        links = re.findall(r"href='#([\w-]+)'", indices[0])
        self.assertEqual(len(links), 6)
        self.assertEqual(links, re.findall(r"href='#([\w-]+)'", indices[1]))
        for anchor in links:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, anchors)

    def test_phone_grid_is_one_column(self) -> None:
        """En el teléfono la grilla es de una columna, y la de escritorio sigue alcanzando para todos los paneles."""
        for n in range(1, 7):
            with self.subTest(paneles=n):
                self.assertEqual(charts.grid_shape(n, 1), (n, 1))
                rows, cols = charts.grid_shape(n)
                self.assertGreaterEqual(
                    rows * cols, n
                )  # y la grilla de escritorio sigue alcanzando


if __name__ == "__main__":
    unittest.main()
