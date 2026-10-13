"""Comprueba el catálogo de datos: integridad de las fichas, cobertura de los productos y la página."""

import re
import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "pipeline"))

import download_era5  # noqa: E402
import process_era5  # noqa: E402

from viewer_app import p_starter, products, variables  # noqa: E402


def _page() -> None:
    """La página Datos sola, sin barra lateral ni datos."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path.cwd() / "scripts"))
    sys.path.insert(0, str(Path.cwd() / "scripts" / "viewer"))
    from viewer_app import p_data

    p_data.page()


class VariablesTest(unittest.TestCase):
    """Las fichas se refieren entre sí y a la bibliografía sin cabos sueltos."""

    def test_unique_keys_and_valid_references(self) -> None:
        """Claves únicas; insumos, grupos y referencias que existen; toda ficha cita una fuente."""
        keys = [v.key for v in variables.VARIABLES]
        self.assertEqual(len(keys), len(set(keys)))
        groups = {g.key for g in variables.GROUPS}
        for v in variables.VARIABLES:
            with self.subTest(variable=v.key):
                self.assertIn(v.group, groups)
                self.assertTrue(set(v.inputs) <= set(variables.BY_KEY))
                self.assertNotIn(v.key, v.inputs)
                refs = variables.references_of(v)
                self.assertTrue(refs)
                self.assertTrue(set(refs) <= set(variables.REFERENCES))

    def test_starter_related_references_exist(self) -> None:
        """Los trabajos relacionados de Starter kit salen de la bibliografía compartida."""
        for title, keys in p_starter.RELATED:
            with self.subTest(group=title):
                self.assertTrue(set(keys) <= set(variables.REFERENCES))

    def test_every_viewer_product_has_a_variable(self) -> None:
        """Cada índice, banda y derivado que puede mostrar Mapas tiene su ficha (la ayuda sale de ahí)."""
        expected = {f"idx:{k}" for k in process_era5.ATTRIBUTES if k not in products.HIDDEN}
        expected |= {f"goes:C{b:02d}" for b in range(1, 17)}
        expected |= set(products.DERIVED) | set(products.FAVORITES)
        expected |= {f"pl:{v}" for v in download_era5.PL_DEFAULT}
        expected |= {f"sfc:{v}" for v in download_era5.SFC_DEFAULT}
        self.assertEqual(expected - set(variables.BY_PRODUCT), set())

    def test_html_text_has_no_bold(self) -> None:
        """``p_data._md_html`` solo entiende cursivas: rasgos y referencias no llevan ``**``."""
        texts = [v for s in variables.SOURCES for _, v in s.facts]
        texts += [r.full for r in variables.REFERENCES.values()]
        for t in texts:
            with self.subTest(texto=t[:40]):
                self.assertNotIn("**", t)
                self.assertEqual(t.count("*") % 2, 0)


class PageTest(unittest.TestCase):
    """La página Datos se dibuja sin datos y con ``?v=`` apuntando a una ficha."""

    def test_without_data_shows_every_variable(self) -> None:
        """Sin datos se ven las fichas y la bibliografía, sin botones «Ver en Mapas»."""
        app = AppTest.from_function(_page)
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        names = [m for m in app.markdown if "class='var-name'" in m.value]
        self.assertEqual(len(names), len(variables.VARIABLES))
        self.assertFalse([b for b in app.button if b.label == "Ver en Mapas"])
        self.assertIn("referencias", {h.proto.anchor for h in app.header})

    def test_toc_links_existing_anchors(self) -> None:
        """Con la lista completa, cada enlace del índice lleva a un encabezado o una ficha que existe."""
        app = AppTest.from_function(_page)
        app.run(timeout=30)
        anchors = {h.proto.anchor for h in [*app.title, *app.header, *app.subheader]} - {""}
        tocs = [m.value for m in app.markdown if "class='toc'" in m.value]
        self.assertEqual(len(tocs), 2)  # el lateral y el del desplegable
        links = re.findall(r"href='#([\w-]+)'", tocs[0])
        self.assertTrue(links)
        for a in links:
            with self.subTest(ancla=a):
                self.assertIn(a, anchors)

    def test_index_links_every_variable(self) -> None:
        """El índice con botones trae un enlace por variable, hacia su ficha."""
        app = AppTest.from_function(_page)
        app.run(timeout=30)
        html = "".join(m.value for m in app.markdown if "class='var-table'" in m.value)
        self.assertEqual(len(re.findall(r"href='#", html)), len(variables.VARIABLES))

    def test_v_query_keeps_every_variable(self) -> None:
        """``?v=vgp_01`` no descarta fichas: se dibujan todas y la página se desplaza a esa."""
        app = AppTest.from_function(_page)
        app.query_params["v"] = "vgp_01"
        app.run(timeout=30)
        names = [m.value for m in app.markdown if "class='var-name'" in m.value]
        self.assertEqual(len(names), len(variables.VARIABLES))
        self.assertTrue(any("id='vgp_01'" in n for n in names))


if __name__ == "__main__":
    unittest.main()
