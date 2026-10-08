"""Regresiones de selección accesible, comparación angosta y salida del recorrido."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from viewer_app import charts, layers, state  # noqa: E402


class ExplorationTest(unittest.TestCase):
    """Comprueba los contratos compartidos de la exploración."""

    def test_narrow_grid_keeps_all_panels_and_shared_zoom(self) -> None:
        """Un ancho angosto conserva seis mapas, cada uno con todo el eje horizontal."""
        layer = layers.Layer(np.ones((2, 2)), np.array([-36, -37]), np.array([-73, -72]), "Prueba")
        fig, backgrounds = charts.grid(
            [layer] * 6, [None] * 6, charts.Extent(-35, -39, -75, -70), ([], []), columns=1
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
