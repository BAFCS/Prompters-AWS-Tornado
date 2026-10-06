"""Catálogo único de lo que puede mostrar un panel de la página Mapas: ERA5, bandas GOES y derivados.

Cada producto tiene una clave con prefijo de fuente (``idx:``, ``sfc:``, ``pl:``, ``goes:`` o ``rgb:``)
para que ERA5 y GOES convivan en una sola lista sin que choquen los nombres de variable.
"""

from dataclasses import dataclass

from visor_app import componentes, datos

DIVERGENTES = {"u", "v", "w", "vo", "d", "10u", "10v", "100u", "100v", "srh_01", "srh_03", "stp_lm"}
OCULTOS = {"u_lm", "v_lm", "u_rm", "v_rm", "u_06", "v_06", "altura_sfc"}
RANGOS = {  # rangos fijos para comparar horas y días; el resto usa percentiles 1–99
    "vgp_01": (0.0, 0.3), "srh_01": (-300.0, 300.0), "srh_03": (-600.0, 600.0),
    "cizalle_01": (0.0, 25.0), "cizalle_03": (0.0, 35.0), "cizalle_06": (0.0, 45.0),
    "stp_lm": (-1.5, 1.5), "sherbs3": (0.0, 2.0), "lcl": (0.0, 2500.0),
}  # fmt: skip
RANGO_GOES = {
    **dict.fromkeys(range(1, 7), (0.0, 1.0)),
    7: (200.0, 320.0), 8: (200.0, 250.0), 9: (205.0, 265.0), 10: (210.0, 275.0),
    **dict.fromkeys(range(11, 17), (190.0, 300.0)),
}  # fmt: skip
DERIVADOS = {  # clave → (etiqueta, bandas que necesita)
    "rgb:airmass": ("RGB Airmass", {"C08", "C10", "C12", "C13"}),
    "goes:dT": ("Enfriamiento del tope en 10 min (ΔC13)", {"C13"}),
    "goes:C08-C13": ("C08 − C13 (tope en la tropopausa)", {"C08", "C13"}),
}
FAVORITOS = (
    "rgb:airmass", "goes:C13", "goes:dT", "goes:C08-C13", "goes:C02",
    "idx:vgp_01", "idx:srh_01", "idx:stp_lm", "idx:sherbs3", "idx:cizalle_01", "idx:lcl",
)  # fmt: skip


@dataclass(frozen=True)
class Producto:
    """Un producto elegible para un panel: su clave, cómo se nombra y a qué grupo pertenece."""

    clave: str
    etiqueta: str  # para la lista: "Índices · VGP₀₋₁ [m/s²]"
    corta: str  # para títulos y botones: "VGP₀₋₁"
    grupo: str  # "Índices", "Superficie", "Presión", "GOES bandas" o "GOES derivados"

    @property
    def fuente(self) -> str:
        """Prefijo de la clave: ``idx``, ``sfc``, ``pl``, ``goes`` o ``rgb``."""
        return self.clave.partition(":")[0]

    @property
    def variable(self) -> str:
        """La clave sin el prefijo (nombre de la variable, banda o derivado)."""
        return self.clave.partition(":")[2]

    @property
    def es_goes(self) -> bool:
        """Si el producto sale de las imágenes GOES (banda, derivado o RGB)."""
        return self.fuente in {"goes", "rgb"}


def catalogo(d: datos.Dia) -> dict[str, Producto]:
    """Productos disponibles el día ``d``: índices, superficie, presión, bandas GOES y derivados."""
    out: dict[str, Producto] = {}
    for prefijo, ruta, grupo in (("idx", d.idx, "Índices"), ("sfc", d.sfc, "Superficie"),
                                 ("pl", d.pl, "Presión")):  # fmt: skip
        if ruta is None:
            continue
        ds = datos.abre(ruta)
        for v in map(str, ds.data_vars):
            if v in OCULTOS:
                continue
            a = ds[v].attrs
            nombre = componentes.CORTOS.get(v) or str(a.get("long_name", v))
            u = componentes.unidad(str(a.get("units", "")))
            clave = f"{prefijo}:{v}"
            out[clave] = Producto(
                clave, f"{grupo} · {nombre}" + (f" [{u}]" if u else ""), nombre, grupo
            )
    if d.goes:
        ds = datos.abre(d.goes[0])
        bandas = [str(b) for b in ds.data_vars]
        for b in bandas:
            um = str(ds[b].attrs.get("longitud_onda_um", "")).replace(".", ",")
            out[f"goes:{b}"] = Producto(
                f"goes:{b}", f"GOES · {b} · {um} µm", f"{b} {um} µm", "GOES bandas"
            )
        for clave, (etiqueta, necesita) in DERIVADOS.items():
            if necesita <= set(bandas):
                corta = etiqueta.split(" (")[0]
                out[clave] = Producto(clave, f"GOES · {etiqueta}", corta, "GOES derivados")
    return out


def ordenados(cat: dict[str, Producto]) -> list[str]:
    """Claves del catálogo con los favoritos primero, en el orden de ``FAVORITOS``."""
    fav = [k for k in FAVORITOS if k in cat]
    return [*fav, *[k for k in cat if k not in fav]]


def vecino(clave: str, cat: dict[str, Producto], paso: int) -> str:
    """El producto anterior (``paso=-1``) o siguiente (``+1``) del mismo grupo, en orden circular."""
    grupo = [k for k, p in cat.items() if p.grupo == cat[clave].grupo]
    return grupo[(grupo.index(clave) + paso) % len(grupo)]
