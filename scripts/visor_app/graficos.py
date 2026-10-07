"""Gráficos plotly del visor: mapa con costa y eventos, Skew-T, hodógrafo y series de tiempo.

Todos salen por ``_estilo``, que les pone la plantilla ``cuaderno`` (o ``cuaderno_oscuro``) de ``tema.py``
según el modo activo. El
rojo se reserva para los glifos de los eventos del catálogo y las líneas de umbral chileno, nunca para
texto; el color de selección marca el punto elegido.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import comun
from visor_app import componentes, tema
from visor_app.estado import Punto

if TYPE_CHECKING:  # capas importa graficos (Encuadre): solo se usa para anotar
    from visor_app.capas import Capa


def _estilo(fig: go.Figure) -> go.Figure:
    """Fija fondo y fuente en el layout de ``fig``: el frontend de Streamlit ignora los de la plantilla."""
    p = tema.colores()
    fig.update_layout(
        template=tema.plantilla(), plot_bgcolor=p.SURFACE, paper_bgcolor=p.SURFACE, separators=", ",
        font={"family": tema.SANS, "color": p.INK, "size": 13},
        hoverlabel={"bgcolor": p.SURFACE, "bordercolor": p.LINE,
                    "font": {"family": tema.MONO, "size": 12, "color": p.INK}},
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


def _punto(punto: Punto, tam: int) -> list[go.Scatter]:
    """El punto elegido como doble anillo: halo del color de la hoja y anillo de selección encima.

    El halo lo separa de cualquier fondo, también de los topes fríos azules del infrarrojo.
    """
    p = tema.colores()
    texto = [f"<b>{punto.nombre}</b><br>{componentes.coord(punto.lat, punto.lon)}"]
    return [
        go.Scatter(
            x=[punto.lon], y=[punto.lat], mode="markers", hoverinfo="skip",
            marker={"symbol": "circle-open", "size": tam, "color": p.SURFACE, "line": {"width": 5.5}},
            unselected={"marker": {"opacity": 1}},
        ),
        go.Scatter(
            x=[punto.lon], y=[punto.lat], mode="markers", hoverinfo="text", text=texto,
            marker={"symbol": "circle-open", "size": tam, "color": p.SELECCION, "line": {"width": 2.5}},
            unselected={"marker": {"opacity": 1}},
        ),
    ]  # fmt: skip


def mapa(
    z: np.ndarray, lat: np.ndarray, lon: np.ndarray, enc: Encuadre, costa: tuple[list, list],
    *, titulo: str, unidad: str, escala: str, rango: tuple[float, float],
    centro: bool = False, eventos: pd.DataFrame | None = None, punto: Punto | None = None,
    umbral: float | None = None, alto: int = 640, clic: bool = False,
) -> go.Figure:  # fmt: skip
    """Mapa de calor de ``z`` con costa, eventos, punto elegido y la línea del umbral chileno.

    Con ``clic`` agrega una grilla invisible de marcadores sobre cada punto de (``lat``, ``lon``)
    para que un clic en el mapa seleccione el punto más cercano (plotly no selecciona en heatmaps).
    """
    fig = go.Figure(
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
                line={"color": tema.colores().SEVERE, "width": 1.6},
            )
        )  # fmt: skip
    xs, ys = costa
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line={"color": tema.colores().INK, "width": 0.9},
            hoverinfo="skip",
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
                marker={"symbol": "triangle-up", "size": 12, "color": tema.colores().SEVERE,
                        "line": {"color": tema.colores().SURFACE, "width": 1.2}},
                unselected={"marker": {"opacity": 1}},
            )
        )  # fmt: skip
    if punto is not None:
        fig.add_traces(_punto(punto, 22))
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


# --- Grilla de Mapas -----------------------------------------------------------------------------
def disposicion(n: int) -> tuple[int, int]:
    """Filas y columnas de la grilla para ``n`` paneles: 1×1, 1×2, 2×2 (3–4) o 2×3 (5–6)."""
    if n <= 2:
        return 1, max(n, 1)
    if n <= 4:
        return 2, 2
    return 2, 3


def z_fondo(c: "Capa") -> np.ndarray:
    """La matriz de ``c`` como entra a su traza: el RGB pasa a latitud creciente para ``go.Image``."""
    if c.es_rgb and c.lat[0] > c.lat[-1]:
        return c.z[::-1]
    return c.z


def _fondo(c: "Capa", barra: dict) -> go.Heatmap | go.Image:
    """Traza de fondo de un panel: imagen RGB o mapa de calor con su barra de color."""
    if c.es_rgb:
        lat = c.lat[::-1] if c.lat[0] > c.lat[-1] else c.lat
        return go.Image(
            z=z_fondo(c), x0=float(c.lon[0]), dx=float(c.lon[1] - c.lon[0]), y0=float(lat[0]),
            dy=float(lat[1] - lat[0]), hovertemplate="%{y:.2f}°, %{x:.2f}°<extra></extra>",
        )  # fmt: skip
    return go.Heatmap(
        z=c.z, x=c.lon, y=c.lat, colorscale=c.escala, zmin=c.rango[0], zmax=c.rango[1],
        zmid=0 if c.centro else None, colorbar=barra,
        hovertemplate="%{y:.2f}°, %{x:.2f}°<br><b>%{z:.3g}</b> " + c.unidad + "<extra></extra>",
    )  # fmt: skip


def _umbral(c: "Capa", ancho: float) -> go.Contour:
    """Línea del umbral chileno de ``c`` en rojo."""
    return go.Contour(
        z=c.z, x=c.lon, y=c.lat, showscale=False, hoverinfo="skip",
        contours={"start": c.umbral, "end": c.umbral, "size": 1, "coloring": "none"},
        line={"color": tema.colores().SEVERE, "width": ancho},
    )  # fmt: skip


def _layout(fig: go.Figure, nombre: str) -> Any:  # noqa: ANN401
    """Propiedad ``nombre`` del layout de ``fig`` (los stubs de plotly no tipan ``layout[...]``)."""
    return fig.layout[nombre]


def grilla(
    capas: list["Capa"], contornos: list["Capa | None"], enc: Encuadre, costa: tuple[list, list],
    *, eventos: pd.DataFrame | None = None, punto: Punto | None = None,
    clic: tuple[np.ndarray, np.ndarray] | None = None, viento: tuple[list, list] | None = None,
) -> tuple[go.Figure, list[int]]:  # fmt: skip
    """Paneles en una figura con los ejes compartidos: el zoom y el desplazamiento van juntos.

    ``contornos[i]`` es un campo ERA5 que se dibuja como isolíneas sobre el panel ``i`` (o ``None``).
    ``clic`` es la grilla (lat, lon) de marcadores invisibles que hace clicable cada panel. Devuelve la
    figura y el índice de la traza de fondo de cada panel, para animarla con ``go.Frame``.
    """
    filas, cols = disposicion(len(capas))
    fig = make_subplots(
        rows=filas, cols=cols, horizontal_spacing=0.09 if cols > 1 else 0.02,
        vertical_spacing=0.08, subplot_titles=[c.titulo for c in capas],
    )  # fmt: skip
    fondos: list[int] = []
    for i, (c, cont) in enumerate(zip(capas, contornos, strict=True)):
        r, k = i // cols + 1, i % cols + 1
        xd, yd = (_layout(fig, f"{eje}axis{i + 1 if i else ''}").domain for eje in "xy")
        barra = {
            "title": {"text": c.unidad, "side": "right"}, "thickness": 10, "outlinewidth": 0,
            "x": xd[1] + 0.004, "xanchor": "left", "y": (yd[0] + yd[1]) / 2, "len": (yd[1] - yd[0]) * 0.9,
        }  # fmt: skip
        fondos.append(len(fig.data))  # pyright: ignore[reportArgumentType]
        fig.add_trace(_fondo(c, barra), row=r, col=k)
        if c.umbral is not None and not c.es_rgb:
            fig.add_trace(_umbral(c, 1.6), row=r, col=k)
        if cont is not None:
            fig.add_trace(
                go.Contour(
                    z=cont.z, x=cont.lon, y=cont.lat, showscale=False, hoverinfo="skip", ncontours=8,
                    contours={"coloring": "lines", "showlabels": True,
                              "labelfont": {"size": 10, "color": tema.colores().INK_2}},
                    colorscale=[[0, tema.colores().INK_2], [1, tema.colores().INK_2]], line={"width": 0.8},
                ),
                row=r, col=k,
            )  # fmt: skip
            if cont.umbral is not None:
                fig.add_trace(_umbral(cont, 2.0), row=r, col=k)
        xs, ys = costa
        fig.add_trace(
            go.Scatter(x=xs, y=ys, mode="lines", line={"color": tema.colores().INK, "width": 0.9},
                       hoverinfo="skip"),
            row=r, col=k,
        )  # fmt: skip
        if viento is not None:
            fig.add_trace(
                go.Scatter(x=viento[0], y=viento[1], mode="lines", hoverinfo="skip",
                           line={"color": tema.colores().INK_2, "width": 1}),
                row=r, col=k,
            )  # fmt: skip
        if clic is not None:
            LA, LO = np.meshgrid(clic[0], clic[1], indexing="ij")
            fig.add_trace(
                go.Scatter(
                    x=LO.ravel(), y=LA.ravel(), mode="markers", hoverinfo="skip",
                    marker={"size": 9, "color": "rgba(0,0,0,0)"},
                    selected={"marker": {"opacity": 0}}, unselected={"marker": {"opacity": 0}},
                ),
                row=r, col=k,
            )  # fmt: skip
        if eventos is not None and len(eventos):
            fig.add_trace(
                go.Scatter(
                    x=eventos["lon"], y=eventos["lat"], mode="markers", text=eventos["texto"],
                    hoverinfo="text",
                    marker={"symbol": "triangle-up", "size": 11, "color": tema.colores().SEVERE,
                            "line": {"color": tema.colores().SURFACE, "width": 1.2}},
                    unselected={"marker": {"opacity": 1}},
                ),
                row=r, col=k,
            )  # fmt: skip
        if punto is not None:
            fig.add_traces(_punto(punto, 20), rows=r, cols=k)
    for i, a in enumerate(
        _layout(fig, "annotations")
    ):  # títulos alineados a la izquierda del panel
        a.update(x=_layout(fig, f"xaxis{i + 1 if i else ''}").domain[0], xanchor="left",
                 font={"family": tema.SANS, "size": 13, "color": tema.colores().INK})  # fmt: skip
    fig.update_xaxes(range=[enc.oeste, enc.este], showgrid=False, ticksuffix="°", title=None)
    fig.update_yaxes(range=[enc.sur, enc.norte], showgrid=False, ticksuffix="°", title=None)
    # Todos los ejes igualan a los del primer panel (zoom sincronizado); la proporción va solo en el
    # primero, porque scaleanchor y matches en el mismo eje chocan en plotly.
    for i in range(1, filas * cols):
        _layout(fig, f"xaxis{i + 1}").matches = "x"
        _layout(fig, f"yaxis{i + 1}").matches = "y"
    fig.update_layout(
        yaxis={"scaleanchor": "x", "scaleratio": enc.aspecto},
        height=640 if filas == 1 else 470 * filas, showlegend=False, dragmode="pan",
        clickmode="event+select", uirevision="grilla", margin={"t": 56, "r": 48},
    )  # fmt: skip
    return _estilo(fig), fondos


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
    fig = go.Figure()
    pp = np.geomspace(1050, 100, 60)
    for iso in range(-100, 50, 10):
        fig.add_trace(
            go.Scatter(
                x=_x(np.full_like(pp, iso), pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.colores().SURFACE_2 if iso else tema.colores().LINE, "width": 1},
            )
        )  # fmt: skip
    for theta in range(250, 470, 10):  # adiabáticas secas
        tt = theta * (pp / 1000.0) ** 0.2857 - 273.15
        fig.add_trace(
            go.Scatter(
                x=_x(tt, pp), y=pp, mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.colores().LINE, "width": 0.8, "dash": "dot"},
            )
        )  # fmt: skip
    hover = "%{customdata:.1f} °C · %{y:.0f} hPa<extra>%{fullData.name}</extra>"
    if parcela is not None:
        fig.add_trace(
            go.Scatter(
                x=_x(parcela, p), y=p, customdata=parcela, name="parcela de superficie",
                mode="lines", line={"color": tema.colores().MUTED, "width": 1.6, "dash": "dash"},
                hovertemplate=hover,
            )
        )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(td, p), y=p, customdata=td, name="punto de rocío", mode="lines",
            line={"color": tema.colores().WARM, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=_x(t, p), y=p, customdata=t, name="temperatura", mode="lines",
            line={"color": tema.colores().INK, "width": 2.4}, hovertemplate=hover,
        )
    )  # fmt: skip
    if p_lcl is not None and np.isfinite(p_lcl):
        fig.add_trace(
            go.Scatter(
                x=[-40, 50], y=[p_lcl, p_lcl], mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.colores().MUTED, "width": 1, "dash": "dot"},
            )
        )  # fmt: skip
        fig.add_annotation(  # en ejes log, las anotaciones van en log10
            x=48, y=np.log10(p_lcl), text=f"LCL {p_lcl:.0f} hPa", showarrow=False,
            xanchor="right", yanchor="bottom", font={"size": 11, "color": tema.colores().MUTED},
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


def hodografo(
    h: np.ndarray, u: np.ndarray, v: np.ndarray, lm: tuple[float, float],
    rm: tuple[float, float], media: tuple[float, float], titulo: str,
) -> go.Figure:  # fmt: skip
    """Hodógrafo coloreado por capas, con los movimientos de Bunkers y el viento medio 0–6 km."""
    fig = go.Figure()
    lim = max(10.0, float(np.nanmax(np.abs(np.r_[u, v, lm, rm]))) * 1.15)
    for r in range(10, int(lim) + 10, 10):
        a = np.linspace(0, 2 * np.pi, 120)
        fig.add_trace(
            go.Scatter(
                x=r * np.cos(a), y=r * np.sin(a), mode="lines", hoverinfo="skip", showlegend=False,
                line={"color": tema.colores().SURFACE_2 if r % 20 else tema.colores().LINE, "width": 1},
            )
        )  # fmt: skip
    p = tema.colores()
    capas = ((0, 1000, p.INK, "0–1 km"), (1000, 3000, p.COLD, "1–3 km"),
             (3000, 6000, p.WARM, "3–6 km"), (6000, 10000, p.MUTED, "6–10 km"))  # fmt: skip
    for h0, h1, color, nombre in capas:
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
        (lm, "Movimiento estimado: rama left-mover", "diamond", tema.colores().SELECCION),
        (rm, "Movimiento estimado: rama right-mover", "diamond-open", tema.colores().MUTED),
        (media, "viento medio 0–6 km", "x-thin", tema.colores().INK_2),
    ):
        fig.add_trace(
            go.Scatter(
                x=[x], y=[y], mode="markers", name=nombre,
                marker={"symbol": simbolo, "size": 13, "color": color,
                        "line": {"color": color, "width": 2}},
                hovertemplate=f"{nombre}<br>u %{{x:.1f}}, v %{{y:.1f}} m/s<extra></extra>",
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
    en_leyenda: set[str] = set()  # cada nombre una sola vez, aunque se repita en varias filas
    for i, f in enumerate(filas, start=1):
        for s, nombre, color in f.trazas:
            fig.add_trace(
                go.Scatter(
                    x=s.index, y=s.values, name=nombre, mode="lines+markers",
                    line={"color": color, "width": 2}, marker={"size": 4},
                    hovertemplate=f"{nombre}: %{{y:.3g}} {f.unidad}<extra></extra>",
                    legendgroup=nombre, showlegend=nombre not in en_leyenda,
                ),
                row=i, col=1,
            )  # fmt: skip
            en_leyenda.add(nombre)
        if f.umbral is not None:
            fig.add_hline(  # row/col aceptan int aunque los stubs de plotly digan str
                y=f.umbral, row=i, col=1,  # pyright: ignore[reportArgumentType]
                line={"color": tema.colores().SEVERE, "width": 1, "dash": "dash"},
                annotation_text="valor de comparación", annotation_position="top left",
                annotation_font={"size": 10, "color": tema.colores().MUTED},
            )  # fmt: skip
    for _, ev in eventos.iterrows():
        if ev["hora"] is None or pd.isna(ev["hora"]):
            continue
        propio = ev["id"] == elegido
        fig.add_vline(
            x=ev["hora"],
            line={
                "color": tema.colores().SEVERE,
                "width": 2 if propio else 1,
                "dash": "solid" if propio else "dot",
            },
            opacity=1 if propio else 0.45,
        )
        if propio:
            fig.add_annotation(
                x=ev["hora"], y=1.0, yref="paper", text=f"{ev['lugar']} {ev['hora']:%H:%M}",
                showarrow=False, yanchor="bottom", font={"size": 11, "color": tema.colores().INK},
            )  # fmt: skip
    fig.update_layout(
        height=190 * len(filas) + 80, hovermode="x unified",
        legend={"orientation": "h", "y": 1.06, "x": 0, "yanchor": "bottom"},
        margin={"t": 70},
    )  # fmt: skip
    fig.update_xaxes(tickformat="%H:%M")  # sin la fecha en inglés que plotly agrega por defecto
    return _estilo(fig)
