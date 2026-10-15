"""Genera la tabla de features del modelo (submuestreo), leyendo ERA5 del bucket CDS.

NO entrena nada: solo construye la tabla que luego consumirá el modelo. Para cada día disponible:

1. Lee ERA5 CDS del bucket (rápido: ya viene recortado a Chile, pocos MB).
2. Calcula los índices por celda-hora con ``process_era5.hourly_indices`` (cizalladura, SRH, VGP,
   STP, SHERBS3, LCL, gradientes, CAPE).
3. Extrae las filas de la muestra:
   - **positivos**: la vecindad ``neighbor``×``neighbor`` alrededor de cada tornado, a lo largo de
     la ventana temporal ±``hours`` (sigue el movimiento del tornado);
   - **negativos**: celdas-hora al azar del día, lejos de cualquier evento (zona de exclusión).
4. Escribe una tabla parquet con las features + etiqueta + split temporal.

Pensado para probar con 1-3 días antes de escalar. La fuente CDS evita el cuello de botella de
NSF-NCAR (segundos por día en vez de minutos).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cds_source  # noqa: E402
from build_data import CATALOG, read_catalog  # noqa: E402
from process_era5 import hourly_indices  # noqa: E402
from sampling import SampleConfig, _season  # noqa: E402

OUT_DIR = ROOT / "data" / "model"

# Índices (features ERA5) que produce hourly_indices y que entran al modelo.
FEATURES = [
    "cape", "shear_01", "shear_03", "shear_06", "srh_01", "srh_03",
    "lcl", "gamma_03", "gamma_75", "vgp_01", "stp_lm", "sherbs3",
]


def _nearest(values: np.ndarray, target: float) -> int:
    """Índice del valor más cercano a ``target``."""
    return int(np.abs(values - target).argmin())


def day_indices(bucket: str, day: dt.date) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    """Calcula los índices de todas las celdas-hora del día. Devuelve (campos, lat, lon, horas)."""
    pl, sfc = cds_source.load_day(bucket, day)
    times = np.intersect1d(pl["time"].values, sfc["time"].values)
    lat = pl["latitude"].values
    lon = pl["longitude"].values
    hours = pd.to_datetime(times).hour.to_numpy()

    # hourly_indices trabaja por hora; apilamos sobre el eje temporal.
    per_hour = [hourly_indices(pl.sel(time=t).load(), sfc.sel(time=t).load()) for t in times]
    fields = {name: np.stack([h[name] for h in per_hour]) for name in FEATURES if name in per_hour[0]}
    # CAPE es variable de entrada (no la re-expone hourly_indices): se toma directo del sfc.
    if "cape" in sfc.data_vars:
        cape = sfc["cape"].sel(time=times).values
        fields["cape"] = np.maximum(cape, 0.0)
    return fields, lat, lon, hours


def rows_for_day(
    bucket: str, day: dt.date, events: pd.DataFrame, cfg: SampleConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """Filas de la muestra para un día: positivos (vecindad) + negativos (lejos de eventos)."""
    fields, lat, lon, hours = day_indices(bucket, day)
    nt, ny, nx = len(hours), len(lat), len(lon)
    half = cfg.neighbor // 2
    rows: list[dict] = []

    day_events = events[events["date"] == day]
    positive_cells: set[tuple[int, int, int]] = set()  # (ti, yi, xi) ocupadas por positivos

    # --- Positivos: vecindad que sigue al tornado, en la ventana temporal ---
    for idx, ev in day_events.iterrows():
        yi0, xi0 = _nearest(lat, ev["lat"]), _nearest(lon, ev["lon"])
        event_id = f"{day:%Y%m%d}-{int(ev['hour_utc']):02d}-{idx}"
        split = "test" if day >= cfg.test_from else "train"
        for dh in range(-cfg.hours, cfg.hours + 1):
            ti = _nearest(hours, (int(ev["hour_utc"]) + dh) % 24)
            for di in range(-half, half + 1):
                for dj in range(-half, half + 1):
                    yi, xi = yi0 + di, xi0 + dj
                    if 0 <= yi < ny and 0 <= xi < nx:
                        positive_cells.add((ti, yi, xi))
                        rows.append(_row(fields, ti, yi, xi, 1, event_id, day, split))

    # --- Negativos: celdas-hora al azar, excluyendo la vecindad amplia de los positivos ---
    n_neg = max(len(rows) * cfg.ratio, cfg.ratio)
    exclude_radius = cfg.neighbor  # excluye un poco más que la vecindad positiva
    tries, got = 0, 0
    while got < n_neg and tries < n_neg * 20:
        tries += 1
        ti, yi, xi = int(rng.integers(nt)), int(rng.integers(ny)), int(rng.integers(nx))
        # ¿cae cerca de un positivo? (zona de exclusión en celdas y horas)
        near = any(
            abs(ti - pti) <= cfg.hours and abs(yi - pyi) <= exclude_radius and abs(xi - pxi) <= exclude_radius
            for pti, pyi, pxi in positive_cells
        )
        if near:
            continue
        split = "test" if day >= cfg.test_from else "train"
        rows.append(_row(fields, ti, yi, xi, 0, f"{day:%Y%m%d}-neg", day, split))
        got += 1

    table = pd.DataFrame(rows)
    return table.dropna(subset=[f for f in FEATURES if f in table]).reset_index(drop=True)


def _row(fields: dict, ti: int, yi: int, xi: int, label: int, event_id: str, day: dt.date, split: str) -> dict:
    """Una fila con los valores de cada feature en (ti, yi, xi) y sus metadatos."""
    r = {name: float(arr[ti, yi, xi]) for name, arr in fields.items()}
    r.update({"label": label, "event_id": event_id, "day": str(day), "split": split,
              "season": _season(day)})
    return r


def main() -> None:
    """Construye la tabla de features para los días pedidos (prueba con pocos primero)."""
    p = argparse.ArgumentParser(description="Genera la tabla de features (submuestreo), sin entrenar.")
    p.add_argument("--bucket", required=True, help="Bucket S3 con ERA5 CDS (sin s3://)")
    p.add_argument("--days", nargs="*", default=[], help="Días AAAA-MM-DD a procesar (vacío = los disponibles)")
    p.add_argument("--neighbor", type=int, default=3)
    p.add_argument("--hours", type=int, default=2)
    p.add_argument("--ratio", type=int, default=10)
    p.add_argument("--out", default=str(OUT_DIR / "features.parquet"))
    a = p.parse_args()

    cfg = SampleConfig(neighbor=a.neighbor, hours=a.hours, ratio=a.ratio)
    rng = np.random.default_rng(cfg.seed)
    events = read_catalog(CATALOG)
    events = events[events["lat"].notna() & events["lon"].notna() & events["hour_utc"].notna()]

    if a.days:
        days = [dt.date.fromisoformat(d) for d in a.days]
    else:
        days = cds_source.available_days(a.bucket)
    print(f"Procesando {len(days)} día(s) desde s3://{a.bucket}: {[str(d) for d in days]}", flush=True)

    parts: list[pd.DataFrame] = []
    for day in days:
        try:
            t = rows_for_day(a.bucket, day, events, cfg, rng)
            n_pos = int((t["label"] == 1).sum())
            print(f"  {day}: {len(t)} filas ({n_pos} positivas, {len(t) - n_pos} negativas)", flush=True)
            parts.append(t)
        except Exception as e:  # noqa: BLE001
            print(f"  {day}: ERROR {e!r}", flush=True)

    if not parts:
        raise SystemExit("No se generó ninguna fila.")
    table = pd.concat(parts, ignore_index=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(a.out, index=False)

    print("\n=== RESUMEN DE LA TABLA ===", flush=True)
    print(f"filas: {len(table)} · columnas: {list(table.columns)}", flush=True)
    print(f"positivas: {int((table['label'] == 1).sum())} · negativas: {int((table['label'] == 0).sum())}", flush=True)
    print(f"días: {table['day'].nunique()} · train/test: "
          f"{int((table['split'] == 'train').sum())}/{int((table['split'] == 'test').sum())}", flush=True)
    print(f"guardada en {a.out}", flush=True)


if __name__ == "__main__":
    main()
