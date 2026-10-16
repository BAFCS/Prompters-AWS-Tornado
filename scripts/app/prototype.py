#!/usr/bin/env python3
"""Prototipo de punta a punta: índices ERA5 → Índice_Favorabilidad → sitio con mapa y alertas.

Versión rápida para demostrar la app mientras se completan las tareas del spec
(``.kiro/specs/merge-tornado-alert-app/``). Usa el Modelo_Sustituto (CAPE × cizalladura 0–6 km)
sobre los ``era5_idx_AAAAMMDD.nc`` que deja ``scripts/model/sync_from_bucket.py`` y produce:

* ``<out>/predictions/pred_AAAAMMDD.csv`` + ``.meta.json`` (esquema de ``predictions.py``);
* ``<out>/site/`` con ``index.html`` (Leaflet desde CDN), ``days/index.json`` y un JSON por día;
* ``<out>/alerts.jsonl`` con las alertas por zona que superan el umbral (también se imprimen).

El sitio se abre en local con ``--serve`` (``http://localhost:8000``). El índice es relativo: no es
una probabilidad calibrada ni un pronóstico oficial.

Uso::

    uv run python scripts/model/sync_from_bucket.py --bucket <bucket> --start 2019-05-30 --only era5
    uv run python scripts/app/prototype.py --start 2019-05-30 --serve

Con ``--predictions-dir`` usa el ``pred_AAAAMMDD.csv`` del Modelo_Real (``infer_grid.py``) si
existe, es válido y su meta dice ``modelo: real``; si no, cae al sustituto. Un CSV real nunca se
pisa con el sustituto.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "app"))
sys.path.insert(0, str(ROOT / "scripts" / "viewer"))

import atomic  # noqa: E402
import predictions  # noqa: E402
import stub_model  # noqa: E402

import common  # noqa: E402

DISCLAIMER = (
    "Índice de favorabilidad relativo; no es una probabilidad calibrada ni un pronóstico oficial"
)
ALERT_DISCLAIMER = "Índice relativo; no es un pronóstico oficial"
SCALE = 10_000  # probability × 10⁴ como entero (redondeo exacto a 4 decimales)
DEMO_DAY = "2019-05-30"

# Zonas de alerta aproximadas (cajas lat/lon) y umbral en % del Índice_Favorabilidad.
ZONES = {
    "Maule-Ñuble": (-37.0, -34.5, -73.0, -70.5),
    "Biobío": (-38.5, -36.4, -73.8, -71.0),
    "Araucanía": (-39.6, -37.5, -73.6, -71.0),
    "Los Ríos-Los Lagos": (-43.5, -39.3, -74.5, -71.5),
}
THRESHOLD = 20.0
SUPPRESSION_H = 6
GRID_STEP = 0.25  # paso ERA5 por defecto si el día tiene una sola latitud
BADGES = {
    "real": "Modelo XGBoost híbrido (ERA5 + imágenes GOES)",
    "real/physical": "Modelo XGBoost (ERA5 + variables GOES)",
    "real/baseline_era5": "Modelo XGBoost (solo ERA5)",
    "sustituto": "Modelo sustituto heurístico (demo)",
}


# --- Predicciones ---------------------------------------------------------------------------


def predict_day(idx_file: Path) -> pd.DataFrame:
    """Tabla de predicciones (``stub_model.OUTPUT_COLUMNS``) de un ``era5_idx`` diario."""
    with xr.open_dataset(idx_file, engine="h5netcdf") as ds:
        missing = [v for v in stub_model.REQUIRED if v not in ds]
        if missing:
            raise SystemExit(f"{idx_file.name}: faltan {missing} (corre sync_from_bucket.py)")
        df = ds[list(stub_model.REQUIRED)].to_dataframe().reset_index()
    df["date"] = pd.to_datetime(df["time"]).dt.normalize()
    df["hour_utc"] = pd.to_datetime(df["time"]).dt.hour
    return stub_model.predict(df, "baseline_era5")


def load_real(pred_dir: Path, day: str) -> tuple[pd.DataFrame, dict] | None:
    """``(predicciones, metadatos)`` del Modelo_Real de ``pred_dir/pred_AAAAMMDD.csv``, o None."""
    csv = pred_dir / f"pred_{day.replace('-', '')}.csv"
    if not csv.exists():
        return None
    try:
        loaded = predictions.load(csv)
    except predictions.InvalidPredictions as exc:
        print(f"aviso: {exc}; se usa el sustituto", file=sys.stderr)
        return None
    return (loaded.df, loaded.meta) if loaded.meta.get("modelo") == "real" else None


def is_real(csv: Path) -> bool:
    """True si ``csv`` ya tiene metadatos con ``modelo: real`` (no se pisa con el sustituto)."""
    meta = predictions.meta_path(csv)
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("modelo") == "real"
    except (OSError, ValueError, AttributeError):
        return False


def grid_step(values: np.ndarray) -> float:
    """Paso de la grilla: la menor separación entre latitudes únicas (0,25° si hay una sola)."""
    u = np.unique(np.asarray(values, dtype=np.float64))
    d = np.diff(u)
    d = d[d > 1e-9]
    return round(float(d.min()), 6) if d.size else GRID_STEP


def write_predictions(pred: pd.DataFrame, out_dir: Path, day: str) -> Path:
    """Escribe el CSV_Predicciones y su ``.meta.json`` de forma atómica."""
    csv = out_dir / f"pred_{day.replace('-', '')}.csv"
    atomic.write_text(csv, pred.to_csv(index=False))
    meta = {
        "modelo": "sustituto",
        "config": "baseline_era5",
        "generado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "filas": len(pred),
    }
    atomic.write_json(csv.with_suffix(".meta.json"), meta)
    return csv


# --- Sitio ----------------------------------------------------------------------------------


def model_info(meta: dict | None) -> dict:
    """Lo que el sitio muestra del modelo: carpeta, configuración y si el día es fuera de muestra."""
    if not meta:
        return {}
    keys = (
        "config",
        "model_dir",
        "evaluacion",
        "en_entrenamiento",
        "generado",
        "stride",
        "version",
    )
    return {k: meta[k] for k in keys if k in meta}


def day_payload(pred: pd.DataFrame, modelo: str, meta: dict | None = None) -> dict:
    """JSON compacto del día: ejes y, por hora, enteros 0–10000 (o null) en orden lat × lon.

    ``meta`` (metadatos del CSV real) agrega ``modelo_info`` y, si el día no se usó para entrenar,
    lo dice en la insignia. ``max`` es el máximo del día (para la escala relativa del sitio).
    """
    lats = sorted(pred["latitude"].unique(), reverse=True)
    lons = sorted(pred["longitude"].unique())
    hours: dict[str, list[int | None]] = {}
    for hour in sorted(pred["hour_utc"].unique()):
        g = pred[pred["hour_utc"] == hour]
        grid = g.pivot_table(index="latitude", columns="longitude", values="probability")
        grid = grid.reindex(index=lats, columns=lons)
        vals = np.rint(grid.to_numpy() * SCALE)
        hours[str(int(hour))] = [None if np.isnan(v) else int(v) for v in vals.ravel()]
    info = model_info(meta)
    badge = BADGES.get(f"{modelo}/{info.get('config')}", BADGES[modelo])
    if info.get("version"):
        badge += f" {info['version']}"
    if info.get("en_entrenamiento") is False:
        badge += " · fuera de muestra (día retenido)"
    elif info.get("en_entrenamiento") is True:
        badge += " · en muestra (día de entrenamiento)"
    if (meta or {}).get("era5") == "tipico":
        badge += " · solo imágenes GOES (ERA5 fijo en valores típicos)"
    return {
        "date": str(pred["date"].iloc[0]),
        "modelo": modelo,
        "badge": badge,
        "modelo_info": info,
        "max": int(np.rint(float(pred["probability"].max()) * SCALE)),
        "lats": [float(x) for x in lats],
        "lons": [float(x) for x in lons],
        "step": grid_step(pred["latitude"].to_numpy()),
        "hours": hours,
    }


def read_catalog(path: Path) -> pd.DataFrame | None:
    """Eventos del catálogo con fecha, lat/lon numéricos, hora, localidad y fuente."""
    if not path.exists():
        print(f"aviso: no está el catálogo {path}; el mapa irá sin eventos", file=sys.stderr)
        return None
    from viewer_app.data import coordinate

    d = pd.read_excel(path, sheet_name="Final_Table")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            ),
            "lat": d["Latitude"].map(coordinate),
            "lon": d["Longitude"].map(coordinate),
            "hour": d["Hour (UTC)"].astype(str).str.slice(0, 5),
            "place": d["Location"].astype(str),
            "source": d["Sources"].astype(str).str.slice(0, 160),
            "type": np.where(d["Tornado"] == 1, "Tornado", "Tromba marina"),
        }
    )
    return out.dropna(subset=["date", "lat", "lon"])


def build_site(payloads: list[dict], catalog: pd.DataFrame | None, site: Path) -> None:
    """Escribe ``index.html``, ``days/index.json`` y un JSON por día en ``site``."""
    days = sorted(p["date"] for p in payloads)
    events: dict[str, list[dict]] = {}
    if catalog is not None:
        for day in days:
            rows = catalog[catalog["date"] == day]
            events[day] = rows[["lat", "lon", "hour", "place", "source", "type"]].to_dict("records")
    for p in payloads:
        atomic.write_json(
            site / "days" / f"{p['date']}.json", p | {"events": events.get(p["date"], [])}
        )
    default = DEMO_DAY if DEMO_DAY in days else days[-1]
    atomic.write_json(site / "days" / "index.json", {"days": days, "default": default})
    atomic.write_text(site / "index.html", INDEX_HTML.replace("__DISCLAIMER__", DISCLAIMER))


# --- Alertas --------------------------------------------------------------------------------


def alerts(pred: pd.DataFrame, modelo: str) -> list[dict]:
    """Alertas por zona y hora con máximo > umbral, suprimiendo repeticiones por ``SUPPRESSION_H``."""
    out: list[dict] = []
    for zone, (s, n, w, e) in ZONES.items():
        inside = pred[pred["latitude"].between(s, n) & pred["longitude"].between(w, e)]
        if inside.empty:
            continue
        peak = inside.groupby(["date", "hour_utc"])["probability"].max() * 100
        last: int | None = None
        for (day, hour), value in peak.items():
            if value <= THRESHOLD or (last is not None and hour - last < SUPPRESSION_H):
                continue
            last = int(hour)
            out.append(
                {
                    "zona": zone,
                    "fecha": str(day),
                    "hora_utc": int(hour),
                    "indice_max": round(float(value), 1),
                    "umbral": THRESHOLD,
                    "modelo": modelo,
                    "descargo": ALERT_DISCLAIMER,
                }
            )
    return out


# --- CLI ------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Corre el prototipo para los días pedidos y, con ``--serve``, abre el sitio en local."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--start", type=dt.date.fromisoformat, help="primer día AAAA-MM-DD")
    p.add_argument(
        "--days",
        type=dt.date.fromisoformat,
        nargs="+",
        help="días sueltos AAAA-MM-DD (en vez de --start/--end)",
    )
    p.add_argument("--end", type=dt.date.fromisoformat, help="último día (por defecto --start)")
    p.add_argument("--region", default="south-central-austral")
    p.add_argument("--out", type=Path, default=common.DATA / "app", help="carpeta de salida")
    p.add_argument("--catalog", type=Path, default=common.DATA / "tornados_chile.xlsx")
    p.add_argument("--serve", action="store_true", help="sirve el sitio en http://localhost:PORT")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--predictions-dir",
        type=Path,
        help="usa pred_AAAAMMDD.csv de esta carpeta si su meta dice modelo real (infer_grid.py)",
    )
    a = p.parse_args(argv)

    idx_dir = common.CROPS / a.region / "era5_indices"
    if a.days:
        days = sorted(set(a.days))
    elif a.start:
        end = a.end or a.start
        days = [a.start + dt.timedelta(days=k) for k in range((end - a.start).days + 1)]
    else:
        p.error("falta --start o --days")
    payloads, all_alerts = [], []
    for day in days:
        real = load_real(a.predictions_dir, day.isoformat()) if a.predictions_dir else None
        meta = None
        if real is not None:
            (pred, meta), modelo = real, "real"
            csv = a.predictions_dir / f"pred_{day:%Y%m%d}.csv"
        else:
            f = idx_dir / f"era5_idx_{day:%Y%m%d}.nc"
            if not f.exists():
                print(f"{day}: falta {f.name}; corre sync_from_bucket.py --start {day} --only era5")
                continue
            pred, modelo = predict_day(f), "sustituto"
            csv = a.out / "predictions" / f"pred_{day:%Y%m%d}.csv"
            if is_real(csv):
                print(f"{day}: {csv.name} es del modelo real; no se pisa (usa --predictions-dir)")
            else:
                csv = write_predictions(pred, a.out / "predictions", day.isoformat())
        payloads.append(day_payload(pred, modelo, meta))
        day_alerts = alerts(pred, modelo)
        all_alerts += day_alerts
        print(f"{day}: {modelo}, {len(pred)} celdas-hora, máx {pred['probability'].max() * 100:.1f} %, "
              f"{len(day_alerts)} alertas → {csv}")  # fmt: skip
    if not payloads:
        raise SystemExit("ningún día con índices ERA5; nada que publicar")

    site = a.out / "site"
    build_site(payloads, read_catalog(a.catalog), site)
    atomic.write_text(
        a.out / "alerts.jsonl",
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in all_alerts),
    )
    for x in all_alerts:
        print(f"ALERTA {x['zona']} {x['fecha']} {x['hora_utc']:02d} UTC: {x['indice_max']} % "
              f"(umbral {x['umbral']} %)")  # fmt: skip
    print(f"Sitio en {site}")
    if a.serve:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
        print(f"Abre http://localhost:{a.port}  (Ctrl+C para salir)")
        http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


INDEX_HTML = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Favorabilidad de tornados — Chile (prototipo)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
 integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
 integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
// Tema: los mismos colores del visor (.streamlit/config.toml). El visor pasa ?theme=dark|light;
// sin parámetro se usa oscuro, como la primera visita al visor.
document.documentElement.dataset.theme =
  new URLSearchParams(location.search).get("theme") === "light" ? "light" : "dark";
</script>
<style>
 :root{--bg:#FFFFFF;--panel:#FFFFFF;--ink:#0E1A2C;--muted:#465463;--line:#BDD4D6;--accent:#376284;--field:#EFF8F9}
 :root[data-theme="dark"]{--bg:#1D3557;--panel:#1D3557;--ink:#F1FAEE;--muted:#A9B8BE;--line:#475C75;--accent:#A8DADC;--field:#2C4362}
 body{margin:0;font:15px/1.4 "IBM Plex Sans",system-ui,sans-serif;color:var(--ink);background:var(--bg);display:flex;flex-direction:column;height:100vh}
 header{background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;position:sticky;top:0;z-index:1000}
 h1{font-size:18px;margin:0 0 4px} h2{font-size:15px} .disc{font-size:13px;color:var(--muted);margin:0}
 .bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:8px}
 label{font-weight:600} select,input{font:inherit}
 select{background:var(--field);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:2px 6px}
 input[type=range]{accent-color:var(--accent)} a{color:var(--accent)}
 .badge{background:#7a3e00;color:#fff;border-radius:6px;padding:2px 8px;font-size:13px} .badge.real{background:#14532d}
 main{flex:1;display:flex;min-height:0} #map{flex:1;background:var(--bg)}
 aside{width:300px;overflow:auto;background:var(--panel);border-left:1px solid var(--line);padding:12px}
 .legend span{display:inline-block;width:44px;height:14px} .legend small{display:flex;justify-content:space-between;width:220px}
 #nodata{color:#E69F00;font-weight:600} .ev{margin:6px 0;font-size:13px;color:var(--muted)}
 .ev.now{color:var(--ink);font-weight:600} .ev.now::marker{color:#E63946}
 .tor{background:#E63946;border:2px solid #fff;border-radius:50%;width:14px;height:14px;box-shadow:0 0 0 1px #000}
 :root[data-theme="dark"] .leaflet-bar a,:root[data-theme="dark"] .leaflet-popup-content-wrapper,
 :root[data-theme="dark"] .leaflet-popup-tip,:root[data-theme="dark"] .leaflet-tooltip{background:var(--field);color:var(--ink);border-color:var(--line)}
 :root[data-theme="dark"] .leaflet-control-attribution{background:rgba(29,53,87,.8);color:var(--muted)}
 :root[data-theme="dark"] .leaflet-control-attribution a{color:var(--accent)}
 @media(max-width:800px){main{flex-direction:column}aside{width:auto;max-height:35vh}}
</style></head><body>
<header>
 <h1>Favorabilidad de tornados en Chile <span id="badge" class="badge" hidden></span></h1>
 <p class="disc">__DISCLAIMER__</p>
 <div class="bar">
  <label for="day">Día</label><select id="day"></select>
  <label for="hour">Hora de Chile</label>
  <input id="hour" type="range" min="0" max="23" value="20">
  <output id="hourlbl" for="hour"></output>
  <label><input id="rel" type="checkbox"> Escala relativa al máximo del día</label>
  <span id="max"></span><span id="nodata" role="status"></span>
 </div>
 <p class="disc" id="minfo"></p>
</header>
<main><div id="map" aria-label="Mapa del índice de favorabilidad"></div>
<aside>
 <h2>Leyenda (%)</h2>
 <div class="legend" id="legend"></div>
 <p class="disc" id="lgnote"></p>
 <h2>Eventos del catálogo en el día</h2>
 <p class="disc">El punto rojo aparece solo en la hora del evento (en negrita).</p>
 <ul id="events" style="padding-left:18px"></ul>
</aside></main>
<script>
const COLORS=["#440154","#3b528b","#21918c","#5ec962","#fde725"];
const color=v=>COLORS[Math.min(4,Math.floor(v/20))];
const lg=document.getElementById("legend");
function legend(rel,dmax){const t=rel?[0,20,40,60,80,100].map(x=>(x*dmax/100).toFixed(1)):[0,20,40,60,80,100];
 lg.innerHTML=COLORS.map(c=>`<span style="background:${c}"></span>`).join("")+"<small>"+t.map(x=>`<b>${x}</b>`).join("")+"</small>";
 document.getElementById("lgnote").textContent=rel?`Colores relativos al máximo del día (${dmax.toFixed(1)} %); el valor absoluto está en el recuadro de cada celda.`:"Colores en % absoluto del índice.";}
// Hora de Chile continental (America/Santiago): el navegador aplica el horario de invierno o verano
// que correspondía en esa fecha. Los datos siguen indexados por hora UTC del día elegido.
const CL=new Intl.DateTimeFormat("es-CL",{timeZone:"America/Santiago",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
const CLDAY=new Intl.DateTimeFormat("es-CL",{timeZone:"America/Santiago",day:"2-digit",month:"2-digit"});
const utc=(date,h,m=0)=>{const[y,mo,d]=date.split("-").map(Number);return new Date(Date.UTC(y,mo-1,d,h,m));};
function chile(date,h,m=0){const t=utc(date,h,m), u=utc(date,12);
 return CL.format(t)+(CLDAY.format(t)===CLDAY.format(u)?"":` del ${CLDAY.format(t)}`);}
// Hora UTC del evento en el catálogo: "21:57", "19:00" o un rango "22-23". Devuelve las horas UTC
// en que hay que mostrarlo y el texto en hora de Chile; sin hora conocida, null.
function evHours(date,txt){
 const r=String(txt).match(/^(\\d{1,2})\\s*-\\s*(\\d{1,2})/);
 if(r){const a=+r[1],b=+r[2]; const hs=[]; for(let h=a;h<=b&&h<24;h++)hs.push(h);
  return{hours:hs,label:`${chile(date,a)}–${chile(date,b)}`};}
 const m=String(txt).match(/^(\\d{1,2})(?::(\\d{2}))?/);
 if(m&&+m[1]<24)return{hours:[+m[1]],label:chile(date,+m[1],+(m[2]||0))};
 return null;}
const map=L.map("map",{preferCanvas:true}).setView([-38.5,-72],5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:9,attribution:"© OpenStreetMap"}).addTo(map);
let relTouched=false, framed=false;
const cells=L.layerGroup().addTo(map), marks=L.layerGroup().addTo(map), cache={};
const $=id=>document.getElementById(id);
async function day(d){return cache[d]??=(await fetch(`days/${d}.json`)).json();}
// Al cambiar de día: si tiene eventos con hora, el control salta a la hora del primero, para que se
// vea su punto rojo sin buscarlo. La primera vez el mapa se encuadra en la grilla del modelo.
async function pickDay(){
 const d=await day($("day").value);
 const hs=d.events.map(e=>evHours(d.date,e.hour)).filter(Boolean).flatMap(t=>t.hours).filter(h=>d.hours[h]);
 if(hs.length)$("hour").value=Math.min(...hs);
 draw();}
function frame(d){if(framed||!d.lats.length)return; framed=true; const h=d.step/2;
 map.invalidateSize(); map.fitBounds([[Math.min(...d.lats)-h,Math.min(...d.lons)-h],[Math.max(...d.lats)+h,Math.max(...d.lons)+h]]);}
async function draw(){
 const d=await day($("day").value), h=+$("hour").value, hl=chile(d.date,h)+" (hora de Chile)";
 $("hourlbl").textContent=hl; $("hour").setAttribute("aria-valuetext",hl); frame(d);
 const b=$("badge"); b.textContent=d.badge; b.className=d.modelo==="real"?"badge real":"badge"; b.hidden=!d.badge;
 const mi=d.modelo_info||{}; $("minfo").textContent=mi.model_dir?`Modelo: ${mi.config} · ${mi.model_dir} · ${mi.evaluacion||""}`:"";
 const dmax=(d.max??10000)/100||1; if(!relTouched)$("rel").checked=dmax<50;
 const rel=$("rel").checked; legend(rel,dmax);
 cells.clearLayers(); const vals=d.hours[h]; const half=d.step/2; let mx=0;
 if(!vals){$("nodata").textContent="Sin datos para esta hora";}
 else{$("nodata").textContent="";
  vals.forEach((v,i)=>{if(v===null)return; const pct=v/100; mx=Math.max(mx,pct); const cv=rel?pct/dmax*100:pct; if(cv<1)return;
   const la=d.lats[Math.floor(i/d.lons.length)], lo=d.lons[i%d.lons.length];
   L.rectangle([[la-half,lo-half],[la+half,lo+half]],{stroke:false,fillColor:color(cv),fillOpacity:.65})
    .bindTooltip(`${pct.toFixed(1)} %`).addTo(cells);});}
 $("max").textContent=vals?`Máximo: ${mx.toFixed(1)} %`:"";
 marks.clearLayers(); const ul=$("events"); ul.replaceChildren();
 for(const e of d.events){
  const t=evHours(d.date,e.hour), now=!!t&&t.hours.includes(h);
  const text=`${e.type} · ${t?t.label+" hora de Chile":"hora desconocida"} · ${e.place} · ${e.source}`;
  if(now){const m=L.marker([e.lat,e.lon],{icon:L.divIcon({className:"tor",iconSize:[14,14]}),keyboard:true,title:e.place}).addTo(marks);
   const div=document.createElement("div"); div.textContent=text; m.bindPopup(div);}
  const li=document.createElement("li"); li.className=now?"ev now":"ev"; li.textContent=text; ul.append(li);}
 if(!d.events.length){const li=document.createElement("li"); li.textContent="Sin eventos registrados"; ul.append(li);}
}
(async()=>{const idx=await (await fetch("days/index.json")).json();
 for(const d of idx.days){const o=document.createElement("option"); o.value=o.textContent=d; $("day").append(o);}
 $("day").value=idx.default; $("day").onchange=pickDay; $("hour").oninput=draw; $("rel").onchange=()=>{relTouched=true;draw();}; pickDay();})();
</script></body></html>
"""

if __name__ == "__main__":
    main()
