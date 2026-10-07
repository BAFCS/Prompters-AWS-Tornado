"""Datos de un panel a una hora: la matriz (o el RGB) que la grilla de Mapas dibuja por producto.

Separa el cálculo del dibujo: ``capa`` devuelve valores, escala y rango; ``graficos.grilla`` los pinta.
"""

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from visor_app import componentes, datos, escalas, graficos, productos

# Receta Airmass (EUMETSAT/CIRA): (banda, banda que se resta, valor para 0, valor para 255), gamma 1.
# El azul va de 243,9 a 208,5 K: C08 invertido, los topes y el aire frío salen azules.
AIRMASS = (("C08", "C10", -26.2, 0.6), ("C12", "C13", -43.2, 6.7), ("C08", None, 243.9, 208.5))


@dataclass(frozen=True)
class Capa:
    """Lo que dibuja un panel: valores sobre (lat, lon), título, unidad, escala y rango de color."""

    z: np.ndarray  # 2D con valores, o 3D uint8 (nlat, nlon, 3) si es RGB
    lat: np.ndarray
    lon: np.ndarray
    titulo: str
    unidad: str = ""
    escala: str | None = None  # nombre plotly; se resuelve con ``tipo`` si falta
    tipo: str | None = None  # tipo de dato de ``escalas.TIPOS``; ``None`` en RGB
    rango: tuple[float, float] = (0.0, 1.0)
    centro: bool = False
    umbral: float | None = None
    nota: str | None = None  # advertencia para el pie de la página

    def __post_init__(self) -> None:
        """Sin escala explícita, usa la predeterminada del tipo de dato."""
        if self.escala is None and self.tipo is not None:
            object.__setattr__(self, "escala", escalas.elige(self.tipo, None).nombre)

    def con_escala(self, nombre: str | None) -> "Capa":
        """La misma capa con la escala ``nombre`` (o la predeterminada si no vale para su tipo)."""
        if self.tipo is None:
            return self
        return dataclasses.replace(self, escala=escalas.elige(self.tipo, nombre).nombre)

    @property
    def es_rgb(self) -> bool:
        """Si ``z`` es una imagen RGB en vez de un campo de valores."""
        return self.z.ndim == 3


def _rango(z: np.ndarray, centro: bool) -> tuple[float, float]:
    """Rango de color entre los percentiles 1 y 99 de ``z`` (simétrico si ``centro``)."""
    lo, hi = np.nanpercentile(z, [1, 99])
    if centro:
        m = float(max(abs(lo), abs(hi)))
        return -m, m
    return float(lo), float(hi)


def vacia(titulo: str, enc: graficos.Encuadre) -> Capa:
    """Panel sin datos (p. ej. ΔC13 sin imagen anterior): conserva su lugar y su título en la grilla."""
    return Capa(np.full((2, 2), np.nan), np.array([enc.norte, enc.sur]),
                np.array([enc.oeste, enc.este]), titulo)  # fmt: skip


def niveles(d: datos.Dia) -> list[float]:
    """Niveles de presión del día, de superficie hacia arriba (vacío si no hay niveles de presión)."""
    if d.pl is None:
        return []
    return sorted(datos.abre(d.pl)["level"].values.tolist(), reverse=True)


def airmass(ds: xr.Dataset, ti: np.datetime64) -> np.ndarray:
    """Imagen RGB Airmass ``uint8`` (nlat, nlon, 3) de la hora ``ti`` de ``ds``; NaN queda en negro."""
    canales = []
    for a, b, v0, v1 in AIRMASS:
        x = ds[a].sel(time=ti).values.astype(np.float32)
        if b is not None:
            x = x - ds[b].sel(time=ti).values
        canales.append(np.clip((x - v0) / (v1 - v0), 0.0, 1.0))
    rgb = np.nan_to_num(np.stack(canales, axis=-1), nan=0.0)
    return (rgb * 255).round().astype(np.uint8)


def _era5(d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, nivel: float | None) -> Capa:
    """Campo ERA5 de ``prod`` a la hora en punto más cercana a ``t`` (en ``nivel`` si es de presión)."""
    ruta = {"idx": d.idx, "sfc": d.sfc, "pl": d.pl}[prod.fuente]
    assert ruta is not None
    ds = datos.abre(ruta)
    v = prod.variable
    da = ds[v].sel(time=t, method="nearest")
    titulo = f"{prod.corta} · {datos.instante(da['time']):%H:%M}"
    nota = None
    if "level" in da.dims:
        nv = niveles(d)
        nivel = nivel if nivel in nv else (850.0 if 850.0 in nv else nv[0])
        da = da.sel(level=nivel)
        titulo += f" · {nivel:g} hPa"
        nota = "Sobre los Andes, algunos niveles de presión pueden estar bajo el terreno; sus valores son extrapolados."
    centro = v in productos.DIVERGENTES
    z = da.values
    umbral = ds[v].attrs.get("umbral_chile")
    return Capa(
        z, ds["latitude"].values, ds["longitude"].values, titulo,
        unidad=componentes.unidad(str(ds[v].attrs.get("units", ""))),
        tipo=prod.tipo,
        rango=productos.RANGOS.get(v) or _rango(z, centro), centro=centro,
        umbral=None if umbral is None else float(umbral), nota=nota,
    )  # fmt: skip


def _goes(d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, sub: int) -> Capa | None:
    """Producto GOES en la imagen más cercana a ``t``, submuestreado ``sub``; ``None`` si falta imagen."""
    img = datos.imagen_en(d, t)
    if img is None:
        return None
    ruta, ti = img
    ds = datos.abre(ruta)
    lat, lon = ds["latitude"].values[::sub], ds["longitude"].values[::sub]
    hora = pd.Timestamp(ti)
    v = prod.variable
    if v == "airmass":
        return Capa(airmass(ds, ti)[::sub, ::sub], lat, lon, f"{prod.corta} · {hora:%H:%M}")
    if v == "dT":
        prev = datos.anterior(d, ti)
        if prev is None:
            return None
        r0, t0 = prev
        z = ds["C13"].sel(time=ti).values - datos.abre(r0)["C13"].sel(time=t0).values
        minutos = (hora - pd.Timestamp(t0)).total_seconds() / 60
        return Capa(z[::sub, ::sub], lat, lon, f"ΔC13 en {minutos:.0f} min · {hora:%H:%M}",
                    unidad="K", tipo=prod.tipo, rango=(-15.0, 15.0), centro=True)  # fmt: skip
    if v == "C08-C13":
        z = ds["C08"].sel(time=ti).values - ds["C13"].sel(time=ti).values
        return Capa(z[::sub, ::sub], lat, lon, f"C08 − C13 · {hora:%H:%M}", unidad="K",
                    tipo=prod.tipo, rango=(-40.0, 5.0))  # fmt: skip
    n = int(v[1:])
    return Capa(
        ds[v].sel(time=ti).values[::sub, ::sub], lat, lon, f"{prod.corta} · {hora:%H:%M}",
        unidad=componentes.unidad(str(ds[v].attrs.get("units", ""))),
        tipo=prod.tipo, rango=productos.RANGO_GOES[n],
    )  # fmt: skip


def capa(
    d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, *, sub: int = 1,
    nivel: float | None = None,
) -> Capa | None:  # fmt: skip
    """La capa de ``prod`` a la hora ``t``; ``None`` si GOES no tiene la imagen que hace falta."""
    if prod.es_goes:
        return _goes(d, prod, t, sub)
    return _era5(d, prod, t, nivel)


def viento_850(
    d: datos.Dia, t: pd.Timestamp, enc: graficos.Encuadre
) -> tuple[list[float | None], list[float | None]] | None:
    """Flechas del viento en 850 hPa (una de cada tres celdas) como líneas x/y separadas por ``None``."""
    if d.pl is None:
        return None
    h = datos.abre(d.pl).sel(time=t, method="nearest").sel(level=850, method="nearest")
    h = h.sel(latitude=slice(enc.norte, enc.sur), longitude=slice(enc.oeste, enc.este))
    u, v = h["u"].values[::3, ::3], h["v"].values[::3, ::3]
    LA, LO = np.meshgrid(h["latitude"].values[::3], h["longitude"].values[::3], indexing="ij")
    k = 0.018  # grados por m/s
    xs: list[float | None] = []
    ys: list[float | None] = []
    for x0, y0, du, dv in zip(LO.ravel(), LA.ravel(), u.ravel(), v.ravel(), strict=True):
        x1, y1 = x0 + du * k, y0 + dv * k
        ang = np.arctan2(dv, du)
        ala = 0.25 * np.hypot(du, dv) * k
        xs += [x0, x1, x1 - ala * np.cos(ang - 0.45), None, x1, x1 - ala * np.cos(ang + 0.45), None]
        ys += [y0, y1, y1 - ala * np.sin(ang - 0.45), None, y1, y1 - ala * np.sin(ang + 0.45), None]
    return xs, ys
