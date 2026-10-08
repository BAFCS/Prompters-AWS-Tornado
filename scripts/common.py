"""Utilidades compartidas por los scripts de descarga, procesamiento y visualización.

Define las regiones de análisis, las rutas de salida en ``data/crops/``, el acceso anónimo a S3 y
la geometría de la grilla fija del ABI de GOES. Los scripts lo importan como módulo hermano
(``import common``), porque ``scripts/`` no es un paquete instalable.
"""

import argparse
import datetime as dt
import multiprocessing as mp
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import s3fs
import xarray as xr
from botocore.exceptions import BotoCoreError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CROPS = DATA / "crops"

G = 9.80665  # m/s², gravedad estándar (geopotencial → altura)

# Compresión sin pérdida para todo lo que se escribe en NetCDF (gzip + shuffle).
COMPRESSION = {"zlib": True, "complevel": 4, "shuffle": True}


@dataclass(frozen=True)
class Region:
    """Rectángulo lat/lon en grados; latitudes negativas al sur y longitudes negativas al oeste."""

    name: str
    north: float
    south: float
    west: float
    east: float
    label: str = ""  # nombre para la interfaz; vacío usa ``name``

    def contains(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Máscara booleana de los puntos (``lat``, ``lon``) que caen dentro de la región."""
        return (lat <= self.north) & (lat >= self.south) & (lon >= self.west) & (lon <= self.east)


REGIONS = {
    r.name: r
    for r in (
        Region("full", -15, -60, -95, -55),
        Region("south-central", -30, -45, -76, -70, "Centro-sur de Chile"),
        Region("south-central-austral", -30, -56, -76, -66, "Centro-sur y zona austral"),
    )
}


def region_of(a: argparse.Namespace) -> Region:
    """Devuelve la región pedida en los argumentos ``a`` (predefinida o a medida con ``--bbox``)."""
    if a.bbox:
        n, s, o, e = a.bbox
        assert n > s and e > o, (
            "--bbox espera NORTH SOUTH WEST EAST con NORTH > SOUTH y EAST > WEST"
        )
        return Region(a.region, n, s, o, e)
    if a.region not in REGIONS:
        raise SystemExit(f"región desconocida {a.region!r}; usa una de {list(REGIONS)} o --bbox")
    return REGIONS[a.region]


def parser(doc: str | None, unit: str) -> argparse.ArgumentParser:
    """Parser de un script de datos con las opciones comunes.

    Trae ``--start`` y ``--end`` (fechas UTC, inclusive), ``--region`` y ``--bbox`` (región de
    trabajo) y ``--force``, que rehace lo que ya existe (``unit``: ``"los días"`` o ``"las horas"``).
    """
    p = argparse.ArgumentParser(
        description=doc, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--start", type=dt.date.fromisoformat, required=True, help="primer día, AAAA-MM-DD"
    )
    p.add_argument(
        "--end", type=dt.date.fromisoformat, help="último día (inclusive); por defecto --start"
    )
    p.add_argument(
        "--region",
        default="south-central-austral",
        help=f"región predefinida: {', '.join(REGIONS)} (por defecto south-central-austral)",
    )
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("NORTH", "SOUTH", "WEST", "EAST"),
        help="región a medida en grados (p. ej. -30 -45 -76 -70); se guarda con el nombre de --region",
    )
    p.add_argument("--force", action="store_true", help=f"rehace {unit} que ya existen")
    return p


def days(a: argparse.Namespace) -> list[dt.date]:
    """Lista de días entre ``a.start`` y ``a.end`` (inclusive)."""
    end = a.end or a.start
    assert end >= a.start, "--end debe ser igual o posterior a --start"
    return [a.start + dt.timedelta(days=i) for i in range((end - a.start).days + 1)]


def folder(region: str, source: str) -> Path:
    """Carpeta de salida ``data/crops/<region>/<source>/``, creada si no existe."""
    d = CROPS / region / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def write(ds: xr.Dataset, out_file: Path, encoding: dict | None = None) -> None:
    """Escribe ``ds`` en ``out_file`` pasando por un ``.tmp``, para no dejar NetCDF a medias.

    Sin ``encoding``, cada variable se comprime con ``COMPRESSION``.
    """
    tmp = out_file.with_suffix(".tmp")
    enc = dict.fromkeys(ds.data_vars, COMPRESSION) if encoding is None else encoding
    ds.to_netcdf(tmp, engine="h5netcdf", encoding=enc)
    tmp.rename(out_file)


def now() -> str:
    """Marca de tiempo UTC para el atributo ``created`` de un NetCDF."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def stamp(reg: Region) -> dict[str, str]:
    """Atributos ``region`` y ``created`` de un NetCDF de ``reg``."""
    return {
        "region": f"{reg.name}: {reg.north}..{reg.south} lat, {reg.west}..{reg.east} lon",
        "created": now(),
    }


def pool(processes: int) -> ProcessPoolExecutor:
    """Pool de procesos con contexto ``spawn`` (s3fs no tolera fork: cada proceso abre su conexión)."""
    return ProcessPoolExecutor(processes, mp_context=mp.get_context("spawn"))


def s3() -> s3fs.S3FileSystem:
    """Sistema de archivos S3 anónimo (los buckets de Open Data no requieren credenciales)."""
    return s3fs.S3FileSystem(anon=True)


def retry[T](fn: Callable[..., T], *args: object, attempts: int = 5) -> T:
    """Llama ``fn(*args)`` y reintenta ante errores de red, esperando 2, 4, 8… segundos entre intentos."""
    for k in range(attempts):
        try:
            return fn(*args)
        except (
            OSError,
            RuntimeError,
            ValueError,
            BotoCoreError,
        ) as e:  # s3fs/botocore envuelven los cortes de red (EndpointConnectionError no es OSError)
            if k == attempts - 1:
                raise
            print(
                f"  reintento {k + 1}/{attempts - 1} de {getattr(fn, '__name__', fn)}: {e!s:.120}",
                flush=True,
            )
            time.sleep(2 ** (k + 1))
    raise AssertionError("inalcanzable")


def dataset(h: h5py.File | h5py.Group, name: str) -> h5py.Dataset:
    """Devuelve el dataset ``name`` de ``h``, fallando si es un grupo u otro tipo de objeto."""
    obj = h[name]
    assert isinstance(obj, h5py.Dataset), f"{name} no es un dataset"
    return obj


def text(v: object) -> str:
    """Convierte un atributo HDF5 (``bytes``, ``str`` o arreglo) a ``str``."""
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray):
        return text(v.item()) if v.size == 1 else str(v.tolist())
    return str(v)


def num(obj: h5py.Dataset, name: str) -> float:
    """Atributo numérico ``name`` de ``obj`` como ``float`` (HDF5 los guarda como arreglos de 1)."""
    return float(np.asarray(obj.attrs[name]).ravel()[0])


def axis(h: h5py.File, name: str) -> np.ndarray:
    """Eje ``name`` (``x`` o ``y``) del ABI en radianes, aplicando su escala y desplazamiento."""
    d = dataset(h, name)
    return d[:] * num(d, "scale_factor") + num(d, "add_offset")


def latlon(x: np.ndarray, y: np.ndarray, pr: h5py.Dataset) -> tuple[np.ndarray, np.ndarray]:
    """Latitud y longitud geodésicas (grados, 2D, NaN fuera del disco) de la grilla ``x`` × ``y``.

    ``x`` e ``y`` son ángulos de barrido del ABI en radianes y ``pr`` es ``goes_imager_projection``.
    Implementa la proyección geoestacionaria del GOES-R PUG (vol. 4, sección 4.2.8).
    """
    req, rpol = num(pr, "semi_major_axis"), num(pr, "semi_minor_axis")
    H = num(pr, "perspective_point_height") + req
    l0 = np.deg2rad(num(pr, "longitude_of_projection_origin"))
    X, Y = np.meshgrid(x, y)
    a = np.sin(X) ** 2 + np.cos(X) ** 2 * (np.cos(Y) ** 2 + req**2 / rpol**2 * np.sin(Y) ** 2)
    b = -2 * H * np.cos(X) * np.cos(Y)
    c = H**2 - req**2
    with np.errstate(invalid="ignore"):
        rs = (-b - np.sqrt(b**2 - 4 * a * c)) / (2 * a)
        sx, sy, sz = rs * np.cos(X) * np.cos(Y), -rs * np.sin(X), rs * np.cos(X) * np.sin(Y)
        lat = np.rad2deg(np.arctan(req**2 / rpol**2 * sz / np.sqrt((H - sx) ** 2 + sy**2)))
        lon = np.rad2deg(l0 - np.arctan(sy / (H - sx)))
    return lat, lon


def latlon_abi(h: h5py.File) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Coordenadas de la grilla fija del ABI de un archivo GOES abierto ``h``.

    Devuelve ``(x, y, lat, lon)``: los ángulos de barrido en radianes (1D) y la latitud y longitud
    geodésicas en grados (2D, ``float32``, NaN fuera del disco), calculadas con ``latlon``.
    """
    x, y = axis(h, "x"), axis(h, "y")
    lat, lon = latlon(x, y, dataset(h, "goes_imager_projection"))
    return x, y, lat.astype("f4"), lon.astype("f4")
