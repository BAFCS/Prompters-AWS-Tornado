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

from viewer_app import colorscales, components, layers, products, state, theme  # noqa: E402


def _luminance(color: str) -> float:
    """Luminancia relativa WCAG de un color ``#RRGGBB``."""
    c = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    """Razón de contraste WCAG entre dos colores."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ColorscalesTest(unittest.TestCase):
    """Verifica que cada tipo de dato tenga escalas estándar válidas y una predeterminada apta."""

    def test_colorscales_exist_in_plotly(self) -> None:
        """Todo nombre de escala debe resolverse en plotly (con o sin ``_r``)."""
        for kind, ops in colorscales.KINDS.items():
            for e in ops:
                with self.subTest(kind=kind, colorscale=e.name):
                    self.assertTrue(pc.get_colorscale(e.name.removesuffix("_r")))

    def test_default_is_colorblind_safe(self) -> None:
        """La primera escala de cada tipo debe leerse con daltonismo."""
        for kind, ops in colorscales.KINDS.items():
            with self.subTest(kind=kind):
                self.assertTrue(ops[0].colorblind_safe)

    def test_invalid_name_falls_back_to_default(self) -> None:
        """Una escala de otro tipo (p. ej. al cambiar el producto del panel) no debe usarse."""
        self.assertEqual(colorscales.pick("diverging", "Viridis").name, "PuOr")
        self.assertEqual(colorscales.pick("sequential", None).name, "Viridis")
        self.assertEqual(colorscales.pick("sequential", "Cividis").name, "Cividis")

    def test_product_kind(self) -> None:
        """El tipo de dato sale del producto: signo, banda GOES o RGB."""
        cases = {
            "idx:srh_01": "diverging", "idx:vgp_01": "sequential", "goes:C02": "visible",
            "goes:C13": "infrared", "goes:dT": "diverging", "goes:C08-C13": "sequential",
            "rgb:airmass": None,
        }  # fmt: skip
        for key, kind in cases.items():
            with self.subTest(key=key):
                self.assertEqual(products.Product(key, "", "", "").kind, kind)

    def test_layer_uses_and_changes_its_colorscale(self) -> None:
        """Una capa toma la escala de su tipo y acepta solo escalas de ese tipo."""
        z = np.zeros((2, 2))
        c = layers.Layer(z, np.array([0.0, 1.0]), np.array([0.0, 1.0]), "t", kind="infrared")
        self.assertEqual(c.colorscale, "Greys")
        self.assertEqual(c.with_colorscale("Cividis_r").colorscale, "Cividis_r")
        self.assertEqual(c.with_colorscale("PuOr").colorscale, "Greys")

    def test_infrared_paints_cold_tops_white(self) -> None:
        """Toda escala infrarroja empieza clara: los topes fríos (valores bajos) se ven blancos."""
        for e in colorscales.KINDS["infrared"]:
            first, last = pc.get_colorscale(e.name)[0][1], pc.get_colorscale(e.name)[-1][1]
            rgb = [
                pc.unlabel_rgb(pc.convert_colors_to_same_type(c, "rgb")[0][0])
                for c in (first, last)
            ]
            hex_colors = ["#{:02X}{:02X}{:02X}".format(*map(round, c)) for c in rgb]
            with self.subTest(colorscale=e.name):
                self.assertGreater(_luminance(hex_colors[0]), _luminance(hex_colors[1]))

    def test_panel_from_previous_session_gets_colorscale(self) -> None:
        """Un panel guardado antes de existir ``colorscale`` se lee como ``Panel`` actual sin escala."""
        old = SimpleNamespace(id=3, key="goes:C13", level=None, contour=None)
        with patch.object(state.st, "session_state", {"panels": [old]}):
            ps = state.panels()
        self.assertEqual(ps, [state.Panel(3, "goes:C13")])


class PalettesTest(unittest.TestCase):
    """Verifica el contraste de los textos en los dos temas."""

    def test_texts_meet_aa(self) -> None:
        """Tinta, entradilla, notas y acción deben alcanzar 4,5:1 sobre el fondo y sobre la hoja."""
        for name, p in (("light", theme.LIGHT), ("dark", theme.DARK)):
            for field in ("INK", "INK_2", "MUTED", "ACCENT"):
                for background in (p.GROUND, p.SURFACE):
                    with self.subTest(theme=name, field=field, background=background):
                        self.assertGreaterEqual(_contrast(getattr(p, field), background), 4.5)
            with self.subTest(theme=name, field="ON_ACCENT"):
                self.assertGreaterEqual(_contrast(p.ON_ACCENT, p.ACCENT), 4.5)
            with self.subTest(theme=name, field="SEVERE_SOFT"):
                self.assertGreaterEqual(_contrast(p.INK, p.SEVERE_SOFT), 4.5)

    def test_css_pairs_meet_aa(self) -> None:
        """Los pares de texto y fondo que usa el CSS, además de fondo y hoja, alcanzan 4,5:1."""
        for name, p in (("light", theme.LIGHT), ("dark", theme.DARK)):
            pairs = {
                "píldora apagada": (p.MUTED, p.SURFACE_2),
                "selección de texto": (p.INK, p.ACCENT_SOFT),
                "acción en la barra": (p.ACCENT, p.SIDEBAR),
                "nota en la barra": (p.MUTED, p.SIDEBAR),
                "tinta en la barra": (p.INK, p.SIDEBAR),
            }
            for pair, (text, background) in pairs.items():
                with self.subTest(theme=name, pair=pair):
                    self.assertGreaterEqual(_contrast(text, background), 4.5)

    def test_categorical_series_stand_out_from_sheet(self) -> None:
        """Las líneas de color alcanzan 3:1 sobre la hoja (WCAG 1.4.11, elementos gráficos)."""
        for name, p in (("light", theme.LIGHT), ("dark", theme.DARK)):
            for field in ("COLD", "WARM", "SELECTION", "SEVERE"):
                with self.subTest(theme=name, field=field):
                    self.assertGreaterEqual(_contrast(getattr(p, field), p.SURFACE), 3.0)

    def test_config_matches_palette(self) -> None:
        """Los colores de ``.streamlit/config.toml`` son los de ``theme.py`` en los dos modos."""
        with (Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").open("rb") as f:
            cfg = tomllib.load(f)["theme"]
        for mode, p in (("light", theme.LIGHT), ("dark", theme.DARK)):
            t = cfg[mode]
            with self.subTest(mode=mode):
                self.assertEqual(t["backgroundColor"], p.SURFACE)
                self.assertEqual(t["secondaryBackgroundColor"], p.SURFACE_2)
                self.assertEqual(t["textColor"], p.INK)
                self.assertEqual(t["primaryColor"], p.ACCENT)
                self.assertEqual(t["borderColor"], p.LINE)
                self.assertEqual(t["grayColor"], p.MUTED)
                self.assertEqual(t["redColor"], p.SEVERE)
                self.assertEqual(t["redTextColor"], p.INK)  # el rojo nunca escribe
                self.assertEqual(t["orangeTextColor"], p.INK)
                self.assertEqual(t["linkColor"], p.ACCENT)
                self.assertEqual(t["greenColor"], p.ACCENT)
                self.assertEqual(t["blueColor"], p.SELECTION)
                self.assertEqual(t["sidebar"]["backgroundColor"], p.SIDEBAR)
                self.assertEqual(t["sidebar"]["secondaryBackgroundColor"], p.SURFACE)
                self.assertEqual(
                    t["chartCategoricalColors"],
                    [p.SELECTION, p.INK, p.WARM, p.COLD, p.MUTED, p.SEVERE],
                )

    def test_css_defines_every_variable(self) -> None:
        """El CSS define cada color de la paleta en los dos modos."""
        css = theme.css()
        for f in fields(theme.Palette):
            with self.subTest(field=f.name):
                self.assertEqual(css.count(theme._var_name(f.name) + ":"), 2)


class CoordinatesTest(unittest.TestCase):
    """Verifica la regla de la coma en las coordenadas."""

    def test_decimal_comma_and_minus_sign(self) -> None:
        """Las coordenadas usan coma decimal y el signo menos tipográfico."""
        self.assertEqual(components.coord(-36.731, -71.806), "−36,73°, −71,81°")


if __name__ == "__main__":
    unittest.main()
