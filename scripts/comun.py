"""Utilidades compartidas por los scripts de descarga, procesamiento y visualización.

Define las regiones de análisis, las rutas de salida en ``data/recortes/``, el acceso anónimo a S3 y
la geometría de la grilla fija del ABI de GOES. Los scripts lo importan como módulo hermano
(``import comun``), porque ``scripts/`` no es un paquete instalable.
"""

import argparse
import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import s3fs
from botocore.exceptions import BotoCoreError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RECORTES = DATA / "recortes"

# Compresión sin pérdida para todo lo que se escribe en NetCDF (gzip + shuffle).
COMPRESION = {"zlib": True, "complevel": 4, "shuffle": True}


@dataclass(frozen=True)
class Region:
    """Rectángulo lat/lon en grados; latitudes negativas al sur y longitudes negativas al oeste."""

    nombre: str
    norte: float
    sur: float
    oeste: float
    este: float

    def contiene(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Máscara booleana de los puntos (``lat``, ``lon``) que caen dentro de la región."""
        return (lat <= self.norte) & (lat >= self.sur) & (lon >= self.oeste) & (lon <= self.este)


REGIONES = {
    r.nombre: r
    for r in (
        Region("completo", -15, -60, -95, -55),
        Region("centro-sur", -30, -45, -76, -70),
        Region("centro-sur-austral", -30, -56, -76, -66),
    )
}


def args_region(p: argparse.ArgumentParser) -> None:
    """Añade a ``p`` las opciones ``--region`` y ``--bbox`` para elegir la región de trabajo."""
    p.add_argument(
        "--region",
        default="centro-sur-austral",
        help=f"región predefinida: {', '.join(REGIONES)} (por defecto centro-sur-austral)",
    )
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("NORTE", "SUR", "OESTE", "ESTE"),
        help="región a medida en grados (p. ej. -30 -45 -76 -70); se guarda con el nombre de --region",
    )


def region_de(a: argparse.Namespace) -> Region:
    """Devuelve la región pedida en los argumentos ``a`` (predefinida o a medida con ``--bbox``)."""
    if a.bbox:
        n, s, o, e = a.bbox
        assert n > s and e > o, "--bbox espera NORTE SUR OESTE ESTE con NORTE > SUR y ESTE > OESTE"
        return Region(a.region, n, s, o, e)
    if a.region not in REGIONES:
        raise SystemExit(f"región desconocida {a.region!r}; usa una de {list(REGIONES)} o --bbox")
    return REGIONES[a.region]


def args_fechas(p: argparse.ArgumentParser) -> None:
    """Añade a ``p`` las opciones ``--inicio`` y ``--fin`` (fechas UTC, inclusive)."""
    p.add_argument(
        "--inicio", type=dt.date.fromisoformat, required=True, help="primer día, AAAA-MM-DD"
    )
    p.add_argument(
        "--fin", type=dt.date.fromisoformat, help="último día (inclusive); por defecto --inicio"
    )


def dias(a: argparse.Namespace) -> list[dt.date]:
    """Lista de días entre ``a.inicio`` y ``a.fin`` (inclusive)."""
    fin = a.fin or a.inicio
    assert fin >= a.inicio, "--fin debe ser igual o posterior a --inicio"
    return [a.inicio + dt.timedelta(days=i) for i in range((fin - a.inicio).days + 1)]


def carpeta(region: str, fuente: str) -> Path:
    """Carpeta de salida ``data/recortes/<region>/<fuente>/``, creada si no existe."""
    d = RECORTES / region / fuente
    d.mkdir(parents=True, exist_ok=True)
    return d


def s3() -> s3fs.S3FileSystem:
    """Sistema de archivos S3 anónimo (los buckets de Open Data no requieren credenciales)."""
    return s3fs.S3FileSystem(anon=True)


def reintenta[T](fn: Callable[..., T], *args: object, intentos: int = 5) -> T:
    """Llama ``fn(*args)`` y reintenta ante errores de red, esperando 2, 4, 8… segundos entre intentos."""
    for k in range(intentos):
        try:
            return fn(*args)
        except (
            OSError,
            RuntimeError,
            ValueError,
            BotoCoreError,
        ) as e:  # s3fs/botocore envuelven los cortes de red (EndpointConnectionError no es OSError)
            if k == intentos - 1:
                raise
            print(
                f"  reintento {k + 1}/{intentos - 1} de {getattr(fn, '__name__', fn)}: {e!s:.120}",
                flush=True,
            )
            time.sleep(2 ** (k + 1))
    raise AssertionError("inalcanzable")


def dataset(h: h5py.File | h5py.Group, name: str) -> h5py.Dataset:
    """Devuelve el dataset ``name`` de ``h``, fallando si es un grupo u otro tipo de objeto."""
    obj = h[name]
    assert isinstance(obj, h5py.Dataset), f"{name} no es un dataset"
    return obj


def texto(v: object) -> str:
    """Convierte un atributo HDF5 (``bytes``, ``str`` o arreglo) a ``str``."""
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray):
        return texto(v.item()) if v.size == 1 else str(v.tolist())
    return str(v)


def num(obj: h5py.Dataset, nombre: str) -> float:
    """Atributo numérico ``nombre`` de ``obj`` como ``float`` (HDF5 los guarda como arreglos de 1)."""
    return float(np.asarray(obj.attrs[nombre]).ravel()[0])


def eje(h: h5py.File, nombre: str) -> np.ndarray:
    """Eje ``nombre`` (``x`` o ``y``) del ABI en radianes, aplicando su escala y desplazamiento."""
    d = dataset(h, nombre)
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
    x, y = eje(h, "x"), eje(h, "y")
    lat, lon = latlon(x, y, dataset(h, "goes_imager_projection"))
    return x, y, lat.astype("f4"), lon.astype("f4")
