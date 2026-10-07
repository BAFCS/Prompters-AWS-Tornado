"""Página «Datos»: el catálogo de datos, una ficha por variable, ordenadas por fuente y linaje.

Los textos viven en ``variables.py``. Esta página no necesita datos: sin recortes muestra todas las
fichas; con recortes, cada ficha cuyo producto existe el día elegido trae un botón «Ver en Mapas».
Una ficha sola se pide con ``?v=<clave>`` en la URL o desde la ayuda de Mapas (``estado.ir_a_ficha``).
"""

import html

import streamlit as st

from visor_app import estado, productos, variables
from visor_app.variables import Variable


def _ancla_ref(k: str) -> str:
    """Ancla de la referencia ``k`` en la bibliografía."""
    return f"ref-{k}"


def _citas(claves: list[str] | tuple[str, ...]) -> str:
    """Las citas cortas de ``claves``, enlazadas a la bibliografía del final de la página."""
    return " · ".join(
        f"<a href='#{_ancla_ref(k)}'>{html.escape(variables.REFERENCIAS[k].corta)}</a>"
        for k in claves
    )


def _foco() -> Variable | None:
    """La ficha pedida por la URL o por otra página; la URL queda al día para compartirla."""
    pedida = st.session_state.pop("datos_foco", None) or st.query_params.get("v")
    if pedida in variables.POR_CLAVE:
        st.query_params["v"] = pedida
        return variables.POR_CLAVE[pedida]
    st.query_params.pop("v", None)
    return None


def _enfoca(clave: str | None) -> None:
    """Callback: muestra solo la ficha ``clave`` (``None``: todas)."""
    if clave is None:
        st.query_params.pop("v", None)
    else:
        st.session_state["datos_foco"] = clave


def _al_elegir_insumo(widget: str) -> None:
    """Callback de las píldoras «Se calcula con»: abre la ficha del insumo elegido."""
    _enfoca(st.session_state[widget])
    st.session_state[widget] = None


def _limpia_busqueda() -> None:
    """Callback: borra el texto del buscador."""
    st.session_state["datos_busca"] = ""


def _disponibles() -> set[str]:
    """Claves de producto del día elegido en la barra lateral; vacío si no hay datos."""
    ctx = st.session_state.get("ctx")
    return set(productos.catalogo(ctx.dia)) if ctx is not None else set()


def _ficha(v: Variable, disponibles: set[str], sufijo: str = "") -> None:
    """Dibuja la ficha de ``v``. ``sufijo`` distingue las claves de widget si la ficha se repite."""
    k = f"{v.clave}{sufijo}"
    with st.container(border=True, key=f"hoja_v_{k}", gap="small"):
        meta = " · ".join(html.escape(x) for x in (v.simbolo, v.unidad) if x)
        st.markdown(
            f"<h4 class='ficha-nombre' id='{html.escape(v.clave)}'>{html.escape(v.nombre)}</h4>"
            f"<p class='ficha-meta mono'>{meta}</p>",
            unsafe_allow_html=True,
        )
        st.markdown(v.que_es)
        if v.importa:
            st.markdown(f"**Por qué importa.** {v.importa}")
        if v.formula:
            st.latex(v.formula)
        if v.calculo:
            st.markdown(f"<div class='nota'>\n\n{v.calculo}\n\n</div>", unsafe_allow_html=True)
        if v.umbral:
            with st.container(key=f"umbral_{k}"):
                st.markdown(f"**Criterio en Chile.** {v.umbral}")
        if v.cuidado:
            st.markdown(f"**Cuidado.** {v.cuidado}")
        if v.insumos:
            st.pills(
                "Se calcula con", list(v.insumos), key=f"ins_{k}",
                format_func=lambda c: variables.POR_CLAVE[c].simbolo,
                on_change=_al_elegir_insumo, args=(f"ins_{k}",),
            )  # fmt: skip
        st.markdown(
            f"<p class='nota ficha-fuentes'>Fuentes: {_citas(variables.fuentes(v))}</p>",
            unsafe_allow_html=True,
        )
        en_mapas = next((p for p in v.productos if p in disponibles), None)
        if en_mapas is not None:
            st.button(
                "Ver en Mapas", key=f"mapa_{k}", icon=":material/map:", type="tertiary",
                on_click=estado.abre_en_mapas, args=(en_mapas, v.nivel),
            )  # fmt: skip


def _grupo(g: variables.Grupo, fichas: list[Variable], disponibles: set[str]) -> None:
    """Encabezado del grupo ``g`` y sus fichas, en dos columnas si el grupo es compacto."""
    st.subheader(g.titulo, anchor=g.clave)
    st.markdown(f"<p class='nota'>{g.bajada}</p>", unsafe_allow_html=True)
    if g.compacto:
        with st.container(horizontal=True, key=f"tarjetas2_{g.clave}"):
            for v in fichas:
                _ficha(v, disponibles)
    else:
        for v in fichas:
            _ficha(v, disponibles)


def _fuente(f: variables.Fuente) -> None:
    """Abre la sección de la fuente ``f``: qué es, sus rasgos y lo que no puede hacer."""
    st.divider()
    st.header(f.titulo, anchor=f.clave)
    st.markdown(f"<p class='lede'>{f.bajada}</p>", unsafe_allow_html=True)
    filas = "".join(f"<tr><th>{r}</th><td>{_md_html(v)}</td></tr>" for r, v in f.ficha)
    with st.container(border=True, key=f"hoja_fuente_{f.clave}"):
        st.markdown(f"<table class='rasgos'>{filas}</table>", unsafe_allow_html=True)
        st.markdown(f"**Lo que no puede hacer.** {f.limites}")
        st.markdown(f"<p class='nota'>Fuentes: {_citas(f.refs)}</p>", unsafe_allow_html=True)


def _bibliografia() -> None:
    """Todas las referencias citadas, cada una con su ancla y su enlace."""
    st.divider()
    st.header("Referencias", anchor="referencias")
    items = []
    for k, r in variables.REFERENCIAS.items():
        texto = r.url.removeprefix("https://").removeprefix("doi.org/")
        enlace = f" <a href='{html.escape(r.url)}'>{html.escape(texto)}</a>" if r.url else ""
        items.append(f"<li id='{_ancla_ref(k)}'>{_md_html(r.completa)}{enlace}</li>")
    st.markdown(f"<ul class='bibliografia'>{''.join(items)}</ul>", unsafe_allow_html=True)


def _md_html(texto: str) -> str:
    """Las cursivas y el código de ``texto`` (markdown) en HTML, para usarlo dentro de una lista HTML."""
    partes = html.escape(texto).split("`")
    texto = "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(partes))
    partes = texto.split("*")
    return "".join(f"<em>{p}</em>" if i % 2 else p for i, p in enumerate(partes))


def _indice() -> str:
    """El índice: cada fuente con sus grupos, y la bibliografía."""
    items = []
    for f in variables.FUENTES:
        sub = "".join(
            f"<li><a href='#{g.clave}'>{g.titulo}</a></li>"
            for g in variables.GRUPOS
            if g.fuente == f.clave
        )
        corto = f.titulo.split(" · ")[0]
        items.append(f"<li><a href='#{f.clave}'>{corto}</a><ol>{sub}</ol></li>")
    items.append("<li><a href='#referencias'>Referencias</a></li>")
    return f"<nav class='indice' aria-label='En esta página'><ol>{''.join(items)}</ol></nav>"


def _cuerpo() -> None:
    """Portada, buscador y fichas (todas, las que coinciden con la búsqueda, o una sola)."""
    st.title("Datos", anchor="inicio")
    st.markdown(
        f"<p class='lede'>Las {len(variables.VARIABLES)} variables del proyecto, ordenadas por linaje: "
        "cada fuente cruda primero y, debajo, lo que se calcula con ella. Cada ficha dice qué es la "
        "variable, por qué importa para un mesociclón, cómo se calcula y qué cuidar en el hemisferio "
        "sur.</p>",
        unsafe_allow_html=True,
    )
    disponibles = _disponibles()
    foco = _foco()
    if foco is not None:
        st.button("Ver todas las variables", icon=":material/arrow_back:", on_click=_enfoca,
                  args=(None,))  # fmt: skip
        _ficha(foco, disponibles, sufijo="_foco")
        _bibliografia()
        return

    consulta = st.text_input(
        "Buscar una variable", key="datos_busca", icon=":material/search:",
        placeholder="CAPE, helicidad, C13, cizalle, Register…",
    )  # fmt: skip
    if not disponibles:
        st.caption(
            "No hay datos preparados para el día elegido: las fichas se leen igual, pero sin el botón "
            "«Ver en Mapas»."
        )
    if consulta.strip():
        hallados = variables.busca(consulta)
        if not hallados:
            st.info(
                f"Ninguna variable coincide con «{consulta.strip()}». Prueba con un símbolo (CAPE, C13) "
                "o una palabra (helicidad, tropopausa)."
            )
            st.button("Borrar la búsqueda", icon=":material/close:", on_click=_limpia_busqueda)
            return
        st.caption(f"{len(hallados)} de {len(variables.VARIABLES)} variables.")
        for g in variables.GRUPOS:
            del_grupo = [v for v in hallados if v.grupo == g.clave]
            if del_grupo:
                _grupo(g, del_grupo, disponibles)
        return

    for f in variables.FUENTES:
        _fuente(f)
        for g in variables.GRUPOS:
            if g.fuente == f.clave:
                _grupo(g, [v for v in variables.VARIABLES if v.grupo == g.clave], disponibles)
    _bibliografia()


def pagina() -> None:
    """Dibuja la página con el índice al costado (o desplegable arriba en pantallas angostas)."""
    with st.container(key="datos"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key="datos_cuerpo"):
            with st.expander("En esta página", key="indice_compacto", icon=":material/toc:"):
                st.markdown(_indice(), unsafe_allow_html=True)
            _cuerpo()
        with st.container(width=220, key="indice_lateral"):
            st.markdown("<p class='indice-titulo'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(_indice(), unsafe_allow_html=True)
