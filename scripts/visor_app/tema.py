"""Identidad visual del visor: la paleta de ``web/index.html``, la plantilla de plotly y el CSS fino.

El tema base (colores y fuentes de los widgets) vive en ``.streamlit/config.toml``; aquí está lo que
config.toml no alcanza: los gráficos y los detalles del navegador (selección de texto, cifras
tabulares, la bitácora y la ficha de umbrales).
"""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

GROUND, SURFACE, SURFACE_2, LINE = "#E4E9EB", "#FFFFFF", "#F1F4F5", "#C9D3D6"
INK, INK_2, MUTED = "#0C1518", "#33454B", "#64757B"
ACCENT, ACCENT_SOFT = "#0E6A63", "#D6E8E5"
SEVERE, SEVERE_SOFT = "#D2492A", "#F7E0D8"
COLD, WARM = "#4C7FB8", "#C98A3C"

SANS = "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
MONO = "'JetBrains Mono', ui-monospace, Menlo, monospace"

# Infrarrojo realzado sin rojo (el rojo es de los eventos): suelo cálido oscuro, nube blanca,
# topes fríos en azul frío y los más fríos (≲ 200 K) en tinta.
IR = [
    [0.00, INK],
    [0.10, "#2B4A73"],
    [0.25, COLD],
    [0.38, "#A9C7E6"],
    [0.47, "#F7F9FA"],
    [0.62, "#AEBBBF"],
    [1.00, "#26343A"],
]
VISIBLE = [[0.0, "#1A2428"], [1.0, "#F7F9FA"]]
SECUENCIAL = [[0.0, SURFACE], [0.35, ACCENT_SOFT], [0.7, ACCENT], [1.0, INK]]
DIVERGENTE = [[0.0, COLD], [0.5, "#F7F9FA"], [1.0, WARM]]

pio.templates["cuaderno"] = go.layout.Template(
    layout={
        "font": {"family": SANS, "color": INK, "size": 13},
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "colorway": [ACCENT, SEVERE, COLD, WARM, MUTED, INK_2],
        "title": {"font": {"family": SANS, "size": 15, "color": INK}, "x": 0, "xanchor": "left"},
        "xaxis": {"gridcolor": SURFACE_2, "linecolor": LINE, "zerolinecolor": LINE, "ticks": ""},
        "yaxis": {"gridcolor": SURFACE_2, "linecolor": LINE, "zerolinecolor": LINE, "ticks": ""},
        "hoverlabel": {
            "bgcolor": SURFACE,
            "bordercolor": LINE,
            "font": {"family": MONO, "size": 12, "color": INK},
        },
        "legend": {"font": {"size": 12}, "bgcolor": "rgba(255,255,255,0.8)"},
        "margin": {"l": 56, "r": 10, "t": 44, "b": 36},
    }
)
pio.templates.default = "cuaderno"

CSS = f"""
<style>
::selection {{ background: {ACCENT_SOFT}; color: {INK}; }}
code, .mono {{ font-family: {MONO}; font-variant-numeric: tabular-nums; }}
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{ font-variant-numeric: tabular-nums; }}
h1 {{ letter-spacing: -0.01em; }}
.lede {{ color: {INK_2}; font-size: 1.08rem; max-width: 68ch; line-height: 1.5; margin: -0.4rem 0 0.6rem; }}
.nota {{ color: {MUTED}; font-size: 0.86rem; line-height: 1.45; max-width: 75ch; }}
.ficha {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
.ficha th {{ text-align: left; font-weight: 600; color: {MUTED}; font-size: 0.78rem;
  border-bottom: 1px solid {LINE}; padding: 4px 6px; }}
.ficha td {{ padding: 6px; border-bottom: 1px solid {SURFACE_2}; vertical-align: baseline; }}
.ficha td.num {{ font-family: {MONO}; font-variant-numeric: tabular-nums; text-align: right;
  white-space: nowrap; }}
.ficha .ref {{ font-family: {SANS}; white-space: normal; color: {MUTED}; font-size: 0.8rem;
  display: inline-block; max-width: 11em; text-align: right; line-height: 1.25; }}
.ficha tr.supera td.num.valor {{ color: {SEVERE}; font-weight: 600; }}
.ficha .marca {{ display: inline-block; min-width: 4.6em; font-size: 0.74rem; font-weight: 600;
  padding: 1px 6px; border-radius: 3px; text-align: center; }}
.ficha tr.supera .marca {{ background: {SEVERE_SOFT}; color: #9A2F17; }}
.ficha tr.bajo .marca {{ background: {SURFACE_2}; color: {MUTED}; }}
.regla {{ margin: -0.35rem 0 0.4rem; }}
.regla-pista {{ position: relative; height: 18px; margin: 0 9px; border-bottom: 1px solid {LINE}; }}
.regla-ev {{ position: absolute; bottom: 0; width: 0; height: 0; transform: translateX(-5px);
  border-left: 5px solid transparent; border-right: 5px solid transparent;
  border-bottom: 9px solid {SEVERE}; }}
.regla-ahora {{ position: absolute; bottom: -4px; width: 2px; height: 20px; background: {ACCENT};
  transform: translateX(-1px); border-radius: 1px; }}
.regla-horas {{ display: flex; justify-content: space-between; margin: 3px 9px 0;
  font-family: {MONO}; font-size: 0.72rem; color: {MUTED}; }}
.block-container {{ padding-top: 2.2rem; }}
[data-testid="stMain"], [data-testid="stHeader"] {{ background: {GROUND}; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"],
[data-testid="stMain"] [data-testid="stDataFrame"],
[data-testid="stMain"] [data-testid="stExpander"] details,
[data-testid="stMain"] .ficha {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 6px; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"] {{ padding: 6px 4px 2px; }}
[data-testid="stMain"] .ficha {{ border-collapse: separate; border-spacing: 0; overflow: hidden; }}
h2, h3, [data-testid="stSidebar"] h2 {{ font-family: {SANS} !important; font-weight: 700; letter-spacing: 0; }}
.paso {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 6px; padding: 10px 12px;
  font-size: 0.92rem; line-height: 1.45; }}
.paso b {{ font-family: {MONO}; font-weight: 600; color: {ACCENT}; font-size: 0.8rem; }}
</style>
"""


def aplica() -> None:
    """Inyecta el CSS fino del visor en la página actual."""
    st.html(CSS)
