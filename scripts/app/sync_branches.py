"""Sincronización repetible de ``merge/datos-modelo`` con las ramas de origen (Requisito 1).

Pasos de cada vuelta (design.md, "Procedimiento de Sincronización"):

1. ``git fetch origin`` y registro de los SHA vigentes de ``origin/main`` y de las dos ramas.
2. Crea ``merge/datos-modelo`` desde ``origin/main`` en la primera vuelta; luego solo la activa.
3. Integra cada rama de origen con ``git merge --no-ff`` (siempre un commit de merge).
5. Verifica que no queden marcadores de conflicto, que ambos SHA sean ancestros de ``HEAD`` y
   corre la Puerta_Calidad (``make check``) salvo con ``--skip-check``. Al final vuelve a leer
   ``origin/main`` y falla si cambió durante la vuelta (Req. 1.6).
6. Agrega la Entrada_Bitácora ``sincronización`` en ``docs/logs/progreso.json``.
7. Agrega una fila a la tabla de Sincronizaciones de ``docs/planificacion_merge.md``.

El paso 4 (resolver conflictos) es manual cuando ``git rerere`` no lo resuelve solo: el script se
detiene con código 1, lista los archivos, deja el merge en curso y registra ``bloqueado``. Tras
resolver y hacer ``git add``, ``--continue`` cierra el merge y sigue con la rama siguiente.

Este script nunca publica ni reescribe historia: no ejecuta push, rebase, reset, squash ni force.
Push y PR quedan siempre manuales y con confirmación del usuario.

Códigos de salida: 0 vuelta completa; 1 conflicto sin resolver, marcadores, SHA no integrado,
Puerta_Calidad fallida u ``origin/main`` cambiado; 2 árbol de trabajo sucio o uso incorrecto.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import atomic  # noqa: E402

REMOTE = "origin"
MAIN = "origin/main"
SOURCES = ("origin/intentos-nico", "origin/feat/multimodal-tornado-predictor-wip")
BRANCH = "merge/datos-modelo"
TASK = "sincronización"
DOC_REL = Path("docs/planificacion_merge.md")
LOG_REL = Path("docs/logs/progreso.json")
TABLE_HEADING = "### Sincronizaciones"
SHORT = 7

Gate = Literal["ok", "falla", "no ejecutada"]

_CONFLICT_RE = re.compile(r"^CONFLICT \([^)]*\): Merge conflict in (.+)$")
_MARKER_RE = r"^(<<<<<<<|=======|>>>>>>>)( |$)"


class GitError(RuntimeError):
    """Un comando ``git`` terminó con código distinto de cero y ``check=True``."""


@dataclass(frozen=True)
class SyncShas:
    """SHA completos registrados al inicio de la vuelta."""

    main: str
    nico: str
    daniel: str


@dataclass
class SyncResult:
    """Datos de una Sincronización, uno por fila de la tabla."""

    date: str
    shas: SyncShas
    conflicts: list[str] = field(default_factory=list)
    gate: Gate = "no ejecutada"


# --- git ---------------------------------------------------------------------------------------


def git(*args: str, check: bool = True) -> str:
    """Ejecuta ``git`` con ``args`` como lista (sin shell) y devuelve stdout sin espacios finales.

    Con ``check=True`` lanza ``GitError`` (con stderr) si el código es distinto de cero.
    """
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} falló ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.rstrip()


def _git_ok(*args: str) -> bool:
    """Devuelve ``True`` si ``git args`` termina con código cero."""
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return proc.returncode == 0


def dirty_files() -> list[str]:
    """Archivos versionados modificados o en el índice (los no versionados ``??`` se permiten)."""
    out = git("status", "--porcelain")
    return [line[3:] for line in out.splitlines() if line and not line.startswith("??")]


def record_shas() -> SyncShas:
    """Lee los SHA completos de ``origin/main`` y de las dos ramas de origen (paso 1)."""
    main_sha, nico, daniel = (
        git("rev-parse", "--verify", f"{ref}^{{commit}}") for ref in (MAIN, *SOURCES)
    )
    return SyncShas(main=main_sha, nico=nico, daniel=daniel)


def ensure_branch(main_sha: str) -> None:
    """Activa ``merge/datos-modelo``; si no existe la crea desde ``main_sha`` (paso 2)."""
    if _git_ok("rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}"):
        git("checkout", BRANCH)
    else:
        git("checkout", "-b", BRANCH, main_sha)


def unmerged_files() -> list[str]:
    """Archivos que siguen en conflicto en el índice (rerere no los resolvió)."""
    return sorted(set(git("diff", "--name-only", "--diff-filter=U").splitlines()))


def merge_in_progress() -> bool:
    """Indica si hay un merge en curso (existe ``MERGE_HEAD``)."""
    return _git_ok("rev-parse", "--verify", "--quiet", "MERGE_HEAD")


def _conflicts_in_merge_msg() -> list[str]:
    """Archivos listados en la sección ``Conflicts:`` de ``MERGE_MSG`` del merge en curso."""
    path = Path(git("rev-parse", "--git-path", "MERGE_MSG"))
    if not path.exists():
        return []
    files: list[str] = []
    in_block = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.lstrip("#").strip()
        if line == "Conflicts:":
            in_block = True
        elif in_block and line:
            files.append(line)
        elif in_block and files:
            break
    return files


def _commit_merge() -> None:
    """Cierra el merge en curso con el mensaje preparado por git."""
    git("commit", "--no-edit", "--cleanup=strip")


def merge_source(ref: str, seen: list[str] | None = None) -> list[str]:
    """Integra ``ref`` con ``git merge --no-ff`` y devuelve los archivos en conflicto sin resolver.

    Si git reporta conflictos y ``rerere`` los resolvió todos (y no quedan marcadores), cierra el
    merge con ``git commit --no-edit``. Si quedan archivos sin resolver, deja el merge en curso y
    los devuelve. Cada archivo reportado como conflicto se agrega a ``seen`` (si se pasa).
    """
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    name = ref.removeprefix(f"{REMOTE}/")
    proc = subprocess.run(
        ["git", "merge", "--no-ff", "-m", f"sync: {name} {sha[:SHORT]}", sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return []
    reported = [m.group(1) for m in map(_CONFLICT_RE.match, proc.stdout.splitlines()) if m]
    if not merge_in_progress():
        raise GitError(f"git merge {ref} falló sin dejar merge en curso: {proc.stderr.strip()}")
    pending = unmerged_files()
    if seen is not None:
        seen.extend(f for f in [*reported, *pending] if f not in seen)
    if pending:
        return pending
    markers = conflict_markers()
    if markers:
        return sorted({m.split(":", 1)[0] for m in markers})
    _commit_merge()
    return []


def conflict_markers() -> list[str]:
    """Líneas ``archivo:línea:texto`` con marcadores de conflicto en archivos versionados."""
    out = git("grep", "-nIE", _MARKER_RE, check=False)
    return out.splitlines()


def is_ancestor(sha: str) -> bool:
    """``git merge-base --is-ancestor sha HEAD`` (Req. 1.2)."""
    return _git_ok("merge-base", "--is-ancestor", sha, "HEAD")


def run_gate() -> Gate:
    """Corre la Puerta_Calidad (``make check``) en la raíz del repo y devuelve ``ok`` o ``falla``."""
    root = git("rev-parse", "--show-toplevel")
    proc = subprocess.run(["make", "check"], cwd=root, check=False)
    return "ok" if proc.returncode == 0 else "falla"


# --- Tabla de Sincronizaciones -----------------------------------------------------------------


def _escape(text: str) -> str:
    """Escapa ``\\`` y ``|`` para que no rompan la celda Markdown."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def sync_row(result: SyncResult) -> str:
    """Fila Markdown de 6 celdas: fecha, SHA nico, SHA daniel, SHA main, conflictos y puerta.

    Los SHA se abrevian a 7 caracteres. Sin conflictos la celda dice ``ninguno``.
    """
    shas = result.shas
    conflicts = ", ".join(f"`{_escape(f)}`" for f in result.conflicts) or "ninguno"
    cells = [
        _escape(result.date),
        f"`{shas.nico[:SHORT]}`",
        f"`{shas.daniel[:SHORT]}`",
        f"`{shas.main[:SHORT]}`",
        conflicts,
        _escape(result.gate),
    ]
    return "| " + " | ".join(cells) + " |"


def append_sync_row(doc: Path, row: str) -> None:
    """Agrega ``row`` después de la última fila de la tabla bajo ``### Sincronizaciones``.

    La escritura es atómica (``atomic.write_text``). Lanza ``ValueError`` si falta el encabezado
    o la tabla.
    """
    lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == TABLE_HEADING)
    except StopIteration:
        raise ValueError(f"{doc}: falta el encabezado {TABLE_HEADING!r}") from None
    last = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("|"):
            last = i
        elif last is not None or stripped.startswith("#"):
            break
    if last is None:
        raise ValueError(f"{doc}: no hay tabla bajo {TABLE_HEADING!r}")
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines.insert(last + 1, row + "\n")
    atomic.write_text(doc, "".join(lines))


# --- Bitácora ----------------------------------------------------------------------------------


def log_entry(estado: str, notas: str, decisiones: list[str], path: Path) -> None:
    """Agrega la Entrada_Bitácora ``sincronización`` con ``progress_log.append``."""
    import progress_log  # importación diferida: módulo hermano

    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tarea": TASK,
        "estado": estado,
        "notas": notas,
        "decisiones": decisiones,
    }
    progress_log.append(entry, path=path)


def _notes(shas: SyncShas, conflicts: list[str], gate: Gate, extra: str = "") -> str:
    """Texto de ``notas``: los tres SHA, los conflictos y el resultado de la Puerta_Calidad."""
    parts = [
        f"origin/main={shas.main}",
        f"intentos-nico={shas.nico}",
        f"feat/multimodal-tornado-predictor-wip={shas.daniel}",
        "conflictos: " + (", ".join(conflicts) or "ninguno"),
        f"make check: {gate}",
    ]
    if extra:
        parts.append(extra)
    return "; ".join(parts)


# --- CLI ---------------------------------------------------------------------------------------


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Sincroniza {BRANCH} con {', '.join(SOURCES)} mediante merge --no-ff. "
            "Nunca publica la rama ni abre PR."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="solo hace fetch y muestra los SHA vigentes"
    )
    mode.add_argument(
        "--continue",
        dest="resume",
        action="store_true",
        help="retoma tras resolver a mano el merge en curso (sin volver a hacer fetch)",
    )
    parser.add_argument(
        "--skip-check", action="store_true", help="no corre make check (Puerta_Calidad)"
    )
    parser.add_argument("--doc", type=Path, help=f"documento con la tabla (por defecto {DOC_REL})")
    parser.add_argument("--log", type=Path, help=f"bitácora JSON (por defecto {LOG_REL})")
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    root = Path(git("rev-parse", "--show-toplevel"))
    doc: Path = args.doc or root / DOC_REL
    log: Path = args.log or root / LOG_REL
    conflicts: list[str] = []

    if args.resume:
        if not merge_in_progress():
            print("--continue: no hay un merge en curso.", file=sys.stderr)
            return 2
        if git("rev-parse", "--abbrev-ref", "HEAD") != BRANCH:
            print(f"--continue: la rama activa no es {BRANCH}.", file=sys.stderr)
            return 2
        conflicts.extend(_conflicts_in_merge_msg())
        pending = unmerged_files()
        markers = conflict_markers()
        if pending or markers:
            print("Quedan conflictos sin resolver:", file=sys.stderr)
            for item in pending or markers:
                print(f"  {item}", file=sys.stderr)
            return 1
        _commit_merge()
        shas = record_shas()
    else:
        dirty = dirty_files()
        if dirty:
            print("Árbol de trabajo sucio; no se toca nada:", file=sys.stderr)
            for f in dirty:
                print(f"  {f}", file=sys.stderr)
            return 2
        git("fetch", REMOTE)
        shas = record_shas()
        if args.dry_run:
            print(f"{MAIN}: {shas.main}")
            print(f"{SOURCES[0]}: {shas.nico}")
            print(f"{SOURCES[1]}: {shas.daniel}")
            return 0
        ensure_branch(shas.main)

    for ref, sha in zip(SOURCES, (shas.nico, shas.daniel), strict=True):
        if is_ancestor(sha):
            continue
        pending = merge_source(ref, seen=conflicts)
        if pending:
            print(f"Conflictos sin resolver al integrar {ref}:", file=sys.stderr)
            for f in pending:
                print(f"  {f}", file=sys.stderr)
            print("Resuélvelos, haz git add y ejecuta de nuevo con --continue.", file=sys.stderr)
            log_entry(
                "bloqueado",
                _notes(
                    shas, conflicts, "no ejecutada", f"sin resolver en {ref}: {', '.join(pending)}"
                ),
                [],
                log,
            )
            return 1

    problems: list[str] = []
    markers = conflict_markers()
    if markers:
        problems.append("marcadores de conflicto: " + ", ".join(markers))
    for label, sha in (("intentos-nico", shas.nico), ("predictor", shas.daniel)):
        if not is_ancestor(sha):
            problems.append(f"{label} {sha[:SHORT]} no es ancestro de HEAD")

    gate: Gate = "no ejecutada"
    if not problems and not args.skip_check:
        gate = run_gate()

    git("fetch", REMOTE)
    current_main = git("rev-parse", "--verify", f"{MAIN}^{{commit}}")
    if current_main != shas.main:
        problems.append(
            f"{MAIN} cambió durante la Sincronización ({shas.main[:SHORT]} → "
            f"{current_main[:SHORT]}); repítela"
        )

    # La fila se registra si la integración quedó completa, aunque la Puerta_Calidad falle
    # (la tabla guarda ``falla``); con problemas estructurales la vuelta no cuenta.
    failed = bool(problems) or gate == "falla"
    notes = _notes(shas, conflicts, gate, "; ".join(problems))
    log_entry("bloqueado" if failed else "hecho", notes, [], log)
    if not problems:
        date = datetime.now(UTC).date().isoformat()
        append_sync_row(doc, sync_row(SyncResult(date, shas, conflicts, gate)))
        print(f"Registrada en {log} y {doc}. La rama no se publicó.")
    for p in problems:
        print(p, file=sys.stderr)
    if failed:
        if gate == "falla":
            print("make check falló: no abras el PR hasta corregirlo.", file=sys.stderr)
        return 1
    print(f"Sincronización completa en {BRANCH} (HEAD {git('rev-parse', '--short', 'HEAD')}).")
    return 0


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada: ``--dry-run``, ``--continue`` y ``--skip-check``."""
    code = _run(_parse(argv))
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
