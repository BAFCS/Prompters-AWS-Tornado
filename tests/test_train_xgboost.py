"""Prueba de paridad de ``scripts/model/train_xgboost.py`` con ``loeo.run_loeo`` directo."""

import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import loeo  # noqa: E402
import synthetic  # noqa: E402
import table  # noqa: E402
import train_xgboost  # noqa: E402

REGION = "test"
DAYS = [dt.date(2020, 1, 5), dt.date(2020, 1, 6)]
OUTPUTS = ("model.json", "metrics.json", "importance.json", "reporte.html")


def write_inputs(root: Path) -> tuple[Path, Path]:
    """Índices ERA5 sintéticos (2 días, 24 h, 2 × 2 puntos) y un catálogo ``.xlsx`` de 4 eventos."""
    rng = np.random.default_rng(1)
    lat, lon = synthetic.era5_grid()
    for day in DAYS:
        shape = (24, len(lat), len(lon))
        values = {c: rng.normal(size=shape) for c in table.ERA5_FEATURES}
        synthetic.write_era5_indices(root / "crops", REGION, day, range(24), values)
    events = pd.DataFrame(
        {
            table.CATALOG_DATE: ["2020-01-05", "2020-01-05", "2020-01-06", "2020-01-06"],
            table.CATALOG_LAT: ["35.0 S", "35.25 S", "35.0 S", "35.25 S"],
            table.CATALOG_LON: ["72.0 O", "71.75 O", "71.75 O", "72.0 O"],
            table.CATALOG_HOUR: ["06:10", "15:40", "09:00", "20:20"],
        }
    )
    catalog = root / "tornados_chile.xlsx"
    events.to_excel(catalog, sheet_name="Final_Table", index=False, engine="openpyxl")
    return root / "crops" / REGION / "era5_indices", catalog


class TrainXgboostParityTest(unittest.TestCase):
    """El script y ``run_loeo`` directo dan los mismos conteos con la misma semilla."""

    def test_script_matches_run_loeo(self) -> None:
        """Mismos aciertos, omisiones y falsas alarmas; se escriben los cuatro archivos."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            indices, catalog = write_inputs(root)
            out = root / "out"
            out.mkdir()
            argv = ["--indices", str(indices), "--catalog", str(catalog), "--out", str(out)]
            with contextlib.redirect_stdout(io.StringIO()):
                train_xgboost.main([*argv, "--seed", "3"])
                tab = train_xgboost.build_table(
                    train_xgboost._list_indices(str(indices)),
                    train_xgboost._read_catalog(str(catalog)),
                    3,
                )
            for name in OUTPUTS:
                self.assertTrue((out / name).is_file(), name)
            metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            direct = loeo.run_loeo(
                tab, train_xgboost.FEATURES, loeo.compute_folds(tab), 3
            ).to_metrics_json("baseline_era5")
            keys = ("hits", "misses", "false_alarms", "n_events")
            for section in ("selection", "development_case"):
                self.assertEqual(
                    {k: metrics[section][k] for k in keys}, {k: direct[section][k] for k in keys}
                )
            self.assertEqual(metrics["selection"]["n_events"], 4)
            self.assertEqual(int((tab["label"] == 1).sum()), 4)
            report = (out / "reporte.html").read_text(encoding="utf-8")
            self.assertIn("PR-AUC", report)
            self.assertIn("corridas históricas", report)
            importance = json.loads((out / "importance.json").read_text(encoding="utf-8"))
            self.assertEqual(set(importance), set(train_xgboost.FEATURES))


if __name__ == "__main__":
    unittest.main()
