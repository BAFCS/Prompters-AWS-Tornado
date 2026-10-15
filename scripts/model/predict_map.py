"""Inferencia por área: de una entrada a un mapa de probabilidad de tornado sobre Chile.

En vez de una sola probabilidad, produce **una probabilidad por celda** de la grilla ERA5 del
centro-sur/austral y la entrega de dos formas:

1. ``probabilidades.csv`` con columnas ``latitude, longitude, prob`` (una fila por celda).
2. ``mapa_probabilidad.png``: el mapa de Chile con la costa y el mapa de calor de probabilidad.

La probabilidad de cada celda sale del modelo de demo (``data/model/demo/model_demo.json``), que
recibe las features ERA5 de esa celda más el embedding de la imagen de entrada (el mismo embedding
para todas las celdas: representa el aspecto del cielo del caso). Si no hay modelo o credenciales,
usa un puntaje físico de respaldo (CAPE × VGP × cizalladura) para que la demo nunca se caiga.

Fuentes de las features ERA5 por celda:
- ``--day AAAA-MM-DD --bucket <bucket>``: lee ese día del bucket (índices reales).
- sin día: genera un campo sintético suave, solo para la demo visual.

Uso:
    uv run python scripts/model/predict_map.py --image recorte.png --out data/model/demo
    uv run python scripts/model/predict_map.py --day 2019-05-30 --bucket <bucket> --out data/model/demo
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

import common  # noqa: E402

DEMO = ROOT / "data" / "model" / "demo"
COAST_ZIP = ROOT / "data" / "coast.zip"
REGION = common.REGIONS["south-central-austral"]
GRID_RES = 0.25  # paso de la grilla en grados (igual que ERA5)

ERA5_FEATURES = [
    "cape", "shear_01", "shear_03", "shear_06", "srh_01", "srh_03",
    "lcl", "gamma_03", "gamma_75", "vgp_01", "stp_lm", "sherbs3",
]


def grid() -> tuple[np.ndarray, np.ndarray]:
    """Latitudes (norte→sur) y longitudes (oeste→este) de la grilla de la región."""
    lat = np.round(np.arange(REGION.north, REGION.south - GRID_RES / 2, -GRID_RES), 3)
    lon = np.round(np.arange(REGION.west, REGION.east + GRID_RES / 2, GRID_RES), 3)
    return lat, lon


def era5_fields_from_bucket(bucket: str, day: dt.date) -> dict[str, np.ndarray] | None:
    """Índices ERA5 reales del día (promedio de las horas de tarde), o None si falla."""
    try:
        import process_era5 as pe
        import xarray as xr

        m = __import__("fsspec").get_mapper(f"s3://{bucket}/era5_store/era5_{day:%Y%m%d}.zarr", anon=True)
        ds = xr.open_zarr(m).load()
        pl = ds[["u", "v", "t", "z"]]
        sfc = ds[[v for v in ("10u", "10v", "2t", "2d", "sp", "cape") if v in ds]]
        times = pl["time"].values
        hours = pd.to_datetime(times).hour
        sel = [i for i, h in enumerate(hours) if 18 <= h <= 23] or list(range(len(times)))
        per = [pe.hourly_indices(pl.isel(time=i).load(), sfc.isel(time=i).load()) for i in sel]
        fields = {k: np.mean([p[k] for p in per], axis=0) for k in ERA5_FEATURES if k in per[0]}
        if "cape" in sfc:
            fields["cape"] = np.maximum(sfc["cape"].isel(time=sel).mean("time").values, 0.0)
        return fields
    except Exception as e:  # noqa: BLE001
        print(f"aviso: no se pudo leer ERA5 del bucket ({e!s:.100}); se usa campo sintético", flush=True)
        return None


def synthetic_fields(lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    """Campos ERA5 sintéticos suaves (para la demo sin datos): un foco de inestabilidad al norte."""
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    focus = np.exp(-(((la + 37) / 4) ** 2 + ((lo + 72) / 4) ** 2))  # foco cerca de -37, -72
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.1, la.shape)
    return {
        "cape": 2000 * focus + 100,
        "shear_01": 15 * focus + 3 + noise,
        "shear_03": 20 * focus + 5,
        "shear_06": 25 * focus + 8,
        "srh_01": -200 * focus - 20,
        "srh_03": -300 * focus - 30,
        "lcl": 800 - 300 * focus,
        "gamma_03": 6 + 2 * focus,
        "gamma_75": 6.5 + 2 * focus,
        "vgp_01": 0.2 * focus + 0.02,
        "stp_lm": -1.5 * focus - 0.1,
        "sherbs3": 1.5 * focus + 0.3,
    }


def image_embedding(image: Path | None, n_emb: int) -> np.ndarray:
    """Embedding de la imagen de entrada (Bedrock si hay credenciales; si no, sintético)."""
    if image is None:
        return np.zeros(n_emb)
    import base64
    import hashlib

    png = image.read_bytes()
    try:
        import botocore.session

        cli = botocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1")
        body = json.dumps({"inputImage": base64.b64encode(png).decode(),
                           "embeddingConfig": {"outputEmbeddingLength": 1024}})
        resp = cli.invoke_model(modelId="amazon.titan-embed-image-v1", body=body)
        return np.array(json.loads(resp["body"].read())["embedding"], dtype=float)[:n_emb]
    except Exception:  # noqa: BLE001
        rng = np.random.default_rng(int(hashlib.sha256(png).hexdigest()[:8], 16))
        return rng.standard_normal(n_emb) * 0.1


def predict_grid(fields: dict, lat: np.ndarray, lon: np.ndarray, emb: np.ndarray) -> np.ndarray:
    """Probabilidad por celda. Usa el modelo de demo si existe; si no, un puntaje físico."""
    ny, nx = len(lat), len(lon)
    model_file = DEMO / "model_demo.json"
    meta_file = DEMO / "model_meta.json"
    if model_file.exists() and meta_file.exists():
        try:
            import xgboost as xgb

            meta = json.loads(meta_file.read_text())
            cols = meta["model_columns"]
            model = xgb.XGBClassifier()
            model.load_model(str(model_file))
            rows = []
            for i in range(ny):
                for j in range(nx):
                    r = {f: float(fields[f][i, j]) for f in ERA5_FEATURES if f in fields}
                    for k, v in enumerate(emb):
                        r[f"emb_{k:04d}"] = float(v)
                    rows.append({c: r.get(c, np.nan) for c in cols})
            x = pd.DataFrame(rows)
            prob = model.predict_proba(x)[:, 1].reshape(ny, nx)
            # Si el modelo da una probabilidad casi constante (features PCA no alineadas en la demo),
            # cae al puntaje físico, que sí varía por celda y es lo que se quiere ver en el mapa.
            if float(prob.max() - prob.min()) > 0.02:
                return prob
            print("aviso: el modelo dio prob casi constante; uso puntaje físico por celda", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"aviso: modelo no aplicable ({e!s:.80}); uso puntaje físico", flush=True)
    # Respaldo físico: combina CAPE, VGP y cizalladura normalizados.
    cape = fields.get("cape", np.zeros((ny, nx)))
    vgp = fields.get("vgp_01", np.zeros((ny, nx)))
    shear = fields.get("shear_06", np.zeros((ny, nx)))
    score = (cape / 2000) * 0.4 + (vgp / 0.2) * 0.4 + (shear / 25) * 0.2
    return 1 / (1 + np.exp(-(score - 0.5) * 4))


def draw_coast(ax: plt.Axes) -> None:
    """Dibuja la costa de Chile desde data/coast.zip (si está)."""
    if not COAST_ZIP.exists():
        return
    try:
        import geopandas as gpd

        with zipfile.ZipFile(COAST_ZIP) as z:
            shp = next((n for n in z.namelist() if n.endswith(".shp")), None)
            if shp:
                gdf = gpd.read_file(f"zip://{COAST_ZIP}!{shp}")
                gdf.boundary.plot(ax=ax, color="black", linewidth=0.6)
    except Exception as e:  # noqa: BLE001
        print(f"aviso: no se dibujó la costa ({e!s:.80})", flush=True)


def main() -> None:
    """Genera CSV y mapa de probabilidad por área."""
    p = argparse.ArgumentParser(description="Inferencia por área: mapa de probabilidad de tornado.")
    p.add_argument("--image", type=Path, help="Imagen de entrada (recorte GOES o cualquiera)")
    p.add_argument("--day", help="Día AAAA-MM-DD para leer ERA5 real del bucket")
    p.add_argument("--bucket", help="Bucket S3 (con --day)")
    p.add_argument("--out", type=Path, default=DEMO, help="Carpeta de salida")
    a = p.parse_args()

    lat, lon = grid()
    print(f"Grilla: {len(lat)} x {len(lon)} = {len(lat) * len(lon)} celdas", flush=True)

    fields = None
    if a.day and a.bucket:
        fields = era5_fields_from_bucket(a.bucket, dt.date.fromisoformat(a.day))
    if fields is None:
        fields = synthetic_fields(lat, lon)
        print("Usando campo ERA5 sintético (demo).", flush=True)

    n_emb = 1024
    meta_file = DEMO / "model_meta.json"
    if meta_file.exists():
        n_emb = json.loads(meta_file.read_text()).get("n_emb", 1024)
    emb = image_embedding(a.image, n_emb)
    print(f"Embedding de la imagen: {'real/sintético' } ({len(emb)} dims)", flush=True)

    prob = predict_grid(fields, lat, lon, emb)
    a.out.mkdir(parents=True, exist_ok=True)

    # CSV: una fila por celda
    rows = [{"latitude": float(lat[i]), "longitude": float(lon[j]), "prob": float(prob[i, j])}
            for i in range(len(lat)) for j in range(len(lon))]
    csv_file = a.out / "probabilidades.csv"
    pd.DataFrame(rows).to_csv(csv_file, index=False)
    print(f"CSV: {csv_file} ({len(rows)} celdas)", flush=True)

    # Mapa
    fig, ax = plt.subplots(figsize=(6, 9))
    mesh = ax.pcolormesh(lon, lat, prob, cmap="turbo", vmin=0, vmax=1, shading="auto")
    draw_coast(ax)
    ax.set_xlim(REGION.west, REGION.east)
    ax.set_ylim(REGION.south, REGION.north)
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title("Probabilidad de entorno tornádico por área")
    fig.colorbar(mesh, ax=ax, label="probabilidad", shrink=0.6)
    png_file = a.out / "mapa_probabilidad.png"
    fig.savefig(png_file, dpi=130, bbox_inches="tight")
    print(f"Mapa: {png_file}", flush=True)
    print(f"prob min/máx: {prob.min():.3f} / {prob.max():.3f}", flush=True)


if __name__ == "__main__":
    main()
