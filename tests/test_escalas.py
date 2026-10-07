"""Comprueba las escalas estándar de los mapas, las paletas de los temas y el formato de coordenadas."""

import sys
import unittest
from dataclasses import fields
from pathlib import Path

import numpy as np
import plotly.colors as pc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from visor_app import capas, componentes, escalas, productos, tema  # noqa: E402


def _luminancia(color: str) -> float:
    """Luminancia relativa WCAG de un color ``#RRGGBB``."""
    c = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contraste(a: str, b: str) -> float:
    """Razón de contraste WCAG entre dos colores."""
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class EscalasTest(unittest.TestCase):
    """Verifica que cada tipo de dato tenga escalas estándar válidas y una predeterminada apta."""

    def test_escalas_existen_en_plotly(self) -> None:
        """Todo nombre de escala debe resolverse en plotly (con o sin ``_r``)."""
        for tipo, ops in escalas.TIPOS.items():
            for e in ops:
                with self.subTest(tipo=tipo, escala=e.nombre):
                    self.assertTrue(pc.get_colorscale(e.nombre.removesuffix("_r")))

    def test_predeterminada_apta_para_daltonismo(self) -> None:
        """La primera escala de cada tipo debe leerse con daltonismo."""
        for tipo, ops in escalas.TIPOS.items():
            with self.subTest(tipo=tipo):
                self.assertTrue(ops[0].daltonismo)

    def test_nombre_invalido_vuelve_a_la_predeterminada(self) -> None:
        """Una escala de otro tipo (p. ej. al cambiar el producto del panel) no debe usarse."""
        self.assertEqual(escalas.elige("divergente", "Viridis").nombre, "PuOr")
        self.assertEqual(escalas.elige("secuencial", None).nombre, "Viridis")
        self.assertEqual(escalas.elige("secuencial", "Cividis").nombre, "Cividis")

    def test_tipo_de_producto(self) -> None:
        """El tipo de dato sale del producto: signo, banda GOES o RGB."""
        casos = {
            "idx:srh_01": "divergente", "idx:vgp_01": "secuencial", "goes:C02": "visible",
            "goes:C13": "infrarrojo", "goes:dT": "divergente", "goes:C08-C13": "secuencial",
            "rgb:airmass": None,
        }  # fmt: skip
        for clave, tipo in casos.items():
            with self.subTest(clave=clave):
                self.assertEqual(productos.Producto(clave, "", "", "").tipo, tipo)

    def test_capa_usa_y_cambia_su_escala(self) -> None:
        """Una capa toma la escala de su tipo y acepta solo escalas de ese tipo."""
        z = np.zeros((2, 2))
        c = capas.Capa(z, np.array([0.0, 1.0]), np.array([0.0, 1.0]), "t", tipo="infrarrojo")
        self.assertEqual(c.escala, "Greys")
        self.assertEqual(c.con_escala("Cividis_r").escala, "Cividis_r")
        self.assertEqual(c.con_escala("PuOr").escala, "Greys")


class PaletasTest(unittest.TestCase):
    """Verifica el contraste de los textos en los dos temas."""

    def test_textos_cumplen_aa(self) -> None:
        """Tinta, entradilla, notas y acción deben alcanzar 4,5:1 sobre el fondo y sobre la hoja."""
        for nombre, p in (("claro", tema.CLARA), ("oscuro", tema.OSCURA)):
            for campo in ("INK", "INK_2", "MUTED", "ACCENT"):
                for fondo in (p.GROUND, p.SURFACE):
                    with self.subTest(tema=nombre, campo=campo, fondo=fondo):
                        self.assertGreaterEqual(_contraste(getattr(p, campo), fondo), 4.5)
            with self.subTest(tema=nombre, campo="SOBRE_ACCENT"):
                self.assertGreaterEqual(_contraste(p.SOBRE_ACCENT, p.ACCENT), 4.5)
            with self.subTest(tema=nombre, campo="SEVERE_SOFT"):
                self.assertGreaterEqual(_contraste(p.INK, p.SEVERE_SOFT), 4.5)

    def test_css_define_todas_las_variables(self) -> None:
        """El CSS define cada color de la paleta en los dos modos."""
        css = tema.css()
        for f in fields(tema.Paleta):
            with self.subTest(campo=f.name):
                self.assertEqual(css.count(tema._nombre_var(f.name) + ":"), 2)


class CoordenadasTest(unittest.TestCase):
    """Verifica la regla de la coma en las coordenadas."""

    def test_coma_decimal_y_signo_menos(self) -> None:
        """Las coordenadas usan coma decimal y el signo menos tipográfico."""
        self.assertEqual(componentes.coord(-36.731, -71.806), "−36,73°, −71,81°")


if __name__ == "__main__":
    unittest.main()
