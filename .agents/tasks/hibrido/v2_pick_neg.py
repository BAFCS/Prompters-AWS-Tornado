"""Elige los días negativos del reentreno v2 desde el inventario del bucket del equipo.

Candidatos: días 2018-2026 con ERA5 (zarr) y GOES C08 + C13 en el bucket, sin ningún Evento del
Catálogo (con o sin hora) a ±1 día. Cuotas por mes: 70 % para mayo-septiembre (temporada de
tornados en Chile) y 30 % para el resto, redistribuyendo lo que falte. Dentro de cada mes se
alterna entre años (semilla fija) y se prefieren días con el ERA5 del día anterior (rezagos) y días
ya sincronizados (ahorra descarga; misma fuente, el bucket).

Uso: .venv/bin/python .agents/tasks/hibrido/v2_pick_neg.py [N=70]
Lee data/model/v2/bucket_inventory.json; escribe .agents/tasks/hibrido/v2_neg_days.txt.
"""

import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts" / "model")]
import build_table as bt  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 70
SEASON = {5, 6, 7, 8, 9}
inv = json.loads((ROOT / "data/model/v2/bucket_inventory.json").read_text())
era5 = {dt.datetime.strptime(x[5:13], "%Y%m%d").date() for x in inv["era5"]}


def bands_ok(day: str, files: list[str]) -> bool:
    ymd = day.replace("-", "")
    c13 = f"goes_{ymd}.nc" in files or f"goes_{ymd}_C13.nc" in files
    return c13 and f"goes_{ymd}_C08.nc" in files


goes = {dt.date.fromisoformat(d) for d, f in inv["goes"].items() if bands_ok(d, f)}
cat = bt.read_catalog(str(bt.DEFAULT_CATALOG))
ev = set(cat["date"].dropna())
near = {d + dt.timedelta(days=k) for d in ev for k in (-1, 0, 1)}
local = ROOT / "data/crops/south-central-austral/goes_latlon"
cands = sorted(d for d in goes & era5 if d.year >= 2018 and d not in near)
by_month: dict[int, list[dt.date]] = {m: [d for d in cands if d.month == m] for m in range(1, 13)}

season_n = round(N * 0.7)
quota = {m: 0 for m in range(1, 13)}
for group, total in ((sorted(SEASON), season_n), ([m for m in range(1, 13) if m not in SEASON], N - season_n)):
    left = total
    while left > 0:
        open_m = [m for m in group if quota[m] < len(by_month[m])]
        if not open_m:
            break
        for m in open_m:
            if left == 0:
                break
            quota[m] += 1
            left -= 1

rng = random.Random(0)
chosen: list[dt.date] = []
for m in range(1, 13):
    pool = by_month[m][:]
    rng.shuffle(pool)
    pool.sort(key=lambda d: (d - dt.timedelta(days=1) not in era5, not (local / f"{d:%Y%m%d}").is_dir()))
    by_year: dict[int, list[dt.date]] = {}
    for d in pool:
        by_year.setdefault(d.year, []).append(d)
    years = sorted(by_year, key=lambda _: rng.random())
    picked: list[dt.date] = []
    while len(picked) < quota[m]:
        for y in years:
            if by_year[y] and len(picked) < quota[m]:
                picked.append(by_year[y].pop(0))
    chosen += picked

chosen.sort()
out = ROOT / ".agents/tasks/hibrido/v2_neg_days.txt"
header = (
    f"# v2: {len(chosen)} negativos del bucket (ERA5 + C08 + C13, sin Evento a ±1 día), "
    f"de {len(cands)} candidatos; cuotas por mes {quota}\n"
)
out.write_text(header + "".join(f"{d}\n" for d in chosen), "utf-8")
print(header.strip())
print("con ERA5 del día anterior:", sum(d - dt.timedelta(days=1) in era5 for d in chosen))
print("ya locales:", sum((local / f"{d:%Y%m%d}").is_dir() for d in chosen))
