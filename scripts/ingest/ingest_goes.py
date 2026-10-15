#!/usr/bin/env python3
"""Ingesta imágenes GOES-East recortadas a Chile al bucket privado de pruebas en S3.

Variante del experimento de ingesta, análoga a ``scripts/ingest/ingest_ncar_zarr.py`` pero para el
satélite GOES en vez de ERA5. Baja un día recortado a la región ``south-central-austral`` y lo
escribe en el bucket privado de la cuenta, dejando además su progreso en un JSON de S3 que lee el
panel orquestador.

PRODUCTO. El pipeline histórico (``scripts/pipeline/download_goes.py``) usa ``ABI-L2-MCMIPF`` (un
archivo por hora con las 16 bandas). Ese producto **no tiene datos para 2019** en el archivo de Open
Data. El producto disponible y correcto para el periodo del proyecto es ``ABI-L2-CMIPF`` (*Cloud and
Moisture Imagery Product, Full Disk*), que trae **un archivo por banda y por escena** con una única
variable ``CMI``. Esta ingesta apunta a ``ABI-L2-CMIPF`` y filtra solo la **banda 13** (infrarrojo de
ventana limpia, ~10,3 µm, la que ve los topes nubosos), cuyos archivos se llaman::

    OR_ABI-L2-CMIPF-M6C13_G16_sYYYYJJJHHMMSS?_eYYYYJJJHHMMSS?_cYYYYJJJHHMMSS?.nc

El modo del barrido (``M3`` antes de abr-2019, ``M6`` después) va en el nombre; este script acepta
cualquier modo y se queda con los archivos de la banda pedida.

LA FRUTA MADURA DEL EXPERIMENTO. A diferencia de ERA5 (``s3://nsf-ncar-era5/`` vive en
``us-west-2``), los dos buckets de GOES-East —``s3://noaa-goes16/`` y ``s3://noaa-goes19/``— están
en **us-east-1**, la MISMA región que la cuenta del experimento (822870558093, solo us-east-1). Por
eso esta ingesta **no cruza regiones**: la lectura es más barata y rápida que la de ERA5, no paga
tráfico inter-región ni sufre la lentitud del cruce, y no depende de ninguna API externa (como el
CDS de Copernicus). Es, con diferencia, el camino de ingesta **menos problemático** de las tres
fuentes del proyecto.

Fuente (lectura, anónima; Open Data no requiere credenciales)::

    s3://noaa-goes16/ABI-L2-CMIPF/<AAAA>/<DÍA_JULIANO>/<HH>/OR_ABI-L2-CMIPF-M?C13_G16_s...nc
    s3://noaa-goes19/ABI-L2-CMIPF/...   (GOES-19, desde 2025-04-04 15 UTC)

El día juliano es el día del año (1 el 1 de enero): 2019-05-30 es el día 150.

Destino (escritura, con credenciales de la cuenta)::

    s3://mesocyclonic-test-data-20261015013924290100000003/goes_store/<AAAA-MM-DD>/goes_<AAAAMMDD>.nc

Progreso (para el panel orquestador)::

    s3://mesocyclonic-test-data-20261015013924290100000003/experimentos/progreso_goes.json

Dado ``--date AAAA-MM-DD`` (o ``--start``/``--end`` para un rango) y ``--band`` (por defecto 13),
baja todas las escenas horarias de cada día recortadas a Chile, las apila en un único
``xarray.Dataset`` ``(time, y, x)`` sobre la grilla fija del ABI (con ``lat``/``lon`` 2D, sin
corrección de paralaje) y lo escribe como NetCDF (por defecto) o Zarr (``--format zarr``).

Uso::

    uv run python scripts/ingest/ingest_goes.py --date 2019-05-30
    uv run python scripts/ingest/ingest_goes.py --start 2019-05-30 --end 2019-06-02
    uv run python scripts/ingest/ingest_goes.py --date 2019-05-30 --no-upload --output-dir /tmp/goes

No descarga ni sube nada al importarse: todo ocurre bajo ``main()``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import h5py
import numpy as np
import s3fs
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

# Se reutilizan de ``download_goes`` solo las piezas genéricas de la lectura por rango de bytes de un
# dataset HDF5 chunked (índice de bloques y ensamblado del recorte); NO su lógica multibanda MCMIPF.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import download_goes as goes  # noqa: E402

# Producto correcto para el periodo del proyecto: un archivo por banda y escena, variable ``CMI``.
PRODUCT = "ABI-L2-CMIPF"
# Fecha de corte de GOES-16 a GOES-19 (misma que usa el pipeline).
G19_SWITCH = dt.datetime(2025, 4, 4, 15)

# Bucket y prefijo de destino del experimento. El bucket se puede sobreescribir con la variable de
# entorno DEST_BUCKET, para que otro equipo escriba en SU propio bucket sin tocar el código.
DEST_BUCKET = os.environ.get("DEST_BUCKET", "mesocyclonic-test-data-20261015013924290100000003")
DEST_PREFIX = "goes_store"
PROGRESS_KEY = "experimentos/progreso_goes.json"
AWS_REGION = "us-east-1"

# Región del proyecto: Norte -30, Sur -56, Oeste -76, Este -66.
REGION_NAME = "south-central-austral"

# Banda ABI por defecto: 13, infrarrojo de ventana limpia (~10,3 µm), la que ve los topes nubosos.
DEFAULT_BAND = 13

# Robustez: tope por operación de red y número de reintentos ante cortes.
S3_TIMEOUT_S = 120
RETRY_ATTEMPTS = 5

# ``OR_ABI-L2-CMIPF-M<modo>C<banda>_G<sat>_s<inicio>_e..._c...nc``. El modo es un dígito (3, 4, 6).
CMIPF_NAME_RE = re.compile(r"OR_ABI-L2-CMIPF-M\dC(\d{2})_G\d{2}_s\d+_e\d+_c\d+\.nc$")


def satellite_bucket(day: dt.date, hour: int) -> str:
    """Bucket de GOES-East para ``day`` a la hora ``hour``: ``noaa-goes16`` o ``noaa-goes19``."""
    t = dt.datetime.combine(day, dt.time(hour))
    return "noaa-goes19" if t >= G19_SWITCH else "noaa-goes16"


def band_of(path: str) -> int | None:
    """Banda ABI del nombre de un archivo CMIPF, o ``None`` si el nombre no encaja."""
    m = CMIPF_NAME_RE.search(path.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else None


def list_scenes(fs: s3fs.S3FileSystem, day: dt.date, band: int) -> dict[int, list[str]]:
    """Escenas CMIPF de ``band`` del día ``day`` agrupadas por hora UTC.

    Recorre las 24 carpetas horarias ``.../<AAAA>/<DÍA_JULIANO>/<HH>/`` del bucket que corresponda a
    la fecha, filtra por banda y por que la hora de inicio del barrido caiga en esa hora, y las
    ordena por nombre (equivale a ordenarlas por tiempo de inicio).
    """
    out: dict[int, list[str]] = defaultdict(list)
    year, jday = day.year, day.timetuple().tm_yday
    for h in range(24):
        bucket = satellite_bucket(day, h)
        folder = f"{bucket}/{PRODUCT}/{year}/{jday:03d}/{h:02d}/"
        try:
            paths = common.retry(fs.ls, folder, attempts=RETRY_ATTEMPTS)
        except FileNotFoundError:
            continue
        scenes = [
            p
            for p in paths
            if p.endswith(".nc") and band_of(p) == band and goes.scan_start(p).hour == h
        ]
        if scenes:
            out[h] = sorted(scenes)
    return out


def read_scene(fs: s3fs.S3FileSystem, path: str, v: dict) -> dict:
    """Lee el recorte ``v`` de la variable ``CMI`` de una escena CMIPF ``path``, como entero crudo.

    Lee el dataset ``CMI`` **directo con h5py** (``d[r0:r1, c0:c1]``), que descomprime cualquier
    filtro HDF5 automáticamente. Antes se usaba ``download_goes.chunk_ranges`` (lectura por rango de
    bytes) pero asume gzip-sin-shuffle, y el ``CMI`` de CMIPF usa otros filtros, lo que hacía fallar
    TODAS las escenas con "filtros inesperados en /CMI". Como GOES está en us-east-1 (intra-región),
    el pequeño sobrecosto de leer el bloque completo del recorte es despreciable y evita el fallo.
    Devuelve datos crudos más la escala y el desfase para reconstruir el valor físico sin pérdida.
    """
    with fs.open(path, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        d = common.dataset(h, "CMI")
        s = v.get("stride", 1)
        data = d[v["r0"] * s : v["r1"] * s : s, v["c0"] * s : v["c1"] * s : s]
        return {
            "time": np.datetime64(goes.scan_start(path), "ms"),
            "satellite": common.text(h.attrs.get("platform_ID", "?")),
            "data": data,
            "scale": common.num(d, "scale_factor"),
            "offset": common.num(d, "add_offset"),
            "unit": common.text(d.attrs["units"]),
            "name": common.text(d.attrs["long_name"]),
        }


class _ByteMeter:
    """Contador de bytes transferidos desde la fuente, compartido entre las lecturas de un día."""

    def __init__(self) -> None:
        """Arranca el contador en cero."""
        self.total: int = 0

    def add(self, n: int) -> None:
        """Suma ``n`` bytes al total transferido."""
        self.total += n


def source_fs(meter: _ByteMeter) -> s3fs.S3FileSystem:
    """``S3FileSystem`` **anónimo** de lectura (Open Data) cuyo tráfico se contabiliza en ``meter``.

    Envuelve ``cat_ranges`` (bloques de la banda) y ``open`` (índice de bloques y ejes al abrir con
    h5py) para medir todo lo leído de la fuente. Fija ``us-east-1`` (misma región que el bucket) y un
    tope de tiempo por operación para no colgarse si la conexión se degrada.
    """
    fs = s3fs.S3FileSystem(
        anon=True,
        client_kwargs={"region_name": AWS_REGION},
        config_kwargs={
            "connect_timeout": S3_TIMEOUT_S,
            "read_timeout": S3_TIMEOUT_S,
            "retries": {"max_attempts": 3},
        },
    )
    raw_cat_ranges: Callable[..., list[bytes]] = fs.cat_ranges
    raw_open = fs.open

    def cat_ranges(
        paths: list[str], starts: list[int], ends: list[int], **kw: object
    ) -> list[bytes]:
        chunks = raw_cat_ranges(paths, starts, ends, **kw)
        for c in chunks:
            if isinstance(c, bytes):
                meter.add(len(c))
        return chunks

    def open_(path: str, mode: str = "rb", **kw: object) -> object:
        f = raw_open(path, mode, **kw)
        if "r" in mode:
            raw_read = f.read

            def counting_read(length: int = -1) -> bytes:
                chunk = raw_read(length)
                assert isinstance(chunk, bytes), "lectura no binaria"
                meter.add(len(chunk))
                return chunk

            f.read = counting_read  # type: ignore[method-assign]
        return f

    fs.cat_ranges = cat_ranges  # type: ignore[method-assign]
    fs.open = open_  # type: ignore[method-assign]
    return fs


def read_day(fs: s3fs.S3FileSystem, day: dt.date, band: int, reg: common.Region) -> list[dict]:
    """Lee todas las escenas horarias de ``band`` del día ``day``, recortadas a ``reg``.

    Calcula una sola vez la ventana (filas/columnas del disco que cubren Chile) con la primera
    escena, la adosa a cada escena en ``"_window"`` y lee cada una con reintentos.
    """
    by_hour = list_scenes(fs, day, band)
    scenes = [p for ps in by_hour.values() for p in ps]
    if not scenes:
        return []
    # Submuestreo según resolución nativa de la banda: C02 es 0,5 km (stride 4 -> 2 km) y las
    # bandas 1/3/5 son 1 km (stride 2). El resto son 2 km (stride 1). Evita el OOM del meshgrid
    # full-disk y deja todas las bandas en la misma grilla de 2 km (apilables para el modelo).
    stride = {2: 4, 1: 2, 3: 2, 5: 2}.get(band, 1)
    v = common.retry(goes.window, scenes[0], reg, stride, attempts=RETRY_ATTEMPTS)
    parts: list[dict] = []
    for path in scenes:
        part = common.retry(read_scene, fs, path, v, attempts=RETRY_ATTEMPTS)
        part["_window"] = v
        parts.append(part)
    return sorted(parts, key=lambda p: p["time"])


def build_dataset(parts: list[dict], band: int, reg: common.Region) -> xr.Dataset:
    """Apila las escenas ``parts`` de ``band`` en un ``xarray.Dataset`` ``(time, y, x)``.

    Reconstruye los valores físicos (con ``scale``/``offset`` del original) y los vuelve a codificar
    como ``int16`` con la misma escala al escribir, sin pérdida respecto del archivo GOES.
    """
    v = parts[0]["_window"]
    name = f"C{band:02d}"
    p0 = parts[0]
    raw = np.stack([p["data"] for p in parts])
    physical = np.where(raw == -1, np.nan, raw * p0["scale"] + p0["offset"]).astype("f4")
    return xr.Dataset(
        {
            name: (
                ("time", "y", "x"),
                physical,
                {
                    "units": p0["unit"],
                    "long_name": p0["name"],
                    "wavelength_um": goes.LAMBDA[band],
                },
            )
        },
        coords={
            "time": np.array([p["time"] for p in parts]),
            "y": ("y", v["y"], {"units": "rad", "long_name": "ángulo de barrido N-S del ABI"}),
            "x": ("x", v["x"], {"units": "rad", "long_name": "ángulo de barrido E-O del ABI"}),
            "lat": (("y", "x"), v["lat"], {"units": "degrees_north"}),
            "lon": (("y", "x"), v["lon"], {"units": "degrees_east"}),
        },
        attrs={
            "source": f"s3://noaa-goes16|19/{PRODUCT} ({p0['satellite']})",
            "note": (
                "grilla fija del ABI; lat/lon sin corrección de paralaje; time = inicio del barrido"
            ),
            "ingest": "goes-byte-range (us-east-1, misma región; sin cruce)",
            **common.stamp(reg),
        },
    )


def encoding(parts: list[dict], band: int) -> dict[str, dict]:
    """Codificación entera (``int16`` con escala/desfase) sin pérdida para escribir el dataset."""
    name = f"C{band:02d}"
    p0 = parts[0]
    enc: dict[str, dict] = {
        name: common.COMPRESSION
        | {
            "dtype": "int16",
            "scale_factor": p0["scale"],
            "add_offset": p0["offset"],
            "_FillValue": -1,
        }
    }
    for c in ("lat", "lon"):
        enc[c] = common.COMPRESSION
    return enc


def dest_path(day: dt.date, fmt: str, band: int) -> str:
    """Ruta ``s3://`` de destino para ``day`` y ``band`` (``nc`` o ``zarr``).

    Incluye la banda en el nombre (``goes_YYYYMMDD_CNN.nc``) para que varias bandas del mismo día
    no se pisen entre sí. El prefijo por banda es ``goes_store/<fecha>/``.
    """
    suffix = "nc" if fmt == "nc" else "zarr"
    return f"s3://{DEST_BUCKET}/{DEST_PREFIX}/{day:%Y-%m-%d}/goes_{day:%Y%m%d}_C{band:02d}.{suffix}"


def dest_fs() -> s3fs.S3FileSystem:
    """``S3FileSystem`` con credenciales de la cuenta, fijado a us-east-1 (bucket regional)."""
    return s3fs.S3FileSystem(
        client_kwargs={"region_name": AWS_REGION},
        config_kwargs={"connect_timeout": S3_TIMEOUT_S, "read_timeout": S3_TIMEOUT_S},
    )


def write_netcdf_s3(ds: xr.Dataset, enc: dict[str, dict], dest: str) -> None:
    """Escribe ``ds`` como NetCDF en ``dest`` (S3): a un ``.tmp`` local y sube con ``s3fs.put``."""
    tmp = Path(f"goes_{int(time.time())}.tmp.nc")
    try:
        ds.to_netcdf(tmp, engine="h5netcdf", encoding=enc)
        common.retry(dest_fs().put, str(tmp), dest, attempts=RETRY_ATTEMPTS)
    finally:
        tmp.unlink(missing_ok=True)


def write_zarr_s3(ds: xr.Dataset, dest: str) -> None:
    """Escribe ``ds`` como store Zarr en ``dest`` (S3, con credenciales), sobrescribiendo."""
    mapper = s3fs.S3Map(root=dest, s3=dest_fs(), check=False)
    ds.to_zarr(mapper, mode="w", consolidated=True)


def write_local(ds: xr.Dataset, enc: dict[str, dict], out_file: Path, fmt: str) -> None:
    """Escribe ``ds`` en disco local (``out_file``) en NetCDF o Zarr, para ``--no-upload``."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "nc":
        common.write(ds, out_file, enc)
    else:
        ds.to_zarr(out_file, mode="w", consolidated=True)


def write_progress(
    *,
    dia_actual: int,
    dia_total: int,
    hecho: int,
    total: int,
    mb: float,
    segundos: float,
    estado: str,
    eta_segundos: float,
) -> None:
    """Escribe ``experimentos/progreso_goes.json`` en S3 con el formato que lee el orquestador.

    Formato exacto: ``{fuente, dia_actual, dia_total, hecho, total, porcentaje, mb, segundos,
    estado, eta_segundos}``. No falla la ingesta si la escritura del progreso falla (best-effort).
    """
    porcentaje = round(100.0 * hecho / total, 1) if total else 0.0
    payload = {
        "fuente": "goes",
        "dia_actual": dia_actual,
        "dia_total": dia_total,
        "hecho": hecho,
        "total": total,
        "porcentaje": porcentaje,
        "mb": round(mb, 1),
        "segundos": round(segundos, 1),
        "estado": estado,
        "eta_segundos": round(eta_segundos, 1),
    }
    try:
        with dest_fs().open(f"{DEST_BUCKET}/{PROGRESS_KEY}", "w") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:  # el progreso es informativo: no debe tumbar la ingesta
        print(f"  aviso: no se pudo escribir el progreso ({e!s:.120})", file=sys.stderr, flush=True)


def ingest_day(
    fs: s3fs.S3FileSystem,
    meter: _ByteMeter,
    day: dt.date,
    band: int,
    reg: common.Region,
    fmt: str,
    *,
    upload: bool,
    output_dir: Path,
) -> tuple[float, float, int, str]:
    """Baja ``day`` para ``band`` recortado a ``reg`` y lo escribe (S3 o local).

    Devuelve ``(segundos, mb_del_día, n_escenas, destino)``. ``meter`` acumula el tráfico global de
    la corrida; el MB del día se calcula por diferencia.
    """
    t0 = time.time()
    mb0 = meter.total / 2**20

    parts = read_day(fs, day, band, reg)
    if not parts:
        return time.time() - t0, meter.total / 2**20 - mb0, 0, ""

    ds = build_dataset(parts, band, reg)
    enc = encoding(parts, band)

    if upload:
        dest = dest_path(day, fmt, band)
        if fmt == "nc":
            write_netcdf_s3(ds, enc, dest)
        else:
            write_zarr_s3(ds, dest)
    else:
        suffix = "nc" if fmt == "nc" else "zarr"
        out_file = output_dir / f"{day:%Y-%m-%d}" / f"goes_{day:%Y%m%d}.{suffix}"
        write_local(ds, enc, out_file, fmt)
        dest = str(out_file)

    return time.time() - t0, meter.total / 2**20 - mb0, len(parts), dest


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Lista de días entre ``start`` y ``end`` (inclusive)."""
    assert end >= start, "--end debe ser igual o posterior a --start/--date"
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def parse_args() -> argparse.Namespace:
    """Interpreta los argumentos de la línea de comandos (``--date`` o ``--start``/``--end``)."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--date", type=dt.date.fromisoformat, help="un solo día, AAAA-MM-DD (UTC)")
    p.add_argument(
        "--start", type=dt.date.fromisoformat, help="primer día de un rango, AAAA-MM-DD (UTC)"
    )
    p.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        help="último día del rango (inclusive); por defecto --start",
    )
    p.add_argument(
        "--band",
        type=int,
        default=DEFAULT_BAND,
        choices=list(goes.LAMBDA),
        help="banda ABI 1-16 (por defecto 13, infrarrojo de ventana ~10,3 µm)",
    )
    p.add_argument(
        "--format",
        choices=("nc", "zarr"),
        default="nc",
        help="formato de salida: NetCDF (nc, por defecto) o Zarr",
    )
    p.add_argument(
        "--no-upload",
        action="store_true",
        help="no sube a S3; solo lee, arma el dataset y lo escribe en --output-dir",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/goes_store"),
        help="carpeta local para --no-upload (por defecto data/goes_store)",
    )
    p.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="índice de este worker en la flota (0..N-1); por defecto 0 (sin sharding)",
    )
    p.add_argument(
        "--shard-total",
        type=int,
        default=1,
        help="número de workers de la flota; por defecto 1 (procesa todos los días)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="salta los días cuyo archivo ya está en S3 (idempotente, no re-baja lo ya hecho)",
    )
    return p.parse_args()


def resolve_days(args: argparse.Namespace) -> list[dt.date]:
    """Devuelve la lista de días a ingestar a partir de ``--date`` o ``--start``/``--end``.

    Si ``--shard-total`` > 1, cada worker toma solo los días cuyo índice ``% shard_total ==
    shard_index`` (reparto sin solapamiento entre instancias de la flota).
    """
    if args.date is not None:
        if args.start is not None or args.end is not None:
            raise SystemExit("usa --date O --start/--end, no ambos")
        all_days = [args.date]
    elif args.start is None:
        raise SystemExit("falta --date o --start")
    else:
        all_days = date_range(args.start, args.end or args.start)
    if args.shard_total > 1:
        return [d for i, d in enumerate(all_days) if i % args.shard_total == args.shard_index]
    return all_days


def main() -> int:
    """Punto de entrada: ingesta cada día pedido, reportando progreso a S3 y por pantalla."""
    args = parse_args()
    reg = common.REGIONS[REGION_NAME]
    band: int = args.band
    days = resolve_days(args)
    dia_total = len(days)
    upload = not args.no_upload

    print(
        f"Ingesta GOES {PRODUCT} -> {args.format.upper()} | {dia_total} día(s) | banda C{band:02d} "
        f"(~{goes.LAMBDA[band]} µm) | región {reg.name} "
        f"({reg.north}..{reg.south} lat, {reg.west}..{reg.east} lon)",
        flush=True,
    )
    print(
        "  fuente: s3://noaa-goes16|19/ en us-east-1 (MISMA región; sin cruce inter-región)",
        flush=True,
    )

    fs = source_fs(meter := _ByteMeter())
    t_run = time.time()
    hecho = 0
    fallidos = 0

    if upload:
        write_progress(
            dia_actual=0,
            dia_total=dia_total,
            hecho=0,
            total=dia_total,
            mb=0.0,
            segundos=0.0,
            estado="en curso",
            eta_segundos=0.0,
        )

    for i, day in enumerate(days, start=1):
        # Idempotencia: si el día ya está en S3, se salta (no re-baja ni pisa lo ya hecho).
        if args.skip_existing and upload:
            try:
                import boto3

                key = f"goes_store/{day:%Y-%m-%d}/goes_{day:%Y%m%d}_C{band:02d}.nc"
                boto3.client("s3", region_name=AWS_REGION).head_object(Bucket=DEST_BUCKET, Key=key)
                hecho += 1
                print(f"  {day}: ya existe en S3, saltado", flush=True)
                continue
            except Exception:  # noqa: BLE001  (no existe -> se procesa normal)
                pass
        try:
            elapsed, mb_day, n, dest = ingest_day(
                fs,
                meter,
                day,
                band,
                reg,
                args.format,
                upload=upload,
                output_dir=args.output_dir,
            )
        except (
            Exception
        ) as e:  # red, h5py o permisos de S3; se informa y se sigue con el día siguiente
            print(
                f"  {day}: ERROR ({e!s:.160}); se continúa con el siguiente",
                file=sys.stderr,
                flush=True,
            )
            fallidos += 1
            elapsed, mb_day, n, dest = 0.0, 0.0, 0, ""

        if n == 0 and dest == "":
            print(f"  {day}: sin escenas GOES (¿fecha sin datos?) o falló", flush=True)
        else:
            hecho += 1
            print(
                f"  {day}: {n} escenas, {mb_day:.1f} MB, {elapsed:.1f} s -> {dest}",
                flush=True,
            )

        total_s = time.time() - t_run
        eta = (total_s / i) * (dia_total - i) if i < dia_total else 0.0
        estado = (
            "en curso"
            if i < dia_total
            else ("terminado" if fallidos == 0 else "terminado con errores")
        )
        if upload:
            write_progress(
                dia_actual=i,
                dia_total=dia_total,
                hecho=i,
                total=dia_total,
                mb=meter.total / 2**20,
                segundos=total_s,
                estado=estado,
                eta_segundos=eta,
            )

    total_s = time.time() - t_run
    mb = meter.total / 2**20
    print("", flush=True)
    print("Resumen del experimento (GOES, rango de bytes, us-east-1):", flush=True)
    print(f"  días pedidos:      {dia_total}", flush=True)
    print(f"  días con datos:    {hecho}", flush=True)
    print(f"  días fallidos:     {fallidos}", flush=True)
    print(f"  tiempo total:      {total_s:.1f} s", flush=True)
    print(f"  MB transferidos:   {mb:.1f} MB (leídos de s3://noaa-goes16|19/)", flush=True)
    if total_s > 0:
        print(f"  rendimiento:       {mb / total_s:.1f} MB/s", flush=True)

    if hecho == 0:
        return 1
    return 0 if fallidos == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
