"""Escalas de color estándar de los mapas, elegidas según el tipo de dato y cambiables por gráfico.

Cada tipo de dato tiene su lista de escalas con nombre de plotly (Viridis, ColorBrewer, cmocean); la
primera es la predeterminada. Las marcadas ``colorblind_safe`` son perceptualmente uniformes o de
ColorBrewer «colorblind safe» y se leen igual con deuteranopía, protanopía o tritanopía.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Colorscale:
    """Una escala estándar: su nombre en plotly, cómo se muestra y si sirve con daltonismo."""

    name: str  # nombre de plotly; el sufijo ``_r`` la invierte
    label: str
    colorblind_safe: bool

    @property
    def display_label(self) -> str:
        """Texto de la lista: la etiqueta con su aptitud para daltonismo."""
        return f"{self.label} · {'apta' if self.colorblind_safe else 'no apta'} para daltonismo"


# Orden: la predeterminada primero, luego las aptas para daltonismo y al final las que no lo son.
KINDS: dict[str, tuple[Colorscale, ...]] = {
    # Magnitudes que crecen desde cero (VGP, cizalladura, CAPE, LCL, C08 − C13).
    "sequential": (
        Colorscale("Viridis", "Viridis", True),
        Colorscale("Cividis", "Cividis", True),
        Colorscale("Plasma", "Plasma", True),
        Colorscale("Magma", "Magma", True),
        Colorscale("YlGnBu", "Amarillo-verde-azul (ColorBrewer)", True),
        Colorscale("Turbo", "Turbo", False),
    ),
    # Campos con signo centrados en cero (SRH, STP, viento, vorticidad, ΔC13). Sin rojo por defecto,
    # porque el rojo marca los eventos del catálogo.
    "diverging": (
        Colorscale("PuOr", "Púrpura-naranja (ColorBrewer)", True),
        Colorscale("RdBu_r", "Azul-rojo (ColorBrewer)", True),
        Colorscale("BrBG", "Marrón-verde azulado (ColorBrewer)", True),
        Colorscale("balance", "Balance (cmocean)", True),
        Colorscale("Picnic", "Picnic", False),
    ),
    # Infrarrojo (temperatura de brillo): por convención los topes fríos se ven blancos.
    "infrared": (
        Colorscale("Greys", "Grises, fríos en blanco", True),
        Colorscale("Cividis_r", "Cividis invertida", True),
        Colorscale("Viridis_r", "Viridis invertida", True),
        Colorscale("ice_r", "Hielo invertida (cmocean)", True),
        Colorscale("Turbo_r", "Turbo invertida", False),
    ),
    # Reflectancia visible: más brillante, más blanco.
    "visible": (
        Colorscale("gray", "Grises", True),
        Colorscale("Cividis", "Cividis", True),
    ),
}


def pick(kind: str, name: str | None) -> Colorscale:
    """La escala ``name`` si es válida para ``kind``; si no, la predeterminada del tipo."""
    for e in KINDS[kind]:
        if e.name == name:
            return e
    return KINDS[kind][0]
