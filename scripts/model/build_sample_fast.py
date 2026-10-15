"""Muestreo rápido y autocontenido para la presentación: arma la tabla del modelo desde el bucket.

Objetivo: tener YA una tabla (parquet) lista para XGBoost, corriendo contra el bucket público del
equipo (``era5_store`` + ``goes_store``), sin pipeline pesado ni dependencias GPU.

Estrategia pensada para ir rápido:

* **ERA5** se lee del store Zarr del bucket (recortado a Chile, vuela) y se calculan los índices.
* **GOES** es opcional (``--goes``): para no bajar los 60 MB/día del disco completo, se leen solo
  **unas horas** alrededor de cada evento y se **submuestrea la grilla** (``--goes-stride``, por
  defecto 4 → ~8 km en vez de 2 km). Baja el volumen ~16× y basta para el tope frío (C13).
* Positivos: vecindad ``3x3`` celdas ERA5 × ventana ``±2 h`` (sigue el movimiento del tornado).
* Negativos: celdas-hora al azar de días sin evento, lejos de los positivos (10:1).
* Split temporal train/test por fecha.

Uso (lo más seguro para mañana, solo ERA5 — rápido y garantizado):

    uv run python scripts/model/build_sample_fast.py --bucket <bucket> --out data/model/tabla.parquet

Con GOES (si da tiempo):

    uv run python scripts/model/build_sample_fast.py --bucket <bucket> --goes --out data/model/tabla.parquet

Lee del bucket con acceso anónimo; no necesita credenciales.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
from pathlib import Path

import fsspec
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

import contextlib  # noqa: E402

import process_era5 as pe  # noqa: E402

CATALOG = ROOT / "data" / "tornados_chile.xlsx"
GOES16_START = dt.date(2017, 12, 1)
TEST_FROM = dt.date(2023, 1, 1)  # split temporal: eventos recientes a test

ERA5_FEATURES = [
    "cape",
    "shear_01",
    "shear_03",
    "shear_06",
    "srh_01",
    "srh_03",
    "lcl",
    "gamma_03",
    "gamma_75",
    "vgp_01",
    "stp_lm",
    "sherbs3",
]


# --------------------------------------------------------------------------- catálogo
def read_catalog() -> pd.DataFrame:
    """Lee y normaliza el catálogo (fecha, lat, lon, hora UTC)."""
    d = pd.read_excel(CATALOG, sheet_name="Final_Table")
    d["date"] = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    d["lat"] = d["Latitude"].map(_coord)
    d["lon"] = d["Longitude"].map(_coord)
    d["hour_utc"] = pd.to_numeric(
        d["Hour (UTC)"].astype(str).str.extract(r"(\d{1,2})", expand=False), errors="coerce"
    )
    return d[d["lat"].notna() & d["lon"].notna() & d["hour_utc"].notna()]


def _coord(value: object) -> float:
    """Coordenada del catálogo (texto o número) a grados decimales con signo."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    s = str(value).strip().replace(",", ".")
    sign = -1.0 if any(c in s.upper() for c in ("S", "W", "O", "-")) else 1.0
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return sign * abs(float(digits))
    except ValueError:
        return float("nan")


# --------------------------------------------------------------------------- bucket
def available_days(bucket: str) -> list[dt.date]:
    """Días con ERA5 en el store Zarr del bucket."""
    fs = fsspec.filesystem("s3", anon=True)
    out: list[dt.date] = []
    for p in fs.ls(f"{bucket}/era5_store", detail=False):
        n = p.rstrip("/").split("/")[-1]
        if n.startswith("era5_") and n.endswith(".zarr"):
            with contextlib.suppress(ValueError):
                out.append(dt.datetime.strptime(n[5:13], "%Y%m%d").date())
    return sorted(out)


def era5_indices(bucket: str, day: dt.date) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    """Índices ERA5 de todas las celdas-hora del día (campos, lat, lon, horas)."""
    m = fsspec.get_mapper(f"s3://{bucket}/era5_store/era5_{day:%Y%m%d}.zarr", anon=True)
    ds = xr.open_zarr(m).load()
    pl = ds[["u", "v", "t", "z"]]
    sfc = ds[[v for v in ("10u", "10v", "2t", "2d", "sp", "cape") if v in ds]]
    times = pl["time"].values
    lat, lon = pl["latitude"].values, pl["longitude"].values
    hours = pd.to_datetime(times).hour.to_numpy()
    per_hour = [pe.hourly_indices(pl.sel(time=t).load(), sfc.sel(time=t).load()) for t in times]
    fields = {k: np.stack([h[k] for h in per_hour]) for k in ERA5_FEATURES if k in per_hour[0]}
    if "cape" in sfc:
        fields["cape"] = np.maximum(sfc["cape"].values, 0.0)
    return fields, lat, lon, hours


def goes_c13_day(bucket: str, day: dt.date, stride: int) -> xr.DataArray | None:
    """Carga C13 del día submuestreando la grilla (stride) para reducir volumen. None si no hay."""
    fs = fsspec.filesystem("s3", anon=True)
    key = f"{bucket}/goes_store/{day:%Y-%m-%d}/goes_{day:%Y%m%d}.nc"
    if not fs.exists(key):
        return None
    with fs.open(key, "rb") as f:
        ds = xr.load_dataset(io.BytesIO(f.read()))
    return ds["C13"].isel(y=slice(None, None, stride), x=slice(None, None, stride))


def goes_features_at(c13: xr.DataArray | None, lat0: float, lon0: float, hour: int) -> dict:
    """Resumen de C13 (tope frío) en un recorte ~25 km alrededor del punto a la hora dada."""
    nan = {"c13_min": float("nan"), "c13_mean": float("nan"), "c13_cold_frac": float("nan")}
    if c13 is None:
        return nan
    lat2d, lon2d = c13["lat"].values, c13["lon"].values
    d2 = (lat2d - lat0) ** 2 + (lon2d - lon0) ** 2
    yi, xi = np.unravel_index(int(np.nanargmin(d2)), d2.shape)
    hours = pd.to_datetime(c13["time"].values).hour.to_numpy()
    ti = int(np.argmin(np.abs(hours - hour)))
    half = 6
    crop = c13.isel(
        time=ti,
        y=slice(max(yi - half, 0), yi + half + 1),
        x=slice(max(xi - half, 0), xi + half + 1),
    ).values
    crop = crop[np.isfinite(crop)]
    if crop.size == 0:
        return nan
    return {
        "c13_min": float(np.min(crop)),
        "c13_mean": float(np.mean(crop)),
        "c13_cold_frac": float(np.mean(crop < 221.0)),  # fracción muy fría (~ -52 C)
    }


# --------------------------------------------------------------------------- muestreo
def _nearest(a: np.ndarray, v: float) -> int:
    return int(np.abs(a - v).argmin())


def rows_for_day(
    bucket: str,
    day: dt.date,
    events: pd.DataFrame,
    use_goes: bool,
    stride: int,
    neighbor: int,
    hours_win: int,
    ratio: int,
    rng: np.random.Generator,
) -> list[dict]:
    """Filas (positivos + negativos) de un día."""
    fields, lat, lon, hours = era5_indices(bucket, day)
    nt, ny, nx = len(hours), len(lat), len(lon)
    half = neighbor // 2
    c13 = goes_c13_day(bucket, day, stride) if use_goes else None
    rows: list[dict] = []
    pos_cells: set[tuple[int, int, int]] = set()
    split = "test" if day >= TEST_FROM else "train"

    for idx, ev in events[events["date"] == day].iterrows():
        yi0, xi0 = _nearest(lat, ev["lat"]), _nearest(lon, ev["lon"])
        eid = f"{day:%Y%m%d}-{int(ev['hour_utc']):02d}-{idx}"
        for dh in range(-hours_win, hours_win + 1):
            hr = (int(ev["hour_utc"]) + dh) % 24
            ti = _nearest(hours, hr)
            for di in range(-half, half + 1):
                for dj in range(-half, half + 1):
                    yi, xi = yi0 + di, xi0 + dj
                    if 0 <= yi < ny and 0 <= xi < nx:
                        pos_cells.add((ti, yi, xi))
                        rows.append(
                            _mk(
                                fields,
                                ti,
                                yi,
                                xi,
                                1,
                                eid,
                                day,
                                split,
                                c13,
                                float(lat[yi]),
                                float(lon[xi]),
                                hr,
                            )
                        )

    n_neg = max(len(rows) * ratio, ratio)
    got, tries = 0, 0
    while got < n_neg and tries < n_neg * 20:
        tries += 1
        ti, yi, xi = int(rng.integers(nt)), int(rng.integers(ny)), int(rng.integers(nx))
        if any(
            abs(ti - a) <= hours_win and abs(yi - b) <= neighbor and abs(xi - c) <= neighbor
            for a, b, c in pos_cells
        ):
            continue
        rows.append(
            _mk(
                fields,
                ti,
                yi,
                xi,
                0,
                f"{day:%Y%m%d}-neg",
                day,
                split,
                c13,
                float(lat[yi]),
                float(lon[xi]),
                int(hours[ti]),
            )
        )
        got += 1
    return rows


def _mk(  # noqa: PLR0913
    fields: dict, ti: int, yi: int, xi: int, label: int, eid: str, day: dt.date, split: str,
    c13: xr.DataArray | None, lat0: float, lon0: float, hr: int,
) -> dict:  # fmt: skip
    """Arma una fila: features ERA5 + GOES + metadatos."""
    r: dict[str, object] = {k: float(v[ti, yi, xi]) for k, v in fields.items()}
    r.update(goes_features_at(c13, lat0, lon0, hr))
    r.update({"label": label, "event_id": eid, "day": str(day), "split": split})
    return r


def main() -> None:
    """Punto de entrada."""
    p = argparse.ArgumentParser(
        description="Muestreo rápido desde el bucket (para la presentación)."
    )
    p.add_argument("--bucket", required=True)
    p.add_argument("--out", default="data/model/tabla.parquet")
    p.add_argument("--goes", action="store_true", help="Añadir features GOES C13 (más lento)")
    p.add_argument(
        "--goes-stride", type=int, default=4, help="Submuestreo de la grilla GOES (4 = ~8 km)"
    )
    p.add_argument("--neighbor", type=int, default=3)
    p.add_argument("--hours", type=int, default=2)
    p.add_argument("--ratio", type=int, default=10)
    p.add_argument("--max-neg-days", type=int, default=15, help="Días sin evento como negativos")
    p.add_argument("--days", nargs="*", default=[], help="Forzar días concretos (debug)")
    a = p.parse_args()

    events = read_catalog()
    avail = available_days(a.bucket)
    event_days = sorted(set(events["date"]) & set(avail))
    neg_days = [d for d in avail if d not in set(events["date"])][: a.max_neg_days]
    days = (
        [dt.date.fromisoformat(d) for d in a.days]
        if a.days
        else sorted(set(event_days) | set(neg_days))
    )

    print(
        f"Bucket: {len(avail)} días ERA5 | con evento: {len(event_days)} | negativos: {len(neg_days)}",
        flush=True,
    )
    print(f"Procesando {len(days)} días (GOES={'sí' if a.goes else 'no'})", flush=True)

    rng = np.random.default_rng(0)
    import time as _time

    all_rows: list[dict] = []
    t_start = _time.time()
    for i, day in enumerate(days, 1):
        t0 = _time.time()
        try:
            r = rows_for_day(
                a.bucket, day, events, a.goes, a.goes_stride, a.neighbor, a.hours, a.ratio, rng
            )
            npos = sum(x["label"] == 1 for x in r)
            elapsed = _time.time() - t0
            total = _time.time() - t_start
            print(
                f"  [{i}/{len(days)}] {day}: {len(r)} filas ({npos} pos) "
                f"— {elapsed:.1f}s (acumulado {total:.0f}s)",
                flush=True,
            )
            all_rows.extend(r)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(days)}] {day}: ERROR {e!r}", flush=True)

    if not all_rows:
        raise SystemExit("No se generó ninguna fila (¿faltan días en el bucket?).")
    table = pd.DataFrame(all_rows).dropna(subset=[f for f in ERA5_FEATURES if f in all_rows[0]])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(a.out, index=False)
    print(f"\n=== TABLA LISTA: {a.out} ===", flush=True)
    print(
        f"filas: {len(table)} | pos: {int((table['label'] == 1).sum())} | neg: {int((table['label'] == 0).sum())}",
        flush=True,
    )
    print(f"columnas: {list(table.columns)}", flush=True)
    print(
        f"train/test: {int((table['split'] == 'train').sum())}/{int((table['split'] == 'test').sum())}",
        flush=True,
    )


if __name__ == "__main__":
    main()
