"""Comprueba la clasificación de eventos reportados sin modificar el catálogo."""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from viewer_app import data  # noqa: E402


class CatalogTest(unittest.TestCase):
    """Comprueba los tipos mostrados para combinaciones de marcas del catálogo."""

    def test_unmarked_event_is_not_a_waterspout(self) -> None:
        """La ausencia de ambas marcas conserva la clasificación desconocida."""
        day = dt.date(2019, 5, 30)
        catalog = pd.DataFrame(
            {
                "date": [day] * 4,
                "Location": ["A", "B", "C", "D"],
                "Hour (UTC)": ["19:00", "20:00", "21:00", "22:00"],
                "Tornado": [1, 0, 1, 0],
                "Waterspout": [0, 1, 1, 0],
                "Max. EF Rating": [1, 1, 1, None],
                "Register": [1, 1, 1, 0],
            }
        )
        # Se sustituye solo la lectura externa; la transformación es la función real.
        with patch.object(data, "catalog", return_value=catalog):
            events = data._events.__wrapped__(day, 0.0)
        self.assertEqual(
            events["kind"].tolist(),
            ["tornado", "tromba", "tornado y tromba", "sin clasificación"],
        )

    def test_catalog_downloaded_while_viewer_is_open_is_read(self) -> None:
        """Si falta el catálogo y luego se descarga, la siguiente lectura lo ve (no queda vacío en caché)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tornados_chile.xlsx"
            with patch.object(data, "CATALOG", path):
                self.assertTrue(data.catalog().empty)
                pd.DataFrame(
                    {
                        "Date (Gregorian Calendar)": ["2019-05-30"],
                        "Latitude": ["-36,8"],
                        "Longitude": ["-73,0"],
                    }
                ).to_excel(path, sheet_name="Final_Table", index=False)
                self.assertEqual(len(data.catalog()), 1)


if __name__ == "__main__":
    unittest.main()
