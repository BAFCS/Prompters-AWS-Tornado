"""Orquesta download_goes.py + process_goes.py para los días de evento (>= 2017-12-01).

Corre varios días en paralelo como procesos separados; registra estado por día en
logs/status.jsonl. Borra goes/ crudo del día solo si goes_latlon/ quedó completo.
"""

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LOGS = Path(__file__).parent / "logs"
CROPS = ROOT / "data/crops/south-central-austral"
DEFAULT_HOURS = (12, 23)  # días sin hora conocida


def event_windows() -> dict[dt.date, tuple[int, int, list[int]]]:
    d = pd.read_excel(ROOT / "data/tornados_chile.xlsx", sheet_name="Final_Table")
    hours: dict[dt.date, list[int]] = {}
    for date, h in zip(d["Date (Gregorian Calendar)"], d["Hour (UTC)"], strict=True):
        try:
            day = pd.Timestamp(date).date()
        except Exception:
            continue
        if day < dt.date(2017, 12, 1):
            continue
        hs = hours.setdefault(day, [])
        if pd.isna(h):
            continue
        for part in str(h).split("-"):
            m = re.match(r"\s*(\d{1,2})", part)
            if m:
                hs.append(int(m.group(1)))
    out = {}
    for day, hs in sorted(hours.items()):
        if hs:
            out[day] = (max(0, min(hs) - 3), min(23, max(hs) + 1), sorted(set(hs)))
        else:
            out[day] = (*DEFAULT_HOURS, [])
    return out


def run_day(day: dt.date, h0: int, h1: int) -> dict:
    tag = f"{day:%Y%m%d}"
    log = LOGS / f"dl_{tag}.log"
    t0 = time.time()
    py = [str(ROOT / ".venv/bin/python")]
    with log.open("a") as f:
        r1 = subprocess.run(
            [*py, "scripts/pipeline/download_goes.py", "--start", str(day),
             "--bands", "8", "13", "--hours", str(h0), str(h1), "--processes", "4"],
            cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
        )  # fmt: skip
        r2 = subprocess.run(
            [*py, "scripts/pipeline/process_goes.py", "--start", str(day)],
            cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
        )  # fmt: skip
    raw = sorted(p.name for p in (CROPS / "goes" / tag).glob("goes_*.nc"))
    done = sorted(p.name for p in (CROPS / "goes_latlon" / tag).glob("goes_*.nc"))
    text = log.read_text()
    missing = re.findall(r"sin datos en s3://\S+/(\d{2})/", text)
    failed = re.findall(r"(goes_\d{10}\.nc): falló \(([^)]*)", text)
    if raw and set(raw) <= set(done):
        shutil.rmtree(CROPS / "goes" / tag)
    return {
        "day": str(day), "window": [h0, h1], "rc": [r1.returncode, r2.returncode],
        "hours_latlon": [int(n[-5:-3]) for n in done], "missing_on_noaa": sorted(set(missing)),
        "failed": failed, "seconds": round(time.time() - t0),
    }  # fmt: skip


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    wins = event_windows()
    only = {dt.date.fromisoformat(s) for s in sys.argv[2:]}
    if only:  # reintento de días concretos
        wins = {d: w for d, w in wins.items() if d in only}
    LOGS.mkdir(exist_ok=True)
    (LOGS / "windows.json").write_text(
        json.dumps({str(k): v for k, v in wins.items()}, indent=1)
    )
    status = LOGS / "status.jsonl"
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(run_day, d, h0, h1): d for d, (h0, h1, _) in wins.items()}
        for fu in futs:
            try:
                rec = fu.result()
            except Exception as e:
                rec = {"day": str(futs[fu]), "error": repr(e)}
            with status.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(rec, flush=True)


if __name__ == "__main__":
    main()
