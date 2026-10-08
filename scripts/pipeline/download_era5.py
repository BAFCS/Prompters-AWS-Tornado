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

    data/crops/<region>/era5_pl/era5_pl_AAAAMMDD.nc    (time, level, latitude, longitude)
    data/crops/<region>/era5_sfc/era5_sfc_AAAAMMDD.nc  (time, latitude, longitude)

Uso::

    uv run python scripts/pipeline/download_era5.py --start 2019-05-30
    uv run python scripts/pipeline/download_era5.py --start 2019-05-29 --end 2019-05-31 --pl u v t --sfc cape
"""

import calendar
import datetime as dt
import multiprocessing as mp
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

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
PL_DEFAULT = ["u", "v", "w", "t", "q", "z", "r", "vo"]
SFC_DEFAULT = ["10u", "10v", "100u", "100v", "2t", "2d", "sp", "msl", "cape", "tcwv", "blh", "tcc"]
EPOCH = np.datetime64("1900-01-01T00:00")


def pl_path(v: str, day: dt.date) -> str:
    """Clave S3 del archivo diario de niveles de presión de la variable ``v``."""
    code, grid = PL[v]
    d = day.strftime("%Y%m%d")
    return f"{BUCKET}/e5.oper.an.pl/{day:%Y%m}/e5.oper.an.pl.{code}.{grid}.{d}00_{d}23.nc"


def sfc_path(v: str, day: dt.date) -> str:
    """Clave S3 del archivo mensual de superficie de la variable ``v`` que contiene ``day``."""
    last = calendar.monthrange(day.year, day.month)[1]
    return (
        f"{BUCKET}/e5.oper.an.sfc/{day:%Y%m}/e5.oper.an.sfc.{SFC[v]}.ll025sc."
        f"{day:%Y%m}0100_{day:%Y%m}{last:02d}23.nc"
    )


def indices(lat: np.ndarray, lon: np.ndarray, reg: common.Region) -> tuple[slice, slice]:
    """Rebanadas de latitud (90→−90) y longitud (0→360 este) que cubren la región ``reg``."""
    assert reg.west < 0 and reg.east < 0, "la región debe estar al oeste de Greenwich"
    i = np.flatnonzero((lat <= reg.north) & (lat >= reg.south))
    j = np.flatnonzero((lon >= 360 + reg.west) & (lon <= 360 + reg.east))
    return slice(i[0], i[-1] + 1), slice(j[0], j[-1] + 1)


def variable(h: h5py.File) -> h5py.Dataset:
    """El único dataset con datos (≥ 3 dimensiones) de un archivo ERA5 de NSF NCAR."""
    (name,) = [k for k, d in h.items() if isinstance(d, h5py.Dataset) and d.ndim >= 3]
    return common.dataset(h, name)


def is_global_chunk(d: h5py.Dataset) -> bool:
    """Si ``d`` está dividido en bloques de un instante con el globo entero, comprimidos con gzip."""
    c = d.chunks
    return bool(c) and c[0] == 1 and c[1:] == d.shape[1:] and d.compression == "gzip"


def decode(b: bytes, d: h5py.Dataset) -> np.ndarray:
    """Descomprime un bloque crudo de ``d`` (gzip y, si corresponde, deshace el filtro shuffle)."""
    raw = zlib.decompress(b)
    size = d.dtype.itemsize
    if d.shuffle:  # shuffle agrupa el byte 0 de todos los valores, luego el byte 1, etc.
        raw = np.frombuffer(raw, np.uint8).reshape(size, -1).T.tobytes()
    return np.frombuffer(raw, d.dtype).reshape(d.chunks or ())


def read(path: str, reg: common.Region, h0: int, h1: int, block: int) -> dict:
    """Lee de ``path`` el recorte de ``reg`` entre los índices de tiempo ``h0`` y ``h1`` (exclusivo).

    Si el archivo guarda cada instante como un bloque global (niveles de presión), pide a S3
    exactamente los bytes de esos bloques y los recorta en memoria; si no, lee con h5py, con
    lecturas de ``block`` bytes. Devuelve los datos en ``float32`` junto con las coordenadas y los
    atributos de la variable.
    """
    fs = common.s3()
    with fs.open(path, "rb", block_size=block) as f, h5py.File(f, "r") as h:
        lat, lon = common.dataset(h, "latitude")[:], common.dataset(h, "longitude")[:]
        si, sj = indices(lat, lon, reg)
        d = variable(h)
        if is_global_chunk(d):
            parts = []
            for k in range(h0, h1):
                info = d.id.get_chunk_info_by_coord((k,) + (0,) * (d.ndim - 1))
                b = fs.cat_file(path, start=info.byte_offset, end=info.byte_offset + info.size)
                assert isinstance(b, bytes), f"lectura fallida en {path}"
                parts.append(decode(b, d)[0, ..., si, sj])
            data = np.stack(parts)
        else:
            data = d[h0:h1, ..., si, sj]
        out = {
            "data": data.astype("f4"),
            "time": EPOCH + common.dataset(h, "time")[h0:h1].astype("timedelta64[h]"),
            "lat": lat[si],
            "lon": lon[sj] - 360,
            "attrs": {a: common.text(d.attrs[a]) for a in ("long_name", "units") if a in d.attrs},
        }
        if "level" in h:
            out["level"] = common.dataset(h, "level")[:]
    return out


def day_hours(path: str, day: dt.date) -> tuple[int, int]:
    """Rango ``[h0, h1)`` de índices de ``path`` (archivo mensual) con las 24 horas de ``day``."""
    fs = common.s3()
    with fs.open(path, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        t = EPOCH + common.dataset(h, "time")[:].astype("timedelta64[h]")
    k = np.flatnonzero(t.astype("datetime64[D]") == np.datetime64(day))
    return int(k[0]), int(k[-1]) + 1


def save(res: dict[str, dict], out_file: Path, has_level: bool, reg: common.Region) -> None:
    """Escribe en ``out_file`` un NetCDF comprimido con las variables leídas en ``res``."""
    r0 = next(iter(res.values()))
    dims = (
        ("time", "level", "latitude", "longitude")
        if has_level
        else ("time", "latitude", "longitude")
    )
    coords = {"time": r0["time"], "latitude": r0["lat"], "longitude": r0["lon"]}
    if has_level:
        coords["level"] = xr.DataArray(r0["level"], dims="level", attrs={"units": "hPa"})
    ds = xr.Dataset(
        {v: (dims, r["data"], r["attrs"]) for v, r in res.items()},
        coords=coords,
        attrs={
            "source": f"s3://{BUCKET}/ (ERA5, ECMWF; copia NSF NCAR, doi:10.5065/BH6N-5N20)",
            "region": f"{reg.name}: {reg.north}..{reg.south} lat, {reg.west}..{reg.east} lon",
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
    )
    common.write(ds, out_file)


def is_complete(out_file: Path, variables: list[str]) -> bool:
    """Si ``out_file`` ya existe y contiene todas las ``variables`` pedidas."""
    if not out_file.exists():
        return False
    with xr.open_dataset(out_file, engine="h5netcdf") as ds:
        return set(variables) <= set(ds.data_vars)


def concat_parts(parts: list[dict]) -> dict:
    """Une las lecturas horarias ``parts`` de una variable en una sola, a lo largo del tiempo."""
    return parts[0] | {
        "data": np.concatenate([x["data"] for x in parts]),
        "time": np.concatenate([x["time"] for x in parts]),
    }


def download_pl(
    ex: ProcessPoolExecutor, day: dt.date, variables: list[str], reg: common.Region, out_file: Path
) -> None:
    """Descarga los niveles de presión de ``day`` y los escribe en ``out_file``.

    Cada variable terminada se guarda aparte en ``.parts/``; si el proceso se corta, al volver a
    correr solo se bajan las variables que faltan. Al final se unen en un solo archivo.
    """
    parts_dir = out_file.parent / ".parts"
    parts_dir.mkdir(exist_ok=True)
    part = {v: parts_dir / f"{out_file.stem}_{v}.nc" for v in variables}
    missing = [v for v in variables if not part[v].exists()]
    # Una tarea por (variable, hora): cada una transfiere un bloque global.
    fut = {
        (v, k): ex.submit(common.retry, read, pl_path(v, day), reg, k, k + 1, 2**20)
        for v in missing
        for k in range(24)
    }
    for v in missing:
        t0 = time.time()
        save({v: concat_parts([fut[v, k].result() for k in range(24)])}, part[v], True, reg)
        print(f"  {out_file.stem} {v}: {time.time() - t0:.0f} s", flush=True)
    merge_parts([part[v] for v in variables], out_file)


def download_sfc(
    ex: ProcessPoolExecutor, day: dt.date, variables: list[str], reg: common.Region, out_file: Path
) -> None:
    """Descarga las variables de superficie de ``day`` (solo el recuadro) y las escribe en ``out_file``."""
    h0, h1 = day_hours(sfc_path(variables[0], day), day)
    fut = {
        v: ex.submit(common.retry, read, sfc_path(v, day), reg, h0, h1, 4 * 2**20)
        for v in variables
    }
    save({v: f.result() for v, f in fut.items()}, out_file, False, reg)


def merge_parts(parts: list[Path], out_file: Path) -> None:
    """Une los archivos de una variable ``parts`` en ``out_file`` y los borra."""
    ds = xr.merge([xr.load_dataset(f, engine="h5netcdf") for f in parts], combine_attrs="override")
    ds.attrs["created"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    common.write(ds, out_file)
    for f in parts:
        f.unlink()


def main() -> None:
    """Punto de entrada: interpreta los argumentos y descarga cada día pedido."""
    p = common.parser(__doc__, "los días")
    p.add_argument(
        "--pl",
        nargs="*",
        default=PL_DEFAULT,
        choices=list(PL),
        help="variables en niveles de presión",
    )
    p.add_argument(
        "--sfc", nargs="*", default=SFC_DEFAULT, choices=list(SFC), help="variables de superficie"
    )
    p.add_argument(
        "--processes",
        type=int,
        default=4,
        help="lecturas simultáneas (por defecto 4; ~400 MB de RAM cada una)",
    )
    a = p.parse_args()
    reg = common.region_of(a)
    ctx = mp.get_context("spawn")  # s3fs no tolera fork: cada proceso abre su propia conexión

    with ProcessPoolExecutor(a.processes, mp_context=ctx) as ex:
        for day in common.days(a):
            for source, variables, download in (
                ("era5_pl", a.pl, download_pl),
                ("era5_sfc", a.sfc, download_sfc),
            ):
                if not variables:
                    continue
                out_file = common.folder(reg.name, source) / f"{source}_{day:%Y%m%d}.nc"
                if is_complete(out_file, variables) and not a.force:
                    print(f"{out_file.name}: ya existe", flush=True)
                    continue
                t0 = time.time()
                download(ex, day, variables, reg, out_file)
                print(
                    f"{out_file.name}: {len(variables)} variables en {time.time() - t0:.0f} s",
                    flush=True,
                )


if __name__ == "__main__":
    main()
