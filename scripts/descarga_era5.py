#!/usr/bin/env python3
"""Descarga ERA5 desde ``s3://nsf-ncar-era5/`` recortado a una región, un archivo NetCDF por día.

Niveles de presión (``e5.oper.an.pl``): cada archivo trae una variable, un día y el globo, dividido
en bloques de una hora con los 37 niveles. No se puede pedir solo el recuadro: por cada hora se
transfiere el bloque global (~50–65 MB) y se recorta en memoria. Superficie (``e5.oper.an.sfc``): los
archivos son mensuales, con bloques pequeños, así que se lee casi solo el recuadro.

En los niveles de presión se lee el índice de bloques del archivo y se piden a S3 exactamente los
bytes de cada bloque horario. Las lecturas se reparten en procesos (cada uno con su propia conexión
S3). Conviene correrlo en AWS us-west-2, donde está el bucket: desde Chile se transfieren ~350 MB
por hora de datos con 6 variables.

Salida::

    data/recortes/<region>/era5_pl/era5_pl_AAAAMMDD.nc    (time, level, latitude, longitude)
    data/recortes/<region>/era5_sfc/era5_sfc_AAAAMMDD.nc  (time, latitude, longitude)

Uso::

    uv run python scripts/descarga_era5.py --inicio 2019-05-30
    uv run python scripts/descarga_era5.py --inicio 2019-05-29 --fin 2019-05-31 --pl u v t --sfc cape
"""

import argparse
import datetime as dt
import multiprocessing as mp
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

import comun

BUCKET = "nsf-ncar-era5"

# Nombre corto -> (tabla_parámetro, grilla) según la clave del bucket.
PL = {
    "u": ("128_131_u", "ll025uv"),
    "v": ("128_132_v", "ll025uv"),
    "w": ("128_135_w", "ll025sc"),
    "t": ("128_130_t", "ll025sc"),
    "q": ("128_133_q", "ll025sc"),
    "z": ("128_129_z", "ll025sc"),
    "r": ("128_157_r", "ll025sc"),
    "vo": ("128_138_vo", "ll025sc"),
    "d": ("128_155_d", "ll025sc"),
    "pv": ("128_060_pv", "ll025sc"),
}
SFC = {
    "10u": "128_165_10u",
    "10v": "128_166_10v",
    "100u": "228_246_100u",
    "100v": "228_247_100v",
    "2t": "128_167_2t",
    "2d": "128_168_2d",
    "sp": "128_134_sp",
    "msl": "128_151_msl",
    "cape": "128_059_cape",
    "tcwv": "128_137_tcwv",
    "blh": "128_159_blh",
    "tcc": "128_164_tcc",
    "skt": "128_235_skt",
    "sstk": "128_034_sstk",
}
PL_DEFECTO = ["u", "v", "w", "t", "q", "z", "r", "vo"]
SFC_DEFECTO = ["10u", "10v", "100u", "100v", "2t", "2d", "sp", "msl", "cape", "tcwv", "blh", "tcc"]
EPOCA = np.datetime64("1900-01-01T00:00")


def ruta_pl(v: str, dia: dt.date) -> str:
    """Clave S3 del archivo diario de niveles de presión de la variable ``v``."""
    code, grid = PL[v]
    d = dia.strftime("%Y%m%d")
    return f"{BUCKET}/e5.oper.an.pl/{dia:%Y%m}/e5.oper.an.pl.{code}.{grid}.{d}00_{d}23.nc"


def ruta_sfc(v: str, dia: dt.date) -> str:
    """Clave S3 del archivo mensual de superficie de la variable ``v`` que contiene ``dia``."""
    ultimo = (dia.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return (
        f"{BUCKET}/e5.oper.an.sfc/{dia:%Y%m}/e5.oper.an.sfc.{SFC[v]}.ll025sc."
        f"{dia:%Y%m}0100_{ultimo:%Y%m%d}23.nc"
    )


def indices(lat: np.ndarray, lon: np.ndarray, reg: comun.Region) -> tuple[slice, slice]:
    """Rebanadas de latitud (90→−90) y longitud (0→360 este) que cubren la región ``reg``."""
    assert reg.oeste < 0 and reg.este < 0, "la región debe estar al oeste de Greenwich"
    i = np.flatnonzero((lat <= reg.norte) & (lat >= reg.sur))
    j = np.flatnonzero((lon >= 360 + reg.oeste) & (lon <= 360 + reg.este))
    return slice(i[0], i[-1] + 1), slice(j[0], j[-1] + 1)


def variable(h: h5py.File) -> h5py.Dataset:
    """El único dataset con datos (≥ 3 dimensiones) de un archivo ERA5 de NSF NCAR."""
    (nombre,) = [k for k, d in h.items() if isinstance(d, h5py.Dataset) and d.ndim >= 3]
    return comun.dataset(h, nombre)


def bloque_global(d: h5py.Dataset) -> bool:
    """Si ``d`` está dividido en bloques de un instante con el globo entero, comprimidos con gzip."""
    c = d.chunks
    return bool(c) and c[0] == 1 and c[1:] == d.shape[1:] and d.compression == "gzip"


def decodifica(b: bytes, d: h5py.Dataset) -> np.ndarray:
    """Descomprime un bloque crudo de ``d`` (gzip y, si corresponde, deshace el filtro shuffle)."""
    crudo = zlib.decompress(b)
    tam = d.dtype.itemsize
    if d.shuffle:  # shuffle agrupa el byte 0 de todos los valores, luego el byte 1, etc.
        crudo = np.frombuffer(crudo, np.uint8).reshape(tam, -1).T.tobytes()
    return np.frombuffer(crudo, d.dtype).reshape(d.chunks or ())


def lee(ruta: str, reg: comun.Region, h0: int, h1: int, bloque: int) -> dict:
    """Lee de ``ruta`` el recorte de ``reg`` entre los índices de tiempo ``h0`` y ``h1`` (exclusivo).

    Si el archivo guarda cada instante como un bloque global (niveles de presión), pide a S3
    exactamente los bytes de esos bloques y los recorta en memoria; si no, lee con h5py, con
    lecturas de ``bloque`` bytes. Devuelve los datos en ``float32`` junto con las coordenadas y los
    atributos de la variable.
    """
    fs = comun.s3()
    with fs.open(ruta, "rb", block_size=bloque) as f, h5py.File(f, "r") as h:
        lat, lon = comun.dataset(h, "latitude")[:], comun.dataset(h, "longitude")[:]
        si, sj = indices(lat, lon, reg)
        d = variable(h)
        if bloque_global(d):
            partes = []
            for k in range(h0, h1):
                info = d.id.get_chunk_info_by_coord((k,) + (0,) * (d.ndim - 1))
                b = fs.cat_file(ruta, start=info.byte_offset, end=info.byte_offset + info.size)
                assert isinstance(b, bytes), f"lectura fallida en {ruta}"
                partes.append(decodifica(b, d)[0, ..., si, sj])
            datos = np.stack(partes)
        else:
            datos = d[h0:h1, ..., si, sj]
        out = {
            "datos": datos.astype("f4"),
            "time": EPOCA + comun.dataset(h, "time")[h0:h1].astype("timedelta64[h]"),
            "lat": lat[si],
            "lon": lon[sj] - 360,
            "attrs": {a: comun.texto(d.attrs[a]) for a in ("long_name", "units") if a in d.attrs},
        }
        if "level" in h:
            out["level"] = comun.dataset(h, "level")[:]
    return out


def horas_del_dia(ruta: str, dia: dt.date) -> tuple[int, int]:
    """Rango ``[h0, h1)`` de índices de ``ruta`` (archivo mensual) con las 24 horas de ``dia``."""
    fs = comun.s3()
    with fs.open(ruta, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        t = EPOCA + comun.dataset(h, "time")[:].astype("timedelta64[h]")
    k = np.flatnonzero(t.astype("datetime64[D]") == np.datetime64(dia))
    return int(k[0]), int(k[-1]) + 1


def guarda(res: dict[str, dict], salida: Path, con_nivel: bool, reg: comun.Region) -> None:
    """Escribe en ``salida`` un NetCDF comprimido con las variables leídas en ``res``."""
    r0 = next(iter(res.values()))
    dims = (
        ("time", "level", "latitude", "longitude")
        if con_nivel
        else ("time", "latitude", "longitude")
    )
    coords = {"time": r0["time"], "latitude": r0["lat"], "longitude": r0["lon"]}
    if con_nivel:
        coords["level"] = xr.DataArray(r0["level"], dims="level", attrs={"units": "hPa"})
    ds = xr.Dataset(
        {v: (dims, r["datos"], r["attrs"]) for v, r in res.items()},
        coords=coords,
        attrs={
            "fuente": f"s3://{BUCKET}/ (ERA5, ECMWF; copia NSF NCAR, doi:10.5065/BH6N-5N20)",
            "region": f"{reg.nombre}: {reg.norte}..{reg.sur} lat, {reg.oeste}..{reg.este} lon",
            "creado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
    )
    comun.escribe(ds, salida)


def completo(salida: Path, variables: list[str]) -> bool:
    """Si ``salida`` ya existe y contiene todas las ``variables`` pedidas."""
    if not salida.exists():
        return False
    with xr.open_dataset(salida, engine="h5netcdf") as ds:
        return set(variables) <= set(ds.data_vars)


def junta(partes: list[dict]) -> dict:
    """Une las lecturas horarias ``partes`` de una variable en una sola, a lo largo del tiempo."""
    return partes[0] | {
        "datos": np.concatenate([x["datos"] for x in partes]),
        "time": np.concatenate([x["time"] for x in partes]),
    }


def descarga_pl(
    ex: ProcessPoolExecutor, dia: dt.date, variables: list[str], reg: comun.Region, salida: Path
) -> None:
    """Descarga los niveles de presión de ``dia`` y los escribe en ``salida``.

    Cada variable terminada se guarda aparte en ``.partes/``; si el proceso se corta, al volver a
    correr solo se bajan las variables que faltan. Al final se unen en un solo archivo.
    """
    partes_dir = salida.parent / ".partes"
    partes_dir.mkdir(exist_ok=True)
    parte = {v: partes_dir / f"{salida.stem}_{v}.nc" for v in variables}
    faltan = [v for v in variables if not parte[v].exists()]
    # Una tarea por (variable, hora): cada una transfiere un bloque global.
    fut = {
        (v, k): ex.submit(comun.reintenta, lee, ruta_pl(v, dia), reg, k, k + 1, 2**20)
        for v in faltan
        for k in range(24)
    }
    for v in faltan:
        t0 = time.time()
        guarda({v: junta([fut[v, k].result() for k in range(24)])}, parte[v], True, reg)
        print(f"  {salida.stem} {v}: {time.time() - t0:.0f} s", flush=True)
    une([parte[v] for v in variables], salida)


def une(partes: list[Path], salida: Path) -> None:
    """Une los archivos de una variable ``partes`` en ``salida`` y los borra."""
    ds = xr.merge([xr.load_dataset(f, engine="h5netcdf") for f in partes], combine_attrs="override")
    ds.attrs["creado"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    comun.escribe(ds, salida)
    for f in partes:
        f.unlink()


def main() -> None:
    """Punto de entrada: interpreta los argumentos y descarga cada día pedido."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    comun.args_fechas(p)
    comun.args_region(p)
    p.add_argument(
        "--pl",
        nargs="*",
        default=PL_DEFECTO,
        choices=list(PL),
        help="variables en niveles de presión",
    )
    p.add_argument(
        "--sfc", nargs="*", default=SFC_DEFECTO, choices=list(SFC), help="variables de superficie"
    )
    p.add_argument(
        "--procesos",
        type=int,
        default=4,
        help="lecturas simultáneas (por defecto 4; ~400 MB de RAM cada una)",
    )
    p.add_argument("--forzar", action="store_true", help="rehace los días que ya existen")
    a = p.parse_args()
    reg = comun.region_de(a)
    ctx = mp.get_context("spawn")  # s3fs no tolera fork: cada proceso abre su propia conexión

    with ProcessPoolExecutor(a.procesos, mp_context=ctx) as ex:
        for dia in comun.dias(a):
            if a.pl:
                salida = comun.carpeta(reg.nombre, "era5_pl") / f"era5_pl_{dia:%Y%m%d}.nc"
                if completo(salida, a.pl) and not a.forzar:
                    print(f"{salida.name}: ya existe", flush=True)
                else:
                    t0 = time.time()
                    descarga_pl(ex, dia, a.pl, reg, salida)
                    print(
                        f"{salida.name}: {len(a.pl)} variables en {time.time() - t0:.0f} s",
                        flush=True,
                    )
            if a.sfc:
                salida = comun.carpeta(reg.nombre, "era5_sfc") / f"era5_sfc_{dia:%Y%m%d}.nc"
                if completo(salida, a.sfc) and not a.forzar:
                    print(f"{salida.name}: ya existe", flush=True)
                else:
                    t0 = time.time()
                    h0, h1 = horas_del_dia(ruta_sfc(a.sfc[0], dia), dia)
                    fut = {
                        v: ex.submit(comun.reintenta, lee, ruta_sfc(v, dia), reg, h0, h1, 4 * 2**20)
                        for v in a.sfc
                    }
                    guarda({v: f.result() for v, f in fut.items()}, salida, False, reg)
                    print(
                        f"{salida.name}: {len(a.sfc)} variables en {time.time() - t0:.0f} s",
                        flush=True,
                    )


if __name__ == "__main__":
    main()
