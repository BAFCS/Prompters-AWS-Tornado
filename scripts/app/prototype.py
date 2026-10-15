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


def day_payload(pred: pd.DataFrame, modelo: str) -> dict:
    """JSON compacto del día: ejes y, por hora, enteros 0–10000 (o null) en orden lat × lon."""
    lats = sorted(pred["latitude"].unique(), reverse=True)
    lons = sorted(pred["longitude"].unique())
    hours: dict[str, list[int | None]] = {}
    for hour in sorted(pred["hour_utc"].unique()):
        g = pred[pred["hour_utc"] == hour]
        grid = g.pivot_table(index="latitude", columns="longitude", values="probability")
        grid = grid.reindex(index=lats, columns=lons)
        vals = np.rint(grid.to_numpy() * SCALE)
        hours[str(int(hour))] = [None if np.isnan(v) else int(v) for v in vals.ravel()]
    return {
        "date": str(pred["date"].iloc[0]),
        "modelo": modelo,
        "lats": [float(x) for x in lats],
        "lons": [float(x) for x in lons],
        "step": 0.25,
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
    p.add_argument(
        "--start", type=dt.date.fromisoformat, required=True, help="primer día AAAA-MM-DD"
    )
    p.add_argument("--end", type=dt.date.fromisoformat, help="último día (por defecto --start)")
    p.add_argument("--region", default="south-central-austral")
    p.add_argument("--out", type=Path, default=common.DATA / "app", help="carpeta de salida")
    p.add_argument("--catalog", type=Path, default=common.DATA / "tornados_chile.xlsx")
    p.add_argument("--serve", action="store_true", help="sirve el sitio en http://localhost:PORT")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    idx_dir = common.CROPS / a.region / "era5_indices"
    end = a.end or a.start
    days = [a.start + dt.timedelta(days=k) for k in range((end - a.start).days + 1)]
    payloads, all_alerts = [], []
    for day in days:
        f = idx_dir / f"era5_idx_{day:%Y%m%d}.nc"
        if not f.exists():
            print(f"{day}: falta {f.name}; corre sync_from_bucket.py --start {day} --only era5")
            continue
        pred = predict_day(f)
        csv = write_predictions(pred, a.out / "predictions", day.isoformat())
        payloads.append(day_payload(pred, "sustituto"))
        day_alerts = alerts(pred, "sustituto")
        all_alerts += day_alerts
        print(f"{day}: {len(pred)} celdas-hora, máx {pred['probability'].max() * 100:.1f} %, "
              f"{len(day_alerts)} alertas → {csv.relative_to(ROOT)}")  # fmt: skip
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
<style>
 body{margin:0;font:15px/1.4 system-ui,sans-serif;color:#1b1f24;background:#f4f6fa;display:flex;flex-direction:column;height:100vh}
 header{background:#fff;border-bottom:1px solid #ccd4e0;padding:10px 16px;position:sticky;top:0;z-index:1000}
 h1{font-size:18px;margin:0 0 4px} .disc{font-size:13px;color:#3d4652;margin:0}
 .bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:8px}
 label{font-weight:600} select,input{font:inherit}
 .badge{background:#7a3e00;color:#fff;border-radius:6px;padding:2px 8px;font-size:13px}
 main{flex:1;display:flex;min-height:0} #map{flex:1}
 aside{width:300px;overflow:auto;background:#fff;border-left:1px solid #ccd4e0;padding:12px}
 .legend span{display:inline-block;width:44px;height:14px} .legend small{display:flex;justify-content:space-between;width:220px}
 #nodata{color:#7a3e00;font-weight:600} .ev{margin:6px 0;font-size:13px}
 .tor{background:#d7263d;border:2px solid #fff;border-radius:50%;width:14px;height:14px;box-shadow:0 0 0 1px #000}
 @media(max-width:800px){main{flex-direction:column}aside{width:auto;max-height:35vh}}
</style></head><body>
<header>
 <h1>Favorabilidad de tornados en Chile <span id="badge" class="badge" hidden>Modelo sustituto heurístico (demo)</span></h1>
 <p class="disc">__DISCLAIMER__</p>
 <div class="bar">
  <label for="day">Día</label><select id="day"></select>
  <label for="hour">Hora UTC</label>
  <input id="hour" type="range" min="0" max="23" value="20" aria-valuetext="20 UTC">
  <output id="hourlbl" for="hour">20 UTC</output>
  <span id="max"></span><span id="nodata" role="status"></span>
 </div>
</header>
<main><div id="map" aria-label="Mapa del índice de favorabilidad"></div>
<aside>
 <h2 style="font-size:15px">Leyenda (%)</h2>
 <div class="legend" id="legend"></div>
 <h2 style="font-size:15px">Eventos del catálogo en el día</h2>
 <ul id="events" style="padding-left:18px"></ul>
</aside></main>
<script>
const COLORS=["#440154","#3b528b","#21918c","#5ec962","#fde725"];
const color=v=>COLORS[Math.min(4,Math.floor(v/20))];
const lg=document.getElementById("legend");
lg.innerHTML=COLORS.map(c=>`<span style="background:${c}"></span>`).join("")+"<small><b>0</b><b>20</b><b>40</b><b>60</b><b>80</b><b>100</b></small>";
const map=L.map("map",{preferCanvas:true}).setView([-38.5,-72],5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:9,attribution:"© OpenStreetMap"}).addTo(map);
const cells=L.layerGroup().addTo(map), marks=L.layerGroup().addTo(map), cache={};
const $=id=>document.getElementById(id);
async function day(d){return cache[d]??=(await fetch(`days/${d}.json`)).json();}
async function draw(){
 const d=await day($("day").value), h=$("hour").value; $("hourlbl").textContent=h+" UTC";
 $("hour").setAttribute("aria-valuetext",h+" UTC"); $("badge").hidden=d.modelo!=="sustituto";
 cells.clearLayers(); const vals=d.hours[h]; const half=d.step/2; let mx=0;
 if(!vals){$("nodata").textContent="Sin datos para esta hora";}
 else{$("nodata").textContent="";
  vals.forEach((v,i)=>{if(v===null)return; const pct=v/100; mx=Math.max(mx,pct); if(pct<1)return;
   const la=d.lats[Math.floor(i/d.lons.length)], lo=d.lons[i%d.lons.length];
   L.rectangle([[la-half,lo-half],[la+half,lo+half]],{stroke:false,fillColor:color(pct),fillOpacity:.65})
    .bindTooltip(`${pct.toFixed(1)} %`).addTo(cells);});}
 $("max").textContent=vals?`Máximo: ${mx.toFixed(1)} %`:"";
 marks.clearLayers(); const ul=$("events"); ul.replaceChildren();
 for(const e of d.events){
  const m=L.marker([e.lat,e.lon],{icon:L.divIcon({className:"tor",iconSize:[14,14]}),keyboard:true,title:e.place}).addTo(marks);
  const div=document.createElement("div"); div.textContent=`${e.type} · ${d.date} ${e.hour} UTC · ${e.place} · ${e.source}`;
  m.bindPopup(div); const li=document.createElement("li"); li.className="ev"; li.textContent=div.textContent; ul.append(li);}
 if(!d.events.length){const li=document.createElement("li"); li.textContent="Sin eventos registrados"; ul.append(li);}
}
(async()=>{const idx=await (await fetch("days/index.json")).json();
 for(const d of idx.days){const o=document.createElement("option"); o.value=o.textContent=d; $("day").append(o);}
 $("day").value=idx.default; $("day").onchange=draw; $("hour").oninput=draw; draw();})();
</script></body></html>
"""

if __name__ == "__main__":
    main()
