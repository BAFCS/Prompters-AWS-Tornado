"""Renderiza los diagramas D2 de ``docs/diagrams/`` a SVG y PNG con el binario ``d2``.

Requiere ``d2`` instalado en el sistema (``brew install d2``). Usa el motor de layout ELK.

Uso::

    uv run python scripts/diagrams/render_diagrams.py
    uv run python scripts/diagrams/render_diagrams.py --scale 1.5
"""

import argparse
import shutil
import subprocess
from pathlib import Path

DIAGRAMS = Path(__file__).resolve().parents[2] / "docs" / "diagrams"


def render(source: Path, target: Path, scale: float) -> None:
    """Ejecuta ``d2`` sobre ``source`` y escribe ``target`` (SVG o PNG según la extensión)."""
    cmd = ["d2", "--layout", "elk", "--pad", "60", "--scale", str(scale), str(source), str(target)]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    """Punto de entrada: renderiza cada ``.d2`` de la carpeta a SVG y PNG."""
    p = argparse.ArgumentParser(description="Renderiza los diagramas D2 a SVG y PNG.")
    p.add_argument("--scale", type=float, default=1.0, help="escala del PNG (por defecto 1)")
    a = p.parse_args()
    if shutil.which("d2") is None:
        raise SystemExit("No se encontró 'd2'. Instálalo con: brew install d2")
    for source in sorted(DIAGRAMS.glob("*.d2")):
        render(source, source.with_suffix(".svg"), 1.0)
        render(source, source.with_suffix(".png"), a.scale)


if __name__ == "__main__":
    main()
