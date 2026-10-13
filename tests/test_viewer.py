"""Comprueba que la página descriptiva funciona sin recortes preparados."""

import ast
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import charts, data, p_starter  # noqa: E402


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
        self.assertEqual(len(links), 11)
        self.assertEqual(links, re.findall(r"href='#([\w-]+)'", indices[1]))
        for anchor in links:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, anchors)

    def test_starter_shows_without_data(self) -> None:
        """Starter kit está entre las páginas que ``viewer.py`` muestra aunque no haya recortes."""
        source = (
            Path(__file__).resolve().parents[1] / "scripts" / "viewer" / "viewer.py"
        ).read_text()
        assignment = next(
            n
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NO_DATA_PAGES"
        )
        self.assertIn("starter", ast.literal_eval(assignment.value))

    def test_starter_toc_links_each_section(self) -> None:
        """Starter kit se dibuja y su índice enlaza todas sus secciones, con anclas que existen."""
        # Una navegación mínima con Starter kit por defecto: AppTest no cambia a páginas que son funciones.
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from viewer_app import p_case, p_data, p_project, p_references, p_starter\n"
            "pages = {'project': st.Page(p_project.page, title='Problema'),\n"
            "         'data': st.Page(p_data.page, title='Datos', url_path='datos'),\n"
            "         'case': st.Page(p_case.page, title='Caso', url_path='caso'),\n"
            "         'starter': st.Page(p_starter.page, title='Starter kit', url_path='starter-kit'),\n"
            "         'references': st.Page(p_references.page, title='Referencias', url_path='referencias')}\n"
            "st.session_state['pages'] = pages\n"
            "st.navigation([pages['starter'], pages['project'], pages['data'], pages['case']]).run()\n"
        )
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Starter kit")
        anchors = {h.proto.anchor for h in [*app.title, *app.header]} - {""}
        toc = next(m.value for m in app.markdown if "class='toc'" in m.value)
        links = re.findall(r"href='#([\w-]+)'", toc)
        self.assertEqual(links, [anchor for anchor, _ in p_starter.SECTIONS])
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
