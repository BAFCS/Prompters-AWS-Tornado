"""Utilidades compartidas por las pruebas de ``scripts/app/`` (datos sintéticos y sin red).

``NoNetworkMixin`` asegura que una prueba no hable con S3, SNS ni ningún otro servicio: parchea
``socket.socket.connect`` (y ``connect_ex``) para que una conexión IP lance ``NetworkBlockedError``
y deja vacías las variables de credenciales AWS durante la prueba (Req. 9.9). Los sockets
``AF_UNIX`` siguen permitidos porque ``multiprocessing`` los usa localmente.
"""

from __future__ import annotations

import os
import socket
import unittest
from unittest import mock

# Variables con las que boto3/botocore encontrarían credenciales o un perfil.
AWS_CREDENTIAL_VARS = (
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
)


# Direcciones que acepta socket.connect (AF_INET/AF_INET6 como tupla, AF_UNIX como ruta).
_Address = str | bytes | tuple[object, ...]


class NetworkBlockedError(OSError):
    """Una prueba intentó abrir una conexión de red."""


def _blocked_connect(sock: socket.socket, address: _Address) -> None:
    """Reemplazo de ``socket.connect``: deja pasar AF_UNIX y bloquea el resto."""
    if sock.family == getattr(socket, "AF_UNIX", None):
        return _REAL_CONNECT(sock, address)
    raise NetworkBlockedError(f"red bloqueada en pruebas: intento de conectar a {address!r}")


def _blocked_connect_ex(sock: socket.socket, address: _Address) -> int:
    """Reemplazo de ``socket.connect_ex`` con la misma regla que ``_blocked_connect``."""
    if sock.family == getattr(socket, "AF_UNIX", None):
        return _REAL_CONNECT_EX(sock, address)
    raise NetworkBlockedError(f"red bloqueada en pruebas: intento de conectar a {address!r}")


_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex


class NoNetworkMixin(unittest.TestCase):
    """Base de prueba sin red ni credenciales AWS; las subclases que redefinen ``setUp`` llaman a
    ``super().setUp()``."""

    def setUp(self) -> None:
        """Parchea los sockets y vacía las credenciales hasta el final de la prueba."""
        super().setUp()
        patches = [
            mock.patch.object(socket.socket, "connect", _blocked_connect),
            mock.patch.object(socket.socket, "connect_ex", _blocked_connect_ex),
            mock.patch.dict(
                os.environ,
                {
                    **dict.fromkeys(AWS_CREDENTIAL_VARS, ""),
                    # Sin consultas al servicio de metadatos de EC2.
                    "AWS_EC2_METADATA_DISABLED": "true",
                },
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


# ================================================================================================
# Generadores sintéticos ERA5 y GOES (Req. 9.2)
#
# Datasets pequeños y deterministas (``seed``) con la misma estructura que el Lago_Datos:
# ``era5_store`` (un Zarr con pl + sfc fusionados, nombres ncar), ``era5_cds_year`` (dos NetCDF con
# nombres CDS y coords ``number``/``expver``) y ``goes_store`` (C13 int16 con escala y desfase).
# Las constantes vienen de ``scripts/app/lake_layout.py``; aquí no se repiten literales del lago.
# ================================================================================================

import datetime as dt  # noqa: E402
import sys  # noqa: E402
from collections.abc import Iterable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import xarray as xr  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "app"))
import lake_layout as L  # noqa: E402

# Nombres CDS a partir de los ncar (inverso de CDS_RENAME).
STORE_TO_CDS = {v: k for k, v in L.CDS_RENAME.items()}

G = 9.80665  # m s-2, para pasar de altura a geopotencial
GRID_STEP = 0.25  # grados, paso de la grilla ERA5

# Escala y desfase típicos de la banda 13 en ABI-L2-CMIP (K por cuenta).
GOES_SCALE = 0.06145332
GOES_OFFSET = 89.62


def _day(day: dt.date | str) -> dt.date:
    """Acepta ``date`` o texto ISO ``AAAA-MM-DD``."""
    return day if isinstance(day, dt.date) else dt.date.fromisoformat(day)


def _std_height(level_hpa: np.ndarray) -> np.ndarray:
    """Altura (m) de la atmósfera estándar para presiones en hPa."""
    return 44330.0 * (1.0 - (level_hpa / 1013.25) ** 0.1903)


def _with_nans(rng: np.random.Generator, arr: np.ndarray, frac: float) -> np.ndarray:
    """Copia de ``arr`` con ``round(frac * size)`` celdas en NaN elegidas al azar."""
    out = arr.copy()
    n = round(frac * out.size)
    if n > 0:
        idx = rng.choice(out.size, size=n, replace=False)
        out.reshape(-1)[idx] = np.nan
    return out


def era5_store_dataset(
    day: dt.date | str,
    nlat: int = 3,
    nlon: int = 3,
    ntime: int = 2,
    seed: int = 0,
    levels: Sequence[int] = L.LEVELS,
    nan_frac: float = 0.0,
    drop_vars: Iterable[str] = (),
    lat0: float = -37.0,
    lon0: float = -73.0,
) -> xr.Dataset:
    """Dataset ERA5 con la estructura de ``era5_store`` (pl + sfc fusionados, nombres ncar).

    Dims ``time``/``level``/``latitude``/``longitude``; latitud descendente desde ``lat0`` y
    longitud en -180..180 desde ``lon0``, paso 0.25°. Los valores son físicamente plausibles:
    ``z`` crece con la altura (g·h estándar), ``t`` decrece, ``u``/``v`` tienen cizalle positiva,
    ``sp`` ≈ 1e5 Pa, ``cape`` en 0..2000 y ``2d`` < ``2t``. ``nan_frac`` pone esa fracción de NaN
    en cada variable y ``drop_vars`` quita variables (nombres ncar). Todo en ``float32``.
    """
    rng = np.random.default_rng(seed)
    d = _day(day)
    time = np.array(
        [np.datetime64(d, "ns") + np.timedelta64(h, "h") for h in range(ntime)],
        dtype="datetime64[ns]",
    )
    lev = np.asarray(levels, dtype=np.int64)
    lat = (lat0 - GRID_STEP * np.arange(nlat)).astype(np.float64)
    lon = (lon0 + GRID_STEP * np.arange(nlon)).astype(np.float64)
    lon = (lon + 180.0) % 360.0 - 180.0

    pl_shape = (ntime, lev.size, nlat, nlon)
    sfc_shape = (ntime, nlat, nlon)
    h = _std_height(lev.astype(np.float64))[None, :, None, None]

    def noise(shape: tuple[int, ...], scale: float) -> np.ndarray:
        return rng.normal(0.0, scale, size=shape)

    pl = {
        "u": 5.0 + 3e-3 * h + noise(pl_shape, 1.0),
        "v": 2.0 + 1e-3 * h + noise(pl_shape, 1.0),
        "t": 288.0 - 6.5e-3 * h + noise(pl_shape, 0.5),
        "z": G * (h + noise(pl_shape, 5.0)),
    }
    t2 = 285.0 + noise(sfc_shape, 3.0)
    sfc = {
        "10u": noise(sfc_shape, 3.0),
        "10v": noise(sfc_shape, 3.0),
        "2t": t2,
        "2d": t2 - rng.uniform(1.0, 10.0, size=sfc_shape),
        "sp": 1.0e5 + noise(sfc_shape, 800.0),
        "cape": rng.uniform(0.0, 2000.0, size=sfc_shape),
    }
    dropped = set(drop_vars)
    data_vars: dict[str, tuple[tuple[str, ...], np.ndarray]] = {}
    for name in L.PL_VARS:
        if name not in dropped:
            arr = _with_nans(rng, pl[name].astype(np.float32), nan_frac)
            data_vars[name] = (L.DIMS, arr)
    for name in L.SFC_VARS:
        if name not in dropped:
            arr = _with_nans(rng, sfc[name].astype(np.float32), nan_frac)
            data_vars[name] = ((L.DIMS[0], L.DIMS[2], L.DIMS[3]), arr)
    return xr.Dataset(
        data_vars,
        coords={"time": time, "level": lev, "latitude": lat, "longitude": lon},
        attrs={"source": "sintético (tests/app_synthetic.py)"},
    )


def era5_cds_datasets(day: dt.date | str, **kwargs: object) -> tuple[xr.Dataset, xr.Dataset]:
    """Par ``(pl, sfc)`` con la estructura de ``era5_cds_year`` (nombres y coords CDS).

    Acepta los mismos argumentos que ``era5_store_dataset`` (``drop_vars`` en nombres ncar) y,
    con la misma semilla, tiene exactamente los mismos números. Coordenadas ``valid_time`` y
    ``pressure_level`` (``float64`` como en CDS), variables ``u10``/``v10``/``t2m``/``d2m`` y las
    coords auxiliares ``number`` (escalar) y ``expver`` (por tiempo).
    """
    store = era5_store_dataset(day, **kwargs)  # type: ignore[arg-type]
    ntime = store.sizes["time"]
    pl_names = [v for v in L.PL_VARS if v in store]
    sfc_names = [v for v in L.SFC_VARS if v in store]
    rename = {k: v for k, v in STORE_TO_CDS.items() if k in store.variables}
    extra = {"number": 0, "expver": ("valid_time", np.array(["0001"] * ntime))}

    pl = store[pl_names].rename(rename)
    pl = pl.assign_coords(pressure_level=pl["pressure_level"].astype(np.float64), **extra)
    sfc = store[sfc_names].drop_vars("level").rename(rename).assign_coords(**extra)
    return pl, sfc


def goes_daily_dataset(
    day: dt.date | str,
    shape: tuple[int, int] = (6, 8),
    hours: Iterable[int] = range(24),
    scenes_per_hour: int = 6,
    scale: float = GOES_SCALE,
    offset: float = GOES_OFFSET,
    seed: int = 0,
    fill_frac: float = 0.0,
) -> xr.Dataset:
    """Dataset GOES crudo de un día con la estructura de ``goes_store`` (lo que da
    ``open_dataset(mask_and_scale=False)``).

    ``C13`` es ``int16`` con dims ``time``/``y``/``x`` y ``scale_factor``, ``add_offset`` y
    ``_FillValue`` (= ``GOES_FILL``) en ``attrs`` y en ``encoding``; ``fill_frac`` de las celdas
    vale ``_FillValue``. Las temperaturas de brillo físicas quedan en 190–310 K. ``time`` es el
    inicio de cada barrido: ``scenes_per_hour`` escenas por hora, dentro de la hora. ``lat``/``lon``
    son coords 2D ``float32`` sobre Chile. Usar ``goes_physical`` para la versión decodificada.
    """
    rng = np.random.default_rng(seed)
    d = _day(day)
    ny, nx = shape
    step = 3600 // scenes_per_hour
    base = np.datetime64(d, "ns")
    times = np.array(
        [
            base + np.timedelta64(h * 3600 + k * step + 20, "s")
            for h in hours
            for k in range(scenes_per_hour)
        ],
        dtype="datetime64[ns]",
    )
    bt = rng.uniform(190.0, 310.0, size=(times.size, ny, nx))
    raw = np.round((bt - offset) / scale).astype(np.int16)
    n_fill = round(fill_frac * raw.size)
    if n_fill > 0:
        raw.reshape(-1)[rng.choice(raw.size, size=n_fill, replace=False)] = L.GOES_FILL

    # Grilla levemente oblicua (como la proyección fija del ABI) sobre el centro-sur de Chile.
    yy, xx = np.meshgrid(np.linspace(0.0, 1.0, ny), np.linspace(0.0, 1.0, nx), indexing="ij")
    lat = (-30.0 - 15.0 * yy + 0.3 * xx).astype(np.float32)
    lon = (-76.0 + 6.0 * xx + 0.2 * yy).astype(np.float32)

    cf = {"scale_factor": scale, "add_offset": offset, "_FillValue": np.int16(L.GOES_FILL)}
    var = xr.Variable(L.GOES_DIMS, raw, attrs={"units": "K", "long_name": "ABI C13", **cf})
    var.encoding = {"dtype": "int16", **cf}
    return xr.Dataset(
        {L.GOES_VAR: var},
        coords={
            "time": times,
            "y": ("y", np.linspace(0.1, 0.05, ny)),
            "x": ("x", np.linspace(-0.08, -0.02, nx)),
            "lat": (("y", "x"), lat),
            "lon": (("y", "x"), lon),
        },
        attrs={"note": "sintético; time = inicio del barrido"},
    )


def goes_physical(raw: xr.Dataset) -> xr.Dataset:
    """Decodifica un dataset de ``goes_daily_dataset``: ``float32`` en K y NaN en el relleno.

    La codificación queda en ``encoding``, así que ``to_netcdf`` vuelve a escribir el int16 crudo.
    """
    ds = xr.decode_cf(raw, mask_and_scale=True)
    ds[L.GOES_VAR] = ds[L.GOES_VAR].astype(np.float32)
    ds[L.GOES_VAR].encoding = dict(raw[L.GOES_VAR].encoding.items())
    return ds


def write_local_lake(
    root: Path | str,
    day: dt.date | str,
    *,
    era5: str | None = "cds",
    goes: bool = True,
    era5_kwargs: dict[str, object] | None = None,
    goes_kwargs: dict[str, object] | None = None,
) -> dict[str, Path]:
    """Escribe un Lago_Datos local bajo ``root`` con los patrones de ``lake_layout``.

    ``era5="store"`` escribe el Zarr (requiere ``zarr``), ``"cds"`` los dos NetCDF y ``None``
    nada de ERA5; ``goes`` escribe ``goes_store/<iso>/goes_<ymd>.nc``. Devuelve las rutas por clave
    (``era5_store``, ``era5_pl``, ``era5_sfc``, ``goes``).
    """
    root = Path(root)
    d = _day(day)
    fmt = {"ymd": f"{d:%Y%m%d}", "iso": d.isoformat(), "yyyy": f"{d:%Y}", "mm": f"{d:%m}"}
    paths: dict[str, Path] = {}
    ekw = era5_kwargs or {}
    if era5 == "store":
        try:
            import zarr  # noqa: F401  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # zarr no es dependencia del proyecto
            raise RuntimeError("write_local_lake(era5='store') necesita el paquete zarr") from exc
        path = root / L.ERA5_STORE_PATTERN.format(**fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        era5_store_dataset(d, **ekw).to_zarr(path, mode="w")  # type: ignore[arg-type]
        paths["era5_store"] = path
    elif era5 == "cds":
        for kind, ds in zip(L.CDS_KINDS, era5_cds_datasets(d, **ekw), strict=True):
            path = root / L.ERA5_CDS_PATTERN.format(kind=kind, **fmt)
            path.parent.mkdir(parents=True, exist_ok=True)
            ds.to_netcdf(path, engine="h5netcdf")
            paths[f"era5_{kind}"] = path
    elif era5 is not None:
        raise ValueError(f"era5 debe ser 'store', 'cds' o None, no {era5!r}")
    if goes:
        path = root / L.GOES_STORE_PATTERN.format(**fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        goes_physical(goes_daily_dataset(d, **(goes_kwargs or {}))).to_netcdf(  # type: ignore[arg-type]
            path, engine="h5netcdf"
        )
        paths["goes"] = path
    return paths
