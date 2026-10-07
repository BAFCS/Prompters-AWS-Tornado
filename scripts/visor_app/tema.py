"""Identidad visual del visor: las paletas clara y oscura, las plantillas de plotly y el CSS fino.

El tema base (colores y fuentes de los widgets) vive en ``.streamlit/config.toml``, con una tabla
``[theme.light]`` y otra ``[theme.dark]`` que el usuario alterna desde el menú de Streamlit. Aquí está
lo que config.toml no alcanza: los gráficos y los detalles del navegador (selección de texto, cifras
tabulares, la bitácora y la ficha de umbrales). ``colores()`` devuelve la paleta del modo activo.

Las dos paletas salen de cinco colores (Strawberry Red, Honeydew, Frosted Blue, Steel Blue y Deep
Space Blue) y de mezclas entre ellos. El rojo marca (glifos y líneas de eventos y umbrales); nunca es
texto. Las series categóricas de los gráficos que la paleta no cubre usan el azul y el naranja de
Okabe-Ito, aptos para daltonismo. Las escalas de los mapas son estándar y viven en ``escalas.py``.
"""

from dataclasses import dataclass, fields

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

SANS = "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, Menlo, monospace"


@dataclass(frozen=True)
class Paleta:
    """Los colores con trabajo asignado en un modo (claro u oscuro)."""

    GROUND: str  # fondo de página
    BARRA: str  # fondo de la barra lateral (``[theme.*.sidebar]`` de config.toml)
    SURFACE: str  # hojas: gráficos, tablas, ficha
    SURFACE_2: str  # grilla de gráficos, separadores internos
    LINE: str  # filete de 1 px
    INK: str  # texto
    INK_2: str  # entradilla
    MUTED: str  # notas y captions (≥ 4,5:1 sobre fondo, barra, hoja y hoja lavada)
    ACCENT: str  # acción en la interfaz: botón primario, slider, foco, enlaces
    ACCENT_SOFT: str  # selección de texto (tinta encima, ≥ 4,5:1)
    SELECCION: str  # lo elegido dentro de un gráfico: el punto, la serie «punto», la hora actual
    SEVERE: str  # eventos y umbrales: solo glifos y líneas, nunca texto
    SEVERE_SOFT: str  # fondo de la píldora «Cumple el criterio» (texto en tinta encima)
    COLD: str  # serie categórica (hodógrafo 1–3 km): azul de Okabe-Ito
    WARM: str  # serie categórica (punto de rocío, hodógrafo 3–6 km, series GOES): naranja de Okabe-Ito
    # (oscurecido en claro para llegar a 3:1 sobre la hoja, el mínimo de un elemento gráfico)
    SOBRE_ACCENT: str  # texto del botón primario sobre ``ACCENT``
    LEYENDA: str  # fondo semitransparente de leyendas


# Claro: Honeydew de fondo, barra Honeydew + 70 % Frosted Blue, hojas blancas, Deep Space oscurecido de tinta (16:1) y puro en la
# entradilla, Steel Blue oscurecido para la acción.
CLARA = Paleta(
    GROUND="#F1FAEE", BARRA="#BEE4E1", SURFACE="#FFFFFF", SURFACE_2="#EFF8F9", LINE="#BDD4D6",
    INK="#0E1A2C", INK_2="#1D3557", MUTED="#465463",
    ACCENT="#376284", ACCENT_SOFT="#A8DADC", SELECCION="#457B9D",
    SEVERE="#E63946", SEVERE_SOFT="#EFD7D0",
    COLD="#0072B2", WARM="#B07800", SOBRE_ACCENT="#FFFFFF", LEYENDA="rgba(255,255,255,0.8)",
)  # fmt: skip
# Oscuro: Deep Space de hojas sobre un fondo más hondo, Honeydew de tinta, Frosted Blue de acento.
# El rojo lleva un 5 % de Honeydew para llegar a 3:1 sobre la hoja (WCAG 1.4.11).
OSCURA = Paleta(
    GROUND="#172A46", BARRA="#172A46", SURFACE="#1D3557", SURFACE_2="#2C4362", LINE="#475C75",
    INK="#F1FAEE", INK_2="#D4EDE7", MUTED="#A9B8BE",
    ACCENT="#A8DADC", ACCENT_SOFT="#3D6E8E", SELECCION="#A8DADC",
    SEVERE="#E7434E", SEVERE_SOFT="#593652",
    COLD="#56B4E9", WARM="#E69F00", SOBRE_ACCENT="#1D3557", LEYENDA="rgba(29,53,87,0.8)",
)  # fmt: skip


def oscuro() -> bool:
    """Si el visitante está en el tema oscuro (Streamlit lo informa en ``st.context.theme``)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:  # fuera de una sesión (pruebas, scripts): tema claro
        return False


def colores() -> Paleta:
    """La paleta del modo activo."""
    return OSCURA if oscuro() else CLARA


def _plantilla(p: Paleta) -> go.layout.Template:
    """Plantilla plotly «cuaderno» con los colores de ``p``."""
    return go.layout.Template(
        layout={
            "font": {"family": SANS, "color": p.INK, "size": 13},
            "paper_bgcolor": p.SURFACE,
            "plot_bgcolor": p.SURFACE,
            "colorway": [p.SELECCION, p.INK, p.WARM, p.COLD, p.MUTED, p.INK_2],
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
            "hoverlabel": {
                "bgcolor": p.SURFACE,
                "bordercolor": p.LINE,
                "font": {"family": MONO, "size": 12, "color": p.INK},
            },
            "legend": {"font": {"size": 12}, "bgcolor": p.LEYENDA},
            "margin": {"l": 56, "r": 10, "t": 44, "b": 36},
        }
    )


pio.templates["cuaderno"] = _plantilla(CLARA)
pio.templates["cuaderno_oscuro"] = _plantilla(OSCURA)
pio.templates.default = "cuaderno"


def plantilla() -> str:
    """Nombre de la plantilla plotly del modo activo."""
    return "cuaderno_oscuro" if oscuro() else "cuaderno"


# Triángulo de evento dibujado con bordes: el mismo glifo de los mapas y de la regla de tiempo.
_TRIANGULO = (
    "width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent;"
)


def _nombre_var(campo: str) -> str:
    """Nombre de la variable CSS de un campo de ``Paleta``: ``INK_2`` → ``--ink-2``."""
    return "--" + campo.lower().replace("_", "-")


# La paleta como referencias a variables CSS: las reglas no cambian y el modo lo decide el navegador.
_VARS = Paleta(**{f.name: f"var({_nombre_var(f.name)})" for f in fields(Paleta)})


def _definiciones(p: Paleta) -> str:
    """Las variables CSS de la paleta ``p``."""
    return " ".join(f"{_nombre_var(f.name)}: {getattr(p, f.name)};" for f in fields(Paleta))


# Streamlit no vuelve a ejecutar la app al cambiar de tema desde su menú, así que el CSS inyectado y
# los gráficos quedarían con la paleta anterior. Este script lee el fondo que pinta Streamlit, marca
# el modo en <html data-tema> (las variables CSS cambian al instante) y, si el modo cambió, pulsa un
# botón oculto para pedir una nueva ejecución: así plotly se redibuja con la paleta nueva. También
# lo pulsa si Python dibujó con otro modo que el del navegador: ``st.context.theme`` puede venir mal en
# la primera carga de una sesión. Usa selectores internos de Streamlit (menú ⋮, opciones de tema)
# probados con la versión 1.64; revisarlos al actualizar Streamlit.
_VIGIA = """
<script>
(() => {
  const raiz = document.documentElement;
  window.__temaServidor = "__SERVIDOR__";
  const modo = () => {
    const app = document.querySelector(".stApp");
    if (!app) return null;
    const [r, g, b, a = 1] = getComputedStyle(app).backgroundColor.match(/[\\d.]+/g).map(Number);
    if (a === 0) return null;  // fondo aún transparente durante la carga: no hay modo que leer
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128 ? "oscuro" : "claro";
  };
  raiz.dataset.tema = modo() || raiz.dataset.tema || "claro";
  if (window.__vigiaTema) return;
  // El botón de la barra elige el otro modo en el menú de Streamlit, oculto mientras tanto.
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".st-key-modo_tema button")) return;
    const destino = raiz.dataset.tema === "oscuro" ? "Light" : "Dark";
    const menu = document.querySelector('[data-testid="stMainMenu"] button')
      || document.querySelector('[data-testid="stMainMenu"]');
    if (!menu) return;
    raiz.classList.add("cambia-tema");
    menu.click();
    let intentos = 0;
    const espera = setInterval(() => {
      const opcion = document.querySelector(`[data-testid="stMainMenuItem-theme-${destino}"]`);
      if (opcion || ++intentos > 40) {
        clearInterval(espera);
        opcion?.click();
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));  // lo cierra
        setTimeout(() => raiz.classList.remove("cambia-tema"), 300);
      }
    }, 25);
  }, true);
  window.__vigiaPedido = 0;
  window.__vigiaDesfases = 0;
  window.__vigiaTema = setInterval(() => {
    const m = modo();
    if (!m) return;
    const cambio = m !== raiz.dataset.tema;
    raiz.dataset.tema = m;
    if (m === window.__temaServidor) window.__vigiaDesfases = 0;
    // Desfase con el servidor: se pide de nuevo como mucho cada 3 s y 5 veces, por si la ejecución
    // tarda o Streamlit sigue informando el otro modo.
    const desfase = m !== window.__temaServidor && window.__vigiaDesfases < 5
      && Date.now() - window.__vigiaPedido > 3000;
    if (cambio || desfase) {
      if (!cambio) window.__vigiaDesfases++;
      window.__vigiaPedido = Date.now();
      document.querySelector(".st-key-vigia_tema button")?.click();
    }
  }, 400);
})();
</script>
"""


def css(p: Paleta = _VARS) -> str:
    """El CSS fino del visor; por omisión, con las variables de las dos paletas según el modo."""
    return f"""
<style>
:root {{ {_definiciones(CLARA)} }}
html[data-tema="oscuro"] {{ {_definiciones(OSCURA)} }}
::selection {{ background: {p.ACCENT_SOFT}; color: {p.INK}; }}
code, .mono {{ font-family: {MONO}; font-variant-numeric: tabular-nums; }}
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{ font-variant-numeric: tabular-nums; }}
h1 {{ letter-spacing: -0.01em; }}
.lede {{ color: {p.INK_2}; font-size: 1.08rem; max-width: 68ch; line-height: 1.5; margin: -0.4rem 0 0.6rem; }}
.nota {{ color: {p.MUTED}; font-size: 0.86rem; line-height: 1.45; max-width: 75ch; }}
.ficha {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
.ficha th {{ text-align: left; font-weight: 600; color: {p.MUTED}; font-size: 0.78rem;
  border-bottom: 1px solid {p.LINE}; padding: 4px 6px; }}
.ficha td {{ padding: 6px; border-bottom: 1px solid {p.SURFACE_2}; vertical-align: baseline; }}
.ficha td.num {{ font-family: {MONO}; font-variant-numeric: tabular-nums; text-align: right;
  white-space: nowrap; }}
.ficha .ref {{ font-family: {SANS}; white-space: normal; color: {p.MUTED}; font-size: 0.8rem;
  display: inline-block; max-width: 11em; text-align: right; line-height: 1.35; }}
.ficha tr.supera td.num.valor {{ font-weight: 700; }}
.ficha tr.supera td.num.valor::before {{ content: ""; display: inline-block; {_TRIANGULO}
  border-bottom: 9px solid {p.SEVERE}; margin-right: 6px; vertical-align: 0; }}
.ficha .marca {{ display: inline-block; min-width: 4.6em; font-size: 0.8rem; font-weight: 600;
  padding: 1px 6px; border-radius: 3px; text-align: center; }}
.ficha tr.supera .marca {{ background: {p.SEVERE_SOFT}; color: {p.INK}; }}
.ficha tr.bajo .marca {{ background: {p.SURFACE_2}; color: {p.MUTED}; }}
.regla {{ margin: -0.35rem 0 0.4rem; }}
.regla-pista {{ position: relative; height: 18px; margin: 0 9px; border-bottom: 1px solid {p.LINE}; }}
.regla-ev {{ position: absolute; bottom: 0; {_TRIANGULO} transform: translateX(-5px);
  border-bottom: 9px solid {p.SEVERE}; }}
.regla-ahora {{ position: absolute; bottom: -4px; width: 2px; height: 20px; background: {p.ACCENT};
  transform: translateX(-1px); border-radius: 1px; }}
.regla-horas {{ display: flex; justify-content: space-between; margin: 3px 9px 0;
  font-family: {MONO}; font-size: 0.75rem; color: {p.MUTED}; }}
.block-container {{ padding-top: 2.2rem; }}
.st-key-vigia_tema, [data-testid="stLayoutWrapper"]:has(> .st-key-vigia_tema) {{ display: none; }}
html.cambia-tema [data-testid="stMainMenuPopover"] {{ visibility: hidden; }}
[data-testid="stMain"], [data-testid="stHeader"] {{ background: {p.GROUND}; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"],
[data-testid="stMain"] [data-testid="stDataFrame"],
[data-testid="stMain"] [data-testid="stExpander"] details,
[data-testid="stMain"] .ficha {{ background: {p.SURFACE}; border: 1px solid {p.LINE}; border-radius: 6px; }}
[data-testid="stMain"] [data-testid="stPlotlyChart"] {{ padding: 6px 4px 2px; }}
[data-testid="stMain"] .ficha {{ border-collapse: separate; border-spacing: 0; overflow: hidden; }}
h2, h3, [data-testid="stSidebar"] h2 {{ font-family: {SANS} !important; font-weight: 700; letter-spacing: 0; }}
.paso {{ background: {p.SURFACE}; border: 1px solid {p.LINE}; border-radius: 6px; padding: 10px 12px;
  font-size: 0.92rem; line-height: 1.45; }}
.antetitulo {{ font-family: {MONO}; font-size: 0.75rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: {p.ACCENT}; margin: 0 0 -0.4rem; }}
.aviso {{ border: 1px solid {p.LINE}; background: {p.SURFACE}; padding: 14px 18px; margin: 1rem 0;
  border-radius: 6px; line-height: 1.5; max-width: 68ch; }}
[class*="st-key-hoja_"] {{ background: {p.SURFACE}; }}
.st-key-proyecto {{ padding-top: 1.6rem; max-width: 1400px; container: proyecto / inline-size; }}
/* El cuerpo es su propio contenedor: tarjetas y cifras se acomodan al espacio que les deja el índice. */
.st-key-proyecto_cuerpo {{ container: cuerpo / inline-size; }}
.st-key-proyecto h1, .st-key-proyecto h2, .st-key-proyecto h3 {{ scroll-margin-top: 4.5rem; }}
/* El proyecto: párrafos sueltos hasta 90ch; en tarjetas, figuras y notas el texto llega al borde. */
[data-testid="stMain"] .st-key-proyecto [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] .st-key-proyecto [data-testid="stMarkdownContainer"] li,
.st-key-proyecto .lede {{ max-width: 90ch; }}
[data-testid="stMain"] .st-key-proyecto [class*="st-key-hoja_"] [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] .st-key-proyecto [class*="st-key-hoja_"] [data-testid="stMarkdownContainer"] li,
.st-key-proyecto .nota {{ max-width: none; }}
/* Índice: columna fija a la derecha si la página mide 880 px o más; si no, desplegable arriba. */
/* Streamlit 1.64 envuelve el contenedor de ancho fijo en un stLayoutWrapper: ese es el que se oculta y
   se fija (selectores internos; revisarlos al actualizar Streamlit). El contenedor también se oculta
   por si una versión futura deja de envolverlo. */
[data-testid="stLayoutWrapper"]:has(> .st-key-indice_lateral) {{ display: none; position: sticky; top: 4.5rem;
  align-self: flex-start; }}
.st-key-indice_lateral {{ display: none; }}
/* El bloque horizontal trae overflow: auto, que vuelve inútil el sticky de su hijo. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stLayoutWrapper"] > .st-key-indice_lateral) {{ overflow: visible; }}
@container proyecto (min-width: 880px) {{
  [data-testid="stLayoutWrapper"]:has(> .st-key-indice_lateral), .st-key-indice_lateral {{ display: flex; }}
  .st-key-indice_compacto {{ display: none; }}
}}
/* Tarjetas: grilla de n columnas que baja a una cuando el cuerpo es angosto. */
.st-key-proyecto [class*="st-key-tarjetas"] {{ display: grid; gap: 1rem; align-items: stretch; }}
.st-key-proyecto [class*="st-key-tarjetas3_"] {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
.st-key-proyecto [class*="st-key-tarjetas2_"] {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.st-key-proyecto [class*="st-key-tarjetas"] > * {{ width: auto; height: 100%; }}
@container cuerpo (max-width: 760px) {{
  .st-key-proyecto [class*="st-key-tarjetas3_"] {{ grid-template-columns: minmax(0, 1fr); }}
}}
@container cuerpo (max-width: 520px) {{
  .st-key-proyecto [class*="st-key-tarjetas2_"] {{ grid-template-columns: minmax(0, 1fr); }}
}}
/* Columnas flexibles (``columnas``): se apilan cuando no caben dos de 26rem; el corte lo pone el contenido. */
[class*="st-key-flex_"] [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {{ flex-wrap: wrap;
  row-gap: 1.5rem; }}
[class*="st-key-flex_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{ min-width: min(100%, 26rem); }}
/* La ficha no se encoge bajo ~400 px: en teléfono se desplaza dentro de su caja, no la página entera. */
[data-testid="stHtml"]:has(> .ficha), [data-testid="stHtml"]:has(> * > .ficha) {{ overflow-x: auto; }}
/* Cifras de la portada: cuatro en fila o dos por dos, nunca una fila a medias. */
.st-key-proyecto .cifras {{ grid-template-columns: repeat(4, 1fr); }}
@container cuerpo (max-width: 760px) {{ .st-key-proyecto .cifras {{ grid-template-columns: repeat(2, 1fr); }} }}
.indice ol {{ list-style: none; margin: 0.6rem 0 0; padding: 0; border-left: 1px solid {p.LINE}; }}
[data-testid="stMain"] .indice li {{ margin: 0; padding: 0; }}
.indice a {{ display: block; margin-left: -1px; padding: 5px 0 5px 12px; border-left: 1px solid transparent;
  color: {p.INK_2}; font-size: 0.92rem; line-height: 1.35; text-decoration: none; }}
.indice a:hover, .indice a:focus-visible {{ color: {p.ACCENT}; border-left-color: {p.ACCENT}; }}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] > p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li {{ max-width: 68ch; }}
.stApp [data-testid="stCaptionContainer"] {{ color: {p.MUTED}; opacity: 1; }}  /* Streamlit lo atenúa al 60 % */
.cifras {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
  background: {p.LINE}; border: 1px solid {p.LINE}; border-radius: 6px; overflow: hidden; margin: 0.6rem 0 1rem; }}
.cifra {{ background: {p.SURFACE}; padding: 14px 16px; }}
.cifra b {{ display: block; font-size: 1.7rem; line-height: 1; font-weight: 600; font-variant-numeric: tabular-nums; }}
.cifra span {{ display: block; font-size: 0.8rem; color: {p.MUTED}; margin-top: 7px; line-height: 1.4; }}
.cifra.sev b::after {{ content: ""; display: inline-block; {_TRIANGULO} border-bottom: 9px solid {p.SEVERE};
  margin-left: 8px; vertical-align: 0.15em; }}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p,
[data-testid="stBaseLinkButton-primary"], [data-testid="stBaseLinkButton-primary"] p {{ color: {p.SOBRE_ACCENT}; }}
.paso b {{ font-family: {MONO}; font-weight: 600; color: {p.ACCENT}; font-size: 0.8rem; }}
</style>
"""


def columnas(spec: int | list[float], clave: str) -> list[DeltaGenerator]:
    """Columnas que se apilan cuando cada una quedaría con menos de 26rem (~416 px).

    ``st.columns`` solo apila en pantallas de teléfono; con la barra lateral abierta en una tablet dejaba
    mapas y tablas de 250 px. Úsese donde el contenido de cada columna necesita ancho propio, no en
    filas que deben quedar alineadas con una figura (los controles de Mapas).
    """
    return st.container(key=f"flex_{clave}").columns(spec, gap="large")


def boton_modo() -> None:
    """Botón de la barra lateral que alterna entre el modo claro y el oscuro (lo atiende el vigía, sin recargar)."""
    rotulo = "Cambiar a modo claro" if oscuro() else "Cambiar a modo oscuro"
    st.sidebar.button(
        rotulo, key="modo_tema", type="tertiary",
        icon=":material/light_mode:" if oscuro() else ":material/dark_mode:",
    )  # fmt: skip


def aplica() -> None:
    """Inyecta el CSS fino, el vigía del modo y su botón oculto en la página actual."""
    vigia = _VIGIA.replace("__SERVIDOR__", "oscuro" if oscuro() else "claro")
    st.html(css() + vigia, unsafe_allow_javascript=True)
    with st.container(key="vigia_tema"):  # oculto por CSS; el vigía lo pulsa al cambiar de tema
        st.button("Actualizar tema", key="vigia_tema_boton")
