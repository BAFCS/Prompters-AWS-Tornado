"""Escritores de NetCDF sintéticos (índices ERA5 y GOES en lat/lon) para las pruebas de las CLI.

Reproducen el formato de ``process_era5.py`` y ``process_goes.py`` (dimensiones ``time``,
``latitude``, ``longitude``; GOES como ``int16`` con ``scale_factor``/``add_offset`` y
``_FillValue = -1``) en un directorio temporal, sin leer ``data/``.
"""

import datetime as dt
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

GOES_SCALE = 0.1
GOES_OFFSET = 100.0
TABLE_DAY = dt.date(2020, 1, 5)


def goes_grid() -> tuple[np.ndarray, np.ndarray]:
    """Grilla GOES de 0,02° que cubre los puntos ERA5 de ``era5_grid`` con margen."""
    lat = np.round(np.arange(-34.8, -35.46, -0.02), 6)
    lon = np.round(np.arange(-72.2, -71.54, 0.02), 6)
    return lat, lon


def era5_grid() -> tuple[np.ndarray, np.ndarray]:
    """Grilla ERA5 de 2 × 2 puntos (0,25°)."""
    return np.array([-35.0, -35.25]), np.array([-72.0, -71.75])


def write_era5_indices(
    crops_root: Path,
    region: str,
    day: dt.date,
    hours: Sequence[int],
    values: dict[str, np.ndarray] | None = None,
) -> Path:
    """Escribe ``era5_indices/era5_idx_AAAAMMDD.nc`` con las ``hours`` del día y ``values``.

    Sin ``values`` escribe una sola variable ``cape`` en cero.
    """
    lat, lon = era5_grid()
    times = np.array([np.datetime64(dt.datetime.combine(day, dt.time(h)), "ns") for h in hours])
    shape = (len(times), len(lat), len(lon))
    data = values or {"cape": np.zeros(shape)}
    ds = xr.Dataset(
        {k: (("time", "latitude", "longitude"), v.astype("f4")) for k, v in data.items()},
        coords={"time": times, "latitude": lat, "longitude": lon},
    )
    out = crops_root / region / "era5_indices" / f"era5_idx_{day:%Y%m%d}.nc"
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out, engine="h5netcdf")
    return out


def write_goes_latlon(
    crops_root: Path,
    region: str,
    hour: dt.datetime,
    scans: Sequence[dt.datetime],
    bands: dict[str, np.ndarray],
) -> Path:
    """Escribe ``goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc`` con BT en kelvin (NaN → relleno).

    Cada banda de ``bands`` tiene forma ``(len(scans), lat, lon)`` sobre ``goes_grid``.
    """
    lat, lon = goes_grid()
    times = np.array([np.datetime64(s, "ns") for s in scans])
    ds = xr.Dataset(
        {b: (("time", "latitude", "longitude"), v.astype("f4")) for b, v in bands.items()},
        coords={"time": times, "latitude": lat, "longitude": lon},
    )
    enc = {
        b: {
            "dtype": "int16",
            "scale_factor": GOES_SCALE,
            "add_offset": GOES_OFFSET,
            "_FillValue": -1,
        }
        for b in bands
    }
    out = crops_root / region / "goes_latlon" / f"{hour:%Y%m%d}" / f"goes_{hour:%Y%m%d%H}.nc"
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out, engine="h5netcdf", encoding=enc)
    return out


def model_tables(n_emb: int = 10, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Tablas de las tres configuraciones (``table.build``) para un día con tres Eventos.

    Cuatro horas de ``TABLE_DAY`` sobre 3 × 3 puntos (36 Celdas_Hora), ERA5 y GOES aleatorios con
    señal en las positivas y ``n_emb`` columnas ``emb_*``. Requiere ``scripts/model`` en
    ``sys.path``.
    """
    import table

    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(TABLE_DAY, tz="UTC")
    times = [t0 + pd.Timedelta(hours=h) for h in range(4)]
    lat, lon = np.array([-35.0, -35.25, -35.5]), np.array([-72.0, -71.75, -71.5])
    cells = table.candidate_cells(times, lat, lon)
    cells["label"] = np.int8(0)
    cells.loc[[3, 17, 30], "label"] = np.int8(1)
    cells["event_id"] = [
        f"{TABLE_DAY:%Y%m%d}-{i}" if lab else "" for i, lab in enumerate(cells["label"])
    ]
    cells["fold_group"] = table.assign_fold_groups(cells, seed)
    grid = pd.MultiIndex.from_product([times, lat, lon], names=table.POINT).to_frame(index=False)
    era5 = grid.copy()
    for c in table.ERA5_FEATURES:
        era5[c] = rng.normal(size=len(grid))
    goes = grid.copy()
    goes["scan_start"] = goes["time"] - pd.Timedelta(minutes=10)
    for c in table.GOES_FEATURES:
        goes[c] = rng.normal(size=len(grid))
    emb = pd.DataFrame(rng.normal(size=(len(cells), n_emb)), columns=table.emb_columns(n_emb))
    emb.insert(0, "cell_id", cells["cell_id"].tolist())
    return {c: table.build(c, cells, era5, goes, emb) for c in table.CONFIGS}


def write_channels(root: Path, df: pd.DataFrame, folds_from: pd.DataFrame) -> Path:
    """Canales de SageMaker bajo ``root/input``: ``train`` (Parquet) y ``folds`` (``folds.json``).

    Las particiones se calculan con ``loeo.compute_folds(folds_from)``. Requiere ``scripts/model``
    en ``sys.path``.
    """
    import json

    import loeo

    inp = root / "input"
    part = inp / "train" / f"date={TABLE_DAY:%Y-%m-%d}" / "part-0.parquet"
    part.parent.mkdir(parents=True)
    df.to_parquet(part, index=False)
    (inp / "folds").mkdir(parents=True)
    doc = loeo.folds_to_json(loeo.compute_folds(folds_from), 0)
    (inp / "folds" / "folds.json").write_text(json.dumps(doc), encoding="utf-8")
    return inp


def uniform_scans(
    hour: dt.datetime, bt_of: dict[str, Callable[[dt.datetime], float]], step_min: int = 10
) -> tuple[list[dt.datetime], dict[str, np.ndarray]]:
    """Seis barridos de ``hour`` (cada ``step_min`` minutos) con BT uniforme por barrido.

    ``bt_of`` asocia cada banda a una función ``(barrido) -> float`` con la BT de todo el campo.
    """
    lat, lon = goes_grid()
    scans = [hour + dt.timedelta(minutes=step_min * k) for k in range(6)]
    bands = {
        b: np.stack([np.full((len(lat), len(lon)), fn(s)) for s in scans])
        for b, fn in bt_of.items()
    }
    return scans, bands
