"""Comprueba el catálogo de datos: integridad de las fichas, cobertura de los productos y la página."""

import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import procesa_era5  # noqa: E402

from visor_app import productos, variables  # noqa: E402


def _pagina() -> None:
    """La página Datos sola, sin barra lateral ni datos."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path.cwd() / "scripts"))
    from visor_app import p_datos

    p_datos.pagina()


class FichasTest(unittest.TestCase):
    """Las fichas se refieren entre sí y a la bibliografía sin cabos sueltos."""

    def test_claves_unicas_y_referencias_validas(self) -> None:
        """Claves únicas; insumos, grupos y referencias que existen; toda ficha cita una fuente."""
        claves = [v.clave for v in variables.VARIABLES]
        self.assertEqual(len(claves), len(set(claves)))
        grupos = {g.clave for g in variables.GRUPOS}
        for v in variables.VARIABLES:
            with self.subTest(ficha=v.clave):
                self.assertIn(v.grupo, grupos)
                self.assertTrue(set(v.insumos) <= set(variables.POR_CLAVE))
                self.assertNotIn(v.clave, v.insumos)
                fuentes = variables.fuentes(v)
                self.assertTrue(fuentes)
                self.assertTrue(set(fuentes) <= set(variables.REFERENCIAS))

    def test_todo_producto_del_visor_tiene_ficha(self) -> None:
        """Cada índice, banda y derivado que puede mostrar Mapas tiene su ficha (la ayuda sale de ahí)."""
        esperados = {f"idx:{k}" for k in procesa_era5.ATRIBUTOS if k not in productos.OCULTOS}
        esperados |= {f"goes:C{b:02d}" for b in range(1, 17)}
        esperados |= set(productos.DERIVADOS) | set(productos.FAVORITOS)
        self.assertEqual(esperados - set(variables.POR_PRODUCTO), set())

    def test_buscador_ignora_tildes_y_mayusculas(self) -> None:
        """«HELICIDAD» y «helicidad» encuentran lo mismo, y la SRH está entre los resultados."""
        self.assertEqual(variables.busca("HELICIDAD"), variables.busca("helicidad"))
        self.assertIn(variables.POR_CLAVE["srh_01"], variables.busca("helicidad"))
        self.assertEqual(variables.busca("zzzz"), [])


class PaginaTest(unittest.TestCase):
    """La página Datos se dibuja sin datos, con una ficha sola o con una búsqueda sin resultados."""

    def _app(self) -> AppTest:
        """La página sola, desde la raíz del repo."""
        return AppTest.from_function(_pagina)

    def test_sin_datos_muestra_todas_las_fichas(self) -> None:
        """Sin datos se ven las fichas y la bibliografía, sin botones «Ver en Mapas»."""
        app = self._app()
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        nombres = [m for m in app.markdown if "class='ficha-nombre'" in m.value]
        self.assertEqual(len(nombres), len(variables.VARIABLES))
        self.assertFalse([b for b in app.button if b.label == "Ver en Mapas"])
        self.assertIn("referencias", {h.proto.anchor for h in app.header})

    def test_url_con_v_muestra_una_ficha(self) -> None:
        """``?v=vgp_01`` deja solo esa ficha, con su criterio chileno y la vuelta a todas."""
        app = self._app()
        app.query_params["v"] = "vgp_01"
        app.run(timeout=30)
        nombres = [m.value for m in app.markdown if "class='ficha-nombre'" in m.value]
        self.assertEqual(len(nombres), 1)
        self.assertIn("vorticidad", nombres[0])
        self.assertTrue(any("Criterio en Chile" in m.value for m in app.markdown))
        self.assertTrue(any(b.label == "Ver todas las variables" for b in app.button))

    def test_busqueda_sin_resultados_ofrece_borrarla(self) -> None:
        """Una búsqueda sin coincidencias lo dice y ofrece borrarla."""
        app = self._app()
        app.run(timeout=30)
        app.text_input(key="datos_busca").input("zzzz").run(timeout=30)
        self.assertEqual(len(app.info), 1)
        self.assertTrue(any(b.label == "Borrar la búsqueda" for b in app.button))


if __name__ == "__main__":
    unittest.main()
