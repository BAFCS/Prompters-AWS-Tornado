#!/usr/bin/env python3
"""Reporte comparativo de una corrida de entrenamiento y seleccion del modelo.

Lee los metrics.json e importance.json de baseline_era5, physical y embeddings bajo
--results (carpeta local o s3://<ml>/model/results/<run_id>) y el estado de los trabajos de
SageMaker (--status, opcional: JSON {config: {"status": "Failed", "failure_reason": "..."}}).
Escribe comparacion.json y comparacion.html en el mismo prefijo (o en --out) con POD, FAR, CSI,
conteos, Eventos evaluados, importancia ordenada, PR-AUC y umbral de maximo CSI (informativos),
el caso de desarrollo aparte, las particiones omitidas y el modelo seleccionado: embeddings solo
si su CSI es estrictamente mayor que el de physical; sin seleccion si falta alguno de los dos.

Con --ec2-metrics (metrics.json del flujo EC2 de training.tf) informa la diferencia absoluta de
POD, FAR y CSI de baseline_era5 frente a ese flujo y si todas son <= 0,01 (paridad, Req. 9.6).

Uso::

    uv run python scripts/model/compare_runs.py --results s3://<ml>/model/results/R1
    uv run python scripts/model/compare_runs.py --results s3://<ml>/model/results/R1 \\
        --ec2-metrics s3://<datos>/resultados/metrics.json
"""

from __future__ import annotations

import argparse
import functools
import html
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loeo  # noqa: E402
from table import CONFIGS  # noqa: E402

Reader = Callable[[str], bytes | None]
Writer = Callable[[str, bytes, str], None]
PARITY_TOLERANCE = 0.01
PARITY_METRICS = ("pod", "far", "csi")
COMPLETED = "Completed"


@dataclass(frozen=True)
class JobStatus:
    """Estado final de un trabajo de entrenamiento de SageMaker."""

    status: str  # Completed, Failed, Stopped...
    failure_reason: str = ""
    model_data: str = ""  # S3ModelArtifacts (model.tar.gz)


def join(uri: str, *parts: str) -> str:
    """``uri/parte/...`` sin barras dobles (sirve para rutas locales y ``s3://``)."""
    return "/".join([uri.rstrip("/"), *(p.strip("/") for p in parts)])


def split_s3(uri: str) -> tuple[str, str]:
    """``s3://bucket/clave`` → ``(bucket, clave)``."""
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


class S3ClientLike(Protocol):
    """Lo que se usa de un cliente S3 de boto3."""

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        """Lee un objeto."""
        ...

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object:
        """Escribe un objeto."""
        ...


@functools.cache
def _s3_client() -> S3ClientLike:
    """Cliente S3 de boto3 (se crea una vez y solo si se usa una URI ``s3://``)."""
    import boto3

    return cast(S3ClientLike, boto3.client("s3"))


def default_reader(uri: str) -> bytes | None:
    """Contenido de una ruta local o ``s3://``; ``None`` si no existe."""
    if not uri.startswith("s3://"):
        path = Path(uri)
        return path.read_bytes() if path.is_file() else None
    from botocore.exceptions import ClientError

    bucket, key = split_s3(uri)
    try:
        return _s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def default_writer(uri: str, data: bytes, content_type: str) -> None:
    """Escribe en una ruta local o en ``s3://`` con su Content-Type."""
    if not uri.startswith("s3://"):
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    bucket, key = split_s3(uri)
    _s3_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def read_json(reader: Reader, uri: str) -> dict[str, Any] | None:
    """JSON de ``uri`` o ``None`` si no existe."""
    raw = reader(uri)
    return None if raw is None else json.loads(raw)


def ec2_selection(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    """Métricas de un ``metrics.json`` del flujo EC2 (forma nueva ``selection`` o la histórica)."""
    sel = doc.get("selection")
    return sel if isinstance(sel, Mapping) else doc


def ec2_parity(baseline: Mapping[str, Any], ec2: Mapping[str, Any]) -> dict[str, Any]:
    """Diferencias absolutas de POD, FAR y CSI y si todas son ≤ ``PARITY_TOLERANCE``."""
    delta = {m: abs(float(baseline[m]) - float(ec2[m])) for m in PARITY_METRICS}
    return {
        "sagemaker": {m: float(baseline[m]) for m in PARITY_METRICS},
        "ec2": {m: float(ec2[m]) for m in PARITY_METRICS},
        "abs_delta": delta,
        "tolerance": PARITY_TOLERANCE,
        "within_tolerance": all(v <= PARITY_TOLERANCE + 1e-12 for v in delta.values()),
    }


def compare(
    run_id: str,
    results_uri: str,
    reader: Reader,
    statuses: Mapping[str, JobStatus] | None = None,
    ec2_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Contenido de ``comparacion.json`` de la corrida ``run_id``.

    Una configuración cuyo trabajo no terminó en ``Completed`` o sin ``metrics.json`` queda como
    ``failed`` con su motivo; las demás se conservan (Req. 7.11).
    """
    configs: dict[str, dict[str, Any]] = {}
    results: dict[str, Mapping[str, Any] | loeo.Failure] = {}
    for c in CONFIGS:
        status = (statuses or {}).get(c)
        metrics = None
        if status is not None and status.status != COMPLETED:
            reason = status.failure_reason or f"el trabajo terminó con estado {status.status}"
        else:
            metrics = read_json(reader, join(results_uri, c, "metrics.json"))
            reason = "no se encontró metrics.json" if metrics is None else ""
        if metrics is None:
            configs[c] = {"status": "failed", "reason": reason}
            results[c] = loeo.Failure(reason)
            continue
        importance = read_json(reader, join(results_uri, c, "importance.json")) or {}
        ranked = sorted(importance.items(), key=lambda kv: float(kv[1]), reverse=True)
        configs[c] = {
            "status": "ok",
            "selection": metrics["selection"],
            "development_case": metrics.get("development_case"),
            "informative": metrics.get("informative"),
            "n_folds_skipped": metrics.get("n_folds_skipped", 0),
            "importance": [{"variable": k, "importance": float(v)} for k, v in ranked],
        }
        if status is not None and status.model_data:
            configs[c]["model_data"] = status.model_data
        results[c] = metrics
    sel = loeo.select_model(results)
    out: dict[str, Any] = {
        "run_id": run_id,
        "configs": configs,
        "selected": sel["selected"],
        "rule": sel["rule"],
        "reason": sel["reason"],
    }
    if ec2_metrics is not None:
        base = configs.get("baseline_era5", {})
        if base.get("status") == "ok":
            out["ec2_parity"] = ec2_parity(base["selection"], ec2_selection(ec2_metrics))
        else:
            out["ec2_parity"] = {"error": "baseline_era5 no terminó; no se puede comparar"}
    return out


def _fmt(value: object, digits: int = 3) -> str:
    """Número con ``digits`` decimales o ``-``."""
    return f"{value:.{digits}f}" if isinstance(value, int | float) else "-"


def report_html(doc: Mapping[str, Any]) -> str:
    """HTML autocontenido de ``comparacion.json``."""
    rows = []
    for c, entry in doc["configs"].items():
        if entry["status"] != "ok":
            reason = html.escape(str(entry.get("reason", "")))
            rows.append(f"<tr><td>{c}</td><td colspan=11>falló: {reason}</td></tr>")
            continue
        s, d = entry["selection"], entry.get("development_case") or {}
        info = entry.get("informative") or {}
        top = ", ".join(html.escape(i["variable"]) for i in entry["importance"][:5])
        rows.append(
            f"<tr><td>{c}</td><td>{_fmt(s['pod'])}</td><td>{_fmt(s['far'])}</td>"
            f"<td>{_fmt(s['csi'])}</td><td>{s['hits']}</td><td>{s['misses']}</td>"
            f"<td>{s['false_alarms']}</td><td>{s['n_events']}</td>"
            f"<td>{_fmt(info.get('pr_auc_oof'))}</td><td>{_fmt(info.get('best_csi_threshold'))}</td>"
            f"<td>CSI {_fmt(d.get('csi'))} ({d.get('n_events', 0)} ev.)</td>"
            f"<td>{entry['n_folds_skipped']}</td></tr><tr><td></td>"
            f'<td colspan=11 class="muted">Importancia: {top}</td></tr>'
        )
    selected = doc["selected"] or f"ninguno ({html.escape(str(doc.get('reason') or ''))})"
    parity = ""
    if "ec2_parity" in doc:
        p = doc["ec2_parity"]
        if "abs_delta" in p:
            deltas = " · ".join(f"|Δ{m.upper()}| = {v:.4f}" for m, v in p["abs_delta"].items())
            verdict = "dentro" if p["within_tolerance"] else "fuera"
            parity = (
                f"<h2>Paridad con el flujo EC2 (baseline_era5)</h2><p>{deltas} — {verdict} "
                f"de la tolerancia {p['tolerance']}.</p>"
            )
        else:
            parity = f"<h2>Paridad con el flujo EC2</h2><p>{html.escape(p['error'])}</p>"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparación de configuraciones — {html.escape(str(doc["run_id"]))}</title>
<style>
 body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
   max-width:1100px;margin:0 auto;padding:32px 24px;color:#182230;background:#f4f6fa}}
 table{{width:100%;border-collapse:collapse;background:#fff}} th,td{{padding:6px 8px;
   border-bottom:1px solid #ccd4e0;text-align:left;font-size:14px}} .muted{{color:#5a6675;font-size:13px}}
</style></head><body>
<h1>Comparación de configuraciones — corrida {html.escape(str(doc["run_id"]))}</h1>
<p><strong>Modelo seleccionado: {selected}</strong>. Regla: {html.escape(doc["rule"])}
  (empate → physical). Métricas de selección sin el caso de desarrollo (30-31/05/2019).</p>
<table><thead><tr><th scope="col">Configuración</th><th scope="col">POD</th>
<th scope="col">FAR</th><th scope="col">CSI</th><th scope="col">Aciertos</th>
<th scope="col">Omisiones</th><th scope="col">Falsas alarmas</th><th scope="col">Eventos</th>
<th scope="col">PR-AUC (inf.)</th><th scope="col">Umbral máx. CSI (inf.)</th>
<th scope="col">Caso de desarrollo</th><th scope="col">Particiones omitidas</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p class="muted">PR-AUC y umbral de máximo CSI son informativos: no intervienen en la selección.</p>
{parity}
</body></html>"""


def write_outputs(doc: Mapping[str, Any], out_uri: str, writer: Writer) -> None:
    """Escribe ``comparacion.json`` y ``comparacion.html`` en ``out_uri``."""
    data = json.dumps(doc, indent=2, ensure_ascii=False).encode()
    writer(join(out_uri, "comparacion.json"), data, "application/json")
    writer(join(out_uri, "comparacion.html"), report_html(doc).encode(), "text/html; charset=utf-8")


def load_statuses(raw: Mapping[str, Any]) -> dict[str, JobStatus]:
    """Estados de ``--status`` (``{config: {"status", "failure_reason", "model_data"}}``)."""
    return {
        c: JobStatus(
            str(v.get("status", COMPLETED)),
            str(v.get("failure_reason", "")),
            str(v.get("model_data", "")),
        )
        for c, v in raw.items()
    }


def build_parser() -> argparse.ArgumentParser:
    """Parser de la CLI."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--results", required=True, help="carpeta o s3:// con <config>/metrics.json")
    p.add_argument("--run-id", help="identificador de la corrida (por defecto, el de --results)")
    p.add_argument("--status", help="JSON con el estado de los trabajos por configuración")
    p.add_argument("--ec2-metrics", help="metrics.json del flujo EC2 (ruta o s3://)")
    p.add_argument("--out", help="dónde escribir comparacion.* (por defecto --results)")
    return p


def main(
    argv: list[str] | None = None, reader: Reader | None = None, writer: Writer | None = None
) -> int:
    """Punto de entrada de la CLI; devuelve el código de salida."""
    a = build_parser().parse_args(argv)
    read = reader or default_reader
    run_id = a.run_id or a.results.replace("\\", "/").rstrip("/").split("/")[-1]
    statuses = None
    if a.status:
        raw = read_json(read, a.status)
        if raw is None:
            raise SystemExit(f"error: no existe {a.status}")
        statuses = load_statuses(raw)
    ec2 = None
    if a.ec2_metrics:
        ec2 = read_json(read, a.ec2_metrics)
        if ec2 is None:
            raise SystemExit(f"error: no existe {a.ec2_metrics}")
    doc = compare(run_id, a.results, read, statuses, ec2)
    out = a.out or a.results
    write_outputs(doc, out, writer or default_writer)
    for c, entry in doc["configs"].items():
        if entry["status"] == "ok":
            s = entry["selection"]
            print(f"{c}: POD={s['pod']:.3f} FAR={s['far']:.3f} CSI={s['csi']:.3f}", flush=True)
        else:
            print(f"{c}: falló ({entry['reason']})", flush=True)
    print(f"Modelo seleccionado: {doc['selected'] or 'ninguno'}", flush=True)
    if "ec2_parity" in doc and "abs_delta" in doc["ec2_parity"]:
        p = doc["ec2_parity"]
        deltas = ", ".join(f"{m}={v:.4f}" for m, v in p["abs_delta"].items())
        print(f"Paridad EC2: {deltas} (<= {PARITY_TOLERANCE}: {p['within_tolerance']})")
    print(f"Escrito {join(out, 'comparacion.json')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
