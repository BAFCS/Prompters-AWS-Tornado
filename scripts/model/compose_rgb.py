#!/usr/bin/env python3
"""Compone una imagen RGB por Celda_Hora elegida a partir de los recortes GOES en lat/lon.

Lee las Celdas_Hora de ``--cells`` (``cells.parquet`` de ``build_table.py --stage select``, con
``cell_id``, ``time``, ``latitude`` y ``longitude``) dentro de ``--start``–``--end`` y, para cada
una, toma el barrido más reciente con inicio en (t - 60 min, t] (``goes_features.select_scan``),
recorta una ventana de ``--window-km`` km centrada en el punto y la compone con la receta
``--recipe`` v``--recipe-version`` en un PNG de ``--size`` píxeles. La receta se valida antes de
procesar nada. Las Celdas_Hora sin barrido, con bandas faltantes o con menos de 50 % de píxeles
válidos en alguna banda se omiten y quedan en ``skipped.parquet`` con el motivo.

Salida::

    data/model/<region>/rgb/<recipe>_v<version>/AAAAMMDD/<cell_id>.png
    data/model/<region>/rgb/<recipe>_v<version>/manifest.parquet   (png_path relativo a esta carpeta)
    data/model/<region>/rgb/<recipe>_v<version>/skipped.parquet

Uso::

    uv run python scripts/model/compose_rgb.py --start 2019-05-30 --cells data/model/south-central-austral/cells.parquet
    uv run python scripts/model/compose_rgb.py --start 2019-05-30 --cells cells.parquet --recipe airmass --force
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import goes_features as gf  # noqa: E402
import rgb  # noqa: E402
from extract_goes_features import MODEL_DATA, GoesReader  # noqa: E402

import common  # noqa: E402

KM_PER_DEG_LAT = 111.32
CELL_COLUMNS = ("cell_id", "time", "latitude", "longitude")
MANIFEST_COLUMNS = [
    "cell_id",
    "png_path",
    "sha256",
    "recipe",
    "recipe_version",
    "scan_start",
    "window_km",
    "size_px",
    "scale_px_per_px",
    "missing_frac",
]
SKIPPED_COLUMNS = ["cell_id", "time", "reason"]


def _utc(values: pd.Series) -> pd.Series:
    """Serie de tiempos como ``datetime64[ns, UTC]`` (acepta tiempos con o sin zona)."""
    return pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]")


def _write_parquet(df: pd.DataFrame, out_file: Path) -> None:
    """Escribe ``df`` en ``out_file`` pasando por un ``.tmp`` (sin archivos a medias)."""
    tmp = out_file.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_file)


def _write_bytes(data: bytes, out_file: Path) -> None:
    """Escribe ``data`` en ``out_file`` pasando por un ``.tmp``."""
    tmp = out_file.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(out_file)


def read_cells(path: Path, days: list[dt.date]) -> pd.DataFrame:
    """Celdas_Hora de ``path`` cuyos días están en ``days``, ordenadas por tiempo y ``cell_id``."""
    cells = pd.read_parquet(path)
    missing = [c for c in CELL_COLUMNS if c not in cells.columns]
    if missing:
        raise SystemExit(f"{path}: faltan las columnas {missing}")
    cells = cells.loc[:, list(CELL_COLUMNS)].copy()
    cells["time"] = _utc(cells["time"])
    cells = cells[cells["time"].dt.date.isin(days)]
    return cells.sort_values(["time", "cell_id"]).reset_index(drop=True)


def compose_cells(
    cells: pd.DataFrame,
    region: str,
    recipe: rgb.Recipe,
    size: int,
    window_km: float,
    crops_root: Path,
    out_root: Path,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compone el PNG de cada Celda_Hora de ``cells`` y escribe el manifiesto y las omitidas.

    Reutiliza los PNG existentes salvo ``force``. Devuelve ``(manifest, skipped)``; ninguna
    Celda_Hora detiene la corrida (Req. 3.8, 3.9).
    """
    out_dir = out_root / region / "rgb" / recipe.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = GoesReader(crops_root, region, recipe.bands, require_all=False)
    half_lat = window_km / 2.0 / KM_PER_DEG_LAT
    manifest: list[dict] = []
    skipped: list[dict] = []
    ordered = cells.sort_values(["time", "cell_id"])
    times = [ts.to_pydatetime() for ts in pd.DatetimeIndex(_utc(ordered["time"])).tz_localize(None)]
    for cell_id, t, lat, lon in zip(
        ordered["cell_id"].astype(str).tolist(),
        times,
        ordered["latitude"].astype(float).tolist(),
        ordered["longitude"].astype(float).tolist(),
        strict=True,
    ):
        reader.prune(t)
        stamp = pd.Timestamp(t, tz="UTC")
        scans = reader.scans(t)
        idx = gf.select_scan([s for _, _, s in scans], t)
        if idx is None:
            reason = "sin barrido GOES en (t - 60 min, t]"
            skipped.append({"cell_id": cell_id, "time": stamp, "reason": reason})
            continue
        f, k, scan_start = scans[idx]
        if f.missing:
            reason = f"banda faltante {', '.join(f.missing)} en {f.path.name}"
            skipped.append({"cell_id": cell_id, "time": stamp, "reason": reason})
            continue
        lat_sl = gf.window_slice(f.lat, lat, half_lat)
        lon_sl = gf.window_slice(f.lon, lon, half_lat / math.cos(math.radians(lat)))
        bands = {b: f.window(b, k, lat_sl, lon_sl) for b in recipe.bands}
        fracs = rgb.valid_fractions(bands, recipe)
        low = [f"{b} ({v:.0%})" for b, v in fracs.items() if v < gf.MIN_VALID_FRACTION]
        if low:
            reason = f"menos de 50 % de píxeles válidos en {', '.join(low)}"
            skipped.append({"cell_id": cell_id, "time": stamp, "reason": reason})
            continue
        res = rgb.compose(bands, recipe, size)
        rel = Path(f"{t:%Y%m%d}") / f"{cell_id}.png"
        png_file = out_dir / rel
        if png_file.exists() and not force:
            data = png_file.read_bytes()
        else:
            data = rgb.to_png_bytes(res.rgb)
            png_file.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes(data, png_file)
        h, w = res.normalized.shape[:2]
        manifest.append(
            {
                "cell_id": cell_id,
                "png_path": rel.as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "recipe": recipe.name,
                "recipe_version": recipe.version,
                "scan_start": pd.Timestamp(scan_start, tz="UTC"),
                "window_km": float(window_km),
                "size_px": int(size),
                "scale_px_per_px": size / max(h, w),
                "missing_frac": res.missing_frac,
            }
        )
    man = pd.DataFrame(manifest, columns=MANIFEST_COLUMNS)
    man["scan_start"] = _utc(man["scan_start"])
    skp = pd.DataFrame(skipped, columns=SKIPPED_COLUMNS)
    skp["time"] = _utc(skp["time"])
    _write_parquet(man, out_dir / "manifest.parquet")
    _write_parquet(skp, out_dir / "skipped.parquet")
    print(f"{recipe.tag}: {len(man)} imágenes, {len(skp)} Celdas_Hora omitidas", flush=True)
    return man, skp


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada: valida la receta y compone las Celdas_Hora del rango pedido."""
    p = common.parser(__doc__, "las imágenes")
    p.add_argument("--cells", type=Path, required=True, help="cells.parquet con las Celdas_Hora")
    p.add_argument("--recipe", default="ir_wv", help="receta RGB (por defecto ir_wv)")
    p.add_argument(
        "--recipe-version", type=int, default=1, help="versión de la receta (por defecto 1)"
    )
    p.add_argument(
        "--size",
        type=int,
        default=rgb.DEFAULT_SIZE,
        help=f"lado del PNG en píxeles, {rgb.MIN_SIZE}–{rgb.MAX_SIZE} (por defecto {rgb.DEFAULT_SIZE})",
    )
    p.add_argument(
        "--window-km", type=float, default=100.0, help="lado de la ventana en km (por defecto 100)"
    )
    a = p.parse_args(argv)
    try:
        recipe = rgb.validate_recipe(a.recipe, a.recipe_version)
    except ValueError as e:
        raise SystemExit(f"error: {e}") from e
    if not rgb.MIN_SIZE <= a.size <= rgb.MAX_SIZE:
        raise SystemExit(f"error: --size {a.size} fuera de {rgb.MIN_SIZE}–{rgb.MAX_SIZE}")
    if a.window_km <= 0:
        raise SystemExit("error: --window-km debe ser positivo")
    reg = common.region_of(a)
    cells = read_cells(a.cells, common.days(a))
    compose_cells(cells, reg.name, recipe, a.size, a.window_km, common.CROPS, MODEL_DATA, a.force)


if __name__ == "__main__":
    main()
