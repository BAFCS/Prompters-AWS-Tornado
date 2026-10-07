#!/usr/bin/env python3
"""Descarga GOES-East ``ABI-L2-MCMIPF`` (16 bandas, disco completo, 2 km) recortado a una región.

Cada archivo del disco completo pesa ~360 MB, pero está dividido en bloques de 226 × 226 píxeles.
El script lee el índice de bloques del archivo y pide a S3, en una sola tanda concurrente, solo los
bloques que tocan la región; después los descomprime y los ensambla. El satélite se elige por fecha:
``noaa-goes16`` hasta el 4-abr-2025 a las 15 UTC y ``noaa-goes19`` desde entonces.

Los valores se guardan tal como vienen (enteros de 12 bits con ``scale_factor`` y ``add_offset``),
en la grilla fija del ABI, junto con la latitud y longitud de cada píxel. No se corrige paralaje.

Salida (un archivo por hora, hasta 6 imágenes; 4 antes del 2-abr-2019)::

    data/recortes/<region>/goes/AAAAMMDD/goes_AAAAMMDDHH.nc   (time, y, x)

Uso::

    uv run python scripts/descarga_goes.py --inicio 2019-05-30
    uv run python scripts/descarga_goes.py --inicio 2019-05-30 --bandas 8 13 --horas 18 23
"""

import argparse
import datetime as dt
import multiprocessing as mp
import re
import time
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

import comun

PRODUCTO = "ABI-L2-MCMIPF"
CAMBIO_G19 = dt.datetime(2025, 4, 4, 15)
LAMBDA = {
    1: 0.47, 2: 0.64, 3: 0.86, 4: 1.37, 5: 1.6, 6: 2.2, 7: 3.9, 8: 6.2,
    9: 6.9, 10: 7.3, 11: 8.4, 12: 9.6, 13: 10.3, 14: 11.2, 15: 12.3, 16: 13.3,
}  # fmt: skip
EPOCA_GOES = np.datetime64("2000-01-01T12:00:00")
INICIO = re.compile(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})(\d)_")


def inicio(ruta: str) -> dt.datetime:
    """Hora de inicio del barrido, leída del campo ``s`` del nombre (nunca del campo ``c``)."""
    m = INICIO.search(ruta)
    assert m, f"nombre GOES inesperado: {ruta}"
    a, j, h, mi, s, d = (int(g) for g in m.groups())
    return dt.datetime(a, 1, 1) + dt.timedelta(days=j - 1, hours=h, minutes=mi, seconds=s + d / 10)


def archivos(dia: dt.date, horas: range) -> dict[int, list[str]]:
    """Archivos del día ``dia`` agrupados por hora, eligiendo GOES-16 o GOES-19 según la fecha."""
    fs = comun.s3()
    out: dict[int, list[str]] = defaultdict(list)
    for h in horas:
        t = dt.datetime.combine(dia, dt.time(h))
        bucket = "noaa-goes19" if t >= CAMBIO_G19 else "noaa-goes16"
        carpeta = f"{bucket}/{PRODUCTO}/{t:%Y}/{t:%j}/{h:02d}/"
        try:
            rutas = fs.ls(carpeta)
        except FileNotFoundError:
            print(f"  sin datos en s3://{carpeta}", flush=True)
            continue
        out[h] = sorted(r for r in rutas if r.endswith(".nc") and inicio(r).hour == h)
    return out


def ventana(ruta: str, reg: comun.Region) -> dict:
    """Rectángulo de la grilla fija (filas y columnas) que cubre ``reg``, con sus coordenadas."""
    fs = comun.s3()
    with fs.open(ruta, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        x, y, lat, lon = comun.latlon_abi(h)
    dentro = reg.contiene(np.nan_to_num(lat, nan=99), np.nan_to_num(lon, nan=999))
    filas, cols = np.flatnonzero(dentro.any(axis=1)), np.flatnonzero(dentro.any(axis=0))
    assert filas.size, f"la región {reg.nombre} no cae dentro del disco del satélite"
    r0, r1, c0, c1 = filas[0], filas[-1] + 1, cols[0], cols[-1] + 1
    return {
        "r0": r0, "r1": r1, "c0": c0, "c1": c1,
        "x": x[c0:c1], "y": y[r0:r1], "lat": lat[r0:r1, c0:c1], "lon": lon[r0:r1, c0:c1],
    }  # fmt: skip


def bloques(d: h5py.Dataset, v: dict) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Bloques de ``d`` que tocan el recorte ``v``: posición en el lienzo y rango de bytes de cada uno.

    El lienzo es el rectángulo alineado a bloques que contiene al recorte. Se omiten los bloques no
    asignados en el archivo (fuera del disco terrestre), que quedan con el valor de relleno.
    """
    assert d.compression == "gzip" and not d.shuffle and d.chunks, (
        f"filtros inesperados en {d.name}"
    )
    bf, bc = d.chunks
    f0, c0 = v["r0"] // bf * bf, v["c0"] // bc * bc
    pos, inicios, fines = [], [], []
    for f in range(f0, min(v["r1"], d.shape[0]), bf):
        for c in range(c0, min(v["c1"], d.shape[1]), bc):
            info = d.id.get_chunk_info_by_coord((f, c))
            if info.byte_offset is None:
                continue
            pos.append((f - f0, c - c0))
            inicios.append(info.byte_offset)
            fines.append(info.byte_offset + info.size)
    return pos, inicios, fines


def recorte(
    d: h5py.Dataset, v: dict, pos: list[tuple[int, int]], crudos: list[bytes]
) -> np.ndarray:
    """Ensambla el recorte ``v`` de ``d`` a partir de los bloques comprimidos ``crudos``."""
    bf, bc = d.chunks or (0, 0)
    f0, c0 = v["r0"] // bf * bf, v["c0"] // bc * bc
    lienzo = np.full((-(-v["r1"] // bf) * bf - f0, -(-v["c1"] // bc) * bc - c0), -1, dtype=d.dtype)
    for (f, c), b in zip(pos, crudos, strict=True):
        lienzo[f : f + bf, c : c + bc] = np.frombuffer(zlib.decompress(b), d.dtype).reshape(bf, bc)
    return lienzo[v["r0"] - f0 : v["r1"] - f0, v["c0"] - c0 : v["c1"] - c0]


def lee_una_vez(ruta: str, v: dict, bandas: list[int]) -> dict:
    """Lee de un archivo ``MCMIPF`` el recorte ``v`` de cada banda, como enteros crudos.

    Los bloques de todas las bandas se piden a S3 en una sola tanda concurrente.
    """
    fs = comun.s3()
    with fs.open(ruta, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
        ds = {b: comun.dataset(h, f"CMI_C{b:02d}") for b in bandas}
        plan = {b: bloques(d, v) for b, d in ds.items()}
        rutas = [ruta for p in plan.values() for _ in p[0]]
        crudos = fs.cat_ranges(
            rutas,
            [i for p in plan.values() for i in p[1]],
            [j for p in plan.values() for j in p[2]],
            batch_size=32,  # pedidos simultáneos por archivo; más satura la conexión
        )
        assert all(isinstance(c, bytes) for c in crudos), f"lectura fallida en {ruta}"
        out = {
            "time": np.datetime64(inicio(ruta), "ms"),
            "t_medio": EPOCA_GOES + np.timedelta64(int(comun.dataset(h, "t")[()] * 1000), "ms"),
            "satelite": comun.texto(h.attrs.get("platform_ID", "?")),
            "bandas": {},
        }
        k = 0
        for b, d in ds.items():
            n = len(plan[b][0])
            out["bandas"][b] = {
                "datos": recorte(d, v, plan[b][0], crudos[k : k + n]),
                "escala": comun.num(d, "scale_factor"),
                "desfase": comun.num(d, "add_offset"),
                "unidad": comun.texto(d.attrs["units"]),
                "nombre": comun.texto(d.attrs["long_name"]),
            }
            k += n
    return out


def lee(ruta: str, v: dict, bandas: list[int]) -> dict:
    """``lee_una_vez`` con reintentos ante cortes de red."""
    return comun.reintenta(lee_una_vez, ruta, v, bandas)


def guarda(partes: list[dict], v: dict, salida: Path, reg: comun.Region) -> None:
    """Escribe en ``salida`` las imágenes ``partes`` de una hora como NetCDF comprimido."""
    partes = sorted(partes, key=lambda p: p["time"])
    datos, encoding = {}, {}
    for b, b0 in partes[0]["bandas"].items():
        crudo = np.stack([p["bandas"][b]["datos"] for p in partes])
        nombre = f"C{b:02d}"
        fisico = np.where(crudo == -1, np.nan, crudo * b0["escala"] + b0["desfase"]).astype("f4")
        datos[nombre] = (
            ("time", "y", "x"),
            fisico,
            {"units": b0["unidad"], "long_name": b0["nombre"], "longitud_onda_um": LAMBDA[b]},
        )
        # Se vuelve a guardar como entero con la misma escala: sin pérdida respecto del original.
        encoding[nombre] = comun.COMPRESION | {
            "dtype": "int16", "scale_factor": b0["escala"], "add_offset": b0["desfase"], "_FillValue": -1,
        }  # fmt: skip
    ds = xr.Dataset(
        datos,
        coords={
            "time": np.array([p["time"] for p in partes]),
            "t_medio": (
                "time",
                np.array([p["t_medio"] for p in partes]),
                {"long_name": "mitad del barrido del disco"},
            ),
            "y": ("y", v["y"], {"units": "rad", "long_name": "ángulo de barrido N-S del ABI"}),
            "x": ("x", v["x"], {"units": "rad", "long_name": "ángulo de barrido E-O del ABI"}),
            "lat": (("y", "x"), v["lat"], {"units": "degrees_north"}),
            "lon": (("y", "x"), v["lon"], {"units": "degrees_east"}),
        },
        attrs={
            "fuente": f"s3://noaa-goes16|19/{PRODUCTO} ({partes[0]['satelite']})",
            "region": f"{reg.nombre}: {reg.norte}..{reg.sur} lat, {reg.oeste}..{reg.este} lon",
            "nota": "grilla fija del ABI; lat/lon sin corrección de paralaje; time = inicio del barrido",
            "creado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
    )
    for c in ("lat", "lon"):
        encoding[c] = comun.COMPRESION
    comun.escribe(ds, salida, encoding)


def main() -> None:
    """Punto de entrada: interpreta los argumentos y descarga cada hora de cada día pedido."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    comun.args_fechas(p)
    comun.args_region(p)
    p.add_argument("--bandas", nargs="+", type=int, default=list(LAMBDA), choices=list(LAMBDA))
    p.add_argument(
        "--horas",
        nargs=2,
        type=int,
        default=[0, 23],
        metavar=("DESDE", "HASTA"),
        help="horas UTC (inclusive)",
    )
    p.add_argument(
        "--procesos", type=int, default=4, help="archivos leídos en paralelo (por defecto 4)"
    )
    p.add_argument("--forzar", action="store_true", help="rehace las horas que ya existen")
    a = p.parse_args()
    reg = comun.region_de(a)
    ctx = mp.get_context("spawn")  # s3fs no tolera fork: cada proceso abre su propia conexión

    with ProcessPoolExecutor(a.procesos, mp_context=ctx) as ex:
        for dia in comun.dias(a):
            dest = comun.carpeta(reg.nombre, "goes") / f"{dia:%Y%m%d}"
            dest.mkdir(exist_ok=True)
            porhora = archivos(dia, range(a.horas[0], a.horas[1] + 1))
            pendientes = {
                h: r
                for h, r in porhora.items()
                if r and (a.forzar or not (dest / f"goes_{dia:%Y%m%d}{h:02d}.nc").exists())
            }
            if not pendientes:
                print(f"{dia}: nada que descargar", flush=True)
                continue
            v = ventana(next(iter(pendientes.values()))[0], reg)
            print(
                f"{dia}: ventana de {v['r1'] - v['r0']} × {v['c1'] - v['c0']} píxeles, {len(pendientes)} horas",
                flush=True,
            )
            fut = {h: [ex.submit(lee, r, v, a.bandas) for r in rs] for h, rs in pendientes.items()}
            for h, fs_ in fut.items():
                t0 = time.time()
                salida = dest / f"goes_{dia:%Y%m%d}{h:02d}.nc"
                try:
                    partes = [f.result() for f in fs_]
                except (
                    Exception
                ) as e:  # se informa y se sigue; volver a correr completa lo que falte
                    print(
                        f"  {salida.name}: falló ({e!s:.120}); vuelve a correr para completarla",
                        flush=True,
                    )
                    continue
                guarda(partes, v, salida, reg)
                print(
                    f"  {salida.name}: {len(fs_)} imágenes ({time.time() - t0:.0f} s de espera)",
                    flush=True,
                )


if __name__ == "__main__":
    main()
