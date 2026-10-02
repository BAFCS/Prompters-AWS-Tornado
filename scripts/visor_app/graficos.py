"""Gráficos plotly del visor: mapa con costa y eventos, Skew-T, hodógrafo y series de tiempo.

Todos usan la plantilla ``cuaderno`` de ``tema.py``. El rojo de severidad se reserva para los
eventos del catálogo y para las líneas de umbral chileno; el verde azulado marca el punto elegido.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import comun
from visor_app import tema
from visor_app.estado import Punto


def _estilo(fig: go.Figure) -> go.Figure:
    """Fija fondo y fuente en el layout de ``fig``: el frontend de Streamlit ignora los de la plantilla."""
    fig.update_layout(
        plot_bgcolor=tema.SURFACE, paper_bgcolor=tema.SURFACE, separators=", ",
        font={"family": tema.SANS, "color": tema.INK, "size": 13},
        hoverlabel={"bgcolor": tema.SURFACE, "bordercolor": tema.LINE,
                    "font": {"family": tema.MONO, "size": 12, "color": tema.INK}},
    )  # fmt: skip
    return fig


@dataclass(frozen=True)
class Encuadre:
    """Límites de un mapa en grados."""

    norte: float
    sur: float
    oeste: float
    este: float

    @property
    def aspecto(self) -> float:
        """Escala del eje y respecto del x para que un grado de longitud mida lo que mide en terreno."""
        return float(1 / np.cos(np.deg2rad((self.norte + self.sur) / 2)))


def encuadre_eventos(ev: pd.DataFrame, reg: comun.Region, margen: float = 2.0) -> Encuadre:
    """Encuadre de los eventos del día con ``margen`` grados, recortado a la región."""
    if ev.empty or ev["lat"].isna().all():
        return Encuadre(reg.norte, reg.sur, reg.oeste, reg.este)
    return Encuadre(
        min(reg.norte, ev["lat"].max() + margen),
        max(reg.sur, ev["lat"].min() - margen),
        max(reg.oeste, ev["lon"].min() - margen - 1),
        min(reg.este, ev["lon"].max() + margen),
    )


def mapa(
    z: np.ndarray, lat: np.ndarray, lon: np.ndarray, enc: Encuadre, costa: tuple[list, list],
    *, titulo: str, unidad: str, escala: list | str, rango: tuple[float, float],
    centro: bool = False, eventos: pd.DataFrame | None = None, punto: Punto | None = None,
    umbral: float | None = None, alto: int = 640, clic: bool = False,
) -> go.Figure:  # fmt: skip
    """Mapa de calor de ``z`` con costa, eventos, punto elegido y la línea del umbral chileno.

    Con ``clic`` agrega una grilla invisible de marcadores sobre cada punto de (``lat``, ``lon``)
    para que un clic en el mapa seleccione el punto más cercano (plotly no selecciona en heatmaps).
    """
    fig = go.Figure(
        layout={"template": "cuaderno"},
        data=go.Heatmap(
            z=z, x=lon, y=lat, colorscale=escala, zmin=rango[0], zmax=rango[1],
            zmid=0 if centro else None,
            colorbar={"title": {"text": unidad, "side": "right"}, "thickness": 12, "outlinewidth": 0},
            hovertemplate="%{y:.2f}°, %{x:.2f}°<br><b>%{z:.3g}</b> " + unidad + "<extra></extra>",
        )
    )  # fmt: skip
    if umbral is not None:
        fig.add_trace(
            go.Contour(
                z=z, x=lon, y=lat, showscale=False, hoverinfo="skip", name="umbral chileno",
                contours={"start": umbral, "end": umbral, "size": 1, "coloring": "none"},
                line={"color": tema.SEVERE, "width": 1.6},
            )
        )  # fmt: skip
    xs, ys = costa
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="lines", line={"color": tema.INK, "width": 0.9}, hoverinfo="skip"
        )
    )
    if clic:
        LA, LO = np.meshgrid(lat, lon, indexing="ij")
        fig.add_trace(
            go.Scatter(
                x=LO.ravel(), y=LA.ravel(), mode="markers", name="grilla",
                marker={"size": 9, "color": "rgba(0,0,0,0)"}, hoverinfo="skip",
                selected={"marker": {"opacity": 0}}, unselected={"marker": {"opacity": 0}},
            )
        )  # fmt: skip
    if eventos is not None and len(eventos):
        fig.add_trace(
            go.Scatter(
                x=eventos["lon"], y=eventos["lat"], mode="markers", text=eventos["texto"],
                hoverinfo="text", name="eventos",
                marker={"symbol": "triangle-up", "size": 12, "color": tema.SEVERE,
                        "line": {"color": tema.SURFACE, "width": 1.2}},
                unselected={"marker": {"opacity": 1}},
            )
        )  # fmt: skip
    if punto is not None:
        fig.add_trace(
            go.Scatter(
                x=[punto.lon], y=[punto.lat], mode="markers", hoverinfo="text",
                text=[f"<b>{punto.nombre}</b><br>{punto.lat:.2f}°, {punto.lon:.2f}°"],
                marker={"symbol": "circle-open", "size": 22, "color": tema.ACCENT,
                        "line": {"width": 2.5}},
                unselected={"marker": {"opacity": 1}},
            )
        )  # fmt: skip
    fig.update_xaxes(range=[enc.oeste, enc.este], showgrid=False, ticksuffix="°", title=None)
    fig.update_yaxes(
        range=[enc.sur, enc.norte], showgrid=False, ticksuffix="°", title=None,
        scaleanchor="x", scaleratio=enc.aspecto,
    )  # fmt: skip
    fig.update_layout(
        title={"text": titulo}, height=alto, showlegend=False, dragmode="pan",
        clickmode="event+select", uirevision="mapa",
    )  # fmt: skip
    return _estilo(fig)


# --- Sondeo --------------------------------------------------------------------------------------
SESGO = 35.0  # °C por unidad de ln(p): inclinación de las isotermas del Skew-T


def _x(t: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Coordenada x del Skew-T para la temperatura ``t`` (°C) a la presión ``p`` (hPa)."""
    return t + SESGO * np.log(1000.0 / p)


def skewt(
    p: np.ndarray, t: np.ndarray, td: np.ndarray, parcela: np.ndarray | None, p_lcl: float | None,
    titulo: str,
) -> go.Figure:  # fmt: skip
    """Diagrama Skew-T log-p con temperatura, punto de rocío y la parcela de superficie."""
    fig = go.Figure(layout={"template": "cuaderno"})
    pp = np.geomspace(1050, 100, 60)
    for iso in range(-100, 50, 10):
        fig.add_trace(
            go.Scatter(
                x=_x(np.full_like(pp, iso), pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.SURFACE_2 if iso else tema.LINE, "width": 1},
            )
        )  # fmt: skip
    for theta in range(250, 470, 10):  # adiabáticas secas
        tt = theta * (pp / 1000.0) ** 0.2857 - 273.15
        fig.add_trace(
            go.Scatter(
                x=_x(tt, pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": "#EADBC6", "width": 0.8, "dash": "dot"},
            )
        )  # fmt: skip
    hover = "%{customdata:.1f} °C · %{y:.0f} hPa<extra>%{fullData.name}</extra>"
    if parcela is not None:
        fig.add_trace(
            go.Scatter(
                x=_x(parcela, p), y=p, customdata=parcela, name="parcela de superficie",
                mode="lines", line={"color": tema.MUTED, "width": 1.6, "dash": "dash"},
                hovertemplate=hover,
            )
        )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(td, p), y=p, customdata=td, name="punto de rocío", mode="lines",
            line={"color": tema.ACCENT, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(t, p), y=p, customdata=t, name="temperatura", mode="lines",
            line={"color": tema.INK, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    if p_lcl is not None and np.isfinite(p_lcl):
        fig.add_trace(
            go.Scatter(
                x=[-40, 50], y=[p_lcl, p_lcl], mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.MUTED, "width": 1, "dash": "dot"},
            )
        )  # fmt: skip
        fig.add_annotation(  # en ejes log, las anotaciones van en log10
            x=48, y=np.log10(p_lcl), text=f"LCL {p_lcl:.0f} hPa", showarrow=False,
            xanchor="right", yanchor="bottom", font={"size": 11, "color": tema.MUTED},
        )  # fmt: skip
    ticks = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]
    fig.update_yaxes(
        type="log", range=[np.log10(1050), np.log10(100)], tickvals=ticks,
        ticktext=[str(v) for v in ticks], title="hPa", showgrid=False,
    )  # fmt: skip
    fig.update_xaxes(
        range=[-40, 50], title="°C (isotermas inclinadas)", showgrid=False, zeroline=False
    )
    fig.update_layout(
        title={"text": titulo}, height=600, hovermode="y",
        legend={"orientation": "h", "y": -0.24, "x": 0, "yanchor": "top"}, margin={"b": 140},
    )  # fmt: skip
    return _estilo(fig)


CAPAS = ((0, 1000, tema.INK, "0–1 km"), (1000, 3000, tema.COLD, "1–3 km"),
         (3000, 6000, tema.WARM, "3–6 km"), (6000, 10000, tema.MUTED, "6–10 km"))  # fmt: skip


def hodografo(
    h: np.ndarray, u: np.ndarray, v: np.ndarray, lm: tuple[float, float],
    rm: tuple[float, float], media: tuple[float, float], titulo: str,
) -> go.Figure:  # fmt: skip
    """Hodógrafo coloreado por capas, con los movimientos de Bunkers y el viento medio 0–6 km."""
    fig = go.Figure(layout={"template": "cuaderno"})
    lim = max(10.0, float(np.nanmax(np.abs(np.r_[u, v, lm, rm]))) * 1.15)
    for r in range(10, int(lim) + 10, 10):
        a = np.linspace(0, 2 * np.pi, 120)
        fig.add_trace(
            go.Scatter(
                x=r * np.cos(a), y=r * np.sin(a), mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.SURFACE_2 if r % 20 else tema.LINE, "width": 1},
            )
        )  # fmt: skip
    for h0, h1, color, nombre in CAPAS:
        k = (h >= h0) & (h <= h1)
        if k.sum() < 2:
            continue
        fig.add_trace(
            go.Scatter(
                x=u[k], y=v[k], mode="lines+markers", name=nombre, customdata=h[k],
                line={"color": color, "width": 3}, marker={"size": 4, "color": color},
                hovertemplate="%{customdata:.0f} m · u %{x:.1f}, v %{y:.1f} m/s<extra></extra>",
            )
        )  # fmt: skip
    for (x, y), nombre, simbolo, color in (
        (lm, "Bunkers left-mover (la del sur)", "diamond", tema.ACCENT),
        (rm, "Bunkers right-mover", "diamond-open", tema.MUTED),
        (media, "viento medio 0–6 km", "x-thin", tema.INK_2),
    ):
        fig.add_trace(
            go.Scatter(
                x=[x], y=[y], mode="markers", name=nombre,
                marker={"symbol": simbolo, "size": 13, "color": color,
                        "line": {"color": color, "width": 2}},
                hovertemplate=f"{nombre}<br>u %{{x:.1f}}, v %{{y:.1f}} m/s<extra></extra>",
            )
        )  # fmt: skip
    fig.update_xaxes(range=[-lim, lim], zeroline=True, showgrid=False, title=None)
    fig.update_yaxes(
        range=[-lim, lim], zeroline=True, showgrid=False, title=None,
        scaleanchor="x", scaleratio=1,
    )  # fmt: skip
    fig.update_layout(
        title={"text": titulo},
        height=600,
        margin={"b": 140},
        legend={"orientation": "h", "y": -0.24, "x": 0, "yanchor": "top"},
    )
    return _estilo(fig)


# --- Series --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Serie:
    """Una fila del gráfico de series: datos, nombre, unidad y umbral chileno opcional."""

    titulo: str
    unidad: str
    trazas: tuple[tuple[pd.Series, str, str], ...]  # (serie con índice de tiempo, nombre, color)
    umbral: float | None = None


def series(filas: list[Serie], eventos: pd.DataFrame, elegido: str | None) -> go.Figure:
    """Series de tiempo apiladas con eje x común, umbrales y la hora de cada evento marcada."""
    fig = make_subplots(
        rows=len(filas), cols=1, shared_xaxes=True, vertical_spacing=0.045,
        subplot_titles=[f"{f.titulo} ({f.unidad})" for f in filas],
    )  # fmt: skip
    for i, f in enumerate(filas, start=1):
        for s, nombre, color in f.trazas:
            fig.add_trace(
                go.Scatter(
                    x=s.index, y=s.values, name=nombre, mode="lines+markers",
                    line={"color": color, "width": 2}, marker={"size": 4},
                    hovertemplate=f"{nombre}: %{{y:.3g}} {f.unidad}<extra></extra>",
                    legendgroup=nombre, showlegend=i == 1 or nombre not in {"punto", "ventana"},
                ),
                row=i, col=1,
            )  # fmt: skip
        if f.umbral is not None:
            fig.add_hline(  # row/col aceptan int aunque los stubs de plotly digan str
                y=f.umbral, row=i, col=1,  # pyright: ignore[reportArgumentType]
                line={"color": tema.SEVERE, "width": 1, "dash": "dash"},
                annotation_text="umbral chileno", annotation_position="top left",
                annotation_font={"size": 10, "color": tema.SEVERE},
            )  # fmt: skip
    for _, ev in eventos.iterrows():
        if ev["hora"] is None or pd.isna(ev["hora"]):
            continue
        propio = ev["id"] == elegido
        fig.add_vline(
            x=ev["hora"],
            line={
                "color": tema.SEVERE,
                "width": 2 if propio else 1,
                "dash": "solid" if propio else "dot",
            },
            opacity=1 if propio else 0.45,
        )
        if propio:
            fig.add_annotation(
                x=ev["hora"], y=1.0, yref="paper", text=f"{ev['lugar']} {ev['hora']:%H:%M}",
                showarrow=False, yanchor="bottom", font={"size": 11, "color": tema.SEVERE},
            )  # fmt: skip
    fig.update_layout(
        template="cuaderno", height=190 * len(filas) + 80, hovermode="x unified",
        legend={"orientation": "h", "y": 1.06, "x": 0, "yanchor": "bottom"},
        margin={"t": 70},
    )  # fmt: skip
    fig.update_xaxes(tickformat="%H:%M")  # sin la fecha en inglés que plotly agrega por defecto
    return _estilo(fig)
