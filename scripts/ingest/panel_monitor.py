#!/usr/bin/env python3
"""Panel orquestador: lee el progreso de las tres fuentes de ingesta en S3 y lo muestra unificado.

Las tres ingestas del experimento de mesociclones (CDS Copernicus, NSF NCAR ERA5 y GOES) escriben
cada una su progreso a un pequeño archivo JSON en el bucket privado de pruebas. Este script LEE esos
tres archivos con ``boto3`` y pinta por ``stdout`` un **panel unificado**: una fila por fuente con
columnas FUENTE, DÍA ACTUAL/TOTAL, PROGRESO %, MB, TIEMPO y ETA (tiempo estimado restante).

Es solo de lectura: no toca las ingestas ni escribe nada en S3. Tolera que un archivo de progreso
aún no exista (la fuente aparece como ``sin iniciar``). Si un JSON no trae un ETA explícito, lo
estima a partir del porcentaje de avance y de los segundos transcurridos.

Esquema esperado de cada JSON de progreso (todas las claves son opcionales; el panel tolera que
falten)::

    {
      "source": "ncar",             # nombre legible de la fuente (si falta, se usa el de la ruta)
      "day_index": 3,              # día que se está procesando (1-based) o días ya completos
      "day_total": 30,            # total de días del trabajo
      "current_day": "2019-05-30", # día en curso (AAAA-MM-DD), informativo
      "percent": 42.5,            # porcentaje de avance 0..100 (si falta, se deriva de los días)
      "mb": 1234.5,               # MB transferidos desde la fuente hasta ahora
      "elapsed_seconds": 530.0,    # segundos de pared transcurridos (si falta, se deriva de started_at)
      "started_at": "2026-10-15T03:00:00+00:00",  # ISO 8601; alternativa a elapsed_seconds
      "eta_seconds": 720.0,        # ETA explícito en segundos (si falta, se estima)
      "status": "running",         # running | done | error | ... (informativo)
      "updated_at": "2026-10-15T03:08:50+00:00"   # última escritura (informativo)
    }

Fuentes (lectura, con credenciales de la cuenta; bucket regional en us-east-1)::

    s3://mesocyclonic-test-data-20261015013924290100000003/experimentos/progreso.json       (CDS)
    s3://mesocyclonic-test-data-20261015013924290100000003/experimentos/progreso_ncar.json  (NCAR)
    s3://mesocyclonic-test-data-20261015013924290100000003/experimentos/progreso_goes.json  (GOES)

Uso::

    uv run python scripts/ingest/panel_monitor.py --once
    uv run python scripts/ingest/panel_monitor.py --watch 15

No ejecuta nada al importarse: todo ocurre bajo ``main()``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# Bucket y prefijo de los archivos de progreso del experimento.
BUCKET = "mesocyclonic-test-data-20261015013924290100000003"
PREFIX = "experimentos"
AWS_REGION = "us-east-1"

# Fuentes del panel: (etiqueta visible, clave S3 de su JSON de progreso). El orden fija las filas.
SOURCES: list[tuple[str, str]] = [
    ("CDS", f"{PREFIX}/progreso.json"),
    ("NCAR", f"{PREFIX}/progreso_ncar.json"),
    ("GOES", f"{PREFIX}/progreso_goes.json"),
]

# Códigos de "no existe" de S3 que se interpretan como "sin iniciar", no como error.
_NOT_FOUND_CODES = {"NoSuchKey", "404", "NoSuchBucket"}


@dataclass
class Row:
    """Fila ya resuelta del panel, lista para formatear como texto.

    ``started`` indica si la fuente ha arrancado (su JSON existe y pudo leerse). Cuando es ``False``
    el resto de los campos quedan vacíos y la fila se muestra como ``sin iniciar``. ``error`` lleva
    un mensaje breve cuando el JSON existe pero no pudo leerse o parsearse.
    """

    source: str
    started: bool
    day: str = ""
    percent: str = ""
    mb: str = ""
    elapsed: str = ""
    eta: str = ""
    error: str = ""


def _s3_client() -> BaseClient:
    """Cliente S3 de ``boto3`` fijado a us-east-1 (la cuenta solo permite esa región).

    Usa un ``Config`` con reintentos en modo adaptativo y tiempos de espera acotados, para que el
    panel no se cuelgue si S3 tarda: ante un fallo de red se informa en la fila, no se bloquea.
    """
    cfg = Config(
        region_name=AWS_REGION,
        retries={"max_attempts": 3, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=10,
    )
    return boto3.client("s3", config=cfg)


def _fetch(client: BaseClient, key: str) -> dict | None:
    """Lee y parsea el JSON de progreso en ``key``; ``None`` si aún no existe (fuente sin iniciar).

    Devuelve el diccionario del JSON si el objeto existe y es válido. Si S3 responde que el objeto
    no existe, devuelve ``None`` (la fuente aún no arrancó). Cualquier otro problema (JSON inválido,
    permisos, red) se propaga como excepción para que la capa superior lo muestre en la fila.
    """
    try:
        obj = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        if code in _NOT_FOUND_CODES:
            return None
        raise
    raw = obj["Body"].read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("el JSON de progreso no es un objeto")
    return data


def _as_float(value: object) -> float | None:
    """Convierte ``value`` a ``float`` si se puede; ``None`` si es ``None`` o no es numérico."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    """Convierte ``value`` a ``int`` si se puede; ``None`` en caso contrario."""
    f = _as_float(value)
    return None if f is None else int(f)


def _elapsed_seconds(data: dict) -> float | None:
    """Segundos transcurridos: usa ``elapsed_seconds`` o los deriva de ``started_at`` hasta ahora."""
    direct = _as_float(data.get("elapsed_seconds"))
    if direct is not None:
        return max(direct, 0.0)
    started_at = data.get("started_at")
    if isinstance(started_at, str):
        t0 = _parse_iso(started_at)
        if t0 is not None:
            delta = (dt.datetime.now(dt.UTC) - t0).total_seconds()
            return max(delta, 0.0)
    return None


def _parse_iso(value: str) -> dt.datetime | None:
    """Parsea una marca ISO 8601 a ``datetime`` con zona horaria UTC; ``None`` si no es válida."""
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _percent(data: dict) -> float | None:
    """Porcentaje de avance 0..100: usa ``percent`` o lo deriva de ``day_index``/``day_total``."""
    direct = _as_float(data.get("percent"))
    if direct is not None:
        return min(max(direct, 0.0), 100.0)
    idx = _as_int(data.get("day_index"))
    total = _as_int(data.get("day_total"))
    if idx is not None and total:
        return min(max(100.0 * idx / total, 0.0), 100.0)
    return None


def _eta_seconds(data: dict, percent: float | None, elapsed: float | None) -> float | None:
    """ETA en segundos: usa ``eta_seconds`` del JSON o lo estima de ``percent`` y ``elapsed``.

    La estimación supone avance a ritmo constante: si en ``elapsed`` segundos se completó ``percent``
    por ciento, el resto (``100 - percent``) tardará proporcionalmente. No estima si el avance es
    nulo (evita dividir por cero) o ya está completo.
    """
    direct = _as_float(data.get("eta_seconds"))
    if direct is not None:
        return max(direct, 0.0)
    if percent is None or elapsed is None:
        return None
    if percent <= 0.0:
        return None
    if percent >= 100.0:
        return 0.0
    return elapsed * (100.0 - percent) / percent


def _fmt_duration(seconds: float | None) -> str:
    """Formatea una duración en segundos como ``HH:MM:SS`` (o ``MM:SS`` si es menos de una hora)."""
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_day(data: dict) -> str:
    """Columna DÍA ACTUAL/TOTAL: ``idx/total`` y, si está, el día en curso entre paréntesis."""
    idx = _as_int(data.get("day_index"))
    total = _as_int(data.get("day_total"))
    if idx is None and total is None:
        base = "—"
    else:
        base = f"{idx if idx is not None else '?'}/{total if total is not None else '?'}"
    current = data.get("current_day")
    if isinstance(current, str) and current:
        return f"{base} ({current})"
    return base


def _fmt_percent(percent: float | None, status: str) -> str:
    """Columna PROGRESO %: el porcentaje con un decimal, o el estado si es terminal (done/error)."""
    label = status.lower()
    if label == "done":
        return "100.0% (listo)"
    if label == "error":
        return f"{percent:.1f}% (error)" if percent is not None else "error"
    return f"{percent:.1f}%" if percent is not None else "—"


def _fmt_mb(data: dict) -> str:
    """Columna MB: MB transferidos con un decimal, o ``—`` si el JSON no lo trae."""
    mb = _as_float(data.get("mb"))
    return f"{mb:.1f}" if mb is not None else "—"


def build_row(source: str, data: dict | None) -> Row:
    """Resuelve una fila del panel a partir del JSON de una fuente (``None`` = sin iniciar).

    Deriva porcentaje, segundos transcurridos y ETA cuando el JSON no los trae explícitos, y los
    deja ya formateados en la ``Row``. No lanza: cualquier dato ausente queda como ``—``.
    """
    if data is None:
        return Row(source=source, started=False)
    name = data.get("source")
    label = str(name) if isinstance(name, str) and name else source
    status = str(data.get("status", ""))
    percent = _percent(data)
    elapsed = _elapsed_seconds(data)
    eta = _eta_seconds(data, percent, elapsed)
    return Row(
        source=label,
        started=True,
        day=_fmt_day(data),
        percent=_fmt_percent(percent, status),
        mb=_fmt_mb(data),
        elapsed=_fmt_duration(elapsed),
        eta=_fmt_duration(eta),
    )


def collect_rows(client: BaseClient) -> list[Row]:
    """Lee las tres fuentes y devuelve sus filas resueltas, en el orden fijo de ``SOURCES``.

    Un objeto ausente se traduce en una fila ``sin iniciar``; un fallo de lectura (permisos, red o
    JSON inválido) queda registrado en ``Row.error`` sin interrumpir la lectura de las demás.
    """
    rows: list[Row] = []
    for label, key in SOURCES:
        try:
            data = _fetch(client, key)
            rows.append(build_row(label, data))
        except (ClientError, BotoCoreError, ValueError, json.JSONDecodeError) as e:
            rows.append(Row(source=label, started=False, error=f"{e!s:.80}"))
    return rows


# Encabezados de las columnas del panel, en orden.
HEADERS = ["FUENTE", "DÍA ACTUAL/TOTAL", "PROGRESO %", "MB", "TIEMPO", "ETA"]


def _row_cells(row: Row) -> list[str]:
    """Celdas de texto de una fila, en el orden de ``HEADERS``.

    Una fuente sin iniciar muestra ``sin iniciar`` en PROGRESO y guiones en el resto; si hubo un
    error de lectura se antepone un aviso breve en esa misma columna.
    """
    if not row.started:
        status = "sin iniciar" if not row.error else f"sin iniciar (error: {row.error})"
        return [row.source, "—", status, "—", "—", "—"]
    return [row.source, row.day, row.percent, row.mb, row.elapsed, row.eta]


def render_table(rows: list[Row]) -> str:
    """Arma el panel como una tabla ASCII alineada (estilo markdown) a partir de ``rows``.

    Calcula el ancho de cada columna con el contenido real para que todo quede alineado, y agrega la
    fila separadora de markdown bajo los encabezados. Devuelve el bloque completo como texto.
    """
    cells = [_row_cells(r) for r in rows]
    widths = [
        max(len(HEADERS[i]), *(len(c[i]) for c in cells)) if cells else len(HEADERS[i])
        for i in range(len(HEADERS))
    ]

    def line(values: list[str]) -> str:
        padded = [v.ljust(widths[i]) for i, v in enumerate(values)]
        return "| " + " | ".join(padded) + " |"

    sep = "| " + " | ".join("-" * widths[i] for i in range(len(HEADERS))) + " |"
    out = [line(HEADERS), sep, *(line(c) for c in cells)]
    return "\n".join(out)


def render_panel(rows: list[Row]) -> str:
    """Panel completo: título con la marca de tiempo local y la tabla alineada de las fuentes."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Panel de ingesta — {stamp} (bucket {BUCKET}, {AWS_REGION})"
    return f"{title}\n{render_table(rows)}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Interpreta los argumentos: ``--once`` (una lectura) o ``--watch N`` (refresco cada N s)."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="hace una sola lectura, imprime el panel y termina (comportamiento por defecto)",
    )
    mode.add_argument(
        "--watch",
        type=int,
        metavar="N",
        help="refresca el panel cada N segundos hasta interrumpir con Ctrl+C",
    )
    return p.parse_args(argv)


def _clear_screen() -> None:
    """Limpia la terminal con secuencias ANSI (cursor arriba a la izquierda y borrado de pantalla)."""
    sys.stdout.write("\033[H\033[J")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: lee las fuentes y muestra el panel una vez o en bucle según los argumentos."""
    args = parse_args(argv)
    client = _s3_client()

    if args.watch is not None:
        if args.watch <= 0:
            print("--watch espera un número de segundos positivo", file=sys.stderr, flush=True)
            return 2
        try:
            while True:
                rows = collect_rows(client)
                _clear_screen()
                print(render_panel(rows), flush=True)
                print(f"\n(refresco cada {args.watch} s — Ctrl+C para salir)", flush=True)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("", flush=True)
            return 0

    rows = collect_rows(client)
    print(render_panel(rows), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
