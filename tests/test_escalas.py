"""Comprueba las escalas estándar de los mapas, las paletas de los temas y el formato de coordenadas."""

import sys
import tomllib
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import plotly.colors as pc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from visor_app import capas, componentes, escalas, estado, productos, tema  # noqa: E402


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

    def test_infrarrojo_pinta_frios_en_blanco(self) -> None:
        """Toda escala infrarroja empieza clara: los topes fríos (valores bajos) se ven blancos."""
        for e in escalas.opciones("infrarrojo"):
            primero, ultimo = pc.get_colorscale(e.nombre)[0][1], pc.get_colorscale(e.nombre)[-1][1]
            rgb = [
                pc.unlabel_rgb(pc.convert_colors_to_same_type(c, "rgb")[0][0])
                for c in (primero, ultimo)
            ]
            hexa = ["#{:02X}{:02X}{:02X}".format(*map(round, c)) for c in rgb]
            with self.subTest(escala=e.nombre):
                self.assertGreater(_luminancia(hexa[0]), _luminancia(hexa[1]))

    def test_panel_de_sesion_anterior_toma_escala(self) -> None:
        """Un panel guardado antes de existir ``escala`` se lee como ``Panel`` actual sin escala."""
        viejo = SimpleNamespace(id=3, clave="goes:C13", nivel=None, contorno=None)
        with patch.object(estado.st, "session_state", {"paneles": [viejo]}):
            ps = estado.paneles()
        self.assertEqual(ps, [estado.Panel(3, "goes:C13")])


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

    def test_pares_del_css_cumplen_aa(self) -> None:
        """Los pares de texto y fondo que usa el CSS, además de fondo y hoja, alcanzan 4,5:1."""
        for nombre, p in (("claro", tema.CLARA), ("oscuro", tema.OSCURA)):
            pares = {
                "píldora apagada": (p.MUTED, p.SURFACE_2),
                "selección de texto": (p.INK, p.ACCENT_SOFT),
                "acción en la barra": (p.ACCENT, p.BARRA),
                "nota en la barra": (p.MUTED, p.BARRA),
                "tinta en la barra": (p.INK, p.BARRA),
            }
            for par, (texto, fondo) in pares.items():
                with self.subTest(tema=nombre, par=par):
                    self.assertGreaterEqual(_contraste(texto, fondo), 4.5)

    def test_series_categoricas_se_distinguen_de_la_hoja(self) -> None:
        """Las líneas de color alcanzan 3:1 sobre la hoja (WCAG 1.4.11, elementos gráficos)."""
        for nombre, p in (("claro", tema.CLARA), ("oscuro", tema.OSCURA)):
            for campo in ("COLD", "WARM", "SELECCION", "SEVERE"):
                with self.subTest(tema=nombre, campo=campo):
                    self.assertGreaterEqual(_contraste(getattr(p, campo), p.SURFACE), 3.0)

    def test_config_coincide_con_la_paleta(self) -> None:
        """Los colores de ``.streamlit/config.toml`` son los de ``tema.py`` en los dos modos."""
        with (Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").open("rb") as f:
            cfg = tomllib.load(f)["theme"]
        for modo, p in (("light", tema.CLARA), ("dark", tema.OSCURA)):
            t = cfg[modo]
            with self.subTest(modo=modo):
                self.assertEqual(t["backgroundColor"], p.SURFACE)
                self.assertEqual(t["secondaryBackgroundColor"], p.SURFACE_2)
                self.assertEqual(t["textColor"], p.INK)
                self.assertEqual(t["primaryColor"], p.ACCENT)
                self.assertEqual(t["borderColor"], p.LINE)
                self.assertEqual(t["grayColor"], p.MUTED)
                self.assertEqual(t["redColor"], p.SEVERE)
                self.assertEqual(t["redTextColor"], p.INK)  # el rojo nunca escribe
                self.assertEqual(t["sidebar"]["backgroundColor"], p.BARRA)
                self.assertIn(p.WARM, t["chartCategoricalColors"])

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
