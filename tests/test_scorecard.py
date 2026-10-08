"""Comprueba que la ficha distingue ausencia de datos y comparación de índices."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "viewer"))

from viewer_app import components  # noqa: E402


class ScorecardTest(unittest.TestCase):
    """Verifica los resultados visibles con valores y referencias controlados."""

    def test_missing_data_is_not_a_failure(self) -> None:
        """Un valor ausente no debe presentarse como resultado de una comparación."""
        for value in (None, float("nan"), float("inf")):
            with self.subTest(value=value):
                row = components.Row("VGP", "m/s²", value, None, 0.1, ">")
                table = components.scorecard([row], "Punto", None)
                self.assertIn("Sin datos", table)
                self.assertNotIn("No cumple el criterio", table)
                self.assertNotIn("Cumple el criterio", table)

    def test_comparison_uses_column_and_index_sense(self) -> None:
        """La ficha de área debe evaluar el área, incluso con umbrales negativos."""
        cases = (
            (components.Row("VGP", "m/s²", 0.05, 0.2, 0.1, ">"), "Cumple el criterio"),
            (components.Row("STP", "", -0.1, -0.4, -0.3, "<"), "Cumple el criterio"),
            (components.Row("STP", "", -0.4, -0.1, -0.3, "<"), "No cumple el criterio"),
        )
        for row, result in cases:
            with self.subTest(indice=row.name, extreme=row.area):
                table = components.scorecard([row], "Punto", "Área")
                self.assertIn(result, table)
                self.assertNotIn("Sin datos", table)

    def test_reference_is_not_shown_as_criterion(self) -> None:
        """Un valor descriptivo carece de un resultado de cumplimiento."""
        row = components.Row("SRH", "m²/s²", -150, None, None, "<", "2019: −100 a −250")
        table = components.scorecard([row], "Punto", None)
        self.assertIn("Sin criterio de decisión", table)
        self.assertIn("2019: −100 a −250", table)
        self.assertNotIn("Cumple el criterio", table)


if __name__ == "__main__":
    unittest.main()
