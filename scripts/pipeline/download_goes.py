#!/usr/bin/env python3
"""Descarga GOES-East ``ABI-L2-MCMIPF`` (16 bandas, disco completo, 2 km) recortado a una región.

Cada archivo del disco completo pesa ~360 MB, pero está dividido en bloques de 226 × 226 píxeles.
El script lee el índice de bloques del archivo y pide a S3, en una sola tanda concurrente, solo los
bloques que tocan la región; después los descomprime y los ensambla. El satélite se elige por fecha:
``noaa-goes16`` hasta el 4-abr-2025 a las 15 UTC y ``noaa-goes19`` desde entonces.

Los valores se guardan tal como vienen (enteros de 12 bits con ``scale_factor`` y ``add_offset``),
en la grilla fija del ABI, junto con la latitud y longitud de cada píxel. No se corrige paralaje.

Salida (un archivo por hora, hasta 6 imágenes; 4 antes del 2-abr-2019)::

    data/crops/<region>/goes/AAAAMMDD/goes_AAAAMMDDHH.nc   (time, y, x)

Uso::

    uv run python scripts/pipeline/download_goes.py --start 2019-05-30
    uv run python scripts/pipeline/download_goes.py --start 2019-05-30 --bands 8 13 --hours 18 23
"""

import datetime as dt
import multiprocessing as mp
import re
import sys
import time
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

PRODUCT = "ABI-L2-MCMIPF"
G19_SWITCH = dt.datetime(2025, 4, 4, 15)
LAMBDA = {
    1: 0.47, 2: 0.64, 3: 0.86, 4: 1.37, 5: 1.6, 6: 2.2, 7: 3.9, 8: 6.2,
    9: 6.9, 10: 7.3, 11: 8.4, 12: 9.6, 13: 10.3, 14: 11.2, 15: 12.3, 16: 13.3,
}  # fmt: skip
GOES_EPOCH = np.datetime64("2000-01-01T12:00:00")
SCAN_START_RE = re.compile(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})(\d)_")


def scan_start(path: str) -> dt.datetime:
    """Hora de inicio del barrido, leída del campo ``s`` del nombre (nunca del campo ``c``)."""
    m = SCAN_START_RE.search(path)
    assert m, f"nombre GOES inesperado: {path}"
    a, j, h, mi, s, d = (int(g) for g in m.groups())
    return dt.datetime(a, 1, 1) + dt.timedelta(days=j - 1, hours=h, minutes=mi, seconds=s + d / 10)


def files(day: dt.date, hours: range) -> dict[int, list[str]]:
    """Archivos del día ``day`` agrupados por hora, eligiendo GOES-16 o GOES-19 según la fecha."""
    fs = common.s3()
    out: dict[int, list[str]] = defaultdict(list)
    for h in hours:
        t = dt.datetime.combine(day, dt.time(h))
        bucket = "noaa-goes19" if t >= G19_SWITCH else "noaa-goes16"
        folder = f"{bucket}/{PRODUCT}/{t:%Y}/{t:%j}/{h:02d}/"
        try:
            paths = fs.ls(folder)
        except FileNotFoundError:
            print(f"  sin datos en s3://{folder}", flush=True)
            continue
        out[h] = sorted(r for r in paths if r.endswith(".nc") and scan_start(r).hour == h)
    return out


def window(path: str, reg: common.Region) -> dict:
    """Rectángulo de la grilla fija (filas y columnas) que cubre ``reg``, con sus coordenadas."""
    fs = common.s3()
    with fs.open(path, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        x, y, lat, lon = common.latlon_abi(h)
    inside = reg.contains(np.nan_to_num(lat, nan=99), np.nan_to_num(lon, nan=999))
    rows, cols = np.flatnonzero(inside.any(axis=1)), np.flatnonzero(inside.any(axis=0))
    assert rows.size, f"la región {reg.name} no cae dentro del disco del satélite"
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    return {
        "r0": r0, "r1": r1, "c0": c0, "c1": c1,
        "x": x[c0:c1], "y": y[r0:r1], "lat": lat[r0:r1, c0:c1], "lon": lon[r0:r1, c0:c1],
    }  # fmt: skip


def chunk_ranges(d: h5py.Dataset, v: dict) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Bloques de ``d`` que tocan el recorte ``v``: posición en el lienzo y rango de bytes de cada uno.

    El lienzo es el rectángulo alineado a bloques que contiene al recorte. Se omiten los bloques no
    asignados en el archivo (fuera del disco terrestre), que quedan con el valor de relleno.
    """
    assert d.compression == "gzip" and not d.shuffle and d.chunks, (
        f"filtros inesperados en {d.name}"
    )
    bf, bc = d.chunks
    f0, c0 = v["r0"] // bf * bf, v["c0"] // bc * bc
    pos, starts, ends = [], [], []
    for f in range(f0, min(v["r1"], d.shape[0]), bf):
        for c in range(c0, min(v["c1"], d.shape[1]), bc):
            info = d.id.get_chunk_info_by_coord((f, c))
            if info.byte_offset is None:
                continue
            pos.append((f - f0, c - c0))
            starts.append(info.byte_offset)
            ends.append(info.byte_offset + info.size)
    return pos, starts, ends


def crop(
    d: h5py.Dataset, v: dict, pos: list[tuple[int, int]], raw_chunks: list[bytes]
) -> np.ndarray:
    """Ensambla el recorte ``v`` de ``d`` a partir de los bloques comprimidos ``raw_chunks``."""
    bf, bc = d.chunks or (0, 0)
    f0, c0 = v["r0"] // bf * bf, v["c0"] // bc * bc
    canvas = np.full((-(-v["r1"] // bf) * bf - f0, -(-v["c1"] // bc) * bc - c0), -1, dtype=d.dtype)
    for (f, c), b in zip(pos, raw_chunks, strict=True):
        canvas[f : f + bf, c : c + bc] = np.frombuffer(zlib.decompress(b), d.dtype).reshape(bf, bc)
    return canvas[v["r0"] - f0 : v["r1"] - f0, v["c0"] - c0 : v["c1"] - c0]


def read(path: str, v: dict, bands: list[int]) -> dict:
    """Lee de un archivo ``MCMIPF`` el recorte ``v`` de cada banda, como enteros crudos.

    Los bloques de todas las bandas se piden a S3 en una sola tanda concurrente.
    """
    fs = common.s3()
    with fs.open(path, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        ds = {b: common.dataset(h, f"CMI_C{b:02d}") for b in bands}
        plan = {b: chunk_ranges(d, v) for b, d in ds.items()}
        paths = [path for p in plan.values() for _ in p[0]]
        raw_chunks = fs.cat_ranges(
            paths,
            [i for p in plan.values() for i in p[1]],
            [j for p in plan.values() for j in p[2]],
            batch_size=32,  # pedidos simultáneos por archivo; más satura la conexión
        )
        assert all(isinstance(c, bytes) for c in raw_chunks), f"lectura fallida en {path}"
        out = {
            "time": np.datetime64(scan_start(path), "ms"),
            "t_mid": GOES_EPOCH + np.timedelta64(int(common.dataset(h, "t")[()] * 1000), "ms"),
            "satellite": common.text(h.attrs.get("platform_ID", "?")),
            "bands": {},
        }
        k = 0
        for b, d in ds.items():
            n = len(plan[b][0])
            out["bands"][b] = {
                "data": crop(d, v, plan[b][0], raw_chunks[k : k + n]),
                "scale": common.num(d, "scale_factor"),
                "offset": common.num(d, "add_offset"),
                "unit": common.text(d.attrs["units"]),
                "name": common.text(d.attrs["long_name"]),
            }
            k += n
    return out


def save(parts: list[dict], v: dict, out_file: Path, reg: common.Region) -> None:
    """Escribe en ``out_file`` las imágenes ``parts`` de una hora como NetCDF comprimido."""
    parts = sorted(parts, key=lambda p: p["time"])
    data, encoding = {}, {}
    for b, b0 in parts[0]["bands"].items():
        raw = np.stack([p["bands"][b]["data"] for p in parts])
        name = f"C{b:02d}"
        physical = np.where(raw == -1, np.nan, raw * b0["scale"] + b0["offset"]).astype("f4")
        data[name] = (
            ("time", "y", "x"),
            physical,
            {"units": b0["unit"], "long_name": b0["name"], "wavelength_um": LAMBDA[b]},
        )
        # Se vuelve a guardar como entero con la misma escala: sin pérdida respecto del original.
        encoding[name] = common.COMPRESSION | {
            "dtype": "int16", "scale_factor": b0["scale"], "add_offset": b0["offset"], "_FillValue": -1,
        }  # fmt: skip
    ds = xr.Dataset(
        data,
        coords={
            "time": np.array([p["time"] for p in parts]),
            "t_mid": (
                "time",
                np.array([p["t_mid"] for p in parts]),
                {"long_name": "mitad del barrido del disco"},
            ),
            "y": ("y", v["y"], {"units": "rad", "long_name": "ángulo de barrido N-S del ABI"}),
            "x": ("x", v["x"], {"units": "rad", "long_name": "ángulo de barrido E-O del ABI"}),
            "lat": (("y", "x"), v["lat"], {"units": "degrees_north"}),
            "lon": (("y", "x"), v["lon"], {"units": "degrees_east"}),
        },
        attrs={
            "source": f"s3://noaa-goes16|19/{PRODUCT} ({parts[0]['satellite']})",
            "region": f"{reg.name}: {reg.north}..{reg.south} lat, {reg.west}..{reg.east} lon",
            "note": "grilla fija del ABI; lat/lon sin corrección de paralaje; time = inicio del barrido",
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
    )
    for c in ("lat", "lon"):
        encoding[c] = common.COMPRESSION
    common.write(ds, out_file, encoding)


def main() -> None:
    """Punto de entrada: interpreta los argumentos y descarga cada hora de cada día pedido."""
    p = common.parser(__doc__, "las horas")
    p.add_argument("--bands", nargs="+", type=int, default=list(LAMBDA), choices=list(LAMBDA))
    p.add_argument(
        "--hours",
        nargs=2,
        type=int,
        default=[0, 23],
        metavar=("FROM", "TO"),
        help="horas UTC (inclusive)",
    )
    p.add_argument(
        "--processes", type=int, default=4, help="archivos leídos en paralelo (por defecto 4)"
    )
    a = p.parse_args()
    reg = common.region_of(a)
    ctx = mp.get_context("spawn")  # s3fs no tolera fork: cada proceso abre su propia conexión

    with ProcessPoolExecutor(a.processes, mp_context=ctx) as ex:
        for day in common.days(a):
            dest = common.folder(reg.name, "goes") / f"{day:%Y%m%d}"
            dest.mkdir(exist_ok=True)
            by_hour = files(day, range(a.hours[0], a.hours[1] + 1))
            pending = {
                h: r
                for h, r in by_hour.items()
                if r and (a.force or not (dest / f"goes_{day:%Y%m%d}{h:02d}.nc").exists())
            }
            if not pending:
                print(f"{day}: nada que descargar", flush=True)
                continue
            v = window(next(iter(pending.values()))[0], reg)
            print(
                f"{day}: ventana de {v['r1'] - v['r0']} × {v['c1'] - v['c0']} píxeles, {len(pending)} horas",
                flush=True,
            )
            fut = {
                h: [ex.submit(common.retry, read, r, v, a.bands) for r in rs]
                for h, rs in pending.items()
            }
            for h, fs_ in fut.items():
                t0 = time.time()
                out_file = dest / f"goes_{day:%Y%m%d}{h:02d}.nc"
                try:
                    parts = [f.result() for f in fs_]
                except (
                    Exception
                ) as e:  # se informa y se sigue; volver a correr completa lo que falte
                    print(
                        f"  {out_file.name}: falló ({e!s:.120}); vuelve a correr para completarla",
                        flush=True,
                    )
                    continue
                save(parts, v, out_file, reg)
                print(
                    f"  {out_file.name}: {len(fs_)} imágenes ({time.time() - t0:.0f} s de espera)",
                    flush=True,
                )


if __name__ == "__main__":
    main()
