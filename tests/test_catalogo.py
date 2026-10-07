"""Comprueba la clasificación de eventos reportados sin modificar el catálogo."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from visor_app import datos  # noqa: E402


class CatalogoTest(unittest.TestCase):
    """Comprueba los tipos mostrados para combinaciones de marcas del catálogo."""

    def test_sin_marcas_no_se_clasifica_como_tromba(self) -> None:
        """La ausencia de ambas marcas conserva la clasificación desconocida."""
        dia = dt.date(2019, 5, 30)
        catalogo = pd.DataFrame(
            {
                "fecha": [dia] * 4,
                "Location": ["A", "B", "C", "D"],
                "Hour (UTC)": ["19:00", "20:00", "21:00", "22:00"],
                "Tornado": [1, 0, 1, 0],
                "Waterspout": [0, 1, 1, 0],
                "Max. EF Rating": [1, 1, 1, None],
                "Register": [1, 1, 1, 0],
            }
        )
        # Se sustituye solo la lectura externa; la transformación es la función real.
        with patch.object(datos, "catalogo", return_value=catalogo):
            eventos = datos.eventos.__wrapped__(dia)
        self.assertEqual(
            eventos["tipo"].tolist(),
            ["tornado", "tromba", "tornado y tromba", "sin clasificación"],
        )


if __name__ == "__main__":
    unittest.main()
