"""Escritura atómica y bloqueo de archivo, compartidos por los módulos de ``scripts/app/``.

Toda salida se escribe primero en un temporal del mismo directorio, se sincroniza con ``fsync`` y
se intercambia con ``os.replace``: un lector ve el archivo anterior o el nuevo completo, nunca uno a
medias. Si algo falla, el temporal se elimina, la excepción se relanza y el archivo final no cambia.

``locked`` serializa los ciclos leer-modificar-escribir (bitácora, estado de alertas, JSONL) con un
``fcntl.flock`` exclusivo sobre ``<path>.lock``.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if TYPE_CHECKING:
    import xarray as xr


def _final_mode(path: Path) -> int:
    """Permisos del archivo final: los del archivo existente o ``0o666`` menos la umask.

    ``mkstemp`` crea el temporal con ``0o600``; sin esto el archivo final quedaría privado.
    """
    try:
        return path.stat().st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _replace_via_temp(path: Path, suffix: str, fill: Callable[[Path], object]) -> None:
    """Crea un temporal junto a ``path``, lo llena con ``fill``, hace ``fsync`` y lo intercambia.

    Crea los directorios que falten. El archivo final conserva los permisos del anterior o, si es
    nuevo, recibe ``0o666`` menos la umask. Ante cualquier fallo elimina el temporal y relanza.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=suffix, dir=path.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        fill(tmp)
        os.chmod(tmp, _final_mode(path))
        with tmp.open("rb+") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_bytes(path: Path, data: bytes) -> None:
    """Escribe ``data`` en ``path`` de forma atómica (temporal, ``fsync`` y ``os.replace``)."""
    _replace_via_temp(path, ".tmp", lambda tmp: tmp.write_bytes(data))


def write_text(path: Path, text: str) -> None:
    """Escribe ``text`` en UTF-8 en ``path`` de forma atómica."""
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, obj: object) -> None:
    """Escribe ``obj`` como JSON UTF-8 (``ensure_ascii=False``, ``indent=2``) de forma atómica."""
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_dataset(ds: xr.Dataset, path: Path, encoding: dict | None = None) -> None:
    """Escribe ``ds`` como NetCDF con ``common.write`` sobre un temporal ``.tmp.nc`` y lo intercambia.

    ``encoding`` se pasa tal cual a ``common.write`` (sin él, compresión por defecto).
    """
    import common  # importación diferida: ``common`` trae s3fs y h5py

    _replace_via_temp(path, ".tmp.nc", lambda tmp: common.write(ds, tmp, encoding))


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Mantiene un ``fcntl.flock`` exclusivo sobre ``<path>.lock`` (se crea si falta)."""
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
