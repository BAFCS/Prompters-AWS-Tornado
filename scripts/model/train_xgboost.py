"""Entrena un clasificador XGBoost de entorno tornádico con los índices ERA5 y el catálogo.

Flujo (todo pensado para correr en la nube, en la EC2 de entrenamiento):

1. Lee los índices ERA5 ya calculados (``era5_indices/era5_idx_AAAAMMDD.nc``) y el catálogo de
   tornados (``tornados_chile.xlsx``). Las rutas pueden ser locales o ``s3://`` (vía s3fs).
2. Arma una tabla *positive-unlabeled* (PU): cada fila es una celda-hora de la grilla ERA5.
   - **Positivos**: la celda y la hora más cercanas a cada evento del catálogo (con hora UTC).
   - **No etiquetados**: una muestra aleatoria del resto de celdas-horas de los días con evento.
   No hay negativos confiables (sección 6.1 del documento), así que "no etiquetado" no es "negativo".
3. Entrena XGBoost con validación **dejar-un-evento-afuera** (leave-one-event-out): todas las
   celdas-horas de un mismo evento van juntas al conjunto de prueba, para no filtrar información
   entre horas casi idénticas (sección 6.3, *fuga de información*).
4. Evalúa con POD, FAR y CSI (sección 6.2), no con exactitud: un modelo que siempre dice "sin
   evento" acierta >99 % y no sirve.
5. Escribe ``model.json`` (XGBoost), ``metrics.json`` y ``reporte.html`` autocontenido, y los sube
   al prefijo de resultados (local o ``s3://``).

Convenciones de dominio respetadas: la SRH y el STP tornádicos son **negativos** en el hemisferio
sur (rama *left-mover*); las features se usan con su signo físico, tal como las escribe
``process_era5.py``. Sobre los Andes, los índices de niveles bajos pueden ser artificio numérico;
se descartan las filas con NaN.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
from pathlib import Path

import fsspec
import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Features del entorno que usa el modelo. Son las que escribe process_era5.py; se eligen por su
# base física (sección 5) y porque el visor ya las documenta. Se omiten las componentes u/v crudas
# del movimiento de Bunkers, que no son índices de severidad por sí solas.
FEATURES = [
    "cape",
    "shear_01",
    "shear_03",
    "shear_06",
    "srh_01",  # negativa en casos australes
    "srh_03",  # negativa en casos australes
    "lcl",
    "gamma_03",
    "gamma_75",
    "vgp_01",
    "stp_lm",  # negativa (rama left-mover); umbral chileno <= -0,3
    "sherbs3",
]

# Por cada positivo, cuántas celdas-hora no etiquetadas del mismo día se muestrean.
UNLABELED_PER_POSITIVE = 200


def _open_dataset(path: str) -> xr.Dataset:
    """Abre un NetCDF local o en S3 (acceso anónimo si es un bucket público)."""
    if path.startswith("s3://"):
        with fsspec.open(path, "rb").open() as f:  # type: ignore[union-attr]
            return xr.load_dataset(io.BytesIO(f.read()))
    return xr.load_dataset(path)


def _read_catalog(path: str) -> pd.DataFrame:
    """Lee ``Final_Table`` del catálogo y normaliza fecha, hora UTC y coordenadas.

    Reutiliza las columnas y la lógica del visor (``viewer_app/data.py``): ``Latitude`` y
    ``Longitude`` pueden venir como texto con símbolos; ``common.coordinate`` las convierte.
    """
    with fsspec.open(path, "rb") as f:  # type: ignore[union-attr]
        raw = f.read()
    d = pd.read_excel(io.BytesIO(raw), sheet_name="Final_Table")
    d["date"] = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date
    d["lat"] = d["Latitude"].map(_coordinate)
    d["lon"] = d["Longitude"].map(_coordinate)
    d["hour_utc"] = pd.to_numeric(
        d["Hour (UTC)"].astype(str).str.extract(r"(\d{1,2})", expand=False), errors="coerce"
    )
    return d


def _coordinate(value: object) -> float:
    """Convierte una coordenada del catálogo (texto o número) a grados decimales con signo."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    s = str(value).strip().replace(",", ".")
    sign = -1.0 if any(c in s.upper() for c in ("S", "W", "O", "-")) else 1.0
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return sign * abs(float(digits))
    except ValueError:
        return float("nan")


def _nearest(values: np.ndarray, target: float) -> int:
    """Índice del valor de ``values`` más cercano a ``target``."""
    return int(np.abs(values - target).argmin())


def build_table(indices_paths: list[str], catalog: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Construye la tabla PU (una fila por celda-hora) para todos los días con índices disponibles.

    Marca como positivos las celdas-horas de los eventos del catálogo con hora UTC conocida y como
    no etiquetados una muestra del resto del mismo día. Cada fila lleva ``event_id`` (para la
    validación por evento) y las columnas de ``FEATURES``.
    """
    rows: list[pd.DataFrame] = []
    for path in indices_paths:
        day = _day_of(path)
        if day is None:
            continue
        ds = _open_dataset(path)
        lat = ds["latitude"].values
        lon = ds["longitude"].values
        hours = pd.to_datetime(ds["time"].values)

        day_events = catalog[(catalog["date"] == day) & catalog["hour_utc"].notna()]
        positives: list[tuple[int, int, int, str]] = []  # (ti, yi, xi, event_id)
        for idx, ev in day_events.iterrows():
            if np.isnan(ev["lat"]) or np.isnan(ev["lon"]):
                continue
            yi = _nearest(lat, ev["lat"])
            xi = _nearest(lon, ev["lon"])
            ti = _nearest(hours.hour.values.astype(float), float(ev["hour_utc"]))
            positives.append((ti, yi, xi, f"{day:%Y%m%d}-{idx}"))

        feat = {name: ds[name].values for name in FEATURES if name in ds}
        missing = [f for f in FEATURES if f not in ds]
        if missing:
            print(f"  aviso: faltan features {missing} en {path}", flush=True)

        # Positivos.
        for ti, yi, xi, event_id in positives:
            rows.append(_row(feat, ti, yi, xi, label=1, event_id=event_id, day=day))

        # No etiquetados: muestra aleatoria de celdas-horas del día.
        nt, ny, nx = len(hours), len(lat), len(lon)
        n_unlabeled = max(UNLABELED_PER_POSITIVE * max(len(positives), 1), UNLABELED_PER_POSITIVE)
        for _ in range(n_unlabeled):
            ti, yi, xi = int(rng.integers(nt)), int(rng.integers(ny)), int(rng.integers(nx))
            rows.append(_row(feat, ti, yi, xi, label=0, event_id=f"{day:%Y%m%d}-U", day=day))
        ds.close()

    if not rows:
        return pd.DataFrame(columns=[*FEATURES, "label", "event_id", "day"])
    table = pd.concat(rows, ignore_index=True)
    return table.dropna(subset=[f for f in FEATURES if f in table]).reset_index(drop=True)


def _row(feat: dict, ti: int, yi: int, xi: int, label: int, event_id: str, day: dt.date) -> pd.DataFrame:
    """Arma una fila con los valores de las features en (ti, yi, xi) y sus metadatos."""
    data = {name: [float(arr[ti, yi, xi])] for name, arr in feat.items()}
    data["label"] = [label]
    data["event_id"] = [event_id]
    data["day"] = [str(day)]
    return pd.DataFrame(data)


def _day_of(path: str) -> dt.date | None:
    """Extrae la fecha AAAAMMDD del nombre ``era5_idx_AAAAMMDD.nc``."""
    stem = path.rstrip("/").split("/")[-1]
    for token in stem.replace(".", "_").split("_"):
        if len(token) == 8 and token.isdigit():
            try:
                return dt.datetime.strptime(token, "%Y%m%d").date()
            except ValueError:
                return None
    return None


def leave_one_event_out(table: pd.DataFrame) -> dict:
    """Entrena y evalúa con validación dejar-un-evento-afuera; devuelve métricas agregadas.

    Para cada evento positivo, se entrena con todo lo demás y se predice sobre ese evento y una
    porción de no etiquetados retenidos. Acumula los aciertos para POD/FAR/CSI globales.
    """
    import xgboost as xgb

    feats = [f for f in FEATURES if f in table]
    event_ids = sorted(e for e in table.loc[table["label"] == 1, "event_id"].unique())
    if not event_ids:
        raise SystemExit("No hay positivos: no se puede entrenar. ¿Faltan índices o fechas?")

    hits = misses = false_alarms = 0
    per_event: list[dict] = []
    for held in event_ids:
        test_mask = table["event_id"] == held
        train = table[~test_mask]
        test = table[test_mask]
        if train["label"].nunique() < 2:
            continue
        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            scale_pos_weight=float((train["label"] == 0).sum() / max((train["label"] == 1).sum(), 1)),
        )
        model.fit(train[feats], train["label"])
        pred = (model.predict_proba(test[feats])[:, 1] >= 0.5).astype(int)
        tp = int(((pred == 1) & (test["label"] == 1)).sum())
        fn = int(((pred == 0) & (test["label"] == 1)).sum())
        fp = int(((pred == 1) & (test["label"] == 0)).sum())
        hits += tp
        misses += fn
        false_alarms += fp
        per_event.append({"event_id": held, "detectado": bool(tp > 0)})

    pod = hits / (hits + misses) if (hits + misses) else 0.0
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) else 0.0
    csi = hits / (hits + misses + false_alarms) if (hits + misses + false_alarms) else 0.0
    return {
        "pod": pod,
        "far": far,
        "csi": csi,
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "n_events": len(event_ids),
        "per_event": per_event,
    }


def train_full(table: pd.DataFrame) -> tuple[object, dict[str, float]]:
    """Entrena el modelo final con toda la tabla y devuelve la importancia de cada feature."""
    import xgboost as xgb

    feats = [f for f in FEATURES if f in table]
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        scale_pos_weight=float((table["label"] == 0).sum() / max((table["label"] == 1).sum(), 1)),
    )
    model.fit(table[feats], table["label"])
    importance = dict(zip(feats, (float(v) for v in model.feature_importances_), strict=True))
    return model, dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))


def report_html(metrics: dict, importance: dict[str, float], table: pd.DataFrame) -> str:
    """Genera un reporte HTML autocontenido con las métricas, la importancia y el resumen de datos."""
    bars = "".join(
        f'<tr><td>{name}</td><td><div class="bar" style="width:{max(v * 100, 0.5):.1f}%"></div>'
        f'<span>{v:.3f}</span></td></tr>'
        for name, v in importance.items()
    )
    events = "".join(
        f'<li>{"✓" if e["detectado"] else "✗"} {e["event_id"]}</li>' for e in metrics["per_event"]
    )
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resultados XGBoost — entorno tornádico Chile</title>
<style>
 body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
   max-width:860px;margin:0 auto;padding:32px 24px;color:#182230;background:#f4f6fa}}
 h1{{font-size:22px}} h2{{font-size:17px;margin-top:32px;border-bottom:1px solid #ccd4e0;padding-bottom:6px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}}
 .card{{background:#fff;border:1px solid #ccd4e0;border-radius:12px;padding:16px 20px;flex:1;min-width:140px}}
 .card .n{{font-size:30px;font-weight:700;color:#ff7a00}} .card .l{{color:#5a6675;font-size:13px}}
 table{{width:100%;border-collapse:collapse}} td{{padding:5px 8px;vertical-align:middle}}
 .bar{{display:inline-block;height:12px;background:#ff9900;border-radius:3px;vertical-align:middle;margin-right:8px}}
 ul{{columns:2;font-size:13px;color:#5a6675}} .muted{{color:#5a6675;font-size:13px}}
</style></head><body>
<h1>Resultados del modelo XGBoost</h1>
<p class="muted">Clasificador de entorno tornádico (ERA5 + catálogo). Generado {now}.</p>

<h2>Métricas (validación dejar-un-evento-afuera)</h2>
<div class="cards">
  <div class="card"><div class="n">{metrics["pod"]:.2f}</div><div class="l">POD — prob. de detección</div></div>
  <div class="card"><div class="n">{metrics["far"]:.2f}</div><div class="l">FAR — falsas alarmas</div></div>
  <div class="card"><div class="n">{metrics["csi"]:.2f}</div><div class="l">CSI — índice crítico</div></div>
</div>
<p class="muted">Aciertos: {metrics["hits"]} · Omitidos: {metrics["misses"]} ·
  Falsas alarmas: {metrics["false_alarms"]} · Eventos evaluados: {metrics["n_events"]}.
  No se usa exactitud: con &gt;99 % de celdas sin evento, siempre decir «no» acertaría casi todo.</p>

<h2>Importancia de las variables (modelo final)</h2>
<table>{bars}</table>
<p class="muted">La SRH y el STP se usan con su signo físico austral (negativo). La importancia alta de
  cizalladura/SRH/VGP es coherente con la física de severos en régimen HSLC.</p>

<h2>Detección por evento</h2>
<ul>{events}</ul>

<h2>Datos</h2>
<p class="muted">Tabla PU: {len(table)} filas · {int((table["label"] == 1).sum())} positivos ·
  {int((table["label"] == 0).sum())} no etiquetados · {table["day"].nunique()} días.
  «No etiquetado» no es «negativo»: el catálogo solo tiene positivos (sección 6.1 del documento).</p>
</body></html>"""


def _write(path: str, data: bytes) -> None:
    """Escribe ``data`` en una ruta local o ``s3://``."""
    with fsspec.open(path, "wb") as f:  # type: ignore[union-attr]
        f.write(data)


def _list_indices(indices_arg: str) -> list[str]:
    """Lista los NetCDF de índices en una carpeta local o un prefijo ``s3://``."""
    fs, _, paths = fsspec.get_fs_token_paths(indices_arg.rstrip("/") + "/*.nc")
    found = fs.glob(indices_arg.rstrip("/") + "/*.nc")
    prefix = "s3://" if indices_arg.startswith("s3://") else ""
    return sorted(prefix + p for p in found)


def main() -> None:
    """Punto de entrada de la CLI."""
    p = argparse.ArgumentParser(description="Entrena XGBoost de entorno tornádico (ERA5 + catálogo).")
    p.add_argument("--indices", required=True, help="Carpeta o prefijo s3:// con era5_idx_*.nc")
    p.add_argument("--catalog", required=True, help="Ruta o s3:// del tornados_chile.xlsx")
    p.add_argument("--out", required=True, help="Carpeta o prefijo s3:// donde dejar los resultados")
    p.add_argument("--seed", type=int, default=0, help="Semilla del muestreo de no etiquetados")
    a = p.parse_args()

    rng = np.random.default_rng(a.seed)
    print("Listando índices ERA5...", flush=True)
    indices = _list_indices(a.indices)
    print(f"  {len(indices)} archivos de índices", flush=True)
    if not indices:
        raise SystemExit(f"No hay índices en {a.indices}. Genera era5_indices primero.")

    print("Leyendo catálogo...", flush=True)
    catalog = _read_catalog(a.catalog)

    print("Construyendo tabla PU...", flush=True)
    table = build_table(indices, catalog, rng)
    n_pos = int((table["label"] == 1).sum())
    print(f"  {len(table)} filas, {n_pos} positivos", flush=True)
    if n_pos == 0:
        raise SystemExit("No hay positivos: revisa que los días de los índices tengan eventos.")

    print("Validación dejar-un-evento-afuera...", flush=True)
    metrics = leave_one_event_out(table)
    print(f"  POD={metrics['pod']:.3f} FAR={metrics['far']:.3f} CSI={metrics['csi']:.3f}", flush=True)

    print("Entrenando modelo final...", flush=True)
    model, importance = train_full(table)

    out = a.out.rstrip("/")
    print(f"Subiendo resultados a {out}...", flush=True)
    # XGBoost serializa a un archivo; se escribe a un temporal y se sube su contenido.
    tmp = Path("/tmp/model.json")
    model.save_model(str(tmp))
    _write(f"{out}/model.json", tmp.read_bytes())
    _write(f"{out}/metrics.json", json.dumps(metrics, indent=2, ensure_ascii=False).encode())
    _write(f"{out}/importance.json", json.dumps(importance, indent=2, ensure_ascii=False).encode())
    _write(f"{out}/reporte.html", report_html(metrics, importance, table).encode())
    print("Listo.", flush=True)


if __name__ == "__main__":
    main()
