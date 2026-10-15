#!/usr/bin/env python3
"""Genera vistas curadas de granularidad variable desde un store Zarr base de ERA5 en S3.

Desafío 2 del experimento de optimización de ingesta: a partir de un único store Zarr de ERA5 con
dimensiones ``(time, level, latitude, longitude)``, deriva **vistas no excluyentes** que distintos
consumidores (entrenamiento, exploración rápida, inspección por variable) pueden elegir según el
compromiso entre resolución y volumen. Todas las vistas son derivadas del mismo store base, así que
coexisten sin reemplazarse: cada una vive en su propio prefijo bajo ``curated/``.

Vistas generadas (todas escritas como stores Zarr en el bucket de destino):

- **Submuestreo temporal** (``curated/every_3h/``, ``curated/every_6h/``): toma uno de cada 3 y uno
  de cada 6 pasos de tiempo (``isel(time=slice(None, None, 3))`` y ``slice(..., 6)``). Conserva los
  valores instantáneos originales, solo que más espaciados.
- **Promedios temporales** (``curated/mean_3h/``, ``curated/mean_6h/``): remuestrea el tiempo a
  bloques de 3 h y 6 h y promedia (``resample(time=...).mean()``). Suaviza el ruido horario a costa
  de la resolución temporal.
- **Una variable por separado** (``curated/by_var/<var>/``): un store por cada variable del dataset,
  para quien solo necesita, por ejemplo, el geopotencial sin arrastrar el resto.
- **Recorte espacial estrecho** (``curated/chile_only/``): acota la grilla a Chile continental más
  estrecho (por defecto lat −45..−30, lon −75..−69), reduciendo el volumen cuando no interesa la
  zona austral ni el océano.

Además escribe un ``curated/catalog.json`` que describe cada vista: ruta en S3, granularidad
temporal, variables, caja geográfica (bbox) y número de pasos de tiempo. El catálogo permite elegir
una vista sin tener que abrir cada store para inspeccionar sus dimensiones.

Contexto operativo: cuenta AWS en us-east-1 (us-west-2 está denegado por IAM), instancia de
laboratorio sin GPU. El acceso al bucket de destino es **autenticado** (no anónimo), con las
credenciales del rol de la instancia. El store base de ERA5 lo produce el Desafío 1.

Uso::

    uv run python scripts/ingest/curate_granularity.py                      # todas las vistas
    uv run python scripts/ingest/curate_granularity.py --views every_3h chile_only
    uv run python scripts/ingest/curate_granularity.py --dry-run            # solo planifica
    uv run python scripts/ingest/curate_granularity.py --force              # rehace vistas

Este script **no se ejecuta** como parte de la entrega: solo prepara el artefacto. Lanzarlo contra
S3 escribe en el bucket de destino.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass

import s3fs
import xarray as xr

# --- Configuración por defecto del experimento -------------------------------------------------

BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
BASE_STORE = f"s3://{BUCKET}/era5_store/"  # store Zarr base (salida del Desafío 1)
CURATED_PREFIX = f"s3://{BUCKET}/curated/"  # raíz de las vistas derivadas
CATALOG_KEY = f"{CURATED_PREFIX}catalog.json"
REGION = "us-east-1"  # única región permitida por IAM

# Recorte espacial estrecho de Chile continental (grados; latitudes y longitudes negativas).
CHILE_LAT = (-45.0, -30.0)  # (sur, norte)
CHILE_LON = (-75.0, -69.0)  # (oeste, este)

# Submuestreos y promedios temporales ofrecidos. El paso en horas supone un store base horario.
SUBSAMPLE_STEPS = {"every_3h": 3, "every_6h": 6}  # isel(time::N)
RESAMPLE_FREQS = {"mean_3h": "3h", "mean_6h": "6h"}  # resample(time=...).mean()

ALL_VIEWS = (
    *SUBSAMPLE_STEPS,
    *RESAMPLE_FREQS,
    "by_var",
    "chile_only",
)


@dataclass(frozen=True)
class ViewEntry:
    """Descripción de una vista curada para el catálogo.

    ``path`` es el prefijo del store en S3; ``granularity`` resume la granularidad temporal
    (p. ej. ``"3h (submuestreo)"``); ``variables`` son las variables presentes; ``bbox`` es la caja
    geográfica como ``(norte, sur, oeste, este)`` en grados; ``time_steps`` es el número de pasos de
    tiempo del store resultante.
    """

    name: str
    path: str
    granularity: str
    variables: list[str]
    bbox: tuple[float, float, float, float]
    time_steps: int


def _bbox_of(ds: xr.Dataset) -> tuple[float, float, float, float]:
    """Caja geográfica ``(norte, sur, oeste, este)`` en grados de un dataset con lat/lon."""
    lat = ds["latitude"]
    lon = ds["longitude"]
    return (
        float(lat.max()),
        float(lat.min()),
        float(lon.min()),
        float(lon.max()),
    )


def _store_exists(fs: s3fs.S3FileSystem, path: str) -> bool:
    """Indica si ya existe un store Zarr en ``path`` (busca su metadato raíz)."""
    root = path.rstrip("/")
    return fs.exists(f"{root}/zarr.json") or fs.exists(f"{root}/.zgroup")


def _write_store(ds: xr.Dataset, path: str, fs: s3fs.S3FileSystem, *, dry_run: bool) -> None:
    """Escribe ``ds`` como store Zarr en ``path`` (sobre S3), o solo lo anuncia si ``dry_run``.

    El dataset se recalcula de forma perezosa al escribir, así que no se materializa en memoria más
    de lo que necesita cada bloque de Zarr.
    """
    if dry_run:
        print(f"  [dry-run] escribiría {path} ({ds.sizes.get('time', 0)} pasos)", flush=True)
        return
    store = s3fs.S3Map(root=path, s3=fs, check=False)
    ds.to_zarr(store, mode="w", consolidated=True)


def subsample_view(base: xr.Dataset, step: int) -> xr.Dataset:
    """Vista de submuestreo temporal: uno de cada ``step`` pasos de tiempo (``isel(time::step)``)."""
    return base.isel(time=slice(None, None, step))


def mean_view(base: xr.Dataset, freq: str) -> xr.Dataset:
    """Vista de promedio temporal: remuestrea el tiempo a ``freq`` y promedia cada bloque."""
    return base.resample(time=freq).mean()


def chile_view(
    base: xr.Dataset,
    lat: tuple[float, float] = CHILE_LAT,
    lon: tuple[float, float] = CHILE_LON,
) -> xr.Dataset:
    """Vista recortada a Chile continental estrecho: lat en ``lat`` y lon en ``lon`` (grados).

    Ordena la selección según el sentido del eje de latitud de ERA5 (habitualmente decreciente, de
    norte a sur), para que ``sel(slice(...))`` no devuelva un rango vacío.
    """
    south, north = min(lat), max(lat)
    west, east = min(lon), max(lon)
    lat_desc = bool(base["latitude"][0] > base["latitude"][-1])
    lat_slice = slice(north, south) if lat_desc else slice(south, north)
    return base.sel(latitude=lat_slice, longitude=slice(west, east))


def _entry_for(name: str, path: str, ds: xr.Dataset, granularity: str) -> ViewEntry:
    """Arma la ficha de catálogo de la vista ``name`` ya calculada ``ds``."""
    return ViewEntry(
        name=name,
        path=path,
        granularity=granularity,
        variables=sorted(str(v) for v in ds.data_vars),
        bbox=_bbox_of(ds),
        time_steps=int(ds.sizes.get("time", 0)),
    )


def build_views(
    base: xr.Dataset,
    fs: s3fs.S3FileSystem,
    selected: list[str],
    *,
    dry_run: bool,
    force: bool,
) -> list[ViewEntry]:
    """Genera las vistas ``selected`` desde ``base`` y devuelve sus fichas de catálogo.

    Cada vista es no excluyente: se escribe en su propio prefijo bajo ``curated/`` sin tocar el store
    base ni las demás vistas. Si una vista ya existe y no se pasó ``force``, se salta la escritura
    pero igual se cataloga leyendo el store existente.
    """
    entries: list[ViewEntry] = []

    for name in selected:
        if name in SUBSAMPLE_STEPS:
            step = SUBSAMPLE_STEPS[name]
            path = f"{CURATED_PREFIX}{name}/"
            view = subsample_view(base, step)
            granularity = f"{step}h (submuestreo isel(time::{step}))"
            _maybe_write(view, path, fs, dry_run=dry_run, force=force)
            entries.append(_entry_for(name, path, view, granularity))

        elif name in RESAMPLE_FREQS:
            freq = RESAMPLE_FREQS[name]
            path = f"{CURATED_PREFIX}{name}/"
            view = mean_view(base, freq)
            granularity = f"{freq} (promedio resample(time).mean())"
            _maybe_write(view, path, fs, dry_run=dry_run, force=force)
            entries.append(_entry_for(name, path, view, granularity))

        elif name == "by_var":
            for var in sorted(str(v) for v in base.data_vars):
                path = f"{CURATED_PREFIX}by_var/{var}/"
                view = base[[var]]
                granularity = "horaria (sin cambio temporal)"
                _maybe_write(view, path, fs, dry_run=dry_run, force=force)
                entries.append(_entry_for(f"by_var/{var}", path, view, granularity))

        elif name == "chile_only":
            path = f"{CURATED_PREFIX}chile_only/"
            view = chile_view(base)
            granularity = "horaria (sin cambio temporal)"
            _maybe_write(view, path, fs, dry_run=dry_run, force=force)
            entries.append(_entry_for(name, path, view, granularity))

        else:
            raise SystemExit(f"vista desconocida {name!r}; elige de {list(ALL_VIEWS)}")

    return entries


def _maybe_write(
    ds: xr.Dataset,
    path: str,
    fs: s3fs.S3FileSystem,
    *,
    dry_run: bool,
    force: bool,
) -> None:
    """Escribe ``ds`` en ``path`` salvo que ya exista y no se haya pedido ``force``."""
    if not force and not dry_run and _store_exists(fs, path):
        print(f"  {path}: ya existe (usa --force para rehacer)", flush=True)
        return
    _write_store(ds, path, fs, dry_run=dry_run)


def write_catalog(
    entries: list[ViewEntry],
    fs: s3fs.S3FileSystem,
    *,
    dry_run: bool,
) -> dict[str, object]:
    """Escribe ``curated/catalog.json`` describiendo cada vista y devuelve el documento serializado.

    El catálogo incluye el store base, la marca de tiempo de generación y una entrada por vista con
    ruta, granularidad temporal, variables, bbox y número de pasos de tiempo.
    """
    catalog: dict[str, object] = {
        "base_store": BASE_STORE,
        "bucket": BUCKET,
        "region": REGION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "views": [
            {
                "name": e.name,
                "path": e.path,
                "temporal_granularity": e.granularity,
                "variables": e.variables,
                "bbox": {
                    "north": e.bbox[0],
                    "south": e.bbox[1],
                    "west": e.bbox[2],
                    "east": e.bbox[3],
                },
                "time_steps": e.time_steps,
            }
            for e in entries
        ],
    }
    body = json.dumps(catalog, indent=2, ensure_ascii=False)
    if dry_run:
        print(f"  [dry-run] escribiría {CATALOG_KEY}:\n{body}", flush=True)
    else:
        with fs.open(CATALOG_KEY, "w") as f:
            f.write(body)
        print(f"  catálogo escrito en {CATALOG_KEY}", flush=True)
    return catalog


def open_base(fs: s3fs.S3FileSystem, store: str = BASE_STORE) -> xr.Dataset:
    """Abre el store Zarr base de ERA5 desde S3 de forma perezosa (sin materializar los datos)."""
    mapper = s3fs.S3Map(root=store, s3=fs, check=False)
    return xr.open_zarr(mapper, consolidated=True)


def parse_args() -> argparse.Namespace:
    """Parser de la CLI: selección de vistas, modo de prueba y rehacer vistas existentes."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--views",
        nargs="+",
        default=list(ALL_VIEWS),
        metavar="VISTA",
        help=f"vistas a generar (por defecto todas): {', '.join(ALL_VIEWS)}",
    )
    p.add_argument(
        "--base-store",
        default=BASE_STORE,
        help=f"store Zarr base de ERA5 en S3 (por defecto {BASE_STORE})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="planifica y muestra las vistas y el catálogo sin escribir nada en S3",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="rehace las vistas que ya existan en curated/",
    )
    return p.parse_args()


def main() -> None:
    """Punto de entrada: abre el store base, genera las vistas pedidas y escribe el catálogo."""
    a = parse_args()
    fs = s3fs.S3FileSystem(anon=False, client_kwargs={"region_name": REGION})

    print(f"abriendo store base {a.base_store}", flush=True)
    base = open_base(fs, a.base_store)
    print(
        f"base: {dict(base.sizes)} con variables {sorted(str(v) for v in base.data_vars)}",
        flush=True,
    )

    entries = build_views(base, fs, a.views, dry_run=a.dry_run, force=a.force)
    write_catalog(entries, fs, dry_run=a.dry_run)
    print(f"listo: {len(entries)} vistas catalogadas", flush=True)


if __name__ == "__main__":
    main()
