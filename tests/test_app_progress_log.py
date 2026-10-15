"""Pruebas de la Bitácora_Progreso (``scripts/app/progress_log.py``), solo en directorios temporales."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))

import progress_log  # noqa: E402


def _entry(**overrides: object) -> dict:
    """Entrada válida con los campos de ``overrides`` reemplazados."""
    base: dict = {
        "timestamp": "2026-08-15T12:00:00Z",
        "tarea": "2.2 progress_log",
        "estado": "hecho",
        "notas": "listo",
        "decisiones": ["usar JSON"],
    }
    base.update(overrides)
    return base


class ProgressLogTest(unittest.TestCase):
    """Agregado, validación y archivo corrupto."""

    def setUp(self) -> None:
        """Crea un directorio temporal por prueba."""
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        """Elimina el directorio temporal."""
        self._tmp.cleanup()

    def test_append_creates_dirs_and_file(self) -> None:
        """Sin archivo previo, crea los directorios y un arreglo con solo esa entrada (Req. 3.6)."""
        path = self.dir / "a" / "b" / "progreso.json"
        progress_log.append(_entry(), path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [_entry()])

    def test_append_keeps_previous_entries(self) -> None:
        """La entrada nueva va al final y las anteriores no cambian (Req. 3.2)."""
        path = self.dir / "progreso.json"
        first, second = _entry(tarea="uno"), _entry(tarea="dos", estado="en_curso")
        progress_log.append(first, path)
        progress_log.append(second, path)
        self.assertEqual(progress_log.read(path), [first, second])

    def test_invalid_fields_named_and_file_untouched(self) -> None:
        """Rechaza la entrada nombrando cada campo inválido y no modifica el archivo (Req. 3.4)."""
        path = self.dir / "progreso.json"
        progress_log.append(_entry(), path)
        before = path.read_bytes()
        bad = _entry(estado="terminado", tarea="", timestamp="2026-08-15T12:00:00-04:00")
        with self.assertRaises(progress_log.LogError) as ctx:
            progress_log.append(bad, path)
        message = str(ctx.exception.code)
        for field in ("estado", "tarea", "timestamp"):
            self.assertIn(field, message)
        self.assertNotIn("notas", message)
        self.assertEqual(path.read_bytes(), before)

    def test_validate_rules(self) -> None:
        """Faltantes, zona no UTC, tarea larga y estados permitidos."""
        self.assertEqual(progress_log.validate(_entry()), [])
        self.assertEqual(progress_log.validate(_entry(timestamp="2026-08-15T12:00:00+00:00")), [])
        self.assertEqual(
            progress_log.validate(_entry(timestamp="2026-08-15T12:00:00")), ["timestamp"]
        )
        self.assertEqual(progress_log.validate(_entry(tarea="x" * 201)), ["tarea"])
        self.assertEqual(progress_log.validate(_entry(tarea="x" * 200)), [])
        for state in progress_log.STATES:
            self.assertEqual(progress_log.validate(_entry(estado=state)), [])
        self.assertEqual(progress_log.validate({}), list(progress_log.FIELDS))

    def test_corrupt_file_untouched(self) -> None:
        """JSON inválido o raíz no arreglo: 'archivo corrupto' y el archivo no cambia (Req. 3.7)."""
        for content in (b"{no es json", b'{"a": 1}\n', b"\xff\xfe"):
            path = self.dir / "progreso.json"
            path.write_bytes(content)
            with self.assertRaises(progress_log.LogError) as ctx:
                progress_log.append(_entry(), path)
            self.assertIn("archivo corrupto", str(ctx.exception.code))
            self.assertNotEqual(ctx.exception.code, 0)
            self.assertEqual(path.read_bytes(), content)

    def test_main_cli(self) -> None:
        """La CLI arma la entrada con decisiones repetibles y rechaza un estado inválido."""
        path = self.dir / "logs" / "progreso.json"
        progress_log.main(
            [
                "--tarea",
                "cli",
                "--estado",
                "bloqueado",
                "--notas",
                "n",
                "--decision",
                "d1",
                "--decision",
                "d2",
                "--file",
                str(path),
            ]  # fmt: skip
        )
        (entry,) = progress_log.read(path)
        self.assertEqual(entry["decisiones"], ["d1", "d2"])
        self.assertEqual(progress_log.validate(entry), [])
        with self.assertRaises(SystemExit) as ctx:
            progress_log.main(["--tarea", "cli", "--estado", "otro", "--file", str(path)])
        self.assertIn("estado", str(ctx.exception.code))
        self.assertEqual(len(progress_log.read(path)), 1)


if __name__ == "__main__":
    unittest.main()
