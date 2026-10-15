#!/usr/bin/env python3
"""Ingesta ERA5 desde ``s3://nsf-ncar-era5/`` a un store **Zarr** en S3, recortado a Chile.

Variante del experimento de ingesta: reutiliza la lógica de ``scripts/pipeline/download_era5.py``
(lectura por rango de bytes de los bloques horarios de niveles de presión, lectura directa del
recuadro en superficie) para bajar un día recortado a la región ``south-central-austral`` y, en vez
de escribir un NetCDF local, **escribe el resultado como un store Zarr** en el bucket privado de
pruebas con ``xarray.Dataset.to_zarr`` sobre ``s3fs``.

El objetivo es comparar de forma justa el camino NSF NCAR (rango de bytes sobre el Pool de Datos
Abiertos de AWS) contra el camino CDS (API de Copernicus): el mismo día, la misma región y las
mismas variables, midiendo el **tiempo total** y los **MB transferidos** desde la fuente.

Fuente (lectura, anónima)::

    s3://nsf-ncar-era5/e5.oper.an.pl/...   niveles de presión u, v, t, z  (bloque global por hora)
    s3://nsf-ncar-era5/e5.oper.an.sfc/...  superficie 10u, 10v, 2t, 2d, sp, cape  (solo el recuadro)

Destino (escritura, con credenciales de la cuenta)::

    s3://mesocyclonic-test-data-20261015013924290100000003/era5_store/era5_AAAAMMDD.zarr

Progreso (escritura, con credenciales de la cuenta)::

    s3://mesocyclonic-test-data-20261015013924290100000003/experimentos/progreso_ncar.json

Uso::

    uv run python scripts/ingest/ingest_ncar_zarr.py --date 2019-05-30
    uv run python scripts/ingest/ingest_ncar_zarr.py --start 2019-05-29 --end 2019-05-31

ROBUSTEZ (us-west-2 -> us-east-1). El bucket NSF NCAR vive en ``us-west-2`` y la cuenta del
experimento solo permite ``us-east-1``: la lectura cruza regiones, es lenta y a veces un socket se
cuelga (síntoma observado: ``Unclosed connector`` y el proceso que muere). Para que un día entero no
se pierda por un ítem colgado, **cada lectura de (variable, hora) se envuelve en reintentos con
backoff y un timeout por operación**: si un socket se cuelga, se reintenta; si falla de forma
definitiva, ese ítem se **omite** (se rellena con NaN) y el proceso **continúa** en vez de morir. Al
terminar cada día se **cierran** las sesiones de ``s3fs``/``aiohttp`` para no dejar conectores
abiertos. El volumen reportado en MB es el mismo desde cualquier región.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

import numpy as np
import s3fs
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

# Se reutiliza tal cual la lógica de lectura por rango de bytes y recorte del script de descarga.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import download_era5 as era5  # noqa: E402

# Bucket y prefijo de destino del experimento (store Zarr).
DEST_BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
DEST_PREFIX = "era5_store"
AWS_REGION = "us-east-1"

# Ruta del archivo de progreso que lee el panel orquestador.
PROGRESS_KEY = f"{DEST_BUCKET}/experimentos/progreso_ncar.json"

# Variables fijadas para comparar de forma justa contra el frente CDS.
PL_VARS = ["u", "v", "t", "z"]
SFC_VARS = ["10u", "10v", "2t", "2d", "sp", "cape"]

# Niveles de presión (hPa) del store final, los mismos que pide el frente CDS, para comparar el
# producto de datos de forma justa. OJO: el camino NSF NCAR transfiere igual el bloque global con
# los 37 niveles (no admite recorte en el servidor), así que los MB reportados reflejan ese costo
# real; aquí solo se recorta el Dataset antes de escribir el Zarr.
PRESSURE_LEVELS_HPA = [1000, 925, 850, 700, 500, 300]

# Región del proyecto: Norte -30, Sur -56, Oeste -76, Este -66.
REGION_NAME = "south-central-austral"

# Robustez de la lectura cross-region.
READ_TIMEOUT_S = 180.0  # timeout por operación (una variable/hora o un recuadro de superficie)
READ_ATTEMPTS = 4  # intentos por ítem antes de omitirlo
BACKOFF_BASE_S = 2.0  # espera inicial del backoff exponencial (2, 4, 8… s)


class _ByteMeter:
    """Contador de bytes transferidos desde la fuente, compartido entre las lecturas de un día."""

    def __init__(self) -> None:
        """Arranca el contador en cero."""
        self.total: int = 0

    def add(self, n: int) -> None:
        """Suma ``n`` bytes al total transferido."""
        self.total += n


def _instrumented_s3(meter: _ByteMeter) -> s3fs.S3FileSystem:
    """``S3FileSystem`` anónimo cuyo tráfico de lectura se contabiliza en ``meter``.

    No subclasea: envuelve en la instancia los dos caminos de lectura que usa ``download_era5`` —
    ``cat_file`` (rangos de bytes de los bloques horarios de niveles de presión) y ``open`` (lectura
    del recuadro de superficie) — para que ``meter.total`` refleje todo lo leído de la fuente.
    """
    fs = s3fs.S3FileSystem(anon=True)
    raw_cat: Callable[..., bytes | str] = fs.cat_file
    raw_open = fs.open

    def cat_file(
        path: str, start: int | None = None, end: int | None = None, **kw: object
    ) -> bytes:
        data = raw_cat(path, start=start, end=end, **kw)
        assert isinstance(data, bytes), f"lectura no binaria de {path}"
        meter.add(len(data))
        return data

    def open_(path: str, mode: str = "rb", **kw: object) -> object:
        f = raw_open(path, mode, **kw)
        if "r" in mode:
            raw_read = f.read

            def counting_read(length: int = -1) -> bytes:
                chunk = raw_read(length)
                assert isinstance(chunk, bytes), "lectura no binaria"
                meter.add(len(chunk))
                return chunk

            f.read = counting_read  # type: ignore[method-assign]
        return f

    fs.cat_file = cat_file  # type: ignore[method-assign]
    fs.open = open_  # type: ignore[method-assign]
    return fs


def _close_s3(fs: s3fs.S3FileSystem) -> None:
    """Cierra la sesión de ``s3fs`` y su ``aiohttp.ClientSession`` subyacente.

    Evita el síntoma ``Unclosed connector``/``Unclosed client session`` al terminar: s3fs mantiene
    una sesión asíncrona de aiohttp sobre su propio event loop; ``fs.close_session`` la cierra de
    forma ordenada sobre ese mismo loop. Se protege con ``try`` porque cerrar nunca debe tumbar la
    ingesta.
    """
    try:
        loop = getattr(fs, "loop", None)
        session = getattr(fs, "_session", None)
        if loop is not None and session is not None:
            s3fs.S3FileSystem.close_session(loop, session)
    except Exception as e:  # cerrar es best-effort; no debe interrumpir el flujo
        print(f"  aviso: no se pudo cerrar la sesión s3fs limpiamente: {e!s:.120}", flush=True)
    finally:
        # Vacía la caché de instancias de s3fs para no reutilizar un filesystem con sesión cerrada.
        with contextlib.suppress(Exception):
            type(fs).clear_instance_cache()


def _read_with_timeout_retry(
    fn: Callable[..., dict],
    *args: object,
    label: str,
) -> dict | None:
    """Ejecuta ``fn(*args)`` con timeout por operación y reintentos con backoff.

    Cada intento corre en un hilo aparte para poder abandonarlo si el socket se cuelga más de
    ``READ_TIMEOUT_S``. Ante timeout o error de red se reintenta tras ``2, 4, 8…`` segundos. Si tras
    ``READ_ATTEMPTS`` intentos no hay éxito, devuelve ``None`` para que la ingesta **omita** ese ítem
    y **continúe**, en vez de morir por un único bloque colgado.
    """
    for k in range(READ_ATTEMPTS):
        # Un ejecutor nuevo por intento: así un hilo colgado del intento anterior no bloquea el
        # apagado (no se hace join sobre él) y el siguiente intento abre su propia conexión.
        ex = ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(fn, *args)
        try:
            result = fut.result(timeout=READ_TIMEOUT_S)
            ex.shutdown(wait=False)
            return result
        except FutureTimeoutError:
            reason = f"timeout tras {READ_TIMEOUT_S:.0f} s"
        except Exception as e:  # red, h5py, botocore… cualquier fallo de la lectura
            reason = f"{type(e).__name__}: {e!s:.120}"
        # No se espera al hilo (puede seguir colgado en el socket): se abandona.
        ex.shutdown(wait=False)
        if k == READ_ATTEMPTS - 1:
            print(f"  OMITIDO {label}: {reason} (último intento)", flush=True)
            return None
        wait = BACKOFF_BASE_S * (2**k)
        print(
            f"  reintento {k + 1}/{READ_ATTEMPTS - 1} de {label}: {reason}; espera {wait:.0f} s",
            flush=True,
        )
        time.sleep(wait)
    return None


def _empty_like(template: dict, has_level: bool) -> dict:
    """Lectura ``template`` rellena de NaN, para sustituir un ítem omitido sin romper el apilado.

    Copia coordenadas (``time``, ``lat``, ``lon``, ``level``) y atributos de una lectura buena y pone
    los datos en NaN con la misma forma, de modo que el ``Dataset`` final quede completo en forma y
    el hueco sea explícito (NaN) en vez de hacer caer el proceso.
    """
    out = dict(template)
    out["data"] = np.full_like(np.asarray(template["data"], dtype="f4"), np.nan)
    return out


def _read_group(
    fs: s3fs.S3FileSystem,
    day: dt.date,
    variables: list[str],
    reg: common.Region,
    kind: str,
    on_step: Callable[[float], None],
) -> dict[str, dict]:
    """Lee en serie las ``variables`` de un día para ``kind`` (``"pl"`` o ``"sfc"``), con robustez.

    Para niveles de presión lee cada hora como un bloque global y las concatena; para superficie lee
    el rango de 24 horas del archivo mensual. Reutiliza ``download_era5.read`` pero fuerza el uso del
    sistema de archivos instrumentado monkey-patcheando ``common.s3`` durante la lectura, y envuelve
    cada ítem en ``_read_with_timeout_retry``: un ítem que no se logra leer se **omite** (se rellena
    con NaN) y la lectura **continúa**. ``on_step`` se llama con los MB acumulados tras cada ítem,
    para refrescar el progreso.
    """
    original_s3 = common.s3
    common.s3 = lambda: fs  # type: ignore[assignment]
    try:
        out: dict[str, dict] = {}
        if kind == "pl":
            for v in variables:
                parts: list[dict | None] = []
                for k in range(24):
                    label = f"pl {v} {day:%Y%m%d}T{k:02d}"
                    part = _read_with_timeout_retry(
                        era5.read, era5.pl_path(v, day), reg, k, k + 1, 2**20, label=label
                    )
                    parts.append(part)
                    on_step(0.0)
                # Rellena los huecos (horas omitidas) con un molde NaN tomado de una hora leída, con
                # el ``time`` corregido a la hora que falta, para que el eje de tiempo quede continuo.
                ref = next(((i, p) for i, p in enumerate(parts) if p is not None), None)
                if ref is None:
                    print(
                        f"  AVISO: {v} sin ninguna hora legible; se omite la variable", flush=True
                    )
                    continue
                ref_i, good = ref
                base_time = np.asarray(good["time"]).ravel()[0]
                filled: list[dict] = []
                for k, p in enumerate(parts):
                    if p is not None:
                        filled.append(p)
                        continue
                    hole = _empty_like(good, has_level=True)
                    hole["time"] = base_time + np.timedelta64(k - ref_i, "h")
                    filled.append(hole)
                out[v] = era5.concat_parts(filled)
        else:
            h0, h1 = era5.day_hours(era5.sfc_path(variables[0], day), day)
            good_sfc: dict | None = None
            tmp: dict[str, dict | None] = {}
            for v in variables:
                label = f"sfc {v} {day:%Y%m%d}"
                res = _read_with_timeout_retry(
                    era5.read, era5.sfc_path(v, day), reg, h0, h1, 4 * 2**20, label=label
                )
                tmp[v] = res
                if res is not None and good_sfc is None:
                    good_sfc = res
                on_step(0.0)
            if good_sfc is None:
                print(f"  AVISO: superficie sin ninguna variable legible para {day}", flush=True)
                return out
            for v, res in tmp.items():
                out[v] = res if res is not None else _empty_like(good_sfc, has_level=False)
        return out
    finally:
        common.s3 = original_s3  # type: ignore[assignment]


def _build_dataset(res: dict[str, dict], has_level: bool, reg: common.Region) -> xr.Dataset:
    """Arma un ``xarray.Dataset`` con las variables leídas en ``res`` (con o sin nivel de presión)."""
    r0 = next(iter(res.values()))
    dims = (
        ("time", "level", "latitude", "longitude")
        if has_level
        else ("time", "latitude", "longitude")
    )
    coords = {"time": r0["time"], "latitude": r0["lat"], "longitude": r0["lon"]}
    if has_level:
        coords["level"] = xr.DataArray(r0["level"], dims="level", attrs={"units": "hPa"})
    return xr.Dataset(
        {v: (dims, r["data"], r["attrs"]) for v, r in res.items()},
        coords=coords,
        attrs={
            "source": f"s3://{era5.BUCKET}/ (ERA5, ECMWF; copia NSF NCAR, doi:10.5065/BH6N-5N20)",
            **common.stamp(reg),
        },
    )


def _zarr_store(day: dt.date) -> str:
    """Ruta ``s3://`` del store Zarr de destino para ``day``."""
    return f"s3://{DEST_BUCKET}/{DEST_PREFIX}/era5_{day:%Y%m%d}.zarr"


def _dest_fs() -> s3fs.S3FileSystem:
    """``S3FileSystem`` con credenciales de la cuenta, fijado a us-east-1 (bucket regional)."""
    return s3fs.S3FileSystem(client_kwargs={"region_name": AWS_REGION})


def _write_zarr(ds: xr.Dataset, store: str) -> None:
    """Escribe ``ds`` como store Zarr en ``store`` (S3, con credenciales de la cuenta).

    Usa un ``s3fs`` con credenciales (no anónimo) y un ``FSMap`` como destino de ``to_zarr``.
    Sobrescribe el store si ya existe (``mode="w"``). Cierra la sesión del filesystem de destino al
    terminar para no dejar conectores abiertos.
    """
    dest_fs = _dest_fs()
    try:
        mapper = s3fs.S3Map(root=store, s3=dest_fs, check=False)
        ds.to_zarr(mapper, mode="w", consolidated=True)
    finally:
        _close_s3(dest_fs)


def _write_progress(
    *,
    dia_actual: int,
    dia_total: int,
    hecho: int,
    total: int,
    mb: float,
    segundos: float,
    estado: str,
    eta_segundos: float,
) -> None:
    """Sube ``progreso_ncar.json`` a S3 con el formato EXACTO que lee el panel orquestador.

    Formato::

        {"fuente": "ncar", "dia_actual": N, "dia_total": M, "hecho": N, "total": M,
         "porcentaje": X.X, "mb": Y, "segundos": S, "estado": "en curso", "eta_segundos": E}

    La escritura es best-effort: si falla (p. ej. un corte de red hacia el bucket de destino), se
    informa pero **no** se interrumpe la ingesta, que es lo que de verdad importa.
    """
    porcentaje = round(100.0 * hecho / total, 1) if total else 0.0
    payload: dict[str, Any] = {
        "fuente": "ncar",
        "dia_actual": dia_actual,
        "dia_total": dia_total,
        "hecho": hecho,
        "total": total,
        "porcentaje": porcentaje,
        "mb": round(mb, 1),
        "segundos": round(segundos, 1),
        "estado": estado,
        "eta_segundos": round(eta_segundos, 1),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    fs = _dest_fs()
    try:
        # ``pipe_file`` sube el payload de bytes de una vez (escritura atómica de un objeto pequeño).
        fs.pipe_file(f"s3://{PROGRESS_KEY}", body)
    except Exception as e:  # el progreso nunca debe tumbar la ingesta
        print(f"  aviso: no se pudo escribir el progreso en S3: {e!s:.120}", flush=True)
    finally:
        _close_s3(fs)


class _Progress:
    """Lleva la cuenta de pasos hechos de un día y publica ``progreso_ncar.json`` tras cada paso.

    ``total`` es la suma de ítems de lectura (24 horas × variables de nivel + variables de
    superficie) más un paso final de escritura del Zarr, para que el porcentaje avance de forma
    pareja. El tiempo y los MB se toman de la ingesta en curso.
    """

    def __init__(
        self, dia_actual: int, dia_total: int, total_items: int, meter: _ByteMeter
    ) -> None:
        """Inicializa el contador de progreso del día ``dia_actual`` de ``dia_total``."""
        self.dia_actual = dia_actual
        self.dia_total = dia_total
        self.total = total_items
        self.hecho = 0
        self.meter = meter
        self.t0 = time.time()

    def _eta(self) -> float:
        """Estimación de segundos restantes según el ritmo observado hasta ahora."""
        if self.hecho <= 0:
            return 0.0
        por_item = (time.time() - self.t0) / self.hecho
        return max(0.0, por_item * (self.total - self.hecho))

    def step(self, _mb_delta: float = 0.0, *, estado: str = "en curso") -> None:
        """Suma un paso hecho y publica el progreso en S3."""
        self.hecho = min(self.total, self.hecho + 1)
        _write_progress(
            dia_actual=self.dia_actual,
            dia_total=self.dia_total,
            hecho=self.hecho,
            total=self.total,
            mb=self.meter.total / 2**20,
            segundos=time.time() - self.t0,
            estado=estado,
            eta_segundos=self._eta(),
        )

    def finish(self, estado: str) -> None:
        """Marca el día como terminado (``estado``: ``"completado"`` o ``"error"``) y lo publica."""
        self.hecho = self.total
        _write_progress(
            dia_actual=self.dia_actual,
            dia_total=self.dia_total,
            hecho=self.hecho,
            total=self.total,
            mb=self.meter.total / 2**20,
            segundos=time.time() - self.t0,
            estado=estado,
            eta_segundos=0.0,
        )


def ingest(
    day: dt.date, reg: common.Region, dia_actual: int, dia_total: int
) -> tuple[float, float, str]:
    """Baja el día ``day`` recortado a ``reg`` y lo escribe como Zarr en S3, con progreso.

    Envuelve cada lectura en reintentos con timeout (omite el ítem si falla de forma definitiva),
    publica ``progreso_ncar.json`` tras cada paso y cierra la sesión de ``s3fs`` al terminar.
    Devuelve ``(segundos, mb_transferidos, ruta_store)``: el tiempo total de pared, los MB leídos de
    la fuente NSF NCAR y la ruta del store Zarr escrito.
    """
    fs = _instrumented_s3(meter := _ByteMeter())
    # Pasos: 24 h por cada variable de nivel + 1 por cada variable de superficie + 1 escritura Zarr.
    total_items = 24 * len(PL_VARS) + len(SFC_VARS) + 1
    prog = _Progress(dia_actual, dia_total, total_items, meter)
    t0 = time.time()
    try:
        pl_res = _read_group(fs, day, PL_VARS, reg, "pl", prog.step)
        sfc_res = _read_group(fs, day, SFC_VARS, reg, "sfc", prog.step)

        if not pl_res and not sfc_res:
            raise RuntimeError(f"no se pudo leer ninguna variable para {day}")

        pl_ds = _build_dataset(pl_res, has_level=True, reg=reg) if pl_res else None
        sfc_ds = _build_dataset(sfc_res, has_level=False, reg=reg) if sfc_res else None
        if pl_ds is not None:
            # Recorta a los mismos niveles que pide CDS, intersectando con los realmente presentes.
            keep = [lev for lev in PRESSURE_LEVELS_HPA if lev in pl_ds["level"].values]
            pl_ds = pl_ds.sel(level=keep)
        parts = [d for d in (pl_ds, sfc_ds) if d is not None]
        ds = xr.merge(parts, combine_attrs="override")
        ds.attrs["created"] = common.now()
        ds.attrs["ingest"] = "ncar-byte-range -> zarr"

        store = _zarr_store(day)
        _write_zarr(ds, store)
        prog.step()  # paso de escritura del Zarr
        prog.finish("completado")

        elapsed = time.time() - t0
        return elapsed, meter.total / 2**20, store
    except Exception:
        prog.finish("error")
        raise
    finally:
        _close_s3(fs)


def _parse_days(a: argparse.Namespace) -> list[dt.date]:
    """Lista de días a ingestar según ``--date`` o el rango ``--start``/``--end`` (inclusive)."""
    if a.date is not None:
        return [a.date]
    assert a.start is not None, "usa --date o --start [--end]"
    end = a.end or a.start
    assert end >= a.start, "--end debe ser igual o posterior a --start"
    return [a.start + dt.timedelta(days=i) for i in range((end - a.start).days + 1)]


def main() -> int:
    """Punto de entrada: ingesta uno o varios días a Zarr, con progreso y robustez cross-region."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        default=None,
        help="día único a ingestar, AAAA-MM-DD (UTC); alternativa a --start/--end",
    )
    p.add_argument(
        "--start",
        type=dt.date.fromisoformat,
        default=None,
        help="primer día de un rango, AAAA-MM-DD (UTC)",
    )
    p.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        default=None,
        help="último día del rango (inclusive); por defecto igual a --start",
    )
    a = p.parse_args()
    if a.date is None and a.start is None:
        p.error("se requiere --date (un día) o --start [--end] (un rango)")
    if a.date is not None and (a.start is not None or a.end is not None):
        p.error("usa --date o --start/--end, no ambos")

    days = _parse_days(a)
    reg = common.REGIONS[REGION_NAME]
    dia_total = len(days)

    print(
        f"Ingesta NSF NCAR -> Zarr | {dia_total} día(s) | región {reg.name} "
        f"({reg.north}..{reg.south} lat, {reg.west}..{reg.east} lon)",
        flush=True,
    )
    print(f"  niveles de presión: {', '.join(PL_VARS)}", flush=True)
    print(f"  superficie:         {', '.join(SFC_VARS)}", flush=True)

    exit_code = 0
    for i, day in enumerate(days, start=1):
        print("", flush=True)
        print(f"== Día {i}/{dia_total}: {day} ==", flush=True)
        try:
            elapsed, mb, store = ingest(day, reg, i, dia_total)
        except Exception as e:  # un día que falla no debe tumbar el rango completo
            print(f"ERROR en {day}: {e!s:.200}", file=sys.stderr, flush=True)
            exit_code = 1
            continue
        print(f"Store Zarr escrito en: {store}", flush=True)
        print("Resumen del día (NSF NCAR, rango de bytes -> Zarr):", flush=True)
        print(f"  tiempo total:      {elapsed:.1f} s", flush=True)
        print(f"  MB transferidos:   {mb:.1f} MB (leídos de s3://{era5.BUCKET}/)", flush=True)
        if elapsed > 0:
            print(f"  rendimiento:       {mb / elapsed:.1f} MB/s", flush=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
