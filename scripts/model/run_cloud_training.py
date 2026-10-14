"""Orquesta el entrenamiento en la nube: genera índices ERA5 de los días con evento y entrena.

Para cada día del catálogo con un evento en la era de GOES-16 (desde dic-2017) y una muestra de
días sin evento:

1. Descarga ERA5 (``download_era5.py``) y calcula los índices (``process_era5.py``). Cada script
   salta lo que ya existe. Los índices ya calculados se **reutilizan desde S3** (``era5_indices/``)
   para no volver a descargar ERA5 en cada corrida: la descarga entre regiones es el paso lento.
2. Llama a ``train_xgboost.py`` con la carpeta de índices y sube los resultados al prefijo S3.

Observabilidad: tras cada paso sube un ``estado.html`` al prefijo de resultados, para seguir el
avance en vivo por CloudFront (``/resultados/estado.html``). Cada día tiene un **timeout**: si la
descarga de ERA5 se cuelga (sockets entre regiones), ese día se omite y el job sigue, en vez de
quedarse bloqueado para siempre.

Opciones para acotar el tiempo (descargar ERA5 es ~minutos por día): ``--max-event-days`` limita
cuántos días con evento se procesan y ``--unlabeled-days`` cuántos días sin evento se añaden.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import subprocess
import sys
from pathlib import Path

import fsspec
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

GOES16_START = dt.date(2017, 12, 1)  # inicio operacional de GOES-16 sobre Chile
DAY_TIMEOUT_S = 600  # tope por día; si ERA5 se cuelga, se omite ese día y el job continúa


def _read_catalog_days(catalog: str) -> list[dt.date]:
    """Días (ordenados, únicos) con evento en la era de GOES-16, leídos del catálogo en S3 o local."""
    with fsspec.open(catalog, "rb") as f:  # type: ignore[union-attr]
        raw = f.read()
    d = pd.read_excel(io.BytesIO(raw), sheet_name="Final_Table")
    dates = pd.to_datetime(d["Date (Gregorian Calendar)"], errors="coerce").dt.date.dropna()
    return sorted({x for x in dates if x >= GOES16_START})


def _run(cmd: list[str], timeout: int | None = None) -> None:
    """Ejecuta un comando y aborta si falla o excede ``timeout`` segundos."""
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, timeout=timeout)


def _status_html(steps: list[str], done: bool = False) -> str:
    """HTML de progreso: fase actual destacada + historial de pasos con marca de tiempo."""
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    state = "✅ Entrenamiento terminado" if done else "⏳ Entrenamiento en curso…"
    current = steps[-1] if steps else "Arrancando…"
    # Historial en orden inverso (lo más reciente arriba).
    items = "".join(f"<li>{s}</li>" for s in reversed(steps))
    refresh = "" if done else '<meta http-equiv="refresh" content="10">'
    link = '<p class="link"><a href="reporte.html">📊 Ver el reporte de métricas →</a></p>' if done else ""
    phase = "" if done else (
        '<div class="phase"><div class="phase-label">Paso actual</div>'
        f'<div class="phase-now">{current}</div></div>'
    )
    legend = (
        '<p class="muted">Fases: <b>⬇️ TOMANDO DATOS</b> baja ERA5 (lo más lento, ~GB por día entre '
        "regiones) · <b>⚙️ CALCULANDO ÍNDICES</b> deriva cizalladura, SRH, VGP, STP · "
        "<b>🧠 ENTRENANDO</b> ajusta XGBoost (segundos).</p>"
    )
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">{refresh}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estado del entrenamiento</title>
<style>body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
max-width:760px;margin:0 auto;padding:32px 24px;color:#182230;background:#f4f6fa}}
h1{{font-size:20px;margin-bottom:4px}} .muted{{color:#5a6675;font-size:13px}}
.phase{{background:#fff;border:1px solid #1769ff;border-left:5px solid #1769ff;border-radius:12px;
padding:14px 18px;margin:18px 0}} .phase-label{{color:#5a6675;font-size:12px;text-transform:uppercase;
letter-spacing:.5px}} .phase-now{{font-size:17px;font-weight:600;margin-top:2px}}
.link a{{display:inline-block;background:#1769ff;color:#fff;padding:10px 18px;border-radius:8px;
text-decoration:none;font-weight:600}}
ol,ul{{background:#fff;border:1px solid #ccd4e0;border-radius:12px;padding:12px 12px 12px 32px}}
li{{margin:3px 0;font-size:13px}} a{{color:#1769ff}} h2{{font-size:14px;color:#5a6675;margin-top:24px}}</style>
</head><body>
<h1>{state}</h1>
<p class="muted">Actualizado {now}. {"" if done else "La página se refresca sola cada 10 s."}</p>
{phase}
{link}
{legend}
<h2>Historial (lo más reciente arriba)</h2>
<ul>{items}</ul>
</body></html>"""


def _publish(out: str, steps: list[str], done: bool = False) -> None:
    """Sube el estado.html al prefijo de resultados (ignora fallos de red para no romper el job)."""
    try:
        with fsspec.open(f"{out}/estado.html", "wb") as f:  # type: ignore[union-attr]
            f.write(_status_html(steps, done).encode())
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no se pudo subir estado.html ({e})", flush=True)


def main() -> None:
    """Punto de entrada: genera índices y entrena, publicando el avance a S3."""
    p = argparse.ArgumentParser(description="Entrenamiento en la nube de XGBoost (índices + modelo).")
    p.add_argument("--catalog", required=True, help="Ruta o s3:// del tornados_chile.xlsx")
    p.add_argument("--out", required=True, help="Prefijo s3:// donde dejar los resultados")
    p.add_argument("--region", default="south-central-austral", help="Región de recorte")
    p.add_argument("--max-event-days", type=int, default=0, help="Límite de días con evento (0 = todos)")
    p.add_argument("--unlabeled-days", type=int, default=0, help="Días extra SIN evento (no etiquetados)")
    p.add_argument("--indices-s3", default="", help="Prefijo s3:// para reutilizar/guardar índices ERA5")
    a = p.parse_args()

    out = a.out.rstrip("/")
    steps: list[str] = []

    # reporte.html provisional: si alguien entra antes de tiempo, ve el avance en vez de un error.
    try:
        placeholder = (
            '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url=estado.html">'
            "<title>Entrenamiento en curso</title></head><body>"
            '<p>El entrenamiento aún no termina. <a href="estado.html">Ver el avance →</a></p>'
            "</body></html>"
        )
        with fsspec.open(f"{out}/reporte.html", "wb") as f:  # type: ignore[union-attr]
            f.write(placeholder.encode())
    except Exception as e:  # noqa: BLE001
        print(f"  aviso: no se pudo subir el reporte provisional ({e})", flush=True)

    def step(msg: str, done: bool = False) -> None:
        print(f"[estado] {msg}", flush=True)
        steps.append(msg)
        _publish(out, steps, done)

    step("Leyendo el catálogo de eventos…")
    event_days = _read_catalog_days(a.catalog)
    if a.max_event_days:
        event_days = event_days[: a.max_event_days]
    step(f"Días con evento a procesar: {len(event_days)}")

    # Días sin evento, intercalados, para enriquecer los no etiquetados del PU learning.
    extra: list[dt.date] = []
    if a.unlabeled_days and event_days:
        gap = max((event_days[-1] - event_days[0]).days // (a.unlabeled_days + 1), 1)
        cur = event_days[0]
        while len(extra) < a.unlabeled_days:
            cur = cur + dt.timedelta(days=gap)
            if cur not in event_days and cur < dt.date.today():
                extra.append(cur)

    indices_dir = common.folder(a.region, "era5_indices")

    # Reutiliza índices ya calculados en S3 (evita rebajar ERA5).
    if a.indices_s3:
        try:
            fs = fsspec.filesystem("s3")
            existing = fs.glob(a.indices_s3.rstrip("/") + "/*.nc")
            indices_dir.mkdir(parents=True, exist_ok=True)
            for key in existing:
                fs.get(key, str(indices_dir / Path(key).name))
            if existing:
                step(f"Reutilizados {len(existing)} índices ya calculados desde S3")
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: no se pudieron reutilizar índices de S3 ({e})", flush=True)

    ok = 0
    total = len(event_days) + len(extra)
    for i, day in enumerate([*event_days, *extra], start=1):
        if (indices_dir / f"era5_idx_{day:%Y%m%d}.nc").exists():
            ok += 1
            step(f"[{i}/{total}] {day} · índice ya disponible ✓")
            continue
        try:
            iso = day.isoformat()
            step(f"[{i}/{total}] {day} · ⬇️ TOMANDO DATOS ERA5 (lo más lento, ~GB entre regiones)…")
            # Solo las 4 variables de presión que usa process_era5 (u, v, t, z). El default baja 8
            # (añade w, q, r, vo) que no entran en ninguna feature: pedir solo 4 corta a la mitad
            # el tráfico de ERA5, que es el cuello de botella. --sfc solo lo que leen los índices.
            _run(
                ["uv", "run", "python", "scripts/pipeline/download_era5.py", "--start", iso,
                 "--region", a.region, "--pl", "u", "v", "t", "z",
                 "--sfc", "10u", "10v", "2t", "2d", "sp", "cape"],
                timeout=DAY_TIMEOUT_S,
            )
            step(f"[{i}/{total}] {day} · ⚙️ CALCULANDO ÍNDICES (cizalladura, SRH, VGP, STP)…")
            _run(
                ["uv", "run", "python", "scripts/pipeline/process_era5.py", "--start", iso,
                 "--region", a.region],
                timeout=120,
            )
            ok += 1
            step(f"[{i}/{total}] {day} · índice ERA5 listo ✓")
            # Sube el índice a S3 para reutilizarlo en futuras corridas.
            if a.indices_s3:
                try:
                    src = indices_dir / f"era5_idx_{day:%Y%m%d}.nc"
                    with open(src, "rb") as fsrc, fsspec.open(
                        f"{a.indices_s3.rstrip('/')}/{src.name}", "wb"
                    ) as fdst:  # type: ignore[union-attr]
                        fdst.write(fsrc.read())
                except Exception as e:  # noqa: BLE001
                    print(f"  aviso: no se pudo subir el índice de {day} ({e})", flush=True)
        except subprocess.TimeoutExpired:
            step(f"[{i}/{total}] {day} · ⏱️ se excedió el tiempo bajando ERA5; se omite y sigue")
        except subprocess.CalledProcessError as e:
            step(f"[{i}/{total}] {day} · ⚠️ falló ({e}); se omite y sigue")

    if ok == 0:
        step("No se generó ningún índice; no se puede entrenar", done=True)
        raise SystemExit("Sin índices ERA5.")

    step(f"🧠 ENTRENANDO XGBoost con {ok} días de índices (esto es rápido, segundos)…")
    _run([
        "uv", "run", "python", "scripts/model/train_xgboost.py",
        "--indices", str(indices_dir),
        "--catalog", a.catalog,
        "--out", out,
    ])
    step("Entrenamiento en la nube completo. Reporte disponible en reporte.html", done=True)


if __name__ == "__main__":
    main()
