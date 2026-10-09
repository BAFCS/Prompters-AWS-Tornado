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

import common


@dataclass(frozen=True)
class Day:
    """Archivos disponibles de un día en una región: ERA5, índices y las horas GOES reproyectadas."""

    date: dt.date
    pl: Path | None
    sfc: Path | None
    idx: Path | None
    goes: tuple[Path, ...]


def regions() -> list[str]:
    """Regiones con recortes en ``data/crops/``."""
    return sorted(p.name for p in common.CROPS.glob("*") if p.is_dir())


def _date(p: Path) -> dt.date:
    """Fecha ``AAAAMMDD`` que aparece en el nombre de ``p``."""
    return dt.datetime.strptime(re.findall(r"\d{8}", p.name)[-1], "%Y%m%d").date()


def days(name: str) -> dict[dt.date, Day]:
    """Todos los días con algún dato en la región ``name``, ordenados por fecha."""
    base = common.CROPS / name

    def by_date(pattern: str) -> dict[dt.date, Path]:
        """Archivos que calzan con ``pattern`` (glob relativo a la región), indexados por fecha."""
        return {_date(p): p for p in base.glob(pattern)}

    pl, sfc = by_date("era5_pl/*.nc"), by_date("era5_sfc/*.nc")
    idx, goes = by_date("era5_indices/*.nc"), by_date("goes_latlon/*")
    dates = sorted(set(pl) | set(sfc) | set(idx) | set(goes))
    return {
        f: Day(
            f,
            pl.get(f),
            sfc.get(f),
            idx.get(f),
            tuple(sorted(goes[f].glob("goes_*.nc"))) if f in goes else (),
        )  # fmt: skip
        for f in dates
    }


@st.cache_resource
def _open_nc(path: Path, version: float) -> xr.Dataset:
    """Abre el NetCDF ``path`` sin cargarlo; ``version`` (mtime) solo separa entradas de caché."""
    return xr.open_dataset(path, engine="h5netcdf")


def open_nc(path: Path) -> xr.Dataset:
    """Abre (una vez por versión del archivo) el NetCDF ``path``, sin cargarlo a memoria.

    La fecha de modificación entra en la clave de caché: si una descarga reemplaza el archivo,
    se abre el nuevo en vez de seguir sirviendo el viejo.
    """
    return _open_nc(path, path.stat().st_mtime)


def images(d: Day) -> list[tuple[np.datetime64, Path]]:
    """Cada imagen GOES del día ``d``: su hora de inicio y el archivo que la contiene."""
    return [(t, r) for r in d.goes for t in open_nc(r)["time"].values]


def era5_ref(d: Day) -> xr.Dataset | None:
    """Algún dataset ERA5 del día (índices, presión o superficie), para leer horas y grilla."""
    for r in (d.idx, d.pl, d.sfc):
        if r is not None:
            return open_nc(r)
    return None


def times(d: Day) -> list[np.datetime64]:
    """Eje de tiempo del visor: cada imagen GOES si las hay; si no, cada hora de ERA5."""
    imgs = images(d)
    if imgs:
        return [t for t, _ in imgs]
    ref = era5_ref(d)
    return [] if ref is None else list(ref["time"].values)


COAST = common.DATA / "coast.zip"
CATALOG = common.DATA / "tornados_chile.xlsx"


def _version(path: Path) -> float:
    """Fecha de modificación de ``path`` (0 si no existe), para separar entradas de caché.

    Así, un archivo descargado con el visor abierto se lee al recargar la página, en vez de seguir
    sirviendo el resultado vacío que se guardó cuando faltaba.
    """
    return path.stat().st_mtime if path.exists() else 0.0


def coast(reg: common.Region) -> tuple[np.ndarray, np.ndarray]:
    """Líneas de costa de ``data/coast.zip`` dentro de ``reg``, como arreglos x/y separados por NaN."""
    return _coast(reg, _version(COAST))


@st.cache_data
def _coast(reg: common.Region, version: float) -> tuple[np.ndarray, np.ndarray]:
    """Lee, recorta y simplifica la costa; ``version`` (mtime) solo separa entradas de caché.

    Simplificada a 0,005° (~500 m, menos que un píxel GOES) y en ``float32``: plotly la recibe como
    arreglo binario y no como lista JSON, y cada panel la repite.
    """
    path = COAST
    if not path.exists():
        return np.array([], np.float32), np.array([], np.float32)
    g = gpd.read_file(f"zip://{path}").clip(box(reg.west, reg.south, reg.east, reg.north))
    xs: list[float] = []
    ys: list[float] = []
    for geom in g.geometry.simplify(0.005):
        for line in getattr(geom, "geoms", [geom]):
            x, y = line.xy
            xs += [*x, np.nan]
            ys += [*y, np.nan]
    return np.array(xs, np.float32), np.array(ys, np.float32)


def coordinate(v: object) -> float:
    """Convierte una coordenada del catálogo a número (algunas filas vienen como texto con comas)."""
    s = str(v).strip().rstrip(",").strip()
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    m = re.match(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else np.nan


def utc_hour(v: object, day: dt.date) -> pd.Timestamp | None:
    """Primera hora ``HH:MM`` de la celda ``Hour (UTC)`` (``22-23:25`` → 22:00), o ``None``."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?", str(v))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return None
    return pd.Timestamp(dt.datetime.combine(day, dt.time(h, mi)))


def catalog() -> pd.DataFrame:
    """Catálogo completo de tornados y trombas (vacío si falta ``data/tornados_chile.xlsx``)."""
    return _catalog(_version(CATALOG))


@st.cache_data
def _catalog(version: float) -> pd.DataFrame:
    """Lee el catálogo; ``version`` (mtime) solo separa entradas de caché."""
    path = CATALOG
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_excel(path, sheet_name="Final_Table")
    d["date"] = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    d["lat"] = d["Latitude"].map(coordinate)
    d["lon"] = d["Longitude"].map(coordinate)
    return d


def kind_of(d: pd.DataFrame) -> np.ndarray:
    """Tipo de cada evento del catálogo: tornado, tromba, ambos o sin clasificación."""
    tornado, waterspout = d["Tornado"] == 1, d["Waterspout"] == 1
    return np.select(
        [tornado & waterspout, tornado, waterspout],
        ["tornado y tromba", "tornado", "tromba"],
        "sin clasificación",
    )


def events(day: dt.date) -> pd.DataFrame:
    """Eventos del catálogo en ``day``, ordenados por hora, con columnas listas para mostrar."""
    return _events(day, _version(CATALOG))


@st.cache_data
def _events(day: dt.date, version: float) -> pd.DataFrame:
    """Calcula los eventos de ``day``; ``version`` (mtime del catálogo) solo separa entradas de caché."""
    c = catalog()
    if c.empty:
        return c
    d = c[c["date"] == day].copy()
    d["place"] = d["Location"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    d["hour"] = [utc_hour(h, day) for h in d["Hour (UTC)"]]
    d["hour_txt"] = d["Hour (UTC)"].astype(str).str.strip().str.replace(":00$", "", regex=True)
    d["kind"] = kind_of(d)
    d["ef"] = d["Max. EF Rating"].fillna("?").astype(str).str.replace(r"\.0$", "", regex=True)
    d["confidence"] = np.where(d["Register"] == 1, "registro confirmado", "registro débil")
    d = d.sort_values("hour", na_position="last").reset_index(drop=True)
    d["id"] = d.index.astype(str)
    d["text"] = [
        f"<b>{place}</b><br>{h} UTC · EF{ef} · {t}"
        for place, h, ef, t in zip(d["place"], d["hour_txt"], d["ef"], d["kind"], strict=True)
    ]
    return d


def to_timestamp(x: xr.DataArray) -> pd.Timestamp:
    """Convierte una coordenada de tiempo escalar de xarray en ``pd.Timestamp``."""
    return pd.Timestamp(str(x.values))


def image_at(d: Day, t: np.datetime64 | pd.Timestamp) -> tuple[Path, np.datetime64] | None:
    """El archivo GOES y la hora de la imagen más cercana a ``t`` (``None`` si no hay GOES)."""
    imgs = images(d)
    if not imgs:
        return None
    k = int(np.argmin([abs(pd.Timestamp(ti) - pd.Timestamp(t)) for ti, _ in imgs]))
    return imgs[k][1], imgs[k][0]


def previous(d: Day, t: np.datetime64) -> tuple[Path, np.datetime64] | None:
    """La imagen GOES inmediatamente anterior a ``t`` (para la tendencia de 10 minutos)."""
    earlier = [(r, ti) for ti, r in images(d) if ti < t]
    return earlier[-1] if earlier else None
