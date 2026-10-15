#!/usr/bin/env python3
"""Constructor_Tabla: elige las Celdas_Hora y arma las tablas (X, y, fold_group) por configuracion.

Etapas (``--stage``):

- ``select``: etiqueta como positivas las Celdas_Hora de los Eventos del Catalogo (``--catalog``)
  en los dias ``--start``-``--end`` y muestrea ``--ratio`` no etiquetadas por positiva con
  ``--seed``. Escribe ``cells.parquet`` con ``fold_group`` e informa los Eventos omitidos y los
  perdidos por colision.
- ``build``: une ERA5, Variables_GOES y (en ``embeddings``) los embeddings de ``--embeddings`` para
  las Celdas_Hora de ``cells.parquet``, con rezagos t-1/-2/-3 h, y escribe una tabla por dia.
- ``infer``: lo mismo para todas las Celdas_Hora de los dias pedidos, sin etiquetas.

Los rezagos de las primeras horas usan el dia anterior si sus indices existen; si no, quedan NaN.

Entradas y salidas::

    data/crops/<region>/era5_indices/era5_idx_AAAAMMDD.nc
    data/model/<region>/goes_features/goes_feat_AAAAMMDD.parquet
    data/model/<region>/cells.parquet                                            (select)
    data/model/<region>/tables/config=<config>/date=AAAA-MM-DD/part-0.parquet     (build)
    data/model/<region>/inference/config=<config>/date=AAAA-MM-DD/part-0.parquet  (infer)

Uso::

    uv run python scripts/model/build_table.py --stage select --start 2019-05-30 --end 2019-05-31
    uv run python scripts/model/build_table.py --stage build --config physical --start 2019-05-30 --end 2019-05-31
    uv run python scripts/model/build_table.py --stage infer --config physical --start 2019-06-01 --force
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
from pathlib import Path
from typing import BinaryIO, cast

import fsspec
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import table as tb  # noqa: E402

import common  # noqa: E402

MODEL_DATA = common.DATA / "model"
DEFAULT_CATALOG = common.DATA / "tornados_chile.xlsx"
STAGES = ("select", "build", "infer")


def read_catalog(path: str) -> pd.DataFrame:
    """Lee la hoja ``Final_Table`` (ruta local o ``s3://``) y la normaliza con ``table``."""
    with fsspec.open(path, "rb") as f:  # type: ignore[union-attr]
        raw = cast(BinaryIO, f).read()
    return tb.normalize_catalog(pd.read_excel(io.BytesIO(raw), sheet_name="Final_Table"))


def previous_day(days: list[dt.date]) -> list[dt.date]:
    """El día anterior al primero de ``days`` (sus horas solo sirven para los rezagos)."""
    return [days[0] - dt.timedelta(days=1)] if days else []


def read_era5(
    crops_root: Path, region: str, days: list[dt.date], optional: list[dt.date] | None = None
) -> pd.DataFrame:
    """Índices ERA5 en formato largo (``time``, ``latitude``, ``longitude``, variables).

    Lee ``optional`` (si existen, sin aviso) y ``days`` (con aviso si faltan).
    """
    parts: list[pd.DataFrame] = []
    extra = optional or []
    for day in [*extra, *days]:
        path = crops_root / region / "era5_indices" / f"era5_idx_{day:%Y%m%d}.nc"
        if not path.exists():
            if day not in extra:
                print(f"  aviso: {day}: sin índices ERA5 en {path}", flush=True)
            continue
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            present = [v for v in tb.ERA5_FEATURES if v in ds.data_vars]
            missing = [v for v in tb.ERA5_FEATURES if v not in ds.data_vars]
            if missing:
                print(f"  aviso: {path.name} no trae {missing}; quedan en NaN", flush=True)
            df = ds[present].to_dataframe(dim_order=list(tb.POINT)).reset_index()
        parts.append(df)
    if not parts:
        return pd.DataFrame(columns=list(tb.POINT))
    era5 = pd.concat(parts, ignore_index=True)
    era5["time"] = tb.utc(era5["time"])
    return era5


def read_goes(
    model_root: Path, region: str, days: list[dt.date], optional: list[dt.date] | None = None
) -> pd.DataFrame | None:
    """Variables_GOES (``goes_feat_AAAAMMDD.parquet``); ``None`` si no hay ninguna.

    Lee ``optional`` (si existen, sin aviso) y ``days`` (con aviso si faltan).
    """
    parts: list[pd.DataFrame] = []
    extra = optional or []
    for day in [*extra, *days]:
        path = model_root / region / "goes_features" / f"goes_feat_{day:%Y%m%d}.parquet"
        if path.exists():
            parts.append(pd.read_parquet(path))
        elif day not in extra:
            print(f"  aviso: {day}: sin Variables_GOES en {path}; quedan en NaN", flush=True)
    return pd.concat(parts, ignore_index=True) if parts else None


def report(skipped: pd.DataFrame) -> None:
    """Imprime los Eventos omitidos y, aparte, los perdidos por colisión (Req. 6.11, 6.12)."""
    coll = skipped["reason"].str.startswith(tb.COLLISION)
    other = skipped[~coll]
    print(f"Eventos omitidos: {len(other)}", flush=True)
    for eid, reason in zip(other["event_id"], other["reason"], strict=True):
        print(f"  {eid}: {reason}", flush=True)
    print(f"Eventos perdidos por colisión: {int(coll.sum())}", flush=True)
    for eid, reason in zip(skipped.loc[coll, "event_id"], skipped.loc[coll, "reason"], strict=True):
        print(f"  {eid}: {reason}", flush=True)


def write_parquet(df: pd.DataFrame, out_file: Path) -> None:
    """Escribe ``df`` en ``out_file`` pasando por un ``.tmp``."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_file)


def write_by_day(df: pd.DataFrame, out_dir: Path, force: bool) -> list[Path]:
    """Escribe ``date=AAAA-MM-DD/part-0.parquet`` por día; salta los existentes salvo ``force``."""
    written: list[Path] = []
    for day in sorted(set(df["date"])):
        out_file = out_dir / f"date={day:%Y-%m-%d}" / "part-0.parquet"
        if out_file.exists() and not force:
            print(f"{out_file.parent.name}: ya existe", flush=True)
            continue
        part = df[df["date"] == day].reset_index(drop=True)
        write_parquet(part, out_file)
        print(f"{out_dir.name}/{out_file.parent.name}: {len(part)} filas", flush=True)
        written.append(out_file)
    return written


def _select(a: argparse.Namespace, region: common.Region, crops_root: Path, out: Path) -> int:
    """Etapa ``select``: escribe ``cells.parquet``."""
    if out.exists() and not a.force:
        print(f"{out}: ya existe", flush=True)
        return 0
    days = common.days(a)
    era5 = read_era5(crops_root, region.name, days)
    if era5.empty:
        raise SystemExit("error: no hay índices ERA5 en el rango pedido")
    catalog = read_catalog(str(a.catalog))
    in_range = catalog["date"].isin(days) | catalog["date"].isna()
    times = sorted(set(era5["time"]))
    lat = era5["latitude"].drop_duplicates().to_numpy()
    lon = era5["longitude"].drop_duplicates().to_numpy()
    cells, skipped = tb.select_cells(catalog[in_range], times, lat, lon, region, a.ratio, a.seed)
    write_parquet(cells, out)
    n_pos = int((cells["label"] == 1).sum())
    print(f"{out.name}: {n_pos} positivas, {len(cells) - n_pos} no etiquetadas", flush=True)
    report(skipped)
    return 0


def _inputs(
    a: argparse.Namespace, region: str, crops_root: Path, model_root: Path, days: list[dt.date]
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    """ERA5 (con el día anterior), Variables_GOES y embeddings que necesita ``--config``."""
    prev = previous_day(days)
    era5 = read_era5(crops_root, region, days, prev)
    goes = None
    if a.config != "baseline_era5":
        goes = read_goes(model_root, region, days, prev)
    emb = None
    if a.config == "embeddings":
        if a.embeddings is None:
            raise SystemExit("error: --config embeddings requiere --embeddings")
        emb = pd.read_parquet(a.embeddings)
    return era5, goes, emb


def run(a: argparse.Namespace, crops_root: Path, model_root: Path) -> int:
    """Ejecuta la etapa ``a.stage`` leyendo de ``crops_root`` y escribiendo en ``model_root``."""
    reg = common.region_of(a)
    base = model_root / reg.name
    cells_file = a.cells or base / "cells.parquet"
    if a.stage == "select":
        return _select(a, reg, crops_root, cells_file)
    days = common.days(a)
    era5, goes, emb = _inputs(a, reg.name, crops_root, model_root, days)
    if era5.empty:
        raise SystemExit("error: no hay índices ERA5 en el rango pedido")
    if a.stage == "build":
        if not cells_file.exists():
            raise SystemExit(f"error: falta {cells_file}; corre antes --stage select")
        cells = pd.read_parquet(cells_file)
        cells["time"] = tb.utc(cells["time"])
        cells = cells[cells["time"].dt.date.isin(days)].reset_index(drop=True)
        out_dir = base / "tables" / f"config={a.config}"
    else:
        in_days = era5[era5["time"].dt.date.isin(days)]
        cells = tb.candidate_cells(
            sorted(set(in_days["time"])),
            in_days["latitude"].drop_duplicates().to_numpy(),
            in_days["longitude"].drop_duplicates().to_numpy(),
        )
        out_dir = base / "inference" / f"config={a.config}"
    df = tb.build(a.config, cells, era5, goes, emb)
    write_by_day(df, out_dir, a.force)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Parser de la CLI (opciones de ``common`` más las del Constructor_Tabla)."""
    p = common.parser(__doc__, "las tablas")
    p.add_argument("--stage", choices=STAGES, required=True, help="etapa a ejecutar")
    p.add_argument(
        "--config",
        choices=tb.CONFIGS,
        default="physical",
        help="Configuración_Experimento de build/infer (por defecto physical)",
    )
    p.add_argument(
        "--ratio",
        type=int,
        default=200,
        help=f"no etiquetadas por positiva, {tb.MIN_RATIO}-{tb.MAX_RATIO} (por defecto 200)",
    )
    p.add_argument("--seed", type=int, default=0, help="semilla del muestreo (por defecto 0)")
    p.add_argument(
        "--catalog",
        default=str(DEFAULT_CATALOG),
        help="tornados_chile.xlsx (ruta o s3://; por defecto data/tornados_chile.xlsx)",
    )
    p.add_argument("--cells", type=Path, help="cells.parquet (por defecto data/model/<region>/)")
    p.add_argument(
        "--embeddings", type=Path, help="parquet de encode_bedrock.py (config embeddings)"
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada de la CLI."""
    a = build_parser().parse_args(argv)
    if not tb.MIN_RATIO <= a.ratio <= tb.MAX_RATIO:
        raise SystemExit(f"error: --ratio {a.ratio} fuera de {tb.MIN_RATIO}-{tb.MAX_RATIO}")
    sys.exit(run(a, common.CROPS, MODEL_DATA))


if __name__ == "__main__":
    main()
