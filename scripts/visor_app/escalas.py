"""Escalas de color estándar de los mapas, elegidas según el tipo de dato y cambiables por gráfico.

Cada tipo de dato tiene su lista de escalas con nombre de plotly (Viridis, ColorBrewer, cmocean); la
primera es la predeterminada. Las marcadas ``daltonismo`` son perceptualmente uniformes o de
ColorBrewer «colorblind safe» y se leen igual con deuteranopía, protanopía o tritanopía.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Escala:
    """Una escala estándar: su nombre en plotly, cómo se muestra y si sirve con daltonismo."""

    nombre: str  # nombre de plotly; el sufijo ``_r`` la invierte
    etiqueta: str
    daltonismo: bool

    @property
    def rotulo(self) -> str:
        """Texto de la lista: la etiqueta con su aptitud para daltonismo."""
        return f"{self.etiqueta} · {'apta' if self.daltonismo else 'no apta'} para daltonismo"


# Orden: la predeterminada primero, luego las aptas para daltonismo y al final las que no lo son.
TIPOS: dict[str, tuple[Escala, ...]] = {
    # Magnitudes que crecen desde cero (VGP, cizalle, CAPE, LCL, C08 − C13).
    "secuencial": (
        Escala("Viridis", "Viridis", True),
        Escala("Cividis", "Cividis", True),
        Escala("Plasma", "Plasma", True),
        Escala("Magma", "Magma", True),
        Escala("YlGnBu", "Amarillo-verde-azul (ColorBrewer)", True),
        Escala("Turbo", "Turbo", False),
    ),
    # Campos con signo centrados en cero (SRH, STP, viento, vorticidad, ΔC13). Sin rojo por defecto,
    # porque el rojo marca los eventos del catálogo.
    "divergente": (
        Escala("PuOr", "Púrpura-naranja (ColorBrewer)", True),
        Escala("RdBu_r", "Azul-rojo (ColorBrewer)", True),
        Escala("BrBG", "Marrón-verde azulado (ColorBrewer)", True),
        Escala("balance", "Balance (cmocean)", True),
        Escala("Picnic", "Picnic", False),
    ),
    # Infrarrojo (temperatura de brillo): por convención los topes fríos se ven blancos.
    "infrarrojo": (
        Escala("Greys", "Grises, fríos en blanco", True),
        Escala("Cividis_r", "Cividis invertida", True),
        Escala("Viridis_r", "Viridis invertida", True),
        Escala("ice_r", "Hielo invertida (cmocean)", True),
        Escala("Turbo_r", "Turbo invertida", False),
    ),
    # Reflectancia visible: más brillante, más blanco.
    "visible": (
        Escala("gray", "Grises", True),
        Escala("Cividis", "Cividis", True),
    ),
}


def opciones(tipo: str) -> tuple[Escala, ...]:
    """Las escalas disponibles para un tipo de dato."""
    return TIPOS[tipo]


def elige(tipo: str, nombre: str | None) -> Escala:
    """La escala ``nombre`` si es válida para ``tipo``; si no, la predeterminada del tipo."""
    for e in TIPOS[tipo]:
        if e.nombre == nombre:
            return e
    return TIPOS[tipo][0]
