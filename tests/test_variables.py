"""Comprueba el catálogo de datos: integridad de las fichas, cobertura de los productos y la página."""

import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import process_era5  # noqa: E402

from viewer_app import products, variables  # noqa: E402


def _page() -> None:
    """La página Datos sola, sin barra lateral ni datos."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path.cwd() / "scripts"))
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

    def test_every_viewer_product_has_a_variable(self) -> None:
        """Cada índice, banda y derivado que puede mostrar Mapas tiene su ficha (la ayuda sale de ahí)."""
        expected = {f"idx:{k}" for k in process_era5.ATTRIBUTES if k not in products.HIDDEN}
        expected |= {f"goes:C{b:02d}" for b in range(1, 17)}
        expected |= set(products.DERIVED) | set(products.FAVORITES)
        self.assertEqual(expected - set(variables.BY_PRODUCT), set())

    def test_search_ignores_accents_and_case(self) -> None:
        """«HELICIDAD» y «helicidad» encuentran lo mismo, y la SRH está entre los resultados."""
        self.assertEqual(variables.search("HELICIDAD"), variables.search("helicidad"))
        self.assertIn(variables.BY_KEY["srh_01"], variables.search("helicidad"))
        self.assertEqual(variables.search("zzzz"), [])


class PageTest(unittest.TestCase):
    """La página Datos se dibuja sin datos, con una ficha sola o con una búsqueda sin resultados."""

    def test_without_data_shows_every_variable(self) -> None:
        """Sin datos se ven las fichas y la bibliografía, sin botones «Ver en Mapas»."""
        app = AppTest.from_function(_page)
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        names = [m for m in app.markdown if "class='var-name'" in m.value]
        self.assertEqual(len(names), len(variables.VARIABLES))
        self.assertFalse([b for b in app.button if b.label == "Ver en Mapas"])
        self.assertIn("referencias", {h.proto.anchor for h in app.header})

    def test_v_query_shows_one_variable(self) -> None:
        """``?v=vgp_01`` deja solo esa ficha, con su criterio chileno y la vuelta a todas."""
        app = AppTest.from_function(_page)
        app.query_params["v"] = "vgp_01"
        app.run(timeout=30)
        names = [m.value for m in app.markdown if "class='var-name'" in m.value]
        self.assertEqual(len(names), 1)
        self.assertIn("vorticidad", names[0])
        self.assertTrue(any("Criterio en Chile" in m.value for m in app.markdown))
        self.assertTrue(any(b.label == "Ver todas las variables" for b in app.button))

    def test_empty_search_offers_to_clear_it(self) -> None:
        """Una búsqueda sin coincidencias lo dice y ofrece borrarla."""
        app = AppTest.from_function(_page)
        app.run(timeout=30)
        app.text_input(key="data_search").input("zzzz").run(timeout=30)
        self.assertEqual(len(app.info), 1)
        self.assertTrue(any(b.label == "Borrar la búsqueda" for b in app.button))


if __name__ == "__main__":
    unittest.main()
