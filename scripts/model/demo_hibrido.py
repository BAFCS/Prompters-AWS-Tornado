"""Demo del modelo híbrido COMPLETO: ERA5 + embedding de GOES en XGBoost (prueba de la máquina).

No es un resultado científico: como el bucket aún no tiene días con tornado + GOES juntos, este
script **inyecta etiquetas positivas sintéticas** sobre días que sí tienen ERA5 y GOES, para ver
el pipeline funcionar de punta a punta con embeddings:

  cells sintéticas (label 1/0) ─► ERA5 (índices) ─┐
                                                  ├─ join por cell_id ─► tabla híbrida ─► XGBoost
  recorte GOES ─► RGB ─► embedding Bedrock ───────┘

Requiere que los días ya estén sincronizados en ``data/crops/<region>/`` (era5_indices + goes_latlon)
con ``sync_from_bucket.py``. Usa solo los días que tengan AMBOS.

Uso:
    AWS_PROFILE=gpu uv run python scripts/model/demo_hibrido.py --n-pos 5 --n-neg 50
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

import table as tb  # noqa: E402

import common  # noqa: E402

REGION = "south-central-austral"
MODEL_DIR = ROOT / "data" / "model" / REGION


def days_with_both() -> list[dt.date]:
    """Días que tienen índice ERA5 y carpeta GOES reproyectada localmente."""
    idx_dir = common.folder(REGION, "era5_indices")
    goes_dir = common.folder(REGION, "goes_latlon")
    out: list[dt.date] = []
    for f in sorted(idx_dir.glob("era5_idx_*.nc")):
        stamp = f.stem.replace("era5_idx_", "")
        day = dt.datetime.strptime(stamp, "%Y%m%d").date()
        if (goes_dir / stamp).is_dir() and any((goes_dir / stamp).glob("goes_*.nc")):
            out.append(day)
    return out


def make_synthetic_cells(days: list[dt.date], n_pos: int, n_neg: int, seed: int) -> pd.DataFrame:
    """Crea cells con cell_id canónico: n_pos positivas sintéticas + n_neg negativas, sobre los días.

    Las posiciones (lat/lon/hora) se eligen al azar dentro de la grilla y en horas con imagen GOES.
    El cell_id usa el formato que esperan compose_rgb y table.build.
    """
    rng = np.random.default_rng(seed)
    lat = np.round(np.arange(-30, -56.01, -0.25), 2)  # grilla ERA5 de la región
    lon = np.round(np.arange(-76, -65.99, 0.25), 2)
    rows = []
    n = n_pos + n_neg
    for k in range(n):
        day = days[int(rng.integers(len(days)))]
        hour = int(rng.integers(12, 24))  # tarde-noche, cuando hay convección
        la = float(lat[int(rng.integers(len(lat)))])
        lo = float(lon[int(rng.integers(len(lon)))])
        t = pd.Timestamp(f"{day}T{hour:02d}:00", tz="UTC")
        cid = tb.make_cell_id(t, la, lo)
        label = 1 if k < n_pos else 0
        rows.append({
            "cell_id": cid, "time": t, "latitude": la, "longitude": lo,
            "label": label, "event_id": f"syn{k}" if label else "",
            "fold_group": f"syn{k}" if label else f"neg{k}",
        })
    return pd.DataFrame(rows)


def _run(cmd: list[str]) -> int:
    """Ejecuta un comando mostrando la línea."""
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> None:
    """Genera cells sintéticas, corre RGB+embedding, arma la tabla híbrida y entrena."""
    p = argparse.ArgumentParser(description="Demo híbrido ERA5+embedding GOES (etiquetas sintéticas).")
    p.add_argument("--n-pos", type=int, default=5, help="Positivas sintéticas")
    p.add_argument("--n-neg", type=int, default=50, help="Negativas")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()

    days = days_with_both()
    print(f"=== Días con ERA5+GOES locales: {len(days)} -> {[str(d) for d in days]} ===", flush=True)
    if not days:
        raise SystemExit("No hay días con ambos. Corre antes sync_from_bucket.py --only both.")

    start, end = min(days).isoformat(), max(days).isoformat()

    # 1) cells sintéticas
    cells = make_synthetic_cells(days, a.n_pos, a.n_neg, a.seed)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    cells_file = MODEL_DIR / "cells.parquet"
    cells.to_parquet(cells_file, index=False)
    print(f"[1/4] cells sintéticas: {a.n_pos} pos + {a.n_neg} neg -> {cells_file.name}", flush=True)

    model = ["uv", "run", "python"]
    # 2) RGB
    print("[2/4] compose_rgb (GOES -> PNG)", flush=True)
    _run([*model, "scripts/model/compose_rgb.py", "--cells", str(cells_file), "--recipe", "ir_wv",
          "--recipe-version", "1", "--size", "224", "--window-km", "100",
          "--start", start, "--end", end, "--region", REGION, "--force"])

    # 3) embeddings
    manifest = MODEL_DIR / "rgb" / "ir_wv_v1" / "manifest.parquet"
    print("[3/4] encode_bedrock (PNG -> embedding)", flush=True)
    _run([*model, "scripts/model/encode_bedrock.py", "--manifest", str(manifest), "--model", "titan",
          "--cache", "local", "--start", start, "--end", end, "--region", REGION, "--force"])

    # 4) tabla híbrida + entrenamiento
    print("[4/4] build_table build --config embeddings + train", flush=True)
    emb = MODEL_DIR / "embeddings" / "titan_1024_ir_wv_v1.parquet"
    _run([*model, "scripts/model/build_table.py", "--stage", "build", "--config", "embeddings",
          "--embeddings", str(emb), "--start", start, "--end", end, "--region", REGION])

    print("\n=== DEMO LISTA ===", flush=True)
    print("La tabla híbrida (ERA5 + embeddings) está en data/model/.../tables/config=embeddings/", flush=True)
    print("Entrena con: uv run python scripts/model/train_xgboost.py (ver su CLI)", flush=True)


if __name__ == "__main__":
    main()
