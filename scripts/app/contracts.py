"""Comparadores puros de contrato entre nuestro código y las interfaces de Nico y Daniel.

Se analiza el código fuente con `ast` en lugar de importarlo: importar `inference.py` o
`build_table.py` cargaría `xgboost` y `sagemaker` y ejecutaría efectos de módulo. Ninguna función
de este módulo hace E/S; las pruebas leen los archivos reales como texto y se los pasan.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType

# Centinela para distinguir "constante ausente" de "constante con valor None".
_MISSING = object()


@dataclass(frozen=True)
class Drift:
    """Una diferencia de contrato: constante `name`, valor esperado y valor encontrado.

    `found` es None cuando la constante no existe.
    """

    name: str
    expected: object
    found: object


def _target_names(target: ast.expr) -> list[str]:
    """Nombres simples asignados por un destino (admite desempaquetado en tuplas o listas)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for elt in target.elts for name in _target_names(elt)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _module_names(tree: ast.Module) -> set[str]:
    """Nombres definidos a nivel de módulo: def, class, asignación, asignación anotada e import."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_target_names(target))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            names.update(_target_names(node.target))
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def missing_symbols(source: str, names: Iterable[str]) -> list[str]:
    """Devuelve los nombres de `names` que `source` no define a nivel de módulo.

    Analiza `source` con `ast.parse` (def, class, asignación, asignación anotada e import) y
    conserva el orden pedido, sin duplicados.
    """
    defined = _module_names(ast.parse(source))
    missing: list[str] = []
    for name in names:
        if name not in defined and name not in missing:
            missing.append(name)
    return missing


def tuple_constant(source: str, name: str) -> tuple[object, ...] | None:
    """Valor literal de la asignación de módulo `name = (...)` en `source`.

    Usa `ast.literal_eval`. Una lista literal se convierte a tupla. Devuelve None si el nombre
    no se asigna a nivel de módulo, si el valor no es literal o si no es una secuencia
    (tupla o lista). Si hay varias asignaciones, vale la última, como al ejecutar el módulo.
    """
    value_node: ast.expr | None = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            value_node = node.value
    if value_node is None:
        return None
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    if isinstance(value, tuple | list):
        return tuple(value)
    return None


def sequence_drift(
    name: str, expected: Sequence[object], found: Sequence[object] | None
) -> list[Drift]:
    """Una Drift si `found` falta o no coincide elemento a elemento y en orden con `expected`."""
    if found is None:
        return [Drift(name, tuple(expected), None)]
    if tuple(found) != tuple(expected):
        return [Drift(name, tuple(expected), tuple(found))]
    return []


def missing_members(expected: Iterable[str], found: Iterable[str]) -> list[str]:
    """Miembros de `expected` ausentes en `found`, en el orden de `expected` y sin duplicados."""
    present = set(found)
    missing: list[str] = []
    for member in expected:
        if member not in present and member not in missing:
            missing.append(member)
    return missing


def layout_drift(expected: Mapping[str, object], module: ModuleType) -> list[Drift]:
    """Una Drift por cada constante de `expected` ausente en `module` o con valor distinto."""
    drifts: list[Drift] = []
    for name, value in expected.items():
        found = getattr(module, name, _MISSING)
        if found is _MISSING:
            drifts.append(Drift(name, value, None))
        elif found != value:
            drifts.append(Drift(name, value, found))
    return drifts


def format_drift(drifts: list[Drift]) -> str:
    """Una línea 'constante X: esperado <e>, encontrado <f>' por cada Drift (Req. 9.12 y 9.15)."""
    return "\n".join(
        f"constante {d.name}: esperado {d.expected!r}, encontrado {d.found!r}" for d in drifts
    )
