"""Piezas HTML pequeñas que plotly y los widgets no resuelven: la ficha de umbrales y la regla de tiempo."""

import html
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr


@dataclass(frozen=True)
class Fila:
    """Una fila de la ficha: índice, valor en el punto, extremo de la zona y umbral chileno."""

    nombre: str
    unidad: str
    punto: float | None
    zona: float | None
    umbral: float | None
    sentido: str | None  # ">" o "<": dirección del criterio de comparación
    referencia: str | None = None  # referencia descriptiva para índices sin criterio


def _num(v: float | None) -> str:
    """Número con 3 cifras significativas y coma decimal, o una raya si falta."""
    if v is None or not np.isfinite(v):
        return "—"
    s = f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}".replace(",", " ")
    return s.replace(".", ",")


def coord(lat: float, lon: float) -> str:
    """Coordenadas con 2 decimales, coma decimal y signo menos tipográfico: ``−36,73°, −71,81°``."""
    return ", ".join(f"{v:.2f}°".replace(".", ",").replace("-", "−") for v in (lat, lon))


def ficha(filas: list[Fila], col_punto: str, col_zona: str | None) -> str:
    """Tabla de valores, criterios y referencias que distingue los datos ausentes."""
    cab = f"<th>Índice</th><th style='text-align:right'>{html.escape(col_punto)}</th>"
    if col_zona:
        cab += f"<th style='text-align:right'>{html.escape(col_zona)}</th>"
    cab += "<th style='text-align:right'>Criterio</th><th>Resultado</th>"
    cuerpo = []
    for f in filas:
        ref = f.zona if col_zona else f.punto
        clase = "bajo"
        if ref is None or not np.isfinite(ref):
            marca = "Sin datos"
        elif f.umbral is None:
            marca = "Sin criterio de decisión"
        elif ref > f.umbral if f.sentido == ">" else ref < f.umbral:
            clase, marca = "supera", "Cumple el criterio"
        else:
            marca = "No cumple el criterio"
        if f.umbral is not None:
            umbral = html.escape(f"{f.sentido} {_num(f.umbral)}")
        elif f.referencia:
            umbral = f"<span class='ref'>{html.escape(f.referencia)}</span>"
        else:
            umbral = "—"
        celdas = [
            f"<td>{html.escape(f.nombre)} <span class='nota'>{html.escape(f.unidad)}</span></td>",
            f"<td class='num{'' if col_zona else ' valor'}'>{_num(f.punto)}</td>",
        ]
        if col_zona:
            celdas.append(f"<td class='num valor'>{_num(f.zona)}</td>")
        celdas += [
            f"<td class='num'>{umbral}</td>",
            f"<td><span class='marca'>{marca}</span></td>",
        ]
        cuerpo.append(f"<tr class='{clase}'>{''.join(celdas)}</tr>")
    return f"<table class='ficha'><thead><tr>{cab}</tr></thead><tbody>{''.join(cuerpo)}</tbody></table>"


UNIDADES = {"m s-1": "m/s", "m2 s-2": "m²/s²", "m s-2": "m/s²", "K km-1": "K/km", "1": "",
            "J kg**-1": "J/kg", "m s**-1": "m/s"}  # fmt: skip


CORTOS = {"vgp_01": "VGP₀₋₁", "srh_01": "SRH₀₋₁ left-mover", "srh_03": "SRH₀₋₃ left-mover",
          "cizalle_01": "Cizalle 0–1 km", "cizalle_03": "Cizalle 0–3 km", "cizalle_06": "Cizalle 0–6 km",
          "stp_lm": "STP aproximado left-mover (sin CIN)", "sherbs3": "SHERBS3", "lcl": "Altura del LCL"}  # fmt: skip


def unidad(u: str) -> str:
    """Unidad legible a partir de la notación CF de los NetCDF (``m s-1`` → ``m/s``)."""
    return UNIDADES.get(u, u)


INDICES_FICHA = ("vgp_01", "srh_01", "cizalle_01", "stp_lm", "sherbs3", "lcl", "cizalle_06")

REFERENCIAS = {
    "cizalle_06": "Sin criterio local de decisión; comparar con el contexto del caso",
    "sherbs3": "SHERBE ≥ 1 corresponde a otra variante; no es un umbral de SHERBS3",
}


def filas_indices(
    ds: xr.Dataset, t: np.datetime64 | pd.Timestamp, punto: tuple[float, float] | None,
    zona: tuple[float, float, float, float] | None,
) -> list[Fila]:  # fmt: skip
    """Filas de la ficha para la hora ERA5 más cercana a ``t``.

    ``punto`` es (lat, lon); ``zona`` es (norte, sur, oeste, este) y da el extremo en el sentido del
    comparación (máximo si el criterio es ``>``, mínimo si es ``<``).
    """
    h = ds.sel(time=t, method="nearest")
    filas = []
    for v in INDICES_FICHA:
        if v not in h:
            continue
        a = h[v].attrs
        umbral, sentido = a.get("umbral_chile"), a.get("umbral_sentido")
        vp = None
        if punto is not None:
            vp = float(h[v].sel(latitude=punto[0], longitude=punto[1], method="nearest"))
        vz = None
        if zona is not None:
            n, s, o, e = zona
            r = h[v].sel(latitude=slice(n, s), longitude=slice(o, e))
            if r.size:
                vz = float(r.max() if sentido != "<" else r.min())
        filas.append(
            Fila(
                CORTOS.get(v) or str(a.get("long_name", v)), unidad(a.get("units", "")), vp, vz, None if umbral is None else float(umbral), sentido, REFERENCIAS.get(v, a.get("referencia")),
            )
        )  # fmt: skip
    return filas


def regla(tiempos: list[np.datetime64], eventos: pd.DataFrame, actual: np.datetime64) -> str:
    """Regla de tiempo en HTML: el día, los eventos como triángulos y la hora elegida.

    Va en HTML y CSS (sin SVG), porque ``st.html`` sanea el SVG. Los estilos usan comillas dobles
    en el atributo para que los nombres de fuente entre comillas simples no lo corten.
    """
    if not tiempos:
        return ""
    t0, t1 = pd.Timestamp(tiempos[0]), pd.Timestamp(tiempos[-1])
    span = max((t1 - t0).total_seconds(), 1.0)

    def x(t: pd.Timestamp) -> float:
        """Posición horizontal (0–100 %) de ``t`` en la regla."""
        return 100 * min(max((t - t0).total_seconds() / span, 0.0), 1.0)

    marcas, nombres = [], []
    for _, ev in eventos.iterrows():
        if ev["hora"] is None or pd.isna(ev["hora"]):
            continue
        nombres.append(f"{ev['hora']:%H:%M} {ev['lugar']}")
        titulo = html.escape(f"{ev['hora']:%H:%M} UTC · {ev['lugar']}", quote=True)
        marcas.append(
            f'<span class="regla-ev" style="left:{x(pd.Timestamp(ev["hora"])):.2f}%" title="{titulo}"></span>'
        )
    # El title de cada triángulo solo aparece al pasar el ratón: la lista completa va en la etiqueta.
    etiqueta = f"Hora elegida {pd.Timestamp(actual):%H:%M} UTC. " + (
        f"Eventos del día (UTC): {'; '.join(nombres)}." if nombres else "Sin eventos con hora."
    )
    return (
        f'<div class="regla" role="img" aria-label="{html.escape(etiqueta, quote=True)}">'
        f'<div class="regla-pista">{"".join(marcas)}'
        f'<span class="regla-ahora" style="left:{x(pd.Timestamp(actual)):.2f}%"></span></div>'
        f'<div class="regla-horas"><span>{t0:%H:%M}</span><span>{t1:%H:%M} UTC</span></div></div>'
    )
