"""Piezas HTML pequeñas que plotly y los widgets no resuelven: la ficha de umbrales y la regla de tiempo."""

import html
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr


@dataclass(frozen=True)
class Row:
    """Una fila de la ficha: índice, valor en el punto, extremo de la zona y umbral chileno."""

    name: str
    unit: str
    point: float | None
    area: float | None
    threshold: float | None
    sense: str | None  # ">" o "<": dirección del criterio de comparación
    reference: str | None = None  # referencia descriptiva para índices sin criterio


def _num(v: float | None) -> str:
    """Número con 3 cifras significativas y coma decimal, o una raya si falta."""
    if v is None or not np.isfinite(v):
        return "—"
    s = f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}".replace(",", " ")
    return s.replace(".", ",")


def coord(lat: float, lon: float) -> str:
    """Coordenadas con 2 decimales, coma decimal y signo menos tipográfico: ``−36,73°, −71,81°``."""
    return ", ".join(f"{v:.2f}°".replace(".", ",").replace("-", "−") for v in (lat, lon))


def scorecard(rows: list[Row], point_col: str, area_col: str | None) -> str:
    """Tabla de valores, criterios y referencias que distingue los datos ausentes."""
    head = f"<th>Índice</th><th style='text-align:right'>{html.escape(point_col)}</th>"
    if area_col:
        head += f"<th style='text-align:right'>{html.escape(area_col)}</th>"
    head += "<th style='text-align:right'>Criterio</th><th>Resultado</th>"
    body = []
    for f in rows:
        ref = f.area if area_col else f.point
        css_class = "below"
        if ref is None or not np.isfinite(ref):
            mark = "Sin datos"
        elif f.threshold is None:
            mark = "Sin criterio de decisión"
        elif ref > f.threshold if f.sense == ">" else ref < f.threshold:
            css_class, mark = "exceeds", "Cumple el criterio"
        else:
            mark = "No cumple el criterio"
        if f.threshold is not None:
            threshold = html.escape(f"{f.sense} {_num(f.threshold)}")
        elif f.reference:
            threshold = f"<span class='ref'>{html.escape(f.reference)}</span>"
        else:
            threshold = "—"
        cells = [
            f"<td>{html.escape(f.name)} <span class='note'>{html.escape(f.unit)}</span></td>",
            f"<td class='num{'' if area_col else ' value'}'>{_num(f.point)}</td>",
        ]
        if area_col:
            cells.append(f"<td class='num value'>{_num(f.area)}</td>")
        cells += [
            f"<td class='num'>{threshold}</td>",
            f"<td><span class='verdict'>{mark}</span></td>",
        ]
        body.append(f"<tr class='{css_class}'>{''.join(cells)}</tr>")
    return f"<table class='scorecard'><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


UNITS = {"m s-1": "m/s", "m2 s-2": "m²/s²", "m s-2": "m/s²", "K km-1": "K/km", "1": "",
            "J kg**-1": "J/kg", "m s**-1": "m/s"}  # fmt: skip


SHORT_NAMES = {"vgp_01": "VGP₀₋₁", "srh_01": "SRH₀₋₁ left-mover", "srh_03": "SRH₀₋₃ left-mover",
          "shear_01": "Cizalle 0–1 km", "shear_03": "Cizalle 0–3 km", "shear_06": "Cizalle 0–6 km",
          "stp_lm": "STP aproximado left-mover (sin CIN)", "sherbs3": "SHERBS3", "lcl": "Altura del LCL"}  # fmt: skip


def unit(u: str) -> str:
    """Unidad legible a partir de la notación CF de los NetCDF (``m s-1`` → ``m/s``)."""
    return UNITS.get(u, u)


SCORECARD_INDICES = ("vgp_01", "srh_01", "shear_01", "stp_lm", "sherbs3", "lcl", "shear_06")

REFERENCES = {
    "shear_06": "Sin criterio local de decisión; comparar con el contexto del caso",
    "sherbs3": "SHERBE ≥ 1 corresponde a otra variante; no es un umbral de SHERBS3",
}


def index_rows(
    ds: xr.Dataset, t: np.datetime64 | pd.Timestamp, point: tuple[float, float] | None,
    area: tuple[float, float, float, float] | None,
) -> list[Row]:  # fmt: skip
    """Filas de la ficha para la hora ERA5 más cercana a ``t``.

    ``point`` es (lat, lon); ``area`` es (norte, sur, oeste, este) y da el extremo en el sentido del
    comparación (máximo si el criterio es ``>``, mínimo si es ``<``).
    """
    h = ds.sel(time=t, method="nearest")
    rows = []
    for v in SCORECARD_INDICES:
        if v not in h:
            continue
        a = h[v].attrs
        threshold, sense = a.get("threshold_chile"), a.get("threshold_sense")
        vp = None
        if point is not None:
            vp = float(h[v].sel(latitude=point[0], longitude=point[1], method="nearest"))
        vz = None
        if area is not None:
            n, s, o, e = area
            r = h[v].sel(latitude=slice(n, s), longitude=slice(o, e))
            if r.size:
                vz = float(r.max() if sense != "<" else r.min())
        rows.append(
            Row(
                SHORT_NAMES.get(v) or str(a.get("long_name", v)), unit(a.get("units", "")), vp, vz, None if threshold is None else float(threshold), sense, REFERENCES.get(v, a.get("reference")),
            )
        )  # fmt: skip
    return rows


def ruler(times: list[np.datetime64], events: pd.DataFrame, current: np.datetime64) -> str:
    """Regla de tiempo en HTML: el día, los eventos como triángulos y la hora elegida.

    Va en HTML y CSS (sin SVG), porque ``st.html`` sanea el SVG. Los estilos usan comillas dobles
    en el atributo para que los nombres de fuente entre comillas simples no lo corten.
    """
    if not times:
        return ""
    t0, t1 = pd.Timestamp(times[0]), pd.Timestamp(times[-1])
    span = max((t1 - t0).total_seconds(), 1.0)

    def x(t: pd.Timestamp) -> float:
        """Posición horizontal (0–100 %) de ``t`` en la regla."""
        return 100 * min(max((t - t0).total_seconds() / span, 0.0), 1.0)

    marks, names = [], []
    for _, ev in events.iterrows():
        if ev["hour"] is None or pd.isna(ev["hour"]):
            continue
        names.append(f"{ev['hour']:%H:%M} {ev['place']}")
        title = html.escape(f"{ev['hour']:%H:%M} UTC · {ev['place']}", quote=True)
        marks.append(
            f'<span class="ruler-event" style="left:{x(pd.Timestamp(ev["hour"])):.2f}%" title="{title}"></span>'
        )
    # El title de cada triángulo solo aparece al pasar el ratón: la lista completa va en la etiqueta.
    label = f"Hora elegida {pd.Timestamp(current):%H:%M} UTC. " + (
        f"Eventos del día (UTC): {'; '.join(names)}." if names else "Sin eventos con hora."
    )
    return (
        f'<div class="ruler" role="img" aria-label="{html.escape(label, quote=True)}">'
        f'<div class="ruler-track">{"".join(marks)}'
        f'<span class="ruler-now" style="left:{x(pd.Timestamp(current)):.2f}%"></span></div>'
        f'<div class="ruler-hours"><span>{t0:%H:%M}</span><span>{t1:%H:%M} UTC</span></div></div>'
    )
