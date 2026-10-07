"""Catálogo único de lo que puede mostrar un panel de la página Mapas: ERA5, bandas GOES y derivados.

Cada producto tiene una clave con prefijo de fuente (``idx:``, ``sfc:``, ``pl:``, ``goes:`` o ``rgb:``)
para que ERA5 y GOES convivan en una sola lista sin que choquen los nombres de variable.
"""

from dataclasses import dataclass

from viewer_app import components, data

DIVERGING = {"u", "v", "w", "vo", "d", "10u", "10v", "100u", "100v", "srh_01", "srh_03", "stp_lm"}
HIDDEN = {"u_lm", "v_lm", "u_rm", "v_rm", "u_06", "v_06", "sfc_height"}
RANGES = {  # rangos fijos para comparar horas y días; el resto usa percentiles 1–99
    "vgp_01": (0.0, 0.3), "srh_01": (-300.0, 300.0), "srh_03": (-600.0, 600.0),
    "shear_01": (0.0, 25.0), "shear_03": (0.0, 35.0), "shear_06": (0.0, 45.0),
    "stp_lm": (-1.5, 1.5), "sherbs3": (0.0, 2.0), "lcl": (0.0, 2500.0),
}  # fmt: skip
GOES_RANGES = {
    **dict.fromkeys(range(1, 7), (0.0, 1.0)),
    7: (200.0, 320.0), 8: (200.0, 250.0), 9: (205.0, 265.0), 10: (210.0, 275.0),
    **dict.fromkeys(range(11, 17), (190.0, 300.0)),
}  # fmt: skip
DERIVED = {  # clave → (etiqueta, bandas que necesita)
    "rgb:airmass": ("RGB Airmass", {"C08", "C10", "C12", "C13"}),
    "goes:dT": ("Cambio de temperatura de brillo entre imágenes (ΔC13)", {"C13"}),
    "goes:C08-C13": ("Diferencia de temperatura de brillo C08 − C13", {"C08", "C13"}),
}
FAVORITES = (
    "rgb:airmass", "goes:C13", "goes:dT", "goes:C08-C13", "goes:C02",
    "idx:vgp_01", "idx:srh_01", "idx:stp_lm", "idx:sherbs3", "idx:shear_01", "idx:lcl",
)  # fmt: skip


@dataclass(frozen=True)
class Product:
    """Un producto elegible para un panel: su clave, cómo se nombra y a qué grupo pertenece."""

    key: str
    label: str  # para la lista: "Índices · VGP₀₋₁ [m/s²]"
    short: str  # para títulos y botones: "VGP₀₋₁"
    group: str  # "Índices", "Superficie", "Presión", "GOES bandas" o "GOES derivados"

    @property
    def source(self) -> str:
        """Prefijo de la clave: ``idx``, ``sfc``, ``pl``, ``goes`` o ``rgb``."""
        return self.key.partition(":")[0]

    @property
    def variable(self) -> str:
        """La clave sin el prefijo (nombre de la variable, banda o derivado)."""
        return self.key.partition(":")[2]

    @property
    def is_goes(self) -> bool:
        """Si el producto sale de las imágenes GOES (banda, derivado o RGB)."""
        return self.source in {"goes", "rgb"}

    @property
    def kind(self) -> str | None:
        """Tipo de dato que decide sus escalas de color (``colorscales.KINDS``); ``None`` si es RGB."""
        v = self.variable
        if self.source == "rgb":
            return None
        if v in DIVERGING or v == "dT":
            return "diverging"
        if self.source == "goes" and v.startswith("C") and v[1:].isdigit():
            return "visible" if int(v[1:]) <= 6 else "infrared"
        return "sequential"


def catalog(d: data.Day) -> dict[str, Product]:
    """Productos disponibles el día ``d``: índices, superficie, presión, bandas GOES y derivados."""
    out: dict[str, Product] = {}
    for prefix, path, group in (("idx", d.idx, "Índices"), ("sfc", d.sfc, "Superficie"),
                                 ("pl", d.pl, "Presión")):  # fmt: skip
        if path is None:
            continue
        ds = data.open_nc(path)
        for v in map(str, ds.data_vars):
            if v in HIDDEN:
                continue
            a = ds[v].attrs
            name = components.SHORT_NAMES.get(v) or str(a.get("long_name", v))
            u = components.unit(str(a.get("units", "")))
            key = f"{prefix}:{v}"
            out[key] = Product(key, f"{group} · {name}" + (f" [{u}]" if u else ""), name, group)
    if d.goes:
        ds = data.open_nc(d.goes[0])
        bands = [str(b) for b in ds.data_vars]
        for b in bands:
            um = str(ds[b].attrs.get("wavelength_um", "")).replace(".", ",")
            out[f"goes:{b}"] = Product(
                f"goes:{b}", f"GOES · {b} · {um} µm", f"{b} {um} µm", "GOES bandas"
            )
        for key, (label, needs) in DERIVED.items():
            if needs <= set(bands):
                short = label.split(" (")[0]
                out[key] = Product(key, f"GOES · {label}", short, "GOES derivados")
    return out


def sorted_keys(cat: dict[str, Product]) -> list[str]:
    """Claves del catálogo con los favoritos primero, en el orden de ``FAVORITES``."""
    fav = [k for k in FAVORITES if k in cat]
    return [*fav, *[k for k in cat if k not in fav]]


def neighbor(key: str, cat: dict[str, Product], step: int) -> str:
    """El producto anterior (``paso=-1``) o siguiente (``+1``) del mismo grupo, en orden circular."""
    group = [k for k, p in cat.items() if p.group == cat[key].group]
    return group[(group.index(key) + step) % len(group)]
