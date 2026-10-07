"""Datos de un panel a una hora: la matriz (o el RGB) que la grilla de Mapas dibuja por producto.

Separa el cálculo del dibujo: ``layer`` devuelve valores, escala y rango; ``charts.grid`` los pinta.
"""

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from viewer_app import charts, colorscales, components, data, products

# Receta Airmass (EUMETSAT/CIRA): (banda, banda que se resta, valor para 0, valor para 255), gamma 1.
# El azul va de 243,9 a 208,5 K: C08 invertido, los topes y el aire frío salen azules.
AIRMASS = (("C08", "C10", -26.2, 0.6), ("C12", "C13", -43.2, 6.7), ("C08", None, 243.9, 208.5))


@dataclass(frozen=True)
class Layer:
    """Lo que dibuja un panel: valores sobre (lat, lon), título, unidad, escala y rango de color."""

    z: np.ndarray  # 2D con valores, o 3D uint8 (nlat, nlon, 3) si es RGB
    lat: np.ndarray
    lon: np.ndarray
    title: str
    unit: str = ""
    colorscale: str | None = None  # nombre plotly; se resuelve con ``kind`` si falta
    kind: str | None = None  # tipo de dato de ``colorscales.KINDS``; ``None`` en RGB
    color_range: tuple[float, float] = (0.0, 1.0)
    centered: bool = False
    threshold: float | None = None
    note: str | None = None  # advertencia para el pie de la página

    def __post_init__(self) -> None:
        """Sin escala explícita, usa la predeterminada del tipo de dato."""
        if self.colorscale is None and self.kind is not None:
            object.__setattr__(self, "colorscale", colorscales.pick(self.kind, None).name)

    def with_colorscale(self, name: str | None) -> "Layer":
        """La misma capa con la escala ``name`` (o la predeterminada si no vale para su tipo)."""
        if self.kind is None:
            return self
        return dataclasses.replace(self, colorscale=colorscales.pick(self.kind, name).name)

    @property
    def is_rgb(self) -> bool:
        """Si ``z`` es una imagen RGB en vez de un campo de valores."""
        return self.z.ndim == 3


def _percentile_range(z: np.ndarray, centered: bool) -> tuple[float, float]:
    """Rango de color entre los percentiles 1 y 99 de ``z`` (simétrico si ``centered``)."""
    lo, hi = np.nanpercentile(z, [1, 99])
    if centered:
        m = float(max(abs(lo), abs(hi)))
        return -m, m
    return float(lo), float(hi)


def empty_layer(title: str, enc: charts.Extent) -> Layer:
    """Panel sin datos (p. ej. ΔC13 sin imagen anterior): conserva su lugar y su título en la grilla."""
    return Layer(np.full((2, 2), np.nan), np.array([enc.north, enc.south]),
                np.array([enc.west, enc.east]), title)  # fmt: skip


def levels(d: data.Day) -> list[float]:
    """Niveles de presión del día, de superficie hacia arriba (vacío si no hay niveles de presión)."""
    if d.pl is None:
        return []
    return sorted(data.open_nc(d.pl)["level"].values.tolist(), reverse=True)


def airmass(ds: xr.Dataset, ti: np.datetime64) -> np.ndarray:
    """Imagen RGB Airmass ``uint8`` (nlat, nlon, 3) de la hora ``ti`` de ``ds``; NaN queda en negro."""
    channels = []
    for a, b, v0, v1 in AIRMASS:
        x = ds[a].sel(time=ti).values.astype(np.float32)
        if b is not None:
            x = x - ds[b].sel(time=ti).values
        channels.append(np.clip((x - v0) / (v1 - v0), 0.0, 1.0))
    rgb = np.nan_to_num(np.stack(channels, axis=-1), nan=0.0)
    return (rgb * 255).round().astype(np.uint8)


def _era5(d: data.Day, prod: products.Product, t: pd.Timestamp, level: float | None) -> Layer:
    """Campo ERA5 de ``prod`` a la hora en punto más cercana a ``t`` (en ``level`` si es de presión)."""
    path = {"idx": d.idx, "sfc": d.sfc, "pl": d.pl}[prod.source]
    assert path is not None
    ds = data.open_nc(path)
    v = prod.variable
    da = ds[v].sel(time=t, method="nearest")
    title = f"{prod.short} · {data.to_timestamp(da['time']):%H:%M}"
    note = None
    if "level" in da.dims:
        nv = levels(d)
        level = level if level in nv else (850.0 if 850.0 in nv else nv[0])
        da = da.sel(level=level)
        title += f" · {level:g} hPa"
        note = "Sobre los Andes, algunos niveles de presión pueden estar bajo el terreno; sus valores son extrapolados."
    centered = v in products.DIVERGING
    z = da.values
    threshold = ds[v].attrs.get("threshold_chile")
    return Layer(
        z, ds["latitude"].values, ds["longitude"].values, title,
        unit=components.unit(str(ds[v].attrs.get("units", ""))),
        kind=prod.kind,
        color_range=products.RANGES.get(v) or _percentile_range(z, centered), centered=centered,
        threshold=None if threshold is None else float(threshold), note=note,
    )  # fmt: skip


def _goes(d: data.Day, prod: products.Product, t: pd.Timestamp, sub: int) -> Layer | None:
    """Producto GOES en la imagen más cercana a ``t``, submuestreado ``sub``; ``None`` si falta imagen."""
    img = data.image_at(d, t)
    if img is None:
        return None
    path, ti = img
    ds = data.open_nc(path)
    lat, lon = ds["latitude"].values[::sub], ds["longitude"].values[::sub]
    hour = pd.Timestamp(ti)
    v = prod.variable
    if v == "airmass":
        return Layer(airmass(ds, ti)[::sub, ::sub], lat, lon, f"{prod.short} · {hour:%H:%M}")
    if v == "dT":
        prev = data.previous(d, ti)
        if prev is None:
            return None
        r0, t0 = prev
        z = ds["C13"].sel(time=ti).values - data.open_nc(r0)["C13"].sel(time=t0).values
        minutes = (hour - pd.Timestamp(t0)).total_seconds() / 60
        return Layer(z[::sub, ::sub], lat, lon, f"ΔC13 en {minutes:.0f} min · {hour:%H:%M}",
                    unit="K", kind=prod.kind, color_range=(-15.0, 15.0), centered=True)  # fmt: skip
    if v == "C08-C13":
        z = ds["C08"].sel(time=ti).values - ds["C13"].sel(time=ti).values
        return Layer(z[::sub, ::sub], lat, lon, f"C08 − C13 · {hour:%H:%M}", unit="K",
                    kind=prod.kind, color_range=(-40.0, 5.0))  # fmt: skip
    n = int(v[1:])
    return Layer(
        ds[v].sel(time=ti).values[::sub, ::sub], lat, lon, f"{prod.short} · {hour:%H:%M}",
        unit=components.unit(str(ds[v].attrs.get("units", ""))),
        kind=prod.kind, color_range=products.GOES_RANGES[n],
    )  # fmt: skip


def layer(
    d: data.Day, prod: products.Product, t: pd.Timestamp, *, sub: int = 1,
    level: float | None = None,
) -> Layer | None:  # fmt: skip
    """La capa de ``prod`` a la hora ``t``; ``None`` si GOES no tiene la imagen que hace falta."""
    if prod.is_goes:
        return _goes(d, prod, t, sub)
    return _era5(d, prod, t, level)


def wind_850(
    d: data.Day, t: pd.Timestamp, enc: charts.Extent
) -> tuple[list[float | None], list[float | None]] | None:
    """Flechas del viento en 850 hPa (una de cada tres celdas) como líneas x/y separadas por ``None``."""
    if d.pl is None:
        return None
    h = data.open_nc(d.pl).sel(time=t, method="nearest").sel(level=850, method="nearest")
    h = h.sel(latitude=slice(enc.north, enc.south), longitude=slice(enc.west, enc.east))
    u, v = h["u"].values[::3, ::3], h["v"].values[::3, ::3]
    LA, LO = np.meshgrid(h["latitude"].values[::3], h["longitude"].values[::3], indexing="ij")
    k = 0.018  # grados por m/s
    xs: list[float | None] = []
    ys: list[float | None] = []
    for x0, y0, du, dv in zip(LO.ravel(), LA.ravel(), u.ravel(), v.ravel(), strict=True):
        x1, y1 = x0 + du * k, y0 + dv * k
        ang = np.arctan2(dv, du)
        head = 0.25 * np.hypot(du, dv) * k
        xs += [
            x0,
            x1,
            x1 - head * np.cos(ang - 0.45),
            None,
            x1,
            x1 - head * np.cos(ang + 0.45),
            None,
        ]
        ys += [
            y0,
            y1,
            y1 - head * np.sin(ang - 0.45),
            None,
            y1,
            y1 - head * np.sin(ang + 0.45),
            None,
        ]
    return xs, ys
