"""Comprueba que la ficha distingue ausencia de datos y comparación de índices."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from visor_app import componentes  # noqa: E402


class FichaTest(unittest.TestCase):
    """Verifica los resultados visibles con valores y referencias controlados."""

    def test_ausencia_de_datos_no_es_incumplimiento(self) -> None:
        """Un valor ausente no debe presentarse como resultado de una comparación."""
        for valor in (None, float("nan"), float("inf")):
            with self.subTest(valor=valor):
                fila = componentes.Fila("VGP", "m/s²", valor, None, 0.1, ">")
                tabla = componentes.ficha([fila], "Punto", None)
                self.assertIn("Sin datos", tabla)
                self.assertNotIn("No cumple el criterio", tabla)
                self.assertNotIn("Cumple el criterio", tabla)

    def test_comparacion_usa_columna_y_sentido_del_indice(self) -> None:
        """La ficha de área debe evaluar el área, incluso con umbrales negativos."""
        casos = (
            (componentes.Fila("VGP", "m/s²", 0.05, 0.2, 0.1, ">"), "Cumple el criterio"),
            (componentes.Fila("STP", "", -0.1, -0.4, -0.3, "<"), "Cumple el criterio"),
            (componentes.Fila("STP", "", -0.4, -0.1, -0.3, "<"), "No cumple el criterio"),
        )
        for fila, resultado in casos:
            with self.subTest(indice=fila.nombre, extremo=fila.zona):
                tabla = componentes.ficha([fila], "Punto", "Área")
                self.assertIn(resultado, tabla)
                self.assertNotIn("Sin datos", tabla)

    def test_referencia_no_se_presenta_como_criterio(self) -> None:
        """Un valor descriptivo carece de un resultado de cumplimiento."""
        fila = componentes.Fila("SRH", "m²/s²", -150, None, None, "<", "2019: −100 a −250")
        tabla = componentes.ficha([fila], "Punto", None)
        self.assertIn("Sin criterio de decisión", tabla)
        self.assertIn("2019: −100 a −250", tabla)
        self.assertNotIn("Cumple el criterio", tabla)


if __name__ == "__main__":
    unittest.main()
