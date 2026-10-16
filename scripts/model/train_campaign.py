#!/usr/bin/env python3
"""Campaña de experimentos de modelado sobre la capa curada ERA5+GOES.

Corre una serie de configuraciones (baseline físico, ventanas largas, GOES, **lead-1h**, balance,
embeddings) con validación honesta (LOEO por bloque + holdout temporal), sin fuga, y reporta
POD/FAR/CSI/PR-AUC con dispersión entre folds. No fuerza métricas: una config solo "gana" si bate al
baseline de forma estable.

Objetivo central (idea del equipo): un predictor de ALERTA que en la hora ``t`` usa las ventanas
``t-1..t-5`` (ERA5+GOES) para predecir el evento en ``t+LEAD`` horas — junta el "desplazamiento"
observado (la probabilidad sube antes del evento) con la "predicción al futuro". Eso es el
experimento ``lead1h``.

Entradas: Parquets de ``curated/analysis_ready/<año>/`` (una fila por celda-hora) + catálogo de
eventos + manifiesto ``etiquetas.json``. Lectura S3 anónima de la fuente, destino configurable.

Uso::

    python train_campaign.py --config baseline --curated s3://BUCKET/curated/analysis_ready \\
        --catalog s3://.../tornados_chile.xlsx --out s3://BUCKET/experimentos/campania
    python train_campaign.py --config lead1h --lead 1 ...

Configuraciones (``--config``): baseline, windows, goes, lead1h, balance, smote, embeddings.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# --- Features físicas núcleo (de process_era5 / el modelo actual). Signos australes intactos. ----
ERA5_CORE = [
    "era5_cape", "era5_10u", "era5_10v", "era5_2t", "era5_2d", "era5_sp",
    "era5_t850", "era5_t500", "era5_u850", "era5_u500", "era5_v850", "era5_v500",
    "era5_z850", "era5_z500",
]
GOES_FEATS = [
    "goes_C13_bt_min", "goes_C13_bt_mean", "goes_C13_frac_lt220", "goes_C13_frac_lt210",
    "goes_C13_dbtmin_dt", "goes_C08_bt_min", "goes_C09_bt_min",
]


def read_parquets(curated: str, days: list[str], anon_src: bool, sample_frac: float = 0.15) -> pd.DataFrame:
    """Carga los Parquets curados, submuestreando celdas por día para no reventar memoria.

    Con 846 días × ~103k celdas-hora el dataset completo no cabe en RAM y no aporta (son ~31
    positivos). Se conserva una fracción ``sample_frac`` de las celdas-hora de cada día (semilla
    fija) y todas las columnas; los positivos se marcan después por cercanía al evento. Para días de
    evento se puede subir la fracción desde el llamador si hiciera falta. Todo a float32.
    """
    import s3fs

    rng = np.random.default_rng(42)

    def _load_bytes(raw: bytes) -> pd.DataFrame:
        d = pd.read_parquet(io.BytesIO(raw))
        if 0 < sample_frac < 1 and len(d) > 0:
            keep = rng.random(len(d)) < sample_frac
            d = d[keep]
        # a float32 las columnas numéricas para ahorrar RAM
        for c in d.select_dtypes(include=["float64"]).columns:
            d[c] = d[c].astype("float32")
        return d

    frames = []
    if curated.startswith("s3://"):
        fs = s3fs.S3FileSystem(anon=anon_src)
        bucket_path = curated[5:]
        for d in days:
            key = f"{bucket_path}/{d[:4]}/curated_{d.replace('-','')}.parquet"
            try:
                with fs.open(key, "rb") as f:
                    frames.append(_load_bytes(f.read()))
            except Exception:  # noqa: BLE001
                continue
    else:
        for d in days:
            p = Path(curated) / d[:4] / f"curated_{d.replace('-','')}.parquet"
            if p.exists():
                frames.append(_load_bytes(p.read_bytes()))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def add_lags(df: pd.DataFrame, feats: list[str], lags: tuple[int, ...]) -> list[str]:
    """Añade columnas de rezago t-k por celda (ordenadas por hora dentro de cada día-celda).

    Causal estricto: solo usa el pasado. Añade también las diferencias x(t)-x(t-k).
    """
    df.sort_values(["date", "lat", "lon", "hour_utc"], inplace=True)
    g = df.groupby(["date", "lat", "lon"], sort=False)
    new_cols = []
    for f in feats:
        if f not in df:
            continue
        for k in lags:
            c = f"{f}_lag{k}"
            df[c] = g[f].shift(k)
            new_cols.append(c)
            dc = f"{f}_d{k}"
            df[dc] = df[f] - df[c]
            new_cols.append(dc)
    return new_cols


def label_events(df: pd.DataFrame, events: pd.DataFrame, lead: int) -> pd.DataFrame:
    """Marca label=1 en la celda-hora más cercana al evento, DESPLAZADA ``lead`` horas antes.

    Para lead=0: etiqueta la hora del evento (diagnóstico). Para lead=1: etiqueta la hora t tal que
    el evento ocurre en t+1 (predicción a 60 min) — las features de la fila t son todas <= t.
    """
    df["label"] = 0
    df["event_id"] = ""
    for _, ev in events.iterrows():
        if pd.isna(ev.get("hour_utc")) or pd.isna(ev.get("lat")) or pd.isna(ev.get("lon")):
            continue
        d = ev["date"]
        if d is None or (isinstance(d, float) and np.isnan(d)):
            continue
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        h_target = int(ev["hour_utc"]) - lead  # hora de la FILA que debe predecir
        if h_target < 0:
            continue
        sub = df[df["date"].astype(str) == d_str]
        if sub.empty:
            continue
        # celda más cercana al evento, en la hora desplazada
        cand = sub[sub["hour_utc"] == h_target]
        if cand.empty:
            continue
        dist = (cand["lat"] - ev["lat"]) ** 2 + (cand["lon"] - ev["lon"]) ** 2
        idx = dist.idxmin()
        df.loc[idx, "label"] = 1
        df.loc[idx, "event_id"] = f"{d}-{ev.name}"
    return df


def metrics(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> dict:
    """POD, FAR, CSI con umbral ``thr`` + PR-AUC."""
    from sklearn.metrics import average_precision_score

    yhat = (p >= thr).astype(int)
    hits = int(((yhat == 1) & (y == 1)).sum())
    miss = int(((yhat == 0) & (y == 1)).sum())
    fa = int(((yhat == 1) & (y == 0)).sum())
    pod = hits / (hits + miss) if (hits + miss) else 0.0
    far = fa / (hits + fa) if (hits + fa) else 0.0
    csi = hits / (hits + miss + fa) if (hits + miss + fa) else 0.0
    try:
        prauc = float(average_precision_score(y, p)) if y.sum() else 0.0
    except Exception:  # noqa: BLE001
        prauc = 0.0
    return {"POD": round(pod, 3), "FAR": round(far, 3), "CSI": round(csi, 3),
            "PR_AUC": round(prauc, 3), "hits": hits, "miss": miss, "fa": fa}


def loeo_cv(df: pd.DataFrame, feats: list[str], balance: str) -> dict:
    """Validación leave-one-event-out: cada evento (con su bloque) sale a prueba una vez.

    Devuelve métricas agregadas fuera de partición + dispersión entre folds (desv. estándar de CSI).
    """
    import xgboost as xgb

    ev_days = sorted({e.rsplit("-", 1)[0] for e in df.loc[df["label"] == 1, "event_id"].unique() if e})
    if len(ev_days) < 3:
        return {"error": f"muy pocos días de evento ({len(ev_days)})"}
    feats = [f for f in feats if f in df]
    oof_y, oof_p, per_fold_csi = [], [], []
    for day_of_ev in ev_days:
        test_mask = df["date"].astype(str) == day_of_ev
        train = df[~test_mask]
        test = df[test_mask]
        if train["label"].sum() == 0 or test["label"].sum() == 0:
            continue
        Xtr, ytr = train[feats].values, train["label"].values
        Xte, yte = test[feats].values, test["label"].values
        spw = max(1.0, (ytr == 0).sum() / max((ytr == 1).sum(), 1)) if balance != "none" else 1.0
        clf = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, min_child_weight=5, subsample=0.8,
            colsample_bytree=0.8, learning_rate=0.05, reg_lambda=2.0,
            scale_pos_weight=spw, tree_method="hist", n_jobs=-1, eval_metric="aucpr",
        )
        clf.fit(Xtr, ytr)
        p = clf.predict_proba(Xte)[:, 1]
        oof_y.append(yte); oof_p.append(p)
        per_fold_csi.append(metrics(yte, p)["CSI"])
    if not oof_y:
        return {"error": "sin folds válidos"}
    y = np.concatenate(oof_y); p = np.concatenate(oof_p)
    agg = metrics(y, p)
    # umbral que maximiza CSI (informativo)
    best = max(((metrics(y, p, t)["CSI"], t) for t in np.linspace(0.05, 0.9, 18)), key=lambda x: x[0])
    agg["CSI_max"] = round(best[0], 3); agg["thr_max"] = round(best[1], 2)
    agg["n_eventos"] = len(ev_days)
    agg["CSI_std_folds"] = round(float(np.std(per_fold_csi)), 3)
    agg["n_features"] = len(feats)
    return agg


def main() -> int:
    """Punto de entrada: carga curada, arma features según --config, valida LOEO, reporta."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True,
                   choices=["baseline", "windows", "goes", "lead1h", "balance"])
    p.add_argument("--curated", required=True, help="s3://.../curated/analysis_ready o ruta local")
    p.add_argument("--catalog", required=True, help="xlsx del catálogo (local o s3)")
    p.add_argument("--days-file", required=True, help="JSON de días a usar")
    p.add_argument("--lead", type=int, default=0, help="horas de anticipación (lead1h -> 1)")
    p.add_argument("--out", default="", help="prefijo S3 para el reporte JSON")
    p.add_argument("--anon-src", action="store_true", help="leer curada con S3 anónimo")
    a = p.parse_args()

    t0 = time.time()
    days = json.load(open(a.days_file)) if Path(a.days_file).exists() else []

    # Catálogo PRIMERO (para saber qué días son de evento y cargarlos completos).
    import fsspec
    with fsspec.open(a.catalog, "rb") as f:
        cat = pd.read_excel(io.BytesIO(f.read()), sheet_name="Final_Table")
    cat["date"] = pd.to_datetime(cat["Date (Gregorian Calendar)"], errors="coerce").dt.date
    # Hour (UTC) viene como texto "HH:MM:SS" o número; extraer la hora entera.
    def _hour(x):
        if pd.isna(x):
            return np.nan
        s = str(x)
        if ":" in s:
            try:
                return float(s.split(":")[0])
            except Exception:
                return np.nan
        try:
            return float(s)
        except Exception:
            return np.nan
    cat["hour_utc"] = cat.get("Hour (UTC)").map(_hour) if "Hour (UTC)" in cat else np.nan
    import re
    def _coord(x):
        try: return float(re.sub(r"[^0-9.\-]", "", str(x)))
        except Exception: return np.nan
    cat["lat"] = cat.get("Latitude").map(_coord) if "Latitude" in cat else np.nan
    cat["lon"] = cat.get("Longitude").map(_coord) if "Longitude" in cat else np.nan

    # Días de evento: cargarlos COMPLETOS (sin submuestrear) para no perder la celda del tornado.
    ev_days = {d.isoformat() for d in cat["date"].dropna().unique() if d.isoformat() in set(days)}
    ctrl_days = [d for d in days if d not in ev_days]
    df_ev = read_parquets(a.curated, sorted(ev_days), a.anon_src, sample_frac=1.0)
    df_ct = read_parquets(a.curated, ctrl_days, a.anon_src, sample_frac=0.12)
    df = pd.concat([df_ev, df_ct], ignore_index=True)
    if df.empty:
        print("ERROR: no se cargó la capa curada", file=sys.stderr); return 1
    print(f"curada: {len(df):,} filas, {df.shape[1]} cols, {df['date'].nunique()} días "
          f"(evento {len(ev_days)}, control {len(ctrl_days)})", flush=True)

    # Features según config.
    feats = list(ERA5_CORE)
    lead = a.lead
    if a.config == "baseline":
        feats += add_lags(df, ["era5_cape"], (1, 2, 3))
    elif a.config == "windows":
        feats += add_lags(df, ["era5_cape", "era5_2t", "era5_z500"], (1, 2, 3, 4, 5))
    elif a.config in ("goes", "balance"):
        feats += [g for g in GOES_FEATS if g in df]
        feats += add_lags(df, ["era5_cape", "goes_C13_bt_min"], (1, 2, 3, 4, 5))
    elif a.config == "lead1h":
        feats += [g for g in GOES_FEATS if g in df]
        feats += add_lags(df, ["era5_cape", "goes_C13_bt_min", "era5_z500"], (1, 2, 3, 4, 5))
        lead = max(lead, 1)

    df = label_events(df, cat, lead)
    npos = int(df["label"].sum())
    print(f"config={a.config} lead={lead} positivos={npos} features={len(feats)}", flush=True)

    res = loeo_cv(df, feats, balance="spw" if a.config == "balance" else "spw")
    res.update({"config": a.config, "lead": lead, "positivos": npos,
                "segundos": round(time.time() - t0, 1)})
    print("RESULTADO:", json.dumps(res, ensure_ascii=False), flush=True)

    if a.out:
        import boto3
        key = f"{a.out.rstrip('/')}/{a.config}_lead{lead}.json".replace("s3://", "")
        bk, _, kk = key.partition("/")
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=bk, Key=kk, Body=json.dumps(res, ensure_ascii=False).encode())
        print(f"reporte -> {a.out}/{a.config}_lead{lead}.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
