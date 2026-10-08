"""Regresiones de selección accesible, comparación angosta y salida del recorrido."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import common  # noqa: E402
from viewer_app import charts, layers, p_data, p_project, state, variables  # noqa: E402


class ExplorationTest(unittest.TestCase):
    """Comprueba los contratos compartidos de la exploración."""

    def test_narrow_grid_keeps_all_panels_and_shared_zoom(self) -> None:
        """Un ancho angosto conserva seis mapas, cada uno con todo el eje horizontal."""
        layer = layers.Layer(np.ones((2, 2)), np.array([-36, -37]), np.array([-73, -72]), "Prueba")
        fig, backgrounds = charts.grid(
            [layer] * 6,
            [None] * 6,
            charts.Extent(-35, -39, -75, -70),
            ([], []),
            columns=1,
            narrow=True,
        )
        self.assertEqual(len(backgrounds), 6)
        self.assertEqual(tuple(fig.layout.xaxis.domain), (0, 1))
        self.assertEqual(tuple(fig.layout.xaxis6.domain), (0, 1))
        self.assertEqual(fig.layout.xaxis6.matches, "x")

    def test_invalid_coordinates_do_not_replace_the_point(self) -> None:
        """Las coordenadas inválidas se rechazan sin perder el punto anterior."""
        previous = state.Point(-37, -73, "Anterior")
        session = {"point": previous}
        with patch.object(state.st, "session_state", session):
            for lat, lon in [(float("nan"), -73), (-37, float("inf")), (91, -73), (-37, -181)]:
                with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                    state.select_point(state.Point(lat, lon, "Inválido"))
                self.assertEqual(state.point(), previous)
            state.select_point(state.Point(-36.5, -72.5, "Coordenadas"))
            self.assertEqual(state.point().lat, -36.5)

    def test_point_must_fall_inside_the_region(self) -> None:
        """Con región, un punto fuera de ella se rechaza y conserva el anterior."""
        reg = common.REGIONS["south-central"]
        previous = state.Point(-37, -73, "Anterior")
        with patch.object(state.st, "session_state", {"point": previous}):
            with self.assertRaises(ValueError):
                state.select_point(state.Point(-50, -73, "Fuera"), reg)
            self.assertEqual(state.point(), previous)
            state.select_point(state.Point(-36, -72, "Dentro"), reg)
            self.assertEqual(state.point().lat, -36)

    def test_grid_shape(self) -> None:
        """La grilla respeta columnas disponibles y máximos por cantidad de paneles."""
        cases = {(0, 3): (1, 1), (1, 3): (1, 1), (4, 3): (2, 2), (5, 3): (2, 3),
                 (6, 3): (2, 3), (6, 2): (3, 2), (6, 1): (6, 1)}  # fmt: skip
        for (n, columns), expected in cases.items():
            with self.subTest(n=n, columns=columns):
                self.assertEqual(charts.grid_shape(n, columns=columns), expected)

    def test_every_image_publishes_a_description(self) -> None:
        """Cada imagen emite el marcador que el vigía usa para su texto alternativo."""
        with patch.object(p_project, "st") as st_mock:
            p_project._image("<svg/>", 'Dice "algo" <b>')
        html_arg = st_mock.html.call_args.args[0]
        self.assertIn('class="project-image-alt"', html_arg)
        self.assertIn("data-description=", html_arg)
        self.assertIn(
            st_mock.container.call_args.kwargs["key"], {"image_cape", "image_mesocyclone"}
        )

    def test_datos_heading_level_follows_context(self) -> None:
        """Una ficha sola o un resultado de búsqueda no saltan niveles bajo el título H1."""
        for level in (2, 3, 4):
            with self.subTest(level=level), patch.object(p_data, "st") as st_mock:
                p_data._variable(variables.VARIABLES[0], set(), level=level)
            self.assertIn(f"<h{level} class='var-name'", st_mock.markdown.call_args_list[0].args[0])

    def test_leaving_tour_restores_free_exploration(self) -> None:
        """Salir devuelve paneles, punto y hora previos al recorrido."""
        previous = state.Point(-37, -73, "Anterior")
        panels = [state.Panel(4, "goes:C13")]
        session = {
            "panels": panels,
            "point": previous,
            "t_idx": 2,
            "times": [np.datetime64("2019-05-30T20:00")],
        }
        with patch.object(state.st, "session_state", session):
            state.apply_step(dt.date(2019, 5, 30), 0, pd.DataFrame())
            state.set_panels([state.Panel(5, "idx:vgp_01")])
            state.select_point(state.Point(-38, -74, "Recorrido"))
            state.apply_step(dt.date(2019, 5, 30), None, pd.DataFrame())
            self.assertEqual(state.panels(), panels)
            self.assertEqual(state.point(), previous)
            self.assertEqual(session["t_idx"], 2)


if __name__ == "__main__":
    unittest.main()
