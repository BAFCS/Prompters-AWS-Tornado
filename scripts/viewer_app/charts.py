"""Gráficos plotly del visor: grilla de mapas con costa y eventos, Skew-T, hodógrafo y series de tiempo.

Todos salen por ``_style``, que les pone la plantilla ``notebook`` (o ``notebook_dark``) de
``theme.py`` según el modo activo. El rojo se reserva para los glifos de los eventos del catálogo y las
líneas de umbral chileno, nunca para texto; el color de selección marca el punto elegido.
"""

import base64
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import plotly.colors as pc
import plotly.graph_objects as go
import streamlit as st
from PIL import Image
from plotly.subplots import make_subplots

import common
from viewer_app import components, theme
from viewer_app.state import Point

if TYPE_CHECKING:  # capas importa graficos (Encuadre): solo se usa para anotar
    from viewer_app.layers import Layer


def _style(fig: go.Figure) -> go.Figure:
    """Fija fondo y fuente en el layout de ``fig``: el frontend de Streamlit ignora los de la plantilla."""
    p = theme.colors()
    fig.update_layout(
        template=theme.template(), plot_bgcolor=p.SURFACE, paper_bgcolor=p.SURFACE, separators=", ",
        font={"family": theme.SANS, "color": p.INK, "size": 13},
        hoverlabel={"bgcolor": p.SURFACE, "bordercolor": p.LINE,
                    "font": {"family": theme.MONO, "size": 12, "color": p.INK}},
    )  # fmt: skip
    return fig


@dataclass(frozen=True)
class Extent:
    """Límites de un mapa en grados."""

    north: float
    south: float
    west: float
    east: float

    @property
    def aspect(self) -> float:
        """Escala del eje y respecto del x para que un grado de longitud mida lo que mide en terreno."""
        return float(1 / np.cos(np.deg2rad((self.north + self.south) / 2)))


def events_extent(ev: pd.DataFrame, reg: common.Region, margin: float = 2.0) -> Extent:
    """Encuadre de los eventos del día con ``margin`` grados, recortado a la región."""
    if ev.empty or ev["lat"].isna().all():
        return Extent(reg.north, reg.south, reg.west, reg.east)
    return Extent(
        min(reg.north, ev["lat"].max() + margin),
        max(reg.south, ev["lat"].min() - margin),
        max(reg.west, ev["lon"].min() - margin - 1),
        min(reg.east, ev["lon"].max() + margin),
    )


def _point(point: Point, size: int) -> list[go.Scatter]:
    """El punto elegido como doble anillo: halo del color de la hoja y anillo de selección encima.

    El halo lo separa de cualquier fondo, también de los topes fríos azules del infrarrojo.
    """
    p = theme.colors()
    text = [f"<b>{point.name}</b><br>{components.coord(point.lat, point.lon)}"]
    return [
        go.Scatter(
            x=[point.lon], y=[point.lat], mode="markers", hoverinfo="skip",
            marker={"symbol": "circle-open", "size": size, "color": p.SURFACE, "line": {"width": 5.5}},
            unselected={"marker": {"opacity": 1}},
        ),
        go.Scatter(
            x=[point.lon], y=[point.lat], mode="markers", hoverinfo="text", text=text,
            marker={"symbol": "circle-open", "size": size, "color": p.SELECTION, "line": {"width": 2.5}},
            unselected={"marker": {"opacity": 1}},
        ),
    ]  # fmt: skip


# --- Grilla de Mapas -----------------------------------------------------------------------------
def grid_shape(n: int, columns: int = 3) -> tuple[int, int]:
    """Filas y columnas según los paneles y el espacio disponible."""
    cols = max(1, min(columns, n, 2 if n <= 4 else 3))
    return max(1, (n + cols - 1) // cols), cols


# Lado mayor de la grilla invisible que da el valor bajo el cursor y recibe el clic.
HOVER_CELLS = 120
ERA5_STEP = (
    0.25  # la grilla de clic nunca es más gruesa que ERA5, que es lo que usan Sondeo y Series
)


@st.cache_data(max_entries=64, show_spinner=False)
def _png(z: np.ndarray, colorscale: str, lo: float, hi: float) -> str:
    """``z`` (de sur a norte) coloreada con ``colorscale`` entre ``lo`` y ``hi``, como PNG en data-URI.

    Un RGB ``uint8`` pasa tal cual; en un campo, NaN queda transparente. Plotly dibuja la imagen sin
    volver a rasterizarla en cada zoom, a diferencia de un ``go.Heatmap`` del mismo tamaño.
    """
    if z.ndim == 3:
        rgba = z
    else:
        colors = pc.sample_colorscale(
            pc.get_colorscale(colorscale), np.linspace(0, 1, 256), colortype="rgb"
        )
        lut = np.array([pc.unlabel_rgb(c) for c in colors]).round().astype(np.uint8)
        i = (
            np.nan_to_num(np.clip((z - lo) / ((hi - lo) or 1.0), 0, 1) * 255, nan=0)
            .round()
            .astype(np.uint8)
        )
        rgba = np.dstack([lut[i], np.where(np.isnan(z), 0, 255).astype(np.uint8)])
    buf = io.BytesIO()  # la fila 0 queda al sur: con ``dy > 0`` plotly voltea la imagen
    Image.fromarray(np.ascontiguousarray(rgba)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def background(
    c: "Layer", colorbar: dict | None = None
) -> list[go.Image | go.Scattergl | go.Scatter]:
    """Trazas de fondo de un panel: la imagen ya coloreada, la grilla invisible y, salvo en RGB, la barra.

    La grilla (un píxel de cada ``step``) da el valor bajo el cursor y el clic que elige el punto:
    Streamlit solo recibe selecciones de trazas de puntos, no de imágenes ni heatmaps. Los puntos sin
    dato van en una segunda grilla que solo muestra las coordenadas. La barra de color
    va en un punto aparte que no se dibuja: colorear cada marcador de la grilla triplica el costo del
    zoom. Los cuadros de la animación usan estas mismas trazas sin ``colorbar``: plotly conserva la inicial.
    """
    up = c.lat[0] > c.lat[-1]
    lat, z = (c.lat[::-1], c.z[::-1]) if up else (c.lat, c.z)
    lo, hi = c.color_range
    image = go.Image(
        source=_png(z, c.colorscale or "gray", lo, hi), x0=float(c.lon[0]),
        dx=float(c.lon[1] - c.lon[0]), y0=float(lat[0]), dy=float(lat[1] - lat[0]), hoverinfo="skip",
    )  # fmt: skip
    # ponytail: el hover da el valor del punto de grilla más cercano, no el del píxel bajo el cursor;
    # si hace falta el exacto, recalcular la grilla con el encuadre visible (requiere un evento de zoom).
    step = max(1, -(-max(z.shape[:2]) // HOVER_CELLS))
    step = min(step, max(1, round(ERA5_STEP / abs(float(lat[1] - lat[0])))))
    LA, LO = np.meshgrid(
        lat[::step].astype(np.float32), c.lon[::step].astype(np.float32), indexing="ij"
    )
    coords = "%{y:.2f}°, %{x:.2f}°"
    # hoverinfo distinto de "skip": con "skip" plotly no emite el clic y Streamlit no se entera.
    marker = {"size": 9, "color": "rgba(0,0,0,0)"}
    if c.is_rgb:
        grid = go.Scattergl(x=LO.ravel(), y=LA.ravel(), mode="markers", marker=marker,
                            hovertemplate=coords + "<extra></extra>")  # fmt: skip
        return [image, grid]
    values = z[::step, ::step].ravel()
    ok = np.isfinite(values)
    grid = go.Scattergl(
        x=LO.ravel()[ok], y=LA.ravel()[ok], customdata=values[ok], mode="markers", marker=marker,
        hovertemplate=coords + "<br><b>%{customdata:.3g}</b> " + c.unit + "<extra></extra>",
    )  # fmt: skip
    empty = go.Scattergl(
        x=LO.ravel()[~ok], y=LA.ravel()[~ok], mode="markers", marker=marker,
        hovertemplate=coords + "<br>sin dato<extra></extra>",
    )  # fmt: skip
    bar = go.Scatter(
        x=[None], y=[None], mode="markers", hoverinfo="skip",
        marker={"color": [lo], "colorscale": c.colorscale, "cmin": lo, "cmax": hi,
                "showscale": c.kind is not None, "colorbar": colorbar},
    )  # fmt: skip
    return [image, grid, empty, bar]


def _threshold(c: "Layer", width: float) -> go.Contour:
    """Línea del umbral chileno de ``c`` en rojo."""
    return go.Contour(
        z=c.z, x=c.lon, y=c.lat, showscale=False, hoverinfo="skip",
        contours={"start": c.threshold, "end": c.threshold, "size": 1, "coloring": "none"},
        line={"color": theme.colors().SEVERE, "width": width},
    )  # fmt: skip


def _layout(fig: go.Figure, name: str) -> Any:  # noqa: ANN401
    """Propiedad ``name`` del layout de ``fig`` (los stubs de plotly no tipan ``layout[...]``)."""
    return fig.layout[name]


def grid(
    layers: list["Layer"], contours: list["Layer | None"], enc: Extent, coast: tuple[np.ndarray, np.ndarray],
    *, events: pd.DataFrame | None = None, point: Point | None = None,
    wind: tuple[list, list] | None = None,
    height: int | None = None, columns: int = 3,
) -> tuple[go.Figure, list[int]]:  # fmt: skip
    """Paneles en una figura con los ejes compartidos: el zoom y el desplazamiento van juntos.

    ``contornos[i]`` es un campo ERA5 que se dibuja como isolíneas sobre el panel ``i`` (o ``None``).
    Devuelve la figura y el índice de la primera traza de fondo de cada panel (``background``), para
    animarla con ``go.Frame``. ``height`` fija la altura en píxeles (si falta, depende del número de filas).
    """
    rows, cols = grid_shape(len(layers), columns)
    fig = make_subplots(
        rows=rows, cols=cols, horizontal_spacing=0.09 if cols > 1 else 0.02,
        vertical_spacing=0.12 / rows, subplot_titles=[c.title for c in layers],
    )  # fmt: skip
    backgrounds: list[int] = []
    for i, (c, cont) in enumerate(zip(layers, contours, strict=True)):
        r, k = i // cols + 1, i % cols + 1
        xd, yd = (_layout(fig, f"{axis}axis{i + 1 if i else ''}").domain for axis in "xy")
        colorbar = {
            "title": {"text": c.unit, "side": "right"}, "thickness": 10, "outlinewidth": 0,
            "x": xd[1] + 0.004, "xanchor": "left", "y": (yd[0] + yd[1]) / 2, "len": (yd[1] - yd[0]) * 0.9,
        }  # fmt: skip
        backgrounds.append(len(fig.data))  # pyright: ignore[reportArgumentType]
        fig.add_traces(background(c, colorbar), rows=r, cols=k)
        if c.threshold is not None and not c.is_rgb:
            fig.add_trace(_threshold(c, 1.6), row=r, col=k)
        if cont is not None:
            fig.add_trace(
                go.Contour(
                    z=cont.z, x=cont.lon, y=cont.lat, showscale=False, hoverinfo="skip", ncontours=8,
                    contours={"coloring": "lines", "showlabels": True,
                              "labelfont": {"size": 10, "color": theme.colors().INK_2}},
                    colorscale=[[0, theme.colors().INK_2], [1, theme.colors().INK_2]], line={"width": 0.8},
                ),
                row=r, col=k,
            )  # fmt: skip
            if cont.threshold is not None:
                fig.add_trace(_threshold(cont, 2.0), row=r, col=k)
        xs, ys = coast
        fig.add_trace(
            go.Scatter(x=xs, y=ys, mode="lines", line={"color": theme.colors().INK, "width": 0.9},
                       hoverinfo="skip"),
            row=r, col=k,
        )  # fmt: skip
        if wind is not None:
            fig.add_trace(
                go.Scatter(x=wind[0], y=wind[1], mode="lines", hoverinfo="skip",
                           line={"color": theme.colors().INK_2, "width": 1}),
                row=r, col=k,
            )  # fmt: skip
        if events is not None and len(events):
            fig.add_trace(
                go.Scatter(
                    x=events["lon"], y=events["lat"], mode="markers", text=events["text"],
                    hoverinfo="text",
                    marker={"symbol": "triangle-up", "size": 11, "color": theme.colors().SEVERE,
                            "line": {"color": theme.colors().SURFACE, "width": 1.2}},
                    unselected={"marker": {"opacity": 1}},
                ),
                row=r, col=k,
            )  # fmt: skip
        if point is not None:
            fig.add_traces(_point(point, 20), rows=r, cols=k)
    for i, a in enumerate(
        _layout(fig, "annotations")
    ):  # títulos alineados a la izquierda del panel
        a.update(x=_layout(fig, f"xaxis{i + 1 if i else ''}").domain[0], xanchor="left",
                 font={"family": theme.SANS, "size": 13, "color": theme.colors().INK})  # fmt: skip
    # constrain="range": con go.Image plotly angostaría el panel en vez de ampliar el rango.
    fig.update_xaxes(range=[enc.west, enc.east], showgrid=False, ticksuffix="°", title=None,
                     constrain="range")  # fmt: skip
    fig.update_yaxes(range=[enc.south, enc.north], showgrid=False, ticksuffix="°", title=None,
                     constrain="range")  # fmt: skip
    # Todos los ejes igualan a los del primer panel (zoom sincronizado); la proporción va solo en el
    # primero, porque scaleanchor y matches en el mismo eje chocan en plotly.
    for i in range(1, rows * cols):
        _layout(fig, f"xaxis{i + 1}").matches = "x"
        _layout(fig, f"yaxis{i + 1}").matches = "y"
    # hoverdistance=-1: con zoom los puntos de la grilla quedan separados y aun así responden.
    fig.update_layout(
        yaxis={"scaleanchor": "x", "scaleratio": enc.aspect},
        height=height or (640 if rows == 1 else 470 * rows), showlegend=False, dragmode="pan",
        clickmode="event+select", hoverdistance=-1, uirevision="grid",
        margin={"t": 110 if cols == 1 else 56, "r": 48},
    )  # fmt: skip
    return _style(fig), backgrounds


# --- Sondeo --------------------------------------------------------------------------------------
SKEW = 35.0  # °C por unidad de ln(p): inclinación de las isotermas del Skew-T


def _x(t: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Coordenada x del Skew-T para la temperatura ``t`` (°C) a la presión ``p`` (hPa)."""
    return t + SKEW * np.log(1000.0 / p)


def skewt(
    p: np.ndarray, t: np.ndarray, td: np.ndarray, parcel: np.ndarray | None, p_lcl: float | None,
    title: str,
) -> go.Figure:  # fmt: skip
    """Diagrama Skew-T log-p con temperatura, punto de rocío y la parcela de superficie."""
    fig = go.Figure()
    pp = np.geomspace(1050, 100, 60)
    for iso in range(-100, 50, 10):
        fig.add_trace(
            go.Scatter(
                x=_x(np.full_like(pp, iso), pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": theme.colors().SURFACE_2 if iso else theme.colors().LINE, "width": 1},
            )
        )  # fmt: skip
    for theta in range(250, 470, 10):  # adiabáticas secas
        tt = theta * (pp / 1000.0) ** 0.2857 - 273.15
        fig.add_trace(
            go.Scatter(
                x=_x(tt, pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": theme.colors().LINE, "width": 0.8, "dash": "dot"},
            )
        )  # fmt: skip
    hover = "%{customdata:.1f} °C · %{y:.0f} hPa<extra>%{fullData.name}</extra>"
    if parcel is not None:
        fig.add_trace(
            go.Scatter(
                x=_x(parcel, p), y=p, customdata=parcel, name="parcela de superficie",
                mode="lines", line={"color": theme.colors().MUTED, "width": 1.6, "dash": "dash"},
                hovertemplate=hover,
            )
        )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(td, p), y=p, customdata=td, name="punto de rocío", mode="lines",
            line={"color": theme.colors().WARM, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(t, p), y=p, customdata=t, name="temperatura", mode="lines",
            line={"color": theme.colors().INK, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    if p_lcl is not None and np.isfinite(p_lcl):
        fig.add_trace(
            go.Scatter(
                x=[-40, 50], y=[p_lcl, p_lcl], mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": theme.colors().MUTED, "width": 1, "dash": "dot"},
            )
        )  # fmt: skip
        fig.add_annotation(  # en ejes log, las anotaciones van en log10
            x=48, y=np.log10(p_lcl), text=f"LCL {p_lcl:.0f} hPa", showarrow=False,
            xanchor="right", yanchor="bottom", font={"size": 11, "color": theme.colors().MUTED},
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
        title={"text": title}, height=600, hovermode="y",
        legend={"orientation": "h", "y": -0.24, "x": 0, "yanchor": "top"}, margin={"b": 140},
    )  # fmt: skip
    return _style(fig)


def hodograph(
    h: np.ndarray, u: np.ndarray, v: np.ndarray, lm: tuple[float, float],
    rm: tuple[float, float], mean: tuple[float, float], title: str,
) -> go.Figure:  # fmt: skip
    """Hodógrafo coloreado por capas, con los movimientos de Bunkers y el viento medio 0–6 km."""
    fig = go.Figure()
    lim = max(10.0, float(np.nanmax(np.abs(np.r_[u, v, lm, rm]))) * 1.15)
    for r in range(10, int(lim) + 10, 10):
        a = np.linspace(0, 2 * np.pi, 120)
        fig.add_trace(
            go.Scatter(
                x=r * np.cos(a), y=r * np.sin(a), mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": theme.colors().SURFACE_2 if r % 20 else theme.colors().LINE, "width": 1},
            )
        )  # fmt: skip
    p = theme.colors()
    layers = ((0, 1000, p.INK, "0–1 km"), (1000, 3000, p.COLD, "1–3 km"),
             (3000, 6000, p.WARM, "3–6 km"), (6000, 10000, p.MUTED, "6–10 km"))  # fmt: skip
    for h0, h1, color, name in layers:
        k = (h >= h0) & (h <= h1)
        if k.sum() < 2:
            continue
        fig.add_trace(
            go.Scatter(
                x=u[k], y=v[k], mode="lines+markers", name=name, customdata=h[k],
                line={"color": color, "width": 3}, marker={"size": 4, "color": color},
                hovertemplate="%{customdata:.0f} m · u %{x:.1f}, v %{y:.1f} m/s<extra></extra>",
            )
        )  # fmt: skip
    for (x, y), name, symbol, color in (
        (lm, "Movimiento estimado: rama left-mover", "diamond", theme.colors().SELECTION),
        (rm, "Movimiento estimado: rama right-mover", "diamond-open", theme.colors().MUTED),
        (mean, "viento medio 0–6 km", "x-thin", theme.colors().INK_2),
    ):
        fig.add_trace(
            go.Scatter(
                x=[x], y=[y], mode="markers", name=name,
                marker={"symbol": symbol, "size": 13, "color": color,
                        "line": {"color": color, "width": 2}},
                hovertemplate=f"{name}<br>u %{{x:.1f}}, v %{{y:.1f}} m/s<extra></extra>",
            )
        )  # fmt: skip
    fig.update_xaxes(
        range=[-lim, lim], zeroline=True, showgrid=False, title="Viento este-oeste, u (m/s)"
    )
    fig.update_yaxes(
        range=[-lim, lim], zeroline=True, showgrid=False, title="Viento norte-sur, v (m/s)",
        scaleanchor="x", scaleratio=1,
    )  # fmt: skip
    fig.update_layout(
        title={"text": title},
        height=600,
        margin={"b": 140},
        legend={"orientation": "h", "y": -0.24, "x": 0, "yanchor": "top"},
    )
    return _style(fig)


# --- Series --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SeriesRow:
    """Una fila del gráfico de series: datos, nombre, unidad y umbral chileno opcional."""

    title: str
    unit: str
    traces: tuple[tuple[pd.Series, str, str], ...]  # (serie con índice de tiempo, nombre, color)
    threshold: float | None = None


def series(rows: list[SeriesRow], events: pd.DataFrame, selected: str | None) -> go.Figure:
    """Series de tiempo apiladas con eje x común, umbrales y la hora de cada evento marcada."""
    fig = make_subplots(
        rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.045,
        subplot_titles=[f"{f.title} ({f.unit})" for f in rows],
    )  # fmt: skip
    in_legend: set[str] = set()  # cada nombre una sola vez, aunque se repita en varias filas
    for i, f in enumerate(rows, start=1):
        for s, name, color in f.traces:
            fig.add_trace(
                go.Scatter(
                    x=s.index, y=s.values, name=name, mode="lines+markers",
                    line={"color": color, "width": 2}, marker={"size": 4},
                    hovertemplate=f"{name}: %{{y:.3g}} {f.unit}<extra></extra>",
                    legendgroup=name, showlegend=name not in in_legend,
                ),
                row=i, col=1,
            )  # fmt: skip
            in_legend.add(name)
        if f.threshold is not None:
            fig.add_hline(  # row/col aceptan int aunque los stubs de plotly digan str
                y=f.threshold, row=i, col=1,  # pyright: ignore[reportArgumentType]
                line={"color": theme.colors().SEVERE, "width": 1, "dash": "dash"},
                annotation_text="valor de comparación", annotation_position="top left",
                annotation_font={"size": 12, "color": theme.colors().MUTED},
            )  # fmt: skip
    for _, ev in events.iterrows():
        if ev["hour"] is None or pd.isna(ev["hour"]):
            continue
        own = ev["id"] == selected
        fig.add_vline(
            x=ev["hour"],
            line={
                "color": theme.colors().SEVERE,
                "width": 2 if own else 1,
                "dash": "solid" if own else "dot",
            },
            opacity=1 if own else 0.45,
        )
        if own:
            fig.add_annotation(
                x=ev["hour"], y=1.08, yref="paper", text=f"{ev['place']} {ev['hour']:%H:%M}",
                showarrow=False, yanchor="bottom", font={"size": 12, "color": theme.colors().INK},
            )  # fmt: skip
    fig.update_layout(
        height=190 * len(rows) + 80, hovermode="x unified",
        legend={"orientation": "h", "y": 1.16, "x": 0, "yanchor": "bottom"},
        margin={"t": 110},
    )  # fmt: skip
    fig.update_xaxes(tickformat="%H:%M")  # sin la fecha en inglés que plotly agrega por defecto
    return _style(fig)
