#!/usr/bin/env python3
"""Entrena el modelo híbrido de Daniel (ERA5 + embeddings GOES de Bedrock Titan) con etiquetas REALES.

A diferencia de ``scripts/model/demo_hibrido.py`` (etiquetas sintéticas), aquí las positivas salen
del Catálogo (``data/tornados_chile.xlsx``) con ``table.select_cells``. Encadena los componentes que
ya existen en ``scripts/model`` sin cambiar su lógica:

1. ``sync_from_bucket``      — (opcional, ``--bucket``) baja ERA5 de los días que falten.
2. ``extract_goes_features`` — Variables_GOES por día (CLI; se rehace si ``goes_latlon`` es más nuevo).
3. selección de Celdas_Hora  — ``table.select_cells`` (lo mismo que ``build_table --stage select``)
   pero restringida a las horas con barrido GOES en (t - 60 min, t]: la descarga GOES de los días de
   evento solo cubre unas horas alrededor del evento, y muestrear no etiquetadas en horas sin imagen
   haría que «tener embedding» delatara la etiqueta (fuga).
4. ``compose_rgb``           — un PNG por Celda_Hora (receta ``ir_wv`` v1, C08 + C13), en una carpeta
   propia (``data/model/hibrido/work``) para no pisar a otros procesos.
5. ``encode_bedrock``        — embeddings Titan (CLI, caché local compartida). Antes estima las
   llamadas nuevas a Bedrock (las que no están en caché) y aborta si superan ``--max-images``.
6. ``build_table --stage build`` — tabla por día de cada configuración (CLI).
7. ``sm_job/train_entry``    — Validación_LOEO + modelo final, igual que el trabajo de SageMaker.

Artefactos (compatibles con ``sm_job/inference.py`` ``model_fn``)::

    data/model/hibrido/{model.json,feature_columns.json,config.json,reducer.npz}   (embeddings)
    data/model/hibrido/physical/…  data/model/hibrido/baseline_era5/…              (comparación)
    data/model/hibrido/results/<config>/{metrics.json,importance.json,reporte.html,model.json}
    data/model/hibrido/train_summary.json                                         (resumen)

Uso::

    AWS_PROFILE=gpu uv run --no-sync python scripts/app/train_hybrid.py
    uv run --no-sync python scripts/app/train_hybrid.py --days 2019-05-30 --skip-encode   # prueba
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "scripts", ROOT / "scripts" / "model", ROOT / "scripts" / "model" / "sm_job"):
    sys.path.insert(0, str(_p))

import bedrock_encoder as be  # noqa: E402
import build_table as bt  # noqa: E402
import compose_rgb as cr  # noqa: E402
import encode_bedrock as enc  # noqa: E402
import goes_features as gf  # noqa: E402
import loeo  # noqa: E402
import rgb  # noqa: E402
import table as tb  # noqa: E402

import common  # noqa: E402

REGION = "south-central-austral"
OUT = ROOT / "data" / "model" / "hibrido"
WORK = OUT / "work"
MODEL_DATA = ROOT / "data" / "model"
CROPS = ROOT / "data" / "crops"
GOES16_START = dt.date(2017, 12, 1)
CONFIGS = ("baseline_era5", "physical", "embeddings")
SYNC = ROOT / "scripts" / "model" / "sync_from_bucket.py"
USD_PER_IMAGE = 0.00006  # Titan Multimodal Embeddings G1, entrada de imagen
EVENT_PAD_H = 2  # horas candidatas alrededor de cada Evento en días de evento sin GOES
# Parada temprana solo si la validación interna tiene al menos estas positivas; con menos, la
# curva aucpr es tan ruidosa que paraba en la iteración 0 (un árbol, dos valores de salida).
MIN_INNER_POSITIVES = 10
FIXED_TREES = loeo.FALLBACK_TREES  # árboles fijos sin parada temprana (300, el respaldo de loeo)


def _fit_xgb_min_rounds(
    X: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray,
    seed: int,
    xgb_overrides: dict | None = None,
) -> loeo.FitInfo:
    """``loeo.fit_xgb`` sin parada temprana cuando la validación interna tiene pocas positivas.

    Mismos hiperparámetros y ``scale_pos_weight`` que ``loeo.fit_xgb``; solo cambia que, si la
    validación interna tiene menos de ``MIN_INNER_POSITIVES`` positivas, entrena ``FIXED_TREES``
    árboles con todo el entrenamiento de la partición (la rama de respaldo de ``loeo``).
    """
    split = loeo.inner_split(groups, y, seed)
    n_val_pos = int((np.asarray(y)[split[1]] == 1).sum()) if split is not None else 0
    if split is not None and n_val_pos >= MIN_INNER_POSITIVES:
        return _ORIG_FIT_XGB(X, y, groups, seed, xgb_overrides)
    overrides = {**(xgb_overrides or {}), "n_estimators": FIXED_TREES}
    params = {
        **loeo.XGB_PARAMS,
        **overrides,
        "early_stopping_rounds": None,
        "random_state": seed,
        "scale_pos_weight": loeo.scale_pos_weight(y),
    }
    model = xgb.XGBClassifier(**params)
    model.fit(X, np.asarray(y).astype(int), verbose=False)
    return loeo.FitInfo(model, float(params["scale_pos_weight"]), FIXED_TREES - 1, False, None)


_ORIG_FIT_XGB = loeo.fit_xgb
# run_loeo y train_final (que llama sm_job/train_entry) buscan fit_xgb en el módulo loeo.
loeo.fit_xgb = _fit_xgb_min_rounds  # type: ignore[assignment]
# Todos los núcleos para XGBoost (tree_method ya es hist en loeo.XGB_PARAMS).
loeo.XGB_PARAMS["n_jobs"] = -1


class Timer:
    """Tiempo de reloj por etapa (segundos), para ``train_summary.json``."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.stages: dict[str, float] = {}

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.stages[name] = round(now - self.t0, 1)
        print(f"[tiempo] {name}: {self.stages[name]:.1f} s", flush=True)
        self.t0 = now


def _py() -> list[str]:
    """Intérprete del proyecto (el mismo que ejecuta este script)."""
    return [sys.executable]


def _run(cmd: list[str], env: dict[str, str] | None = None, log: Path | None = None) -> int:
    """Ejecuta ``cmd`` en la raíz del repo; con ``log`` guarda la salida ahí."""
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    full_env = {**os.environ, **(env or {})}
    if log is None:
        return subprocess.run(cmd, cwd=ROOT, env=full_env).returncode
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        return subprocess.run(
            cmd, cwd=ROOT, env=full_env, stdout=f, stderr=subprocess.STDOUT
        ).returncode


def _era5_file(day: dt.date) -> Path:
    return CROPS / REGION / "era5_indices" / f"era5_idx_{day:%Y%m%d}.nc"


def _goes_dir(day: dt.date) -> Path:
    return CROPS / REGION / "goes_latlon" / f"{day:%Y%m%d}"


def _has_goes(day: dt.date) -> bool:
    return any(_goes_dir(day).glob("goes_*.nc"))


def catalog_days() -> tuple[set[dt.date], set[dt.date]]:
    """``(días con Evento con hora UTC desde GOES-16, todos los días con algún Evento)``."""
    cat = bt.read_catalog(str(bt.DEFAULT_CATALOG))
    dated = cat[cat["date"].notna()]
    with_hour = {d for d, h in zip(dated["date"], dated["hour_utc"], strict=True) if np.isfinite(h)}
    return {d for d in with_hour if d >= GOES16_START}, set(dated["date"])


def local_days() -> list[dt.date]:
    """Días con índices ERA5 locales."""
    out = []
    for f in sorted((CROPS / REGION / "era5_indices").glob("era5_idx_*.nc")):
        out.append(dt.datetime.strptime(f.stem[-8:], "%Y%m%d").date())
    return out


def read_day_list(path: Path | None) -> list[str]:
    """Días ``AAAA-MM-DD`` de un archivo de texto (uno por línea; ``#`` comenta)."""
    if path is None:
        return []
    lines = (ln.split("#")[0].strip() for ln in path.read_text("utf-8").splitlines())
    return [ln for ln in lines if ln]


def pick_days(a: argparse.Namespace) -> tuple[list[dt.date], list[dt.date]]:
    """Días de evento y días negativos a usar (todos con ERA5 local).

    Días de evento: todos los del Catálogo con hora UTC desde GOES-16, tengan o no GOES (sin
    GOES, sus Variables_GOES y embeddings quedan en NaN, que XGBoost admite). Con
    ``--require-goes`` se exige GOES también a ellos. Negativos: días sin ningún Evento del
    Catálogo (con o sin hora) ni Evento el día anterior; siempre con GOES (si no, «GOES en NaN»
    delataría al día negativo). ``--exclude-days`` saca días por completo (modelo de retención).
    """
    events, any_event = catalog_days()
    have = set(local_days())
    excluded = {dt.date.fromisoformat(d) for d in a.exclude_days}
    if a.days or a.neg_days_file:
        chosen = {dt.date.fromisoformat(d) for d in [*a.days, *read_day_list(a.neg_days_file)]}
        if a.neg_days_file and not a.days:
            chosen |= events  # con solo la lista de negativos: todos los días de evento
        ev = sorted(d for d in chosen if d in events and d in have)
        neg = sorted(d for d in chosen if d not in any_event and d in have)
    else:
        ev = sorted(d for d in events if d in have)
        neg = sorted(
            d
            for d in have
            if d >= GOES16_START
            and d not in any_event
            and d - dt.timedelta(days=1) not in any_event
        )
    if a.require_goes:
        ev = [d for d in ev if _has_goes(d)]
    neg = [d for d in neg if _has_goes(d)]
    ev = [d for d in ev if d not in excluded]
    neg = [d for d in neg if d not in excluded]
    return ev, neg[: a.max_neg_days]


def _bucket_has_bands(bucket: str, day: dt.date) -> bool:
    """True si ``goes_store`` del bucket trae C13 (con o sin sufijo) y C08 para ``day``."""
    import fsspec

    fs = fsspec.filesystem("s3", anon=True)
    base = f"{bucket}/goes_store/{day:%Y-%m-%d}/goes_{day:%Y%m%d}"
    c13 = fs.exists(f"{base}.nc") or fs.exists(f"{base}_C13.nc")
    return c13 and fs.exists(f"{base}_C08.nc")


def sync_bucket(bucket: str, days: list[dt.date], workers: int, goes: bool) -> None:
    """Baja del bucket lo que falte: ERA5 de los días y su día anterior y, con ``goes``, GOES.

    Un proceso ``sync_from_bucket`` por día, ``workers`` a la vez (paralelismo real: cada uno es
    un intérprete aparte). GOES solo se baja si el bucket trae C08 y C13 del día; si no, el día
    queda sin GOES (sus Variables_GOES y embeddings en NaN) en vez de quedar con C13 solo.
    """
    need = sorted(
        {x for d in days for x in (d, d - dt.timedelta(days=1)) if not _era5_file(x).exists()}
    )
    jobs: list[tuple[dt.date, str]] = [(d, "era5") for d in need]
    if goes:
        todo = [d for d in days if not _has_goes(d)]
        with ThreadPoolExecutor(workers) as ex:
            ok = list(ex.map(lambda d: _bucket_has_bands(bucket, d), todo))
        jobs += [(d, "goes") for d, k in zip(todo, ok, strict=True) if k]
        no_bands = [str(d) for d, k in zip(todo, ok, strict=True) if not k]
        if no_bands:
            print(f"[sync] sin C08+C13 en el bucket (GOES en NaN): {no_bands}", flush=True)
    print(f"[sync] faltantes: {sum(k == 'era5' for _, k in jobs)} ERA5, "
          f"{sum(k == 'goes' for _, k in jobs)} GOES", flush=True)  # fmt: skip

    def one(job: tuple[dt.date, str]) -> int:
        d, kind = job
        cmd = [*_py(), str(SYNC), "--bucket", bucket, "--start", d.isoformat(), "--only", kind]
        return _run(cmd, log=WORK / "logs" / f"sync_{kind}_{d:%Y%m%d}.log")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, jobs))


def goes_features(days: list[dt.date], workers: int) -> None:
    """``extract_goes_features`` por día; rehace el parquet si hay GOES más nuevo que él."""
    out_dir = MODEL_DATA / REGION / "goes_features"

    def one(d: dt.date) -> int:
        out = out_dir / f"goes_feat_{d:%Y%m%d}.parquet"
        files = list(_goes_dir(d).glob("goes_*.nc"))
        if not files:
            return 0
        newest = max(f.stat().st_mtime for f in files)
        if out.exists() and out.stat().st_mtime >= newest:
            return 0
        cmd = [
            *_py(),
            "scripts/model/extract_goes_features.py",
            "--start",
            d.isoformat(),
            "--force",
        ]
        return _run(cmd, log=WORK / "logs" / f"goes_feat_{d:%Y%m%d}.log")

    # Día anterior incluido: aporta los rezagos de las primeras horas si tiene GOES.
    todo = sorted({x for d in days for x in (d, d - dt.timedelta(days=1))})
    with ThreadPoolExecutor(workers) as ex:
        codes = list(ex.map(one, todo))
    print(f"[goes] Variables_GOES listas ({sum(c != 0 for c in codes)} fallos)", flush=True)


def goes_times(days: list[dt.date]) -> set[pd.Timestamp]:
    """Horas ERA5 ``t`` de ``days`` con algún barrido GOES que empiece en (t - 60 min, t]."""
    scans: list[dt.datetime] = []
    for d in sorted({x for day in days for x in (day, day - dt.timedelta(days=1))}):
        for f in sorted(_goes_dir(d).glob("goes_*.nc")):
            with xr.open_dataset(f, engine="h5netcdf", decode_cf=True) as ds:
                scans += [ts.to_pydatetime() for ts in pd.to_datetime(ds["time"].values)]
    out: set[pd.Timestamp] = set()
    for d in days:
        for h in range(24):
            t = dt.datetime.combine(d, dt.time(h))
            if gf.select_scan(scans, t) is not None:
                out.add(pd.Timestamp(t, tz="UTC"))
    return out


def event_times(catalog: pd.DataFrame) -> dict[dt.date, set[pd.Timestamp]]:
    """Horas ERA5 (redondeadas como en ``table.label_positives``) de los Eventos con hora, por día."""
    out: dict[dt.date, set[pd.Timestamp]] = {}
    for d, h in zip(catalog["date"], catalog["hour_utc"], strict=True):
        if d is not None and not pd.isna(d) and np.isfinite(h):
            out.setdefault(d, set()).add(tb.round_hour(d, float(h)))
    return out


def candidate_times(
    days: list[dt.date], era5_times: list[pd.Timestamp], catalog: pd.DataFrame, require_goes: bool
) -> tuple[list[pd.Timestamp], dict[str, int]]:
    """Horas candidatas por día (positivas y no etiquetadas salen de las mismas horas).

    - Día de evento con GOES: horas con barrido GOES en (t - 60 min, t] más las horas de sus
      Eventos (si un Evento cae en una hora sin barrido, su fila queda con GOES en NaN, igual que
      las no etiquetadas de esa hora).
    - Día de evento sin GOES: horas de sus Eventos ± ``EVENT_PAD_H`` (todo GOES/embedding en NaN).
    - Día negativo: horas con barrido GOES cuya hora del día está a ± ``EVENT_PAD_H`` de la hora
      de algún Evento, para que el ciclo diurno de positivas y no etiquetadas sea comparable.

    Con ``require_goes`` (comportamiento anterior) solo se usan las horas con barrido GOES.
    """
    available = set(era5_times)
    ok = goes_times(days)
    ev_t = event_times(catalog)
    if require_goes:
        times = sorted(t for t in available if t in ok)
        return times, {"horas": len(times)}
    hours_of_day = {
        (t + pd.Timedelta(hours=k)).hour
        for d in days
        if d in ev_t
        for t in ev_t[d]
        for k in range(-EVENT_PAD_H, EVENT_PAD_H + 1)
    }
    by_day: dict[dt.date, set[pd.Timestamp]] = {}
    for d in days:
        if d not in ev_t:
            continue
        if _has_goes(d):
            # GOES del bucket cubre el día entero: mismas horas del día que los negativos.
            by_day[d] = {t for t in ok if t.date() == d and t.hour in hours_of_day} | ev_t[d]
        else:
            by_day[d] = {
                t + pd.Timedelta(hours=k)
                for t in ev_t[d]
                for k in range(-EVENT_PAD_H, EVENT_PAD_H + 1)
            }
    for d in days:
        if d not in ev_t:
            by_day[d] = {t for t in ok if t.date() == d and t.hour in hours_of_day}
    times = sorted({t for ts in by_day.values() for t in ts if t in available})
    n_ev = sum(1 for t in times if t.date() in ev_t)
    stats = {
        "horas": len(times),
        "horas_dias_evento": n_ev,
        "horas_dias_negativos": len(times) - n_ev,
    }
    stats["horas_del_dia"] = sorted(hours_of_day)  # type: ignore[assignment]
    return times, stats


def select(days: list[dt.date], ratio: int, seed: int, require_goes: bool) -> pd.DataFrame:
    """Celdas_Hora con etiquetas reales (``table.select_cells``), escritas en ``work/cells.parquet``."""
    era5 = bt.read_era5(CROPS, REGION, days)
    catalog = bt.read_catalog(str(bt.DEFAULT_CATALOG))
    catalog = catalog[catalog["date"].isin(days) | catalog["date"].isna()]
    times, stats = candidate_times(days, sorted(set(era5["time"])), catalog, require_goes)
    print(f"[select] {len(times)} horas candidatas en {len(days)} días: {stats}", flush=True)
    (WORK / "candidate_hours.json").write_text(json.dumps(stats, indent=2), "utf-8")
    lat = era5["latitude"].drop_duplicates().to_numpy()
    lon = era5["longitude"].drop_duplicates().to_numpy()
    cells, skipped = tb.select_cells(catalog, times, lat, lon, common.REGIONS[REGION], ratio, seed)
    bt.write_parquet(cells, WORK / "cells.parquet")
    bt.write_parquet(skipped, WORK / "skipped_events.parquet")
    n_pos = int((cells["label"] == 1).sum())
    print(f"[select] {n_pos} positivas, {len(cells) - n_pos} no etiquetadas", flush=True)
    bt.report(skipped)
    return cells


def compose(cells: pd.DataFrame, recipe_name: str, size: int, window_km: float) -> Path:
    """PNG por Celda_Hora con ``compose_rgb.compose_cells`` en ``work/``; devuelve el manifiesto."""
    recipe = rgb.validate_recipe(recipe_name, 1)
    c = cells.loc[:, list(cr.CELL_COLUMNS)].copy()
    c["time"] = tb.utc(c["time"])
    cr.compose_cells(c, REGION, recipe, size, window_km, CROPS, WORK, force=False)
    return WORK / REGION / "rgb" / recipe.tag / "manifest.parquet"


def estimate_calls(manifest: Path, model: str) -> tuple[int, int]:
    """``(imágenes del manifiesto, llamadas nuevas a Bedrock)`` según la caché local."""
    man = pd.read_parquet(manifest)
    spec = be.MODELS[model]
    cache = be.LocalCache(MODEL_DATA / "embeddings" / "cache")
    new = 0
    for rel, rec, ver in zip(man["png_path"], man["recipe"], man["recipe_version"], strict=True):
        png = (manifest.parent / rel).read_bytes()
        key = be.cache_key(png, spec.model_id, spec.default_dim, f"{rec}_v{int(ver)}")
        new += not cache.path(key).exists()
    return len(man), new


def encode(manifest: Path, days: list[dt.date], a: argparse.Namespace) -> Path:
    """``encode_bedrock`` (CLI) con caché local; copia la salida a ``work/embeddings.parquet``."""
    total, new = estimate_calls(manifest, a.model)
    print(
        f"[encode] {total} imágenes, {new} llamadas nuevas a Bedrock "
        f"(~{new * USD_PER_IMAGE:.4f} USD); tope {a.max_images}",
        flush=True,
    )
    if new > a.max_images:
        raise SystemExit(f"error: {new} llamadas superan el tope --max-images {a.max_images}")
    # Lo mismo que la CLI encode_bedrock (misma caché, receta y modelo), pero con
    # ``--bedrock-workers`` hilos (infer_grid.encode_parallel); los reintentos con espera
    # creciente los hace BedrockEncoder.
    import infer_grid

    os.environ["AWS_PROFILE"] = a.profile
    spec = be.MODELS[a.model]
    items, _ = enc.read_items(manifest, days)
    runtime, control = be.make_clients(a.ml_region)
    encoder = be.BedrockEncoder(
        runtime, control, spec, spec.default_dim, be.LocalCache(MODEL_DATA / "embeddings" / "cache")
    )
    encoder.preflight(a.ml_region)
    summary = infer_grid.encode_parallel(encoder, items, a.bedrock_workers)
    if summary.failed:
        print(f"  aviso: {summary.failed} imágenes fallidas (sus filas quedan en NaN)", flush=True)
    dst = WORK / "embeddings.parquet"
    enc.embeddings_frame(summary, spec.model_id, spec.default_dim).to_parquet(dst, index=False)
    report = summary.to_json(spec.model_id, spec.default_dim)
    (WORK / "embeddings_run_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), "utf-8"
    )
    return dst


def build_tables(config: str, days: list[dt.date], emb: Path | None, workers: int) -> pd.DataFrame:
    """``build_table --stage build`` por día y concatena las tablas de ``days``."""

    def one(d: dt.date) -> int:
        cmd = [
            *_py(), "scripts/model/build_table.py", "--stage", "build", "--config", config,
            "--cells", str(WORK / "cells.parquet"), "--start", d.isoformat(), "--region", REGION,
            "--force",
        ]  # fmt: skip
        if config == "embeddings" and emb is not None:
            cmd += ["--embeddings", str(emb)]
        return _run(cmd, log=WORK / "logs" / f"build_{config}_{d:%Y%m%d}.log")

    with ThreadPoolExecutor(workers) as ex:
        codes = list(ex.map(one, days))
    if any(codes):
        raise SystemExit(
            f"error: build_table falló en {sum(c != 0 for c in codes)} días ({config})"
        )
    base = MODEL_DATA / REGION / "tables" / f"config={config}"
    parts = [pd.read_parquet(base / f"date={d:%Y-%m-%d}" / "part-0.parquet") for d in days]
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)
    df["time"] = tb.utc(df["time"])
    return df.sort_values(tb.POINT, kind="mergesort").reset_index(drop=True)


def train(config: str, df: pd.DataFrame, folds_json: dict, a: argparse.Namespace) -> dict:
    """Corre ``sm_job/train_entry.main`` con canales locales; devuelve sus métricas."""
    from sm_job import train_entry

    stage = WORK / "channels" / config
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "train").mkdir(parents=True)
    (stage / "folds").mkdir(parents=True)
    df.to_parquet(stage / "train" / "part-0.parquet", index=False)
    (stage / "folds" / "folds.json").write_text(json.dumps(folds_json, indent=2), "utf-8")
    model_dir = OUT if config == "embeddings" else OUT / config
    model_dir.mkdir(parents=True, exist_ok=True)
    if config == "embeddings":
        (model_dir / "reducer.npz").unlink(missing_ok=True)
    argv = ["--config", config, "--seed", str(a.seed), "--n-components", str(a.n_components)]
    argv += ["--model-id", be.MODELS[a.model].model_id]
    train_entry.main(argv, input_dir=stage, model_dir=model_dir, results_uri=str(OUT / "results"))
    return json.loads((OUT / "results" / config / "metrics.json").read_text("utf-8"))


def verify(config: str, df: pd.DataFrame) -> dict:
    """Carga los artefactos con ``inference.model_fn`` y predice toda la tabla.

    Devuelve 5 probabilidades de muestra (positivas primero) y cuántos valores distintos da el
    modelo final sobre las filas de la tabla: con 1 árbol (la degeneración anterior) eran 2.
    """
    from sm_job import inference

    model_dir = OUT if config == "embeddings" else OUT / config
    bundle = inference.model_fn(str(model_dir))
    rows = pd.concat([df[df["label"] == 1].head(3), df[df["label"] == 0].head(2)])
    sample = inference.predict_fn(rows, bundle)["probability"]
    p_all = inference.predict_fn(df, bundle)["probability"].to_numpy()
    return {
        "sample_probs": [round(float(p), 4) for p in sample],
        "distinct_values_table": int(np.unique(np.round(p_all, 6)).size),
        "min": round(float(p_all.min()), 4),
        "max": round(float(p_all.max()), 4),
    }


def oof_summary(m: dict, n_test_unlabeled: dict[str, int]) -> dict:
    """Métricas fuera de partición por Evento a partir de ``metrics.json``."""
    per = [
        {
            "event_id": f["held"],
            "dev": f["dev"],
            "detectado": f["hits"] > 0,
            "falsas_alarmas": f["false_alarms"],
            "no_etiquetadas_en_prueba": n_test_unlabeled.get(f["held"], 0),
            "best_iteration": f["best_iteration"],
            "early_stopping": f["early_stopping"],
        }
        for f in m["per_fold"]
        if not f["skipped"]
    ]
    return {"per_event": per}


def bias_check(df: pd.DataFrame, event_days: set[dt.date]) -> dict:
    """Comprobación de sesgo de fuente GOES sobre la tabla ``physical``.

    - Media, desviación y fracción NaN de cada Variable_GOES (hora t) en tres grupos: positivas,
      no etiquetadas de días de evento y filas de días negativos.
    - AUC (validación cruzada agrupada por día) de un XGBoost pequeño que, solo con Variables_GOES
      y solo con filas no etiquetadas, distingue «día de evento» de «día negativo». Con una sola
      fuente debería quedar en la señal meteorológica (días de evento más tormentosos); un AUC
      cercano a 1 haría sospechar de la fuente.
    """
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    cols = [c for c in tb.GOES_FEATURES if c in df.columns]
    day = tb.utc(df["time"]).dt.date
    is_ev = day.isin(event_days).to_numpy()
    lab = df["label"].to_numpy() == 1
    groups = {
        "positivas": lab,
        "no_etiquetadas_dias_evento": ~lab & is_ev,
        "dias_negativos": ~lab & ~is_ev,
    }
    stats = {
        g: {
            "n": int(m.sum()),
            **{
                c: {
                    "mean": round(float(df.loc[m, c].mean()), 3),
                    "std": round(float(df.loc[m, c].std()), 3),
                    "nan": round(float(df.loc[m, c].isna().mean()), 3),
                }
                for c in cols
            },
        }
        for g, m in groups.items()
    }
    unl = ~lab
    X = df.loc[unl, cols].to_numpy(dtype=float)
    y = is_ev[unl].astype(int)
    g = day[unl].astype(str).to_numpy()
    oof = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=5).split(X, y, g):
        m = xgb.XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, n_jobs=-1,
                              tree_method="hist")  # fmt: skip
        m.fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
    return {
        "stats": stats,
        "auc_dia_evento_vs_negativo_goes_only": round(float(roc_auc_score(y, oof)), 3),
    }


def column_counts(df: pd.DataFrame, config: str) -> dict[str, int]:
    """Columnas de variables por tipo en la tabla de ``config``."""
    n_emb = sum(str(c).startswith("emb_") for c in df.columns)
    feats = tb.config_columns(config, n_emb)
    era5 = [c for c in feats if c.split("_lag")[0].split("_d")[0] in tb.ERA5_FEATURES]
    goes = [c for c in feats if c.startswith("goes_")]
    return {"total": len(feats), "era5": len(era5), "goes_fisicas": len(goes), "emb": n_emb}


def main() -> None:
    """Punto de entrada del orquestador."""
    global OUT, WORK
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--days", nargs="*", default=[],
                   help="días AAAA-MM-DD a usar (por defecto: todos los disponibles)")  # fmt: skip
    p.add_argument("--neg-days-file", type=Path,
                   help="archivo con días negativos (uno por línea); se suman todos los de evento")  # fmt: skip
    p.add_argument("--exclude-days", nargs="*", default=[],
                   help="días AAAA-MM-DD que se sacan por completo (modelo de retención)")  # fmt: skip
    p.add_argument(
        "--out", type=Path, default=OUT, help=f"carpeta de artefactos (por defecto {OUT})"
    )
    p.add_argument("--bucket", help="si se da, baja del bucket (anónimo) los ERA5 que falten")
    p.add_argument(
        "--ratio", type=int, default=20, help="no etiquetadas por positiva (por defecto 20)"
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-neg-days", type=int, default=15, help="tope de días negativos")
    p.add_argument("--require-goes", action="store_true",
                   help="exigir GOES también a los días de evento (comportamiento anterior)")  # fmt: skip
    p.add_argument("--recipe", default="ir_wv", help="receta RGB (ir_wv necesita C08 y C13)")
    p.add_argument("--size", type=int, default=224)
    p.add_argument("--window-km", type=float, default=100.0)
    p.add_argument("--model", default="titan", choices=sorted(be.MODELS))
    p.add_argument("--ml-region", default="us-east-1", help="región de Bedrock")
    p.add_argument("--profile", default="gpu", help="perfil AWS para Bedrock")
    p.add_argument(
        "--max-images", type=int, default=20000, help="tope de llamadas nuevas a Bedrock"
    )
    p.add_argument("--n-components", type=int, default=8, help="componentes PCA (8-16)")
    p.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=CONFIGS)
    p.add_argument(
        "--skip-encode", action="store_true", help="no llamar a Bedrock (sin embeddings)"
    )
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--sync-goes", action="store_true",
                   help="con --bucket, baja también GOES (C08 + C13) de los días que no lo tengan")  # fmt: skip
    p.add_argument("--bedrock-workers", type=int, default=8, help="hilos de llamadas a Bedrock")
    p.add_argument("--version", default="", help="etiqueta del modelo (p. ej. v2) para el sitio")
    a = p.parse_args()
    OUT = a.out.resolve()
    WORK = OUT / "work"
    timer = Timer()

    configs = [c for c in a.configs if not (a.skip_encode and c == "embeddings")]
    WORK.mkdir(parents=True, exist_ok=True)
    if a.bucket:
        events, _ = catalog_days()
        wanted = {dt.date.fromisoformat(d) for d in [*a.days, *read_day_list(a.neg_days_file)]}
        if not a.days:
            wanted |= events
        wanted -= {dt.date.fromisoformat(d) for d in a.exclude_days}
        sync_bucket(a.bucket, sorted(wanted), a.workers, a.sync_goes)
    timer.lap("sync")
    ev, neg = pick_days(a)
    days = sorted(ev + neg)
    print(f"Días: {len(days)} ({len(ev)} con evento, {len(neg)} negativos)", flush=True)
    print(f"  eventos: {[str(d) for d in ev]}\n  negativos: {[str(d) for d in neg]}", flush=True)
    if not ev:
        raise SystemExit("error: no hay días de evento con ERA5 locales")

    if "baseline_era5" not in configs or len(configs) > 1:
        goes_features(days, a.workers)
    timer.lap("goes_features")
    cells = select(days, a.ratio, a.seed, a.require_goes)
    timer.lap("select")

    summary: dict = {
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "event_days": [str(d) for d in ev],
        "negative_days": [str(d) for d in neg],
        "cells": {"rows": len(cells), "positives": int((cells["label"] == 1).sum())},
        "args": dict(vars(a)),
    }
    emb = None
    if "embeddings" in configs:
        manifest = compose(cells, a.recipe, a.size, a.window_km)
        skipped = pd.read_parquet(manifest.parent / "skipped.parquet")
        summary["rgb"] = {"images": len(pd.read_parquet(manifest)), "skipped": len(skipped)}
        timer.lap("compose_rgb")
        emb = encode(manifest, days, a)
        summary["bedrock"] = json.loads((WORK / "embeddings_run_summary.json").read_text())
        summary["bedrock"].pop("failures", None)
        timer.lap("bedrock")

    cell_days = sorted(set(tb.utc(cells["time"]).dt.date))
    summary["cells"]["days_with_cells"] = len(cell_days)
    tables = {c: build_tables(c, cell_days, emb, a.workers) for c in configs}
    timer.lap("build_tables")
    # Mismas particiones para todas las configuraciones (dependen solo de label/event_id/fold_group).
    folds = loeo.compute_folds(next(iter(tables.values())))
    folds_json = loeo.folds_to_json(folds, a.seed)
    (OUT / "folds.json").write_text(json.dumps(folds_json, indent=2), "utf-8")

    t0 = next(iter(tables.values()))
    g = t0[t0["label"] == 0].groupby("fold_group").size()
    n_test_unl = {f.held: int(g.get(f.held, 0)) for f in folds}
    summary["configs"] = {}
    for c in configs:
        df = tables[c]
        m = train(c, df, folds_json, a)
        imp = json.loads((OUT / "results" / c / "importance.json").read_text("utf-8"))
        summary["configs"][c] = {
            "rows": len(df),
            "positives": int((df["label"] == 1).sum()),
            "columns": column_counts(df, c),
            "emb_rows_valid": int(df.filter(like="emb_").notna().all(axis=1).sum())
            if c == "embeddings"
            else None,
            "selection": m["selection"],
            "development_case": m["development_case"],
            "informative": m["informative"],
            "n_folds": len(m["per_fold"]),
            "n_folds_skipped": m["n_folds_skipped"],
            "top15_importance": dict(list(imp.items())[:15]),
            "verify": verify(c, df),
            "final_model": json.loads(
                ((OUT if c == "embeddings" else OUT / c) / "config.json").read_text("utf-8")
            ),
            **oof_summary(m, n_test_unl),
        }
        summary["configs"][c]["final_model"].pop("xgb_params", None)
        sel = m["selection"]
        print(f"== {c}: POD={sel['pod']:.3f} FAR={sel['far']:.3f} CSI={sel['csi']:.3f}", flush=True)
    # Unlabeled en prueba por partición (para comprobar que FAR no es trivialmente 0).
    summary["unlabeled_in_test_per_fold"] = n_test_unl
    if "physical" in tables:
        summary["source_bias_check"] = bias_check(tables["physical"], set(ev))
    timer.lap("train")
    summary["timings_s"] = timer.stages
    summary["version"] = a.version
    (OUT / "train_summary.json").write_text(json.dumps(summary, indent=2, default=str), "utf-8")
    print(f"Resumen en {OUT / 'train_summary.json'}", flush=True)


if __name__ == "__main__":
    main()
