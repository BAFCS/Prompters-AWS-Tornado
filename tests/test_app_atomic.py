"""Pruebas de la escritura atómica y el bloqueo (``scripts/app/atomic.py``)."""

import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))

import atomic  # noqa: E402


class AtomicWriteTest(unittest.TestCase):
    """Escrituras completas, sin temporales sobrantes y sin tocar el destino ante fallos."""

    def setUp(self) -> None:
        """Crea un directorio temporal por prueba."""
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        """Elimina el directorio temporal."""
        self._tmp.cleanup()

    def test_write_json_roundtrip_and_creates_dirs(self) -> None:
        """``write_json`` crea directorios, escribe UTF-8 legible y no deja temporales."""
        path = self.dir / "a" / "b" / "x.json"
        atomic.write_json(path, {"región": "Biobío", "n": [1, 2]})
        self.assertEqual(json.loads(path.read_text("utf-8")), {"región": "Biobío", "n": [1, 2]})
        self.assertIn("Biobío", path.read_text("utf-8"))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["x.json"])

    def test_permissions_follow_umask_or_existing_file(self) -> None:
        """Un archivo nuevo recibe ``0o666`` menos la umask; uno existente conserva su modo."""
        new = self.dir / "nuevo.json"
        old_umask = os.umask(0o022)
        try:
            atomic.write_json(new, {})
        finally:
            os.umask(old_umask)
        self.assertEqual(stat.S_IMODE(new.stat().st_mode), 0o644)

        existing = self.dir / "existente.txt"
        existing.write_text("a", encoding="utf-8")
        existing.chmod(0o640)
        atomic.write_text(existing, "b")
        self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o640)

    def test_failure_keeps_previous_file_and_removes_temp(self) -> None:
        """Si ``os.replace`` falla, el archivo anterior sigue igual y el temporal desaparece."""
        path = self.dir / "x.txt"
        atomic.write_text(path, "viejo")
        with (
            mock.patch.object(atomic.os, "replace", side_effect=OSError("falla")),
            self.assertRaises(OSError),
        ):
            atomic.write_text(path, "nuevo")
        self.assertEqual(path.read_text("utf-8"), "viejo")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["x.txt"])

    def test_write_dataset(self) -> None:
        """``write_dataset`` deja un NetCDF legible y ningún temporal."""
        path = self.dir / "ds.nc"
        ds = xr.Dataset({"v": ("x", np.arange(3.0))})
        atomic.write_dataset(ds, path)
        with xr.open_dataset(path, engine="h5netcdf") as back:
            np.testing.assert_array_equal(back["v"].values, np.arange(3.0))
        self.assertEqual([p.name for p in self.dir.iterdir()], ["ds.nc"])


class LockedTest(unittest.TestCase):
    """``locked`` excluye a un segundo poseedor mientras el primero lo mantiene."""

    def test_locked_serializes(self) -> None:
        """El segundo hilo entra recién cuando el primero suelta el bloqueo."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            events: list[str] = []

            def second() -> None:
                """Toma el bloqueo después del primero."""
                with atomic.locked(path):
                    events.append("second")

            with atomic.locked(path):
                thread = threading.Thread(target=second)
                thread.start()
                time.sleep(0.2)
                events.append("first")
            thread.join(timeout=5)
            self.assertEqual(events, ["first", "second"])
            self.assertTrue((Path(d) / "state.json.lock").exists())


if __name__ == "__main__":
    unittest.main()
