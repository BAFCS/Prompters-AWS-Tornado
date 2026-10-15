"""Bitácora_Progreso: arreglo JSON de solo agregado en ``docs/logs/progreso.json``.

Cada entrada tiene los cinco campos ``timestamp`` (ISO 8601 en UTC), ``tarea`` (1 a 200
caracteres), ``estado`` (uno de ``STATES``), ``notas`` (texto) y ``decisiones`` (lista de textos).
El agregado valida la entrada, lee el arreglo actual y lo reescribe de forma atómica bajo un
``flock``; ante una entrada inválida o un archivo corrupto termina con código distinto de cero y
no toca el archivo.

Uso:
    uv run python scripts/app/progress_log.py --tarea "2.2 progress_log" --estado hecho \
        --notas "CLI lista" --decision "JSON sin dependencias" --decision "flock en .lock"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import atomic  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "docs/logs/progreso.json"
STATES = ("pendiente", "en_curso", "hecho", "bloqueado")
FIELDS = ("timestamp", "tarea", "estado", "notas", "decisiones")
MAX_TAREA = 200


class LogError(SystemExit):
    """Entrada inválida o archivo corrupto; termina con código 1 y el mensaje en stderr."""


def _is_utc_iso(value: object) -> bool:
    """True si ``value`` es una fecha y hora ISO 8601 con zona UTC (``Z`` o ``+00:00``)."""
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return False
    return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


def validate(entry: dict) -> list[str]:
    """Devuelve los nombres de los campos inválidos o faltantes de ``entry`` (vacía si es válida)."""
    bad: list[str] = []
    if not _is_utc_iso(entry.get("timestamp")):
        bad.append("timestamp")
    tarea = entry.get("tarea")
    if not isinstance(tarea, str) or not 1 <= len(tarea) <= MAX_TAREA:
        bad.append("tarea")
    if entry.get("estado") not in STATES:
        bad.append("estado")
    if not isinstance(entry.get("notas"), str):
        bad.append("notas")
    decisiones = entry.get("decisiones")
    if not isinstance(decisiones, list) or not all(isinstance(d, str) for d in decisiones):
        bad.append("decisiones")
    return bad


def read(path: Path) -> list[dict]:
    """Lee la bitácora; ``[]`` si no existe. Lanza ``LogError`` si no es JSON o no es un arreglo."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LogError(f"archivo corrupto: {path} no es JSON válido ({exc})") from exc
    if not isinstance(data, list):
        raise LogError(f"archivo corrupto: la raíz de {path} no es un arreglo")
    return data


def append(entry: dict, path: Path = DEFAULT) -> None:
    """Agrega ``entry`` al final de la bitácora en ``path`` (crea directorios y archivo si faltan)."""
    bad = validate(entry)
    if bad:
        raise LogError(f"entrada inválida; campos inválidos: {', '.join(bad)}")
    with atomic.locked(path):
        entries = read(path)
        atomic.write_json(path, [*entries, {k: entry[k] for k in FIELDS}])


def main(argv: list[str] | None = None) -> None:
    """CLI: arma la entrada con los argumentos y la agrega a la bitácora."""
    parser = argparse.ArgumentParser(description="Agrega una entrada a la Bitácora_Progreso.")
    parser.add_argument("--tarea", required=True, help="tarea (1 a 200 caracteres)")
    parser.add_argument("--estado", required=True, help=f"uno de: {', '.join(STATES)}")
    parser.add_argument("--notas", default="", help="notas libres")
    parser.add_argument(
        "--decision", action="append", default=[], help="decisión tomada (se puede repetir)"
    )
    parser.add_argument("--timestamp", help="ISO 8601 en UTC (por defecto, ahora)")
    parser.add_argument("--file", type=Path, default=DEFAULT, help="ruta de la bitácora")
    args = parser.parse_args(argv)
    timestamp = args.timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "timestamp": timestamp,
        "tarea": args.tarea,
        "estado": args.estado,
        "notas": args.notas,
        "decisiones": args.decision,
    }
    append(entry, args.file)
    print(f"entrada agregada a {args.file}")


if __name__ == "__main__":
    main()
