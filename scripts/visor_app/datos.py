"""Acceso a los datos del visor: recortes ERA5/GOES, índices, catálogo de eventos y costa.

Todo lo que lee disco pasa por aquí y se cachea con Streamlit. Las listas de archivos no se cachean
(se relistan en cada ejecución), así que lo que se va descargando aparece al recargar la página.
"""

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import streamlit as st
import xarray as xr
from shapely.geometry import box

import comun


@dataclass(frozen=True)
class Dia:
    """Archivos disponibles de un día en una región: ERA5, índices y las horas GOES reproyectadas."""

    fecha: dt.date
    pl: Path | None
    sfc: Path | None
    idx: Path | None
    goes: tuple[Path, ...]


def regiones() -> list[str]:
    """Regiones con recortes en ``data/recortes/``."""
    return sorted(p.name for p in comun.RECORTES.glob("*") if p.is_dir())


def region(nombre: str) -> comun.Region | None:
    """La región predefinida ``nombre``, o ``None`` si es una región a medida (``--bbox``)."""
    return comun.REGIONES.get(nombre)


def _fecha(p: Path) -> dt.date:
    """Fecha ``AAAAMMDD`` que aparece en el nombre de ``p``."""
    return dt.datetime.strptime(re.findall(r"\d{8}", p.name)[-1], "%Y%m%d").date()


def dias(nombre: str) -> dict[dt.date, Dia]:
    """Todos los días con algún dato en la región ``nombre``, ordenados por fecha."""
    base = comun.RECORTES / nombre

    def por_fecha(patron: str) -> dict[dt.date, Path]:
        """Archivos que calzan con ``patron`` (glob relativo a la región), indexados por fecha."""
        return {_fecha(p): p for p in base.glob(patron)}

    pl, sfc = por_fecha("era5_pl/*.nc"), por_fecha("era5_sfc/*.nc")
    idx, goes = por_fecha("era5_indices/*.nc"), por_fecha("goes_latlon/*")
    fechas = sorted(set(pl) | set(sfc) | set(idx) | set(goes))
    return {
        f: Dia(
            f,
            pl.get(f),
            sfc.get(f),
            idx.get(f),
            tuple(sorted(goes[f].glob("goes_*.nc"))) if f in goes else (),
        )  # fmt: skip
        for f in fechas
    }


@st.cache_resource
def _abre(ruta: Path, version: float) -> xr.Dataset:
    """Abre el NetCDF ``ruta`` sin cargarlo; ``version`` (mtime) solo separa entradas de caché."""
    return xr.open_dataset(ruta, engine="h5netcdf")


def abre(ruta: Path) -> xr.Dataset:
    """Abre (una vez por versión del archivo) el NetCDF ``ruta``, sin cargarlo a memoria.

    La fecha de modificación entra en la clave de caché: si una descarga reemplaza el archivo,
    se abre el nuevo en vez de seguir sirviendo el viejo.
    """
    return _abre(ruta, ruta.stat().st_mtime)


@st.cache_data
def tiempos_archivo(ruta: Path) -> list[np.datetime64]:
    """Horas de inicio de las imágenes GOES guardadas en ``ruta``."""
    with xr.open_dataset(ruta, engine="h5netcdf") as ds:
        return list(ds["time"].values)


def imagenes(d: Dia) -> list[tuple[np.datetime64, Path]]:
    """Cada imagen GOES del día ``d``: su hora de inicio y el archivo que la contiene."""
    return [(t, r) for r in d.goes for t in tiempos_archivo(r)]


def era5_ref(d: Dia) -> xr.Dataset | None:
    """Algún dataset ERA5 del día (índices, presión o superficie), para leer horas y grilla."""
    for r in (d.idx, d.pl, d.sfc):
        if r is not None:
            return abre(r)
    return None


def tiempos(d: Dia) -> list[np.datetime64]:
    """Eje de tiempo del visor: cada imagen GOES si las hay; si no, cada hora de ERA5."""
    imgs = imagenes(d)
    if imgs:
        return [t for t, _ in imgs]
    ref = era5_ref(d)
    return [] if ref is None else list(ref["time"].values)


COSTA = comun.DATA / "coast.zip"
CATALOGO = comun.DATA / "tornados_chile.xlsx"


def _version(ruta: Path) -> float:
    """Fecha de modificación de ``ruta`` (0 si no existe), para separar entradas de caché.

    Así, un archivo descargado con el visor abierto se lee al recargar la página, en vez de seguir
    sirviendo el resultado vacío que se guardó cuando faltaba.
    """
    return ruta.stat().st_mtime if ruta.exists() else 0.0


def costa(reg: comun.Region) -> tuple[list[float | None], list[float | None]]:
    """Líneas de costa de ``data/coast.zip`` dentro de ``reg``, como listas x/y separadas por None."""
    return _costa(reg, _version(COSTA))


@st.cache_data
def _costa(reg: comun.Region, version: float) -> tuple[list[float | None], list[float | None]]:
    """Lee y recorta la costa; ``version`` (mtime) solo separa entradas de caché."""
    ruta = COSTA
    if not ruta.exists():
        return [], []
    g = gpd.read_file(f"zip://{ruta}").clip(box(reg.oeste, reg.sur, reg.este, reg.norte))
    xs: list[float | None] = []
    ys: list[float | None] = []
    for geom in g.geometry:
        for linea in getattr(geom, "geoms", [geom]):
            x, y = linea.xy
            xs += [*x, None]
            ys += [*y, None]
    return xs, ys


def coordenada(v: object) -> float:
    """Convierte una coordenada del catálogo a número (algunas filas vienen como texto con comas)."""
    s = str(v).strip().rstrip(",").strip()
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    m = re.match(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else np.nan


def hora_utc(v: object, dia: dt.date) -> pd.Timestamp | None:
    """Primera hora ``HH:MM`` de la celda ``Hour (UTC)`` (``22-23:25`` → 22:00), o ``None``."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?", str(v))
    if not m or str(v).strip() in {"-", "nan", ""}:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return None
    return pd.Timestamp(dt.datetime.combine(dia, dt.time(h, mi)))


def catalogo() -> pd.DataFrame:
    """Catálogo completo de tornados y trombas (vacío si falta ``data/tornados_chile.xlsx``)."""
    return _catalogo(_version(CATALOGO))


@st.cache_data
def _catalogo(version: float) -> pd.DataFrame:
    """Lee el catálogo; ``version`` (mtime) solo separa entradas de caché."""
    ruta = CATALOGO
    if not ruta.exists():
        return pd.DataFrame()
    d = pd.read_excel(ruta, sheet_name="Final_Table")
    d["fecha"] = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    d["lat"] = d["Latitude"].map(coordenada)
    d["lon"] = d["Longitude"].map(coordenada)
    return d


def eventos(dia: dt.date) -> pd.DataFrame:
    """Eventos del catálogo en ``dia``, ordenados por hora, con columnas listas para mostrar."""
    return _eventos(dia, _version(CATALOGO))


@st.cache_data
def _eventos(dia: dt.date, version: float) -> pd.DataFrame:
    """Calcula los eventos de ``dia``; ``version`` (mtime del catálogo) solo separa entradas de caché."""
    c = catalogo()
    if c.empty:
        return c
    d = c[c["fecha"] == dia].copy()
    d["lugar"] = d["Location"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    d["hora"] = [hora_utc(h, dia) for h in d["Hour (UTC)"]]
    d["hora_txt"] = d["Hour (UTC)"].astype(str).str.strip().str.replace(":00$", "", regex=True)
    tornado, tromba = d["Tornado"] == 1, d["Waterspout"] == 1
    d["tipo"] = np.select(
        [tornado & tromba, tornado, tromba],
        ["tornado y tromba", "tornado", "tromba"],
        "sin clasificación",
    )
    d["ef"] = d["Max. EF Rating"].fillna("?").astype(str).str.replace(r"\.0$", "", regex=True)
    d["confianza"] = np.where(d["Register"] == 1, "registro confirmado", "registro débil")
    d = d.sort_values("hora", na_position="last").reset_index(drop=True)
    d["id"] = [f"{i}" for i in range(len(d))]
    d["texto"] = [
        f"<b>{lugar}</b><br>{h} UTC · EF{ef} · {t}"
        for lugar, h, ef, t in zip(d["lugar"], d["hora_txt"], d["ef"], d["tipo"], strict=True)
    ]
    return d


def instante(x: xr.DataArray) -> pd.Timestamp:
    """Convierte una coordenada de tiempo escalar de xarray en ``pd.Timestamp``."""
    return pd.Timestamp(str(x.values))


def ventana(da: xr.DataArray, la: float, lo: float, radio: float) -> xr.DataArray:
    """Recorte de ``da`` a un cuadrado de ±``radio`` grados alrededor de (la, lo)."""
    lat = da["latitude"].values
    sl = slice(la + radio, la - radio) if lat[0] > lat[-1] else slice(la - radio, la + radio)
    return da.sel(latitude=sl, longitude=slice(lo - radio, lo + radio))


@st.cache_data
def serie_goes(ruta: Path, la: float, lo: float, radio: float) -> pd.DataFrame:
    """Para cada imagen de ``ruta``: Tb mínima de C13 y área de topes más fríos que −50 °C.

    El área se mide en km² sobre el cuadrado de ±``radio`` grados alrededor de (la, lo), contando
    píxeles de la grilla reproyectada (2 km × 2 km aproximados en la resolución por defecto).
    """
    ds = abre(ruta)
    c13 = ventana(ds["C13"], la, lo, radio).load()
    dlat = abs(float(np.diff(ds["latitude"].values[:2])[0]))
    km2 = (dlat * 111.2) * (dlat * 111.2 * np.cos(np.deg2rad(la)))
    return pd.DataFrame(
        {
            "time": pd.to_datetime(ds["time"].values),
            "tb_min": c13.min(dim=["latitude", "longitude"]).values,
            "area_50": (c13 < 223.15).sum(dim=["latitude", "longitude"]).values * km2,
        }
    )


def imagen_en(d: Dia, t: np.datetime64 | pd.Timestamp) -> tuple[Path, np.datetime64] | None:
    """El archivo GOES y la hora de la imagen más cercana a ``t`` (``None`` si no hay GOES)."""
    imgs = imagenes(d)
    if not imgs:
        return None
    k = int(np.argmin([abs(pd.Timestamp(ti) - pd.Timestamp(t)) for ti, _ in imgs]))
    return imgs[k][1], imgs[k][0]


def anterior(d: Dia, t: np.datetime64) -> tuple[Path, np.datetime64] | None:
    """La imagen GOES inmediatamente anterior a ``t`` (para la tendencia de 10 minutos)."""
    previas = [(r, ti) for ti, r in imagenes(d) if ti < t]
    return previas[-1] if previas else None
