"""Recetas RGB versionadas y composición de Ventanas_GOES en imágenes de 8 bits (lógica pura).

El Compositor_RGB convierte temperaturas de brillo (K) en una imagen de tres canales con una receta
fija: cada canal declara la banda o diferencia de bandas, los límites inferior y superior en kelvin
y el valor de relleno de los píxeles sin dato. La normalización recorta al rango, escala lineal a
0–255 y redondea con ``np.rint`` (mitad a par). El remuestreo es por vecino más cercano, que no
crea valores nuevos, y el PNG se escribe sin metadatos ni fecha para que sea determinista byte a
byte. Solo usa NumPy y Pillow.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

MIN_SIZE = 224
MAX_SIZE = 1024
DEFAULT_SIZE = 224
PNG_COMPRESS_LEVEL = 6


@dataclass(frozen=True)
class Channel:
    """Un canal de la receta: expresión de bandas, rango en kelvin y relleno (0–255)."""

    expr: str  # "C13" o "C08-C13"
    lower_k: float
    upper_k: float  # lower_k < upper_k
    fill: int  # 0..255

    @property
    def bands(self) -> tuple[str, ...]:
        """Bandas que usa la expresión, en orden de aparición."""
        return tuple(b.strip() for b in self.expr.split("-"))


@dataclass(frozen=True)
class Recipe:
    """Receta de composición identificada por nombre y versión, con tres canales (R, G, B)."""

    name: str
    version: int
    channels: tuple[Channel, Channel, Channel]

    @property
    def bands(self) -> tuple[str, ...]:
        """Bandas distintas que necesita la receta, ordenadas."""
        return tuple(sorted({b for ch in self.channels for b in ch.bands}))

    @property
    def tag(self) -> str:
        """Identificador ``<nombre>_v<versión>`` (carpeta de salida y clave de caché)."""
        return f"{self.name}_v{self.version}"


RECIPES: dict[tuple[str, int], Recipe] = {
    ("ir_wv", 1): Recipe(
        "ir_wv",
        1,
        (
            Channel("C13", 183.15, 303.15, 0),
            Channel("C08", 193.15, 263.15, 0),
            Channel("C08-C13", -80.0, 10.0, 0),
        ),
    ),
    ("airmass", 1): Recipe(
        "airmass",
        1,
        (
            Channel("C08-C10", -26.2, 0.6, 0),
            Channel("C12-C13", -43.2, 6.7, 0),
            Channel("C08", 208.5, 243.9, 0),
        ),
    ),
}


@dataclass(frozen=True)
class ComposeResult:
    """Imagen remuestreada, matriz normalizada antes del remuestreo y fracción sin dato."""

    rgb: np.ndarray  # uint8 (size, size, 3)
    normalized: np.ndarray  # uint8 (alto, ancho, 3), antes del remuestreo
    missing_frac: float  # fracción de píxeles sin dato en algún canal


class MissingBandError(ValueError):
    """La Ventana_GOES no trae una banda que la receta necesita."""

    def __init__(self, band: str) -> None:
        """Error que nombra la banda faltante."""
        super().__init__(f"falta la banda {band}")
        self.band = band


def check_recipe(recipe: Recipe) -> Recipe:
    """Valida los canales de ``recipe``; ``ValueError`` que nombra la receta y el campo inválido."""
    where = f"receta {recipe.name!r} v{recipe.version}"
    if len(recipe.channels) != 3:
        raise ValueError(f"{where}: channels debe tener 3 canales, tiene {len(recipe.channels)}")
    for i, ch in enumerate(recipe.channels):
        tag = f"{where}, canal {i} ({ch.expr})"
        if not ch.bands or len(ch.bands) > 2 or not all(ch.bands):
            raise ValueError(f"{tag}: expr inválida {ch.expr!r} (banda o «banda-banda»)")
        if not (np.isfinite(ch.lower_k) and np.isfinite(ch.upper_k)):
            raise ValueError(f"{tag}: lower_k y upper_k deben ser finitos")
        if ch.lower_k >= ch.upper_k:
            raise ValueError(
                f"{tag}: lower_k ({ch.lower_k}) debe ser menor que upper_k ({ch.upper_k})"
            )
        if not 0 <= ch.fill <= 255:
            raise ValueError(f"{tag}: fill ({ch.fill}) debe estar entre 0 y 255")
    return recipe


def validate_recipe(
    name: str, version: int, recipes: dict[tuple[str, int], Recipe] | None = None
) -> Recipe:
    """Busca la receta ``name`` v``version`` y la valida (Req. 3.10).

    ``ValueError`` si el nombre o la versión no existen (indica las disponibles) o si algún canal
    es inválido. ``recipes`` permite pasar un catálogo distinto de ``RECIPES`` (pruebas).
    """
    table = RECIPES if recipes is None else recipes
    names = sorted({n for n, _ in table})
    if name not in names:
        raise ValueError(f"receta {name!r} inexistente (campo name); disponibles: {names}")
    versions = sorted(v for n, v in table if n == name)
    if (name, version) not in table:
        raise ValueError(
            f"receta {name!r}: versión {version} inexistente (campo version); hay {versions}"
        )
    return check_recipe(table[(name, version)])


def channel_values(bands: dict[str, np.ndarray], ch: Channel) -> np.ndarray:
    """BT (K) del canal ``ch``: una banda o la diferencia de dos; NaN donde falta alguna."""
    for b in ch.bands:
        if b not in bands:
            raise MissingBandError(b)
    first = np.asarray(bands[ch.bands[0]], dtype=np.float64)
    if len(ch.bands) == 1:
        return first
    return first - np.asarray(bands[ch.bands[1]], dtype=np.float64)


def normalize(bt: np.ndarray, ch: Channel) -> np.ndarray:
    """Recorta a [lower_k, upper_k], escala lineal a 0–255 y redondea (``np.rint``) a ``uint8``.

    Los valores no finitos (sin dato) toman el ``fill`` del canal (Req. 3.3, 3.6).
    """
    x = np.asarray(bt, dtype=np.float64)
    ok = np.isfinite(x)
    clipped = np.clip(np.where(ok, x, ch.lower_k), ch.lower_k, ch.upper_k)
    q = np.rint((clipped - ch.lower_k) / (ch.upper_k - ch.lower_k) * 255.0)
    return np.where(ok, q, ch.fill).astype(np.uint8)


def denormalize(q: np.ndarray, ch: Channel) -> np.ndarray:
    """Inversa lineal de ``normalize``: 0 → ``lower_k`` y 255 → ``upper_k`` exactos."""
    f = np.asarray(q, dtype=np.float64) / 255.0
    return ch.lower_k * (1.0 - f) + ch.upper_k * f


def valid_fractions(bands: dict[str, np.ndarray], recipe: Recipe) -> dict[str, float]:
    """Fracción de píxeles finitos de cada banda de la receta (``MissingBandError`` si falta)."""
    out: dict[str, float] = {}
    for b in recipe.bands:
        if b not in bands:
            raise MissingBandError(b)
        arr = np.asarray(bands[b], dtype=np.float64)
        out[b] = float(np.isfinite(arr).sum() / arr.size) if arr.size else 0.0
    return out


def compose(
    bands: dict[str, np.ndarray], recipe: Recipe, size: int = DEFAULT_SIZE
) -> ComposeResult:
    """Compone la Ventana_GOES ``bands`` (banda → BT 2D en K) con ``recipe`` a ``size`` × ``size``.

    Normaliza cada canal (relleno donde no hay dato), registra la fracción de píxeles sin dato en
    algún canal y remuestrea por vecino más cercano (Req. 3.1, 3.6).
    """
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f"size ({size}) debe estar entre {MIN_SIZE} y {MAX_SIZE}")
    values = [channel_values(bands, ch) for ch in recipe.channels]
    shape = values[0].shape
    if len(shape) != 2 or 0 in shape or any(v.shape != shape for v in values):
        raise ValueError(f"las bandas deben ser 2D, no vacías y de igual forma: {shape}")
    missing = np.zeros(shape, dtype=bool)
    for v in values:
        missing |= ~np.isfinite(v)
    normalized = np.stack(
        [normalize(v, ch) for v, ch in zip(values, recipe.channels, strict=True)], axis=-1
    )
    img = Image.fromarray(np.ascontiguousarray(normalized))
    rgb = np.asarray(img.resize((size, size), Image.Resampling.NEAREST), dtype=np.uint8)
    return ComposeResult(rgb, normalized, float(missing.mean()))


def to_png_bytes(rgb: np.ndarray) -> bytes:
    """PNG determinista de ``rgb`` (``uint8`` H × W × 3): sin metadatos, ``compress_level=6``."""
    arr = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"se espera un arreglo H × W × 3, no {arr.shape}")
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", compress_level=PNG_COMPRESS_LEVEL, optimize=False)
    return buf.getvalue()
