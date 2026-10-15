"""Pruebas del Documento_Predictor (`docs/modelo_predictor.md`) y su enlace en el README.

Solo lee archivos versionados del repositorio: no toca `data/`, no abre red y no necesita
credenciales de AWS. Comprueba que los umbrales HSLC coinciden con la sección 3.2 del
Documento_Fuente, que los enlaces relativos resuelven, que el diagrama contiene todos los nodos del
glosario y que el README enlaza al documento.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREDICTOR = REPO / "docs" / "modelo_predictor.md"
SOURCE = REPO / "docs" / "mesociclones_chile.md"
README = REPO / "README.md"

# Umbrales HSLC con su índice, valor y unidad, tal como aparecen en la sección 3.2 del
# Documento_Fuente. El test comprueba que estén en ambos documentos (misma redacción del valor).
HSLC_THRESHOLDS = (
    "> 0,1 m/s²",  # VGP₀₋₁
    "SHERBE ≥ 1",
    "≤ −0,3",  # STP rama left-mover (signo austral)
)

# Nodos del flujo de datos, por su nombre del glosario (Req. 1.11).
DIAGRAM_NODES = (
    "Extractor_GOES",
    "Compositor_RGB",
    "Codificador_Bedrock",
    "Reductor",
    "Constructor_Tabla",
    "Entrenador",
    "Servicio_Inferencia",
)


def _section(text: str, header_prefix: str) -> str:
    """Devuelve el cuerpo de la sección cuyo encabezado empieza por ``header_prefix``.

    Toma desde la línea del encabezado hasta el siguiente encabezado del mismo nivel o superior.
    """
    lines = text.splitlines()
    start = None
    level = None
    for i, line in enumerate(lines):
        if line.startswith(header_prefix):
            start = i
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].lstrip("#")
        this_level = len(lines[j]) - len(stripped)
        if lines[j].startswith("#") and this_level <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def _github_anchor(header_text: str) -> str:
    """Convierte el texto de un encabezado en el ancla estilo GitHub."""
    anchor = header_text.strip().lower()
    anchor = anchor.replace(" ", "-")
    anchor = re.sub(r"[^\w\-]", "", anchor)  # \w incluye acentos en Unicode
    return anchor


class PredictorDocTest(unittest.TestCase):
    """Comprueba el contenido del Documento_Predictor y sus enlaces."""

    @classmethod
    def setUpClass(cls) -> None:
        """Carga los tres documentos versionados una sola vez."""
        cls.predictor = PREDICTOR.read_text(encoding="utf-8")
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")

    def test_document_exists(self) -> None:
        """El documento está en la ruta esperada."""
        self.assertTrue(PREDICTOR.is_file())

    def test_hslc_thresholds_match_source_section_3_2(self) -> None:
        """Cada umbral HSLC aparece en la sección 3.2 del Fuente y en el Documento_Predictor."""
        section = _section(self.source, "### 3.2")
        self.assertNotEqual(section, "", "No se encontró la sección 3.2 del Documento_Fuente.")
        for threshold in HSLC_THRESHOLDS:
            with self.subTest(threshold=threshold):
                self.assertIn(
                    threshold,
                    section,
                    f"El umbral {threshold!r} no está en la sección 3.2 del Fuente.",
                )
                self.assertIn(
                    threshold,
                    self.predictor,
                    f"El umbral {threshold!r} no está en el Documento_Predictor.",
                )

    def test_diagram_contains_all_glossary_nodes(self) -> None:
        """El diagrama en texto nombra todos los nodos del flujo de datos."""
        match = re.search(r"```text\n(.*?)```", self.predictor, re.DOTALL)
        self.assertIsNotNone(match, "No se encontró el diagrama en bloque ```text```.")
        diagram = match.group(1)
        for node in DIAGRAM_NODES:
            with self.subTest(node=node):
                self.assertIn(node, diagram, f"El diagrama no contiene el nodo {node}.")

    def test_relative_links_resolve(self) -> None:
        """Cada enlace relativo del documento resuelve a un archivo o ancla existente."""
        # Enlaces Markdown [texto](destino) que no sean URLs absolutas.
        links = re.findall(r"\]\((?!https?://)([^)]+)\)", self.predictor)
        self.assertTrue(links, "El documento debería tener al menos un enlace relativo.")
        for link in links:
            with self.subTest(link=link):
                path_part, _, anchor = link.partition("#")
                target = (PREDICTOR.parent / path_part).resolve() if path_part else PREDICTOR
                self.assertTrue(target.is_file(), f"El enlace {link!r} no resuelve a un archivo.")
                if anchor:
                    text = target.read_text(encoding="utf-8")
                    anchors = {
                        _github_anchor(line.lstrip("#"))
                        for line in text.splitlines()
                        if line.startswith("#")
                    }
                    self.assertIn(
                        anchor,
                        anchors,
                        f"El ancla #{anchor} no existe en {target.name}.",
                    )

    def test_readme_links_to_predictor(self) -> None:
        """El README enlaza con una ruta relativa al Documento_Predictor existente."""
        links = re.findall(r"\]\((?!https?://)([^)]+)\)", self.readme)
        relative = [link.partition("#")[0] for link in links]
        self.assertIn(
            "docs/modelo_predictor.md",
            relative,
            "El README no enlaza a docs/modelo_predictor.md.",
        )
        target = (README.parent / "docs" / "modelo_predictor.md").resolve()
        self.assertTrue(target.is_file(), "El enlace del README no resuelve al documento.")


if __name__ == "__main__":
    unittest.main()
