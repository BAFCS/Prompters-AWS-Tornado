"""Identidad visual del visor: las paletas clara y oscura, las plantillas de plotly y el CSS fino.

El tema base (colores y fuentes de los widgets) vive en ``.streamlit/config.toml``, con una tabla
``[theme.light]`` y otra ``[theme.dark]`` que el usuario alterna desde el menú de Streamlit. Aquí está
lo que config.toml no alcanza: los gráficos y los detalles del navegador (selección de texto, cifras
tabulares, la bitácora y la ficha de umbrales). ``colores()`` devuelve la paleta del modo activo.

Las dos paletas salen de cinco colores (Strawberry Red, Honeydew, Frosted Blue, Steel Blue y Deep
Space Blue) y de mezclas entre ellos. El rojo marca (glifos y líneas de eventos y umbrales); nunca es
texto. Las series categóricas de los gráficos que la paleta no cubre usan el azul y el naranja de
Okabe-Ito, aptos para daltonismo. Las escalas de los mapas son estándar y viven en ``colorscales.py``.
"""

from dataclasses import dataclass, fields

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

SANS = "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, Menlo, monospace"


@dataclass(frozen=True)
class Palette:
    """Los colores con trabajo asignado en un modo (claro u oscuro)."""

    GROUND: str  # fondo de página
    SIDEBAR: str  # fondo de la barra lateral (``[theme.*.sidebar]`` de config.toml)
    SURFACE: str  # hojas: gráficos, tablas, ficha
    SURFACE_2: str  # grilla de gráficos, separadores internos
    LINE: str  # filete de 1 px
    INK: str  # texto
    INK_2: str  # entradilla
    MUTED: str  # notas y captions (≥ 4,5:1 sobre fondo, barra, hoja y hoja lavada)
    ACCENT: str  # acción en la interfaz: botón primario, slider, foco, enlaces
    ACCENT_SOFT: str  # selección de texto (tinta encima, ≥ 4,5:1)
    SELECTION: str  # lo elegido dentro de un gráfico: el punto, la serie «punto», la hora actual
    SEVERE: str  # eventos y umbrales: solo glifos y líneas, nunca texto
    SEVERE_SOFT: str  # fondo de la píldora «Cumple el criterio» (texto en tinta encima)
    COLD: str  # serie categórica (hodógrafo 1–3 km): azul de Okabe-Ito
    WARM: str  # serie categórica (punto de rocío, hodógrafo 3–6 km, series GOES): naranja de Okabe-Ito
    # (oscurecido en claro para llegar a 3:1 sobre la hoja, el mínimo de un elemento gráfico)
    ON_ACCENT: str  # texto del botón primario sobre ``ACCENT``
    LEGEND: str  # fondo semitransparente de leyendas


# Claro: Honeydew de fondo, barra Honeydew + 70 % Frosted Blue, hojas blancas, Deep Space oscurecido de tinta (16:1) y puro en la
# entradilla, Steel Blue oscurecido para la acción.
LIGHT = Palette(
    GROUND="#F1FAEE", SIDEBAR="#BEE4E1", SURFACE="#FFFFFF", SURFACE_2="#EFF8F9", LINE="#BDD4D6",
    INK="#0E1A2C", INK_2="#1D3557", MUTED="#465463",
    ACCENT="#376284", ACCENT_SOFT="#A8DADC", SELECTION="#457B9D",
    SEVERE="#E63946", SEVERE_SOFT="#EFD7D0",
    COLD="#0072B2", WARM="#B07800", ON_ACCENT="#FFFFFF", LEGEND="rgba(255,255,255,0.8)",
)  # fmt: skip
# Oscuro: Deep Space de hojas sobre un fondo más hondo, Honeydew de tinta, Frosted Blue de acento.
# El rojo lleva un 5 % de Honeydew para llegar a 3:1 sobre la hoja (WCAG 1.4.11).
DARK = Palette(
    GROUND="#172A46", SIDEBAR="#172A46", SURFACE="#1D3557", SURFACE_2="#2C4362", LINE="#475C75",
    INK="#F1FAEE", INK_2="#D4EDE7", MUTED="#A9B8BE",
    ACCENT="#A8DADC", ACCENT_SOFT="#3D6E8E", SELECTION="#A8DADC",
    SEVERE="#E7434E", SEVERE_SOFT="#593652",
    COLD="#56B4E9", WARM="#E69F00", ON_ACCENT="#1D3557", LEGEND="rgba(29,53,87,0.8)",
)  # fmt: skip


def is_dark() -> bool:
    """Si el visitante está en el tema oscuro (Streamlit lo informa en ``st.context.theme``)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:  # fuera de una sesión (pruebas, scripts): tema claro
        return False


def colors() -> Palette:
    """La paleta del modo activo."""
    return DARK if is_dark() else LIGHT


def _template(p: Palette) -> go.layout.Template:
    """Plantilla plotly «notebook» con los colores de ``p``.

    Fondo, fuente y etiqueta flotante no van aquí: el frontend de Streamlit ignora los de la plantilla y
    ``charts._style`` los fija en el layout.
    """
    return go.layout.Template(
        layout={
            "colorway": [p.SELECTION, p.INK, p.WARM, p.COLD, p.MUTED, p.INK_2],
            "title": {
                "font": {"family": SANS, "size": 15, "color": p.INK},
                "x": 0,
                "xanchor": "left",
            },
            "xaxis": {
                "gridcolor": p.SURFACE_2,
                "linecolor": p.LINE,
                "zerolinecolor": p.LINE,
                "ticks": "",
            },
            "yaxis": {
                "gridcolor": p.SURFACE_2,
                "linecolor": p.LINE,
                "zerolinecolor": p.LINE,
                "ticks": "",
            },
            "legend": {"font": {"size": 12}, "bgcolor": p.LEGEND},
            "margin": {"l": 56, "r": 10, "t": 44, "b": 36},
        }
    )


pio.templates["notebook"] = _template(LIGHT)
pio.templates["notebook_dark"] = _template(DARK)


def template() -> str:
    """Nombre de la plantilla plotly del modo activo."""
    return "notebook_dark" if is_dark() else "notebook"


# Triángulo de evento dibujado con bordes: el mismo glifo de los mapas y de la regla de tiempo.
_TRIANGLE = (
    "width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent;"
)


def _var_name(field: str) -> str:
    """Nombre de la variable CSS de un campo de ``Palette``: ``INK_2`` → ``--ink-2``."""
    return "--" + field.lower().replace("_", "-")


# La paleta como referencias a variables CSS: las reglas no cambian y el modo lo decide el navegador.
_VARS = Palette(**{f.name: f"var({_var_name(f.name)})" for f in fields(Palette)})


def definitions(p: Palette) -> str:
    """Las variables CSS de la paleta ``p``."""
    return " ".join(f"{_var_name(f.name)}: {getattr(p, f.name)};" for f in fields(Palette))


# Streamlit no vuelve a ejecutar la app al cambiar de tema desde su menú, así que el CSS inyectado y
# los gráficos quedarían con la paleta anterior. Este script lee el fondo que pinta Streamlit, marca
# el modo en <html data-theme> (las variables CSS cambian al instante) y, si el modo cambió, pulsa un
# botón oculto para pedir una nueva ejecución: así plotly se redibuja con la paleta nueva. También
# lo pulsa si Python dibujó con otro modo que el del navegador: ``st.context.theme`` puede venir mal en
# la primera carga de una sesión. Usa selectores internos de Streamlit (menú ⋮, opciones de tema)
# probados con la versión 1.64; revisarlos al actualizar Streamlit.
_WATCHER = """
<script>
(() => {
  const root = document.documentElement;
  window.__serverTheme = "__SERVER__";
  const mode = () => {
    const app = document.querySelector(".stApp");
    if (!app) return null;
    const [r, g, b, a = 1] = getComputedStyle(app).backgroundColor.match(/[\\d.]+/g).map(Number);
    if (a === 0) return null;  // fondo aún transparente durante la carga: no hay modo que leer
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128 ? "dark" : "light";
  };
  root.dataset.theme = mode() || root.dataset.theme || "light";
  if (window.__themeWatcher) return;
  // El botón de la barra elige el otro modo en el menú de Streamlit, oculto mientras tanto.
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".st-key-theme_mode button")) return;
    const target = root.dataset.theme === "dark" ? "Light" : "Dark";
    const menu = document.querySelector('[data-testid="stMainMenu"] button')
      || document.querySelector('[data-testid="stMainMenu"]');
    if (!menu) return;
    root.classList.add("theme-switching");
    menu.click();
    let attempts = 0;
    const wait = setInterval(() => {
      const option = document.querySelector(`[data-testid="stMainMenuItem-theme-${target}"]`);
      if (option || ++attempts > 40) {
        clearInterval(wait);
        option?.click();
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));  // lo cierra
        setTimeout(() => root.classList.remove("theme-switching"), 300);
      }
    }, 25);
  }, true);
  window.__watcherRequestedAt = 0;
  window.__watcherMismatches = 0;
  window.__themeWatcher = setInterval(() => {
    const m = mode();
    if (!m) return;
    const changed = m !== root.dataset.theme;
    root.dataset.theme = m;
    if (m === window.__serverTheme) window.__watcherMismatches = 0;
    // Desfase con el servidor: se pide de nuevo como mucho cada 3 s y 5 veces, por si la ejecución
    // tarda o Streamlit sigue informando el otro modo.
    const mismatch = m !== window.__serverTheme && window.__watcherMismatches < 5
      && Date.now() - window.__watcherRequestedAt > 3000;
    if (changed || mismatch) {
      if (!changed) window.__watcherMismatches++;
      window.__watcherRequestedAt = Date.now();
      document.querySelector(".st-key-theme_watcher button")?.click();
    }
  }, 400);
})();
</script>
"""


def css(p: Palette = _VARS) -> str:
    """El CSS fino del visor; por omisión, con las variables de las dos paletas según el modo."""
    return f"""
<style>
:root {{ {definitions(LIGHT)} }}
html[data-theme="dark"] {{ {definitions(DARK)} }}
::selection {{ background: {p.ACCENT_SOFT}; color: {p.INK}; }}
code, .mono {{ font-family: {MONO}; font-variant-numeric: tabular-nums; }}
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{ font-variant-numeric: tabular-nums; }}
h1 {{ letter-spacing: -0.01em; }}
.lede {{ color: {p.INK_2}; font-size: 1.08rem; max-width: 68ch; line-height: 1.5; margin: -0.4rem 0 0.6rem; }}
.note {{ color: {p.MUTED}; font-size: 0.86rem; line-height: 1.45; max-width: 75ch; }}
.scorecard {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
.scorecard th {{ text-align: left; font-weight: 600; color: {p.MUTED}; font-size: 0.78rem;
  border-bottom: 1px solid {p.LINE}; padding: 4px 6px; }}
.scorecard td {{ padding: 6px; border-bottom: 1px solid {p.SURFACE_2}; vertical-align: baseline; }}
.scorecard td.num {{ font-family: {MONO}; font-variant-numeric: tabular-nums; text-align: right;
  white-space: nowrap; }}
.scorecard .ref {{ font-family: {SANS}; white-space: normal; color: {p.MUTED}; font-size: 0.8rem;
  display: inline-block; max-width: 11em; text-align: right; line-height: 1.35; }}
.scorecard tr.exceeds td.num.value {{ font-weight: 700; }}
.scorecard tr.exceeds td.num.value::before {{ content: ""; display: inline-block; {_TRIANGLE}
  border-bottom: 9px solid {p.SEVERE}; margin-right: 6px; vertical-align: 0; }}
.scorecard .verdict {{ display: inline-block; min-width: 4.6em; font-size: 0.8rem; font-weight: 600;
  padding: 1px 6px; border-radius: 3px; text-align: center; }}
.scorecard tr.exceeds .verdict {{ background: {p.SEVERE_SOFT}; color: {p.INK}; }}
.scorecard tr.below .verdict {{ background: {p.SURFACE_2}; color: {p.MUTED}; }}
.ruler {{ margin: -0.35rem 0 0.4rem; }}
.ruler-track {{ position: relative; height: 18px; margin: 0 9px; border-bottom: 1px solid {p.LINE}; }}
.ruler-event {{ position: absolute; bottom: 0; {_TRIANGLE} transform: translateX(-5px);
  border-bottom: 9px solid {p.SEVERE}; }}
.ruler-now {{ position: absolute; bottom: -4px; width: 2px; height: 20px; background: {p.ACCENT};
  transform: translateX(-1px); border-radius: 1px; }}
.ruler-hours {{ display: flex; justify-content: space-between; margin: 3px 9px 0;
  font-family: {MONO}; font-size: 0.75rem; color: {p.MUTED}; }}
.block-container {{ padding-top: 2.2rem; }}
.st-key-theme_watcher, [data-testid="stLayoutWrapper"]:has(> .st-key-theme_watcher) {{ display: none; }}
html.theme-switching [data-testid="stMainMenuPopover"] {{ visibility: hidden; }}
[data-testid="stMain"], [data-testid="stHeader"] {{ background: {p.GROUND}; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"],
[data-testid="stMain"] [data-testid="stDataFrame"],
[data-testid="stMain"] [data-testid="stExpander"] details,
[data-testid="stMain"] .scorecard {{ background: {p.SURFACE}; border: 1px solid {p.LINE}; border-radius: 6px; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"] {{ padding: 6px 4px 2px; }}
[data-testid="stMain"] .scorecard {{ border-collapse: separate; border-spacing: 0; overflow: hidden; }}
h2, h3, [data-testid="stSidebar"] h2 {{ font-family: {SANS} !important; font-weight: 700; letter-spacing: 0; }}
.step {{ background: {p.SURFACE}; border: 1px solid {p.LINE}; border-radius: 6px; padding: 10px 12px;
  font-size: 0.92rem; line-height: 1.45; }}
.toc-title {{ font-size: 0.875rem; font-weight: 600; color: {p.INK_2}; margin: 0 0 -0.4rem; }}
.notice {{ border: 1px solid {p.LINE}; background: {p.SURFACE}; padding: 14px 18px; margin: 1rem 0;
  border-radius: 6px; line-height: 1.5; max-width: 68ch; }}
[class*="st-key-sheet_"] {{ background: {p.SURFACE}; }}
:is(.st-key-project, .st-key-data) {{ padding-top: 1.6rem; max-width: 1400px; container: project / inline-size; }}
/* El cuerpo es su propio contenedor: tarjetas y cifras se acomodan al espacio que les deja el índice. */
:is(.st-key-project_body, .st-key-data_body) {{ container: body / inline-size; }}
/* Datos sin índice (búsqueda o una ficha): el mismo ancho de lectura que con el índice al lado. */
.st-key-data_body {{ max-width: 44rem; }}
:is(.st-key-project, .st-key-data) h1, :is(.st-key-project, .st-key-data) h2, :is(.st-key-project, .st-key-data) h3 {{ scroll-margin-top: 4.5rem; }}
/* El proyecto: párrafos sueltos hasta 90ch; en tarjetas, figuras y notas el texto llega al borde. */
[data-testid="stMain"] :is(.st-key-project, .st-key-data) [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] :is(.st-key-project, .st-key-data) [data-testid="stMarkdownContainer"] li,
:is(.st-key-project, .st-key-data) .lede {{ max-width: 90ch; }}
[data-testid="stMain"] :is(.st-key-project, .st-key-data) [class*="st-key-sheet_"] [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] :is(.st-key-project, .st-key-data) [class*="st-key-sheet_"] [data-testid="stMarkdownContainer"] li,
:is(.st-key-project, .st-key-data) .note {{ max-width: none; }}
/* Índice: columna fija a la derecha si la página mide 880 px o más; si no, desplegable arriba. */
/* Streamlit 1.64 envuelve el contenedor de ancho fijo en un stLayoutWrapper: ese es el que se oculta y
   se fija (selectores internos; revisarlos al actualizar Streamlit). El contenedor también se oculta
   por si una versión futura deja de envolverlo. */
[data-testid="stLayoutWrapper"]:has(> .st-key-toc_side) {{ display: none; position: sticky; top: 4.5rem;
  align-self: flex-start; }}
.st-key-toc_side {{ display: none; }}
/* El bloque horizontal trae overflow: auto, que vuelve inútil el sticky de su hijo. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stLayoutWrapper"] > .st-key-toc_side) {{ overflow: visible; }}
@container project (min-width: 880px) {{
  [data-testid="stLayoutWrapper"]:has(> .st-key-toc_side), .st-key-toc_side {{ display: flex; }}
  .st-key-toc_compact {{ display: none; }}
}}
/* Tarjetas: grilla de n columnas que baja a una cuando el cuerpo es angosto. */
:is(.st-key-project, .st-key-data) [class*="st-key-cards"] {{ display: grid; gap: 1rem; align-items: stretch; }}
:is(.st-key-project, .st-key-data) [class*="st-key-cards3_"] {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
:is(.st-key-project, .st-key-data) [class*="st-key-cards2_"] {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
:is(.st-key-project, .st-key-data) [class*="st-key-cards"] > * {{ width: auto; height: 100%; }}
@container body (max-width: 760px) {{
  :is(.st-key-project, .st-key-data) [class*="st-key-cards3_"] {{ grid-template-columns: minmax(0, 1fr); }}
}}
@container body (max-width: 520px) {{
  :is(.st-key-project, .st-key-data) [class*="st-key-cards2_"] {{ grid-template-columns: minmax(0, 1fr); }}
}}
/* Columnas flexibles (``columns``): se apilan cuando no caben dos de 26rem; el corte lo pone el contenido. */
[class*="st-key-flex_"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {{ flex-wrap: wrap;
  row-gap: 1.5rem; }}
[class*="st-key-flex_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{ min-width: min(100%, 26rem); }}
/* La ficha no se encoge bajo ~400 px: en teléfono se desplaza dentro de su caja, no la página entera. */
[data-testid="stHtml"]:has(> .scorecard), [data-testid="stHtml"]:has(> * > .scorecard) {{ overflow-x: auto; }}
/* Cifras de la portada: cuatro en fila o dos por dos, nunca una fila a medias. */
:is(.st-key-project, .st-key-data) .stats {{ grid-template-columns: repeat(4, 1fr); }}
@container body (max-width: 760px) {{ :is(.st-key-project, .st-key-data) .stats {{ grid-template-columns: repeat(2, 1fr); }} }}
.toc ol {{ list-style: none; margin: 0.6rem 0 0; padding: 0; border-left: 1px solid {p.LINE}; }}
[data-testid="stMain"] .toc li {{ margin: 0; padding: 0; }}
.toc a {{ display: block; margin-left: -1px; padding: 5px 0 5px 12px; border-left: 1px solid transparent;
  color: {p.INK_2}; font-size: 0.92rem; line-height: 1.35; text-decoration: none; }}
.toc a:hover, .toc a:focus-visible {{ color: {p.ACCENT}; border-left-color: {p.ACCENT}; }}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li {{ max-width: 68ch; }}
.stApp [data-testid="stCaptionContainer"] {{ color: {p.MUTED}; opacity: 1; }}  /* Streamlit lo atenúa al 60 % */
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
  background: {p.LINE}; border: 1px solid {p.LINE}; border-radius: 6px; overflow: hidden; margin: 0.6rem 0 1rem; }}
.stat {{ background: {p.SURFACE}; padding: 14px 16px; }}
.stat b {{ display: block; font-size: 1.7rem; line-height: 1; font-weight: 600; font-variant-numeric: tabular-nums; }}
.stat span {{ display: block; font-size: 0.8rem; color: {p.MUTED}; margin-top: 7px; line-height: 1.4; }}
.stat.sev b::after {{ content: ""; display: inline-block; {_TRIANGLE} border-bottom: 9px solid {p.SEVERE};
  margin-left: 8px; vertical-align: 0.15em; }}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p,
[data-testid="stBaseLinkButton-primary"], [data-testid="stBaseLinkButton-primary"] p {{ color: {p.ON_ACCENT}; }}
.step b {{ font-family: {MONO}; font-weight: 600; color: {p.ACCENT}; font-size: 0.8rem; }}
/* Datos: fichas de variables. El nombre es la ancla (?v= y el índice); el símbolo y la unidad, mono. */
.var-name {{ font-size: 1.1rem; font-weight: 600; line-height: 1.3; margin: 0; padding: 0;
  scroll-margin-top: 4.5rem; }}
.var-meta {{ color: {p.MUTED}; font-size: 0.86rem; margin: 0.2rem 0 0.35rem; }}
.facts {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
.facts th {{ text-align: left; font-weight: 600; color: {p.MUTED}; white-space: nowrap; padding: 6px 16px 6px 0;
  vertical-align: baseline; }}
.facts td {{ padding: 6px 0; vertical-align: baseline; }}
.facts tr + tr > * {{ border-top: 1px solid {p.SURFACE_2}; }}
@container body (max-width: 520px) {{ .facts th, .facts td {{ display: block; padding: 0; border: 0; }}
  .facts td {{ padding-bottom: 8px; }} .facts tr + tr > th {{ padding-top: 8px; }} }}
[class*="st-key-threshold_"] p::before {{ content: ""; display: inline-block; {_TRIANGLE}
  border-bottom: 9px solid {p.SEVERE}; margin-right: 8px; vertical-align: 0; }}
/* Fórmulas largas: se desplazan dentro de la ficha en teléfono, no la página entera. */
[data-testid="stMain"] .katex-display {{ overflow-x: auto; overflow-y: hidden; margin: 0.3rem 0; padding: 2px 0; }}
.var-refs a, .bibliography a {{ text-underline-offset: 2px; }}
.bibliography {{ padding-left: 1.1rem; }}
[data-testid="stMain"] .bibliography li {{ margin: 0.4rem 0; max-width: 90ch; line-height: 1.45; }}
.bibliography a {{ overflow-wrap: anywhere; }}
.toc ol ol {{ margin: 0 0 0.35rem; border-left: none; }}
.toc ol ol a {{ padding-left: 24px; font-size: 0.86rem; color: {p.MUTED}; }}
</style>
"""


def columns(spec: int | list[float], key: str) -> list[DeltaGenerator]:
    """Columnas que se apilan cuando cada una quedaría con menos de 26rem (~416 px).

    ``st.columns`` solo apila en pantallas de teléfono; con la barra lateral abierta en una tablet dejaba
    mapas y tablas de 250 px. Úsese donde el contenido de cada columna necesita ancho propio, no en
    filas que deben quedar alineadas con una figura (los controles de Mapas).
    """
    return st.container(key=f"flex_{key}").columns(spec, gap="large")


def mode_button() -> None:
    """Botón de la barra lateral que alterna entre el modo claro y el oscuro (lo atiende el vigía, sin recargar)."""
    display_label = "Cambiar a modo claro" if is_dark() else "Cambiar a modo oscuro"
    st.sidebar.button(
        display_label, key="theme_mode", type="tertiary",
        icon=":material/light_mode:" if is_dark() else ":material/dark_mode:",
    )  # fmt: skip


def apply() -> None:
    """Inyecta el CSS fino, el vigía del modo y su botón oculto en la página actual."""
    watcher = _WATCHER.replace("__SERVER__", "dark" if is_dark() else "light")
    st.html(css() + watcher, unsafe_allow_javascript=True)
    with st.container(key="theme_watcher"):  # oculto por CSS; el vigía lo pulsa al cambiar de tema
        st.button("Actualizar tema", key="theme_watcher_button")
