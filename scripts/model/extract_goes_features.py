#!/usr/bin/env python3
"""Calcula las Variables_GOES de cada Celda_Hora ERA5 a partir de los recortes GOES en lat/lon.

Para cada hora ``t`` de los índices ERA5 del día y cada punto de su grilla, toma la Ventana_GOES
(cuadrado de lado ``--window-deg`` centrado en el punto) del barrido más reciente con inicio en
(t - 60 min, t] y calcula BT mínima de C13, fracción bajo -60 °C, máx. C08 - C13 y la tasa de
enfriamiento contra un barrido anterior separado 15–30 min. Lee solo los archivos de la hora ``t``
y de ``t - 1``: nunca usa barridos posteriores a ``t``. Los NetCDF se abren con
``mask_and_scale=False`` y se decodifican con ``goes_features.decode`` usando los atributos de
``C08`` y ``C13``.

Entrada y salida::

    data/crops/<region>/era5_indices/era5_idx_AAAAMMDD.nc            (puntos y horas)
    data/crops/<region>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc       (C08, C13)
    data/model/<region>/goes_features/goes_feat_AAAAMMDD.parquet

Uso::

    uv run python scripts/model/extract_goes_features.py --start 2019-05-30
    uv run python scripts/model/extract_goes_features.py --start 2019-05-30 --end 2019-05-31 --force
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import goes_features as gf  # noqa: E402

import common  # noqa: E402

BANDS = ("C08", "C13")
COLUMNS = [
    "time",
    "latitude",
    "longitude",
    "scan_start",
    *gf.GOES_FEATURES,
    "valid_frac_c13",
]
MODEL_DATA = common.DATA / "model"


@dataclass
class GoesFile:
    """Un NetCDF de ``goes_latlon`` con sus bandas como enteros crudos y su codificación."""

    path: Path
    times: list[dt.datetime]  # inicio de cada barrido (UTC, sin zona)
    lat: np.ndarray
    lon: np.ndarray
    raw: dict[str, np.ndarray]  # banda → enteros (time, latitude, longitude)
    coding: dict[str, tuple[float, float, int]]  # banda → (scale_factor, add_offset, _FillValue)
    missing: list[str]  # bandas pedidas que el archivo no trae

    def band(self, name: str, k: int) -> np.ndarray:
        """BT en kelvin de la banda ``name`` en el barrido ``k`` (NaN donde hay relleno)."""
        scale, offset, fill = self.coding[name]
        return gf.decode(self.raw[name][k], scale, offset, fill)

    def window(self, name: str, k: int, lat_sl: slice, lon_sl: slice) -> np.ndarray:
        """Como ``band``, pero decodifica solo la ventana ``[lat_sl, lon_sl]``."""
        scale, offset, fill = self.coding[name]
        return gf.decode(self.raw[name][k][lat_sl, lon_sl], scale, offset, fill)


def goes_path(crops_root: Path, region: str, hour: dt.datetime) -> Path:
    """Ruta ``goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc`` de la hora ``hour``."""
    return crops_root / region / "goes_latlon" / f"{hour:%Y%m%d}" / f"goes_{hour:%Y%m%d%H}.nc"


def _attr(attrs: dict, name: str, default: float) -> float:
    """Atributo numérico ``name`` (escalar o arreglo de 1) como ``float``."""
    return float(np.asarray(attrs.get(name, default)).ravel()[0])


def load_goes_file(path: Path, bands: Sequence[str]) -> GoesFile:
    """Lee ``path`` sin decodificar (``mask_and_scale=False``) y guarda las ``bands`` presentes."""
    with xr.open_dataset(path, engine="h5netcdf", mask_and_scale=False) as ds:
        times = [ts.to_pydatetime() for ts in pd.to_datetime(ds["time"].values)]
        raw: dict[str, np.ndarray] = {}
        coding: dict[str, tuple[float, float, int]] = {}
        missing = [b for b in bands if b not in ds.data_vars]
        for b in bands:
            if b in missing:
                continue
            da = ds[b]
            raw[b] = np.asarray(da.transpose("time", "latitude", "longitude").values)
            coding[b] = (
                _attr(da.attrs, "scale_factor", 1.0),
                _attr(da.attrs, "add_offset", 0.0),
                int(_attr(da.attrs, "_FillValue", gf.FILL_VALUE)),
            )
        return GoesFile(
            path,
            times,
            np.asarray(ds["latitude"].values, dtype=np.float64),
            np.asarray(ds["longitude"].values, dtype=np.float64),
            raw,
            coding,
            missing,
        )


class GoesReader:
    """Abre los archivos GOES de una región una sola vez y da los barridos de cada hora ``t``."""

    def __init__(
        self, crops_root: Path, region: str, bands: Sequence[str], require_all: bool = True
    ) -> None:
        """Lector de ``crops_root/<region>/goes_latlon`` para las bandas ``bands``.

        Con ``require_all`` los archivos a los que les falta alguna banda se omiten con aviso
        (Extractor_GOES); sin él se conservan con ``GoesFile.missing`` para que el llamador
        registre la banda faltante (Compositor_RGB).
        """
        self.crops_root = crops_root
        self.region = region
        self.bands = tuple(bands)
        self.require_all = require_all
        self._cache: dict[dt.datetime, GoesFile | None] = {}

    def file(self, hour: dt.datetime) -> GoesFile | None:
        """Archivo de la hora ``hour``; ``None`` si no existe o le falta alguna banda (con aviso)."""
        key = hour.replace(minute=0, second=0, microsecond=0)
        if key not in self._cache:
            path = goes_path(self.crops_root, self.region, key)
            f = load_goes_file(path, self.bands) if path.exists() else None
            if f is not None and f.missing and self.require_all:
                for b in f.missing:
                    print(f"  aviso: {path.name} no trae la banda {b}; se omite", flush=True)
                f = None
            self._cache[key] = f
        return self._cache[key]

    def prune(self, t: dt.datetime) -> None:
        """Libera los archivos de horas anteriores a ``t - 1`` (recorridos en orden de tiempo)."""
        keep = t.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
        for key in [k for k in self._cache if k < keep]:
            del self._cache[key]

    def scans(self, t: dt.datetime) -> list[tuple[GoesFile, int, dt.datetime]]:
        """Barridos ``(archivo, índice, inicio)`` de los archivos de la hora ``t`` y de ``t - 1``.

        Solo esos dos archivos: los barridos de (t - 60 min, t] están ahí y nunca se mira el
        archivo de ``t + 1``.
        """
        out: list[tuple[GoesFile, int, dt.datetime]] = []
        for hour in (t - dt.timedelta(hours=1), t):
            f = self.file(hour)
            if f is not None:
                out.extend((f, k, s) for k, s in enumerate(f.times))
        return out


def hour_rows(
    reader: GoesReader, t: dt.datetime, lat: np.ndarray, lon: np.ndarray, half: float
) -> dict[str, list]:
    """Variables_GOES de todos los puntos (``lat`` × ``lon``) de la hora ``t``.

    Sin barrido en (t - 60 min, t] las variables quedan en NaN y ``scan_start`` vacío, pero las
    filas se conservan (Req. 6.9).
    """
    scans = reader.scans(t)
    times = [s for _, _, s in scans]
    late = gf.select_scan(times, t)
    early = gf.select_pair(times, late) if late is not None else None
    rows: dict[str, list] = {c: [] for c in COLUMNS}
    fields: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    lat_sl: list[slice] = []
    lon_sl: list[slice] = []
    lat_sl_e: list[slice] = []
    lon_sl_e: list[slice] = []
    if late is not None:
        f, k, _ = scans[late]
        fields["late"] = (f.band("C13", k), f.band("C08", k))
        lat_sl = [gf.window_slice(f.lat, y, half) for y in lat]
        lon_sl = [gf.window_slice(f.lon, x, half) for x in lon]
    if early is not None:
        fe, ke, _ = scans[early]
        fields["early"] = (fe.band("C13", ke), fe.band("C08", ke))
        lat_sl_e = [gf.window_slice(fe.lat, y, half) for y in lat]
        lon_sl_e = [gf.window_slice(fe.lon, x, half) for x in lon]
    for i, y in enumerate(lat):
        for j, x in enumerate(lon):
            rows["time"].append(t)
            rows["latitude"].append(float(y))
            rows["longitude"].append(float(x))
            if late is None:
                rows["scan_start"].append(None)
                for c in (*gf.GOES_FEATURES, "valid_frac_c13"):
                    rows[c].append(float("nan"))
                continue
            b13, b08 = fields["late"]
            win = (lat_sl[i], lon_sl[j])
            feats = gf.window_features(b13[win], b08[win])
            rate = float("nan")
            if early is not None:
                e13, e08 = fields["early"]
                win_e = (lat_sl_e[i], lon_sl_e[j])
                bt_early = gf.window_features(e13[win_e], e08[win_e])["goes_bt13_min"]
                gap = (times[late] - times[early]).total_seconds() / 60.0
                rate = gf.cooling_rate(bt_early, feats["goes_bt13_min"], gap)
            rows["scan_start"].append(times[late])
            for c in ("goes_bt13_min", "goes_cold_frac", "goes_wv_ir_max", "valid_frac_c13"):
                rows[c].append(feats[c])
            rows["goes_cooling_rate"].append(rate)
    return rows


def to_frame(rows: dict[str, list]) -> pd.DataFrame:
    """Tabla con los tipos del modelo de datos (tiempos en UTC, variables en ``float32``)."""
    df = pd.DataFrame(rows, columns=COLUMNS)
    for c in ("time", "scan_start"):
        df[c] = pd.to_datetime(df[c]).dt.tz_localize("UTC").astype("datetime64[ns, UTC]")
    df["latitude"] = df["latitude"].astype("float64")
    df["longitude"] = df["longitude"].astype("float64")
    for c in (*gf.GOES_FEATURES, "valid_frac_c13"):
        df[c] = df[c].astype("float32")
    return df


def process_day(
    day: dt.date,
    region: str,
    crops_root: Path,
    out_root: Path,
    window_deg: float,
    force: bool,
) -> Path | None:
    """Calcula y escribe ``goes_feat_AAAAMMDD.parquet`` del día; ``None`` si no escribe nada.

    No escribe si la tabla ya existe (salvo ``force``), si faltan los índices ERA5 del día o si
    el día no tiene archivos GOES (avisa con la fecha y sigue, Req. 2.12).
    """
    out_dir = out_root / region / "goes_features"
    out_file = out_dir / f"goes_feat_{day:%Y%m%d}.parquet"
    if out_file.exists() and not force:
        print(f"{out_file.name}: ya existe", flush=True)
        return None
    idx_file = crops_root / region / "era5_indices" / f"era5_idx_{day:%Y%m%d}.nc"
    if not idx_file.exists():
        print(f"  aviso: {day}: sin índices ERA5 en {idx_file}; se omite el día", flush=True)
        return None
    goes_dir = crops_root / region / "goes_latlon" / f"{day:%Y%m%d}"
    if not any(goes_dir.glob("goes_*.nc")):
        print(f"  aviso: {day}: sin archivos GOES en {goes_dir}; se omite el día", flush=True)
        return None
    with xr.open_dataset(idx_file, engine="h5netcdf") as ds:
        lat = np.asarray(ds["latitude"].values, dtype=np.float64)
        lon = np.asarray(ds["longitude"].values, dtype=np.float64)
        hours = [ts.to_pydatetime() for ts in pd.to_datetime(ds["time"].values)]
    reader = GoesReader(crops_root, region, BANDS)
    parts = [to_frame(hour_rows(reader, t, lat, lon, window_deg / 2)) for t in hours]
    df = pd.concat(parts, ignore_index=True) if parts else to_frame({c: [] for c in COLUMNS})
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_file)
    print(f"{out_file.name}: {len(df)} Celdas_Hora", flush=True)
    return out_file


def main() -> None:
    """Punto de entrada: calcula las Variables_GOES de cada día pedido."""
    p = common.parser(__doc__, "los días")
    p.add_argument(
        "--window-deg",
        type=float,
        default=0.25,
        help="lado de la Ventana_GOES en grados (por defecto 0,25 = una celda ERA5)",
    )
    a = p.parse_args()
    reg = common.region_of(a)
    for day in common.days(a):
        process_day(day, reg.name, common.CROPS, MODEL_DATA, a.window_deg, a.force)


if __name__ == "__main__":
    main()
