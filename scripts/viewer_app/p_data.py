"""Página «Datos»: el catálogo de datos, una ficha por variable, ordenadas por fuente y linaje.

Los textos viven en ``variables.py``. Esta página no necesita datos: sin recortes muestra todas las
fichas; con recortes, cada ficha cuyo producto existe el día elegido trae un botón «Ver en Mapas».
Una ficha sola se pide con ``?v=<clave>`` en la URL o desde la ayuda de Mapas
(``state.go_to_variable``).
"""

import html

import streamlit as st

from viewer_app import products, state, variables
from viewer_app.variables import Variable


def _ref_anchor(k: str) -> str:
    """Ancla de la referencia ``k`` en la bibliografía."""
    return f"ref-{k}"


def _citations(keys: list[str] | tuple[str, ...]) -> str:
    """Las citas cortas de ``keys``, enlazadas a la bibliografía del final de la página."""
    return " · ".join(
        f"<a href='#{_ref_anchor(k)}'>{html.escape(variables.REFERENCES[k].short)}</a>"
        for k in keys
    )


def _focus() -> Variable | None:
    """La ficha pedida por la URL o por otra página; la URL queda al día para compartirla."""
    requested = st.session_state.pop("data_focus", None) or st.query_params.get("v")
    if requested in variables.BY_KEY:
        st.query_params["v"] = requested
        return variables.BY_KEY[requested]
    st.query_params.pop("v", None)
    return None


def _set_focus(key: str | None) -> None:
    """Callback: muestra solo la ficha ``key`` (``None``: todas)."""
    if key is None:
        st.query_params.pop("v", None)
    else:
        st.session_state["data_focus"] = key


def _on_input(widget: str) -> None:
    """Callback de las píldoras «Se calcula con»: abre la ficha del insumo elegido."""
    _set_focus(st.session_state[widget])
    st.session_state[widget] = None


def _clear_search() -> None:
    """Callback: borra el texto del buscador."""
    st.session_state["data_search"] = ""


def _available() -> set[str]:
    """Claves de producto del día elegido en la barra lateral; vacío si no hay datos."""
    ctx = st.session_state.get("ctx")
    return set(products.catalog(ctx.day)) if ctx is not None else set()


def _variable(v: Variable, available: set[str], suffix: str = "") -> None:
    """Dibuja la ficha de ``v``. ``suffix`` distingue las claves de widget si la ficha se repite."""
    k = f"{v.key}{suffix}"
    with st.container(border=True, key=f"sheet_v_{k}", gap="small"):
        meta = " · ".join(html.escape(x) for x in (v.symbol, v.unit) if x)
        st.markdown(
            f"<h4 class='var-name' id='{html.escape(v.key)}'>{html.escape(v.name)}</h4>"
            f"<p class='var-meta mono'>{meta}</p>",
            unsafe_allow_html=True,
        )
        st.markdown(v.what)
        if v.why:
            st.markdown(f"**Por qué importa.** {v.why}")
        if v.formula:
            st.latex(v.formula)
        if v.method:
            st.markdown(f"<div class='note'>\n\n{v.method}\n\n</div>", unsafe_allow_html=True)
        if v.threshold:
            with st.container(key=f"threshold_{k}"):
                st.markdown(f"**Criterio en Chile.** {v.threshold}")
        if v.caveat:
            st.markdown(f"**Cuidado.** {v.caveat}")
        if v.inputs:
            st.pills(
                "Se calcula con", list(v.inputs), key=f"inputs_{k}",
                format_func=lambda c: variables.BY_KEY[c].symbol,
                on_change=_on_input, args=(f"inputs_{k}",),
            )  # fmt: skip
        st.markdown(
            f"<p class='note var-refs'>Fuentes: {_citations(variables.references_of(v))}</p>",
            unsafe_allow_html=True,
        )
        in_maps = next((p for p in v.products if p in available), None)
        if in_maps is not None:
            st.button(
                "Ver en Mapas", key=f"map_{k}", icon=":material/map:", type="tertiary",
                on_click=state.open_in_maps, args=(in_maps, v.level),
            )  # fmt: skip


def _group(g: variables.Group, vs: list[Variable], available: set[str]) -> None:
    """Encabezado del grupo ``g`` y sus fichas, en dos columnas si el grupo es compacto."""
    st.subheader(g.title, anchor=g.key)
    st.markdown(f"<p class='note'>{g.lede}</p>", unsafe_allow_html=True)
    if g.compact:
        with st.container(horizontal=True, key=f"cards2_{g.key}"):
            for v in vs:
                _variable(v, available)
    else:
        for v in vs:
            _variable(v, available)


def _source(s: variables.Source) -> None:
    """Abre la sección de la fuente ``s``: qué es, sus rasgos y lo que no puede hacer."""
    st.divider()
    st.header(s.title, anchor=s.key)
    st.markdown(f"<p class='lede'>{s.lede}</p>", unsafe_allow_html=True)
    rows = "".join(f"<tr><th>{f}</th><td>{_md_html(v)}</td></tr>" for f, v in s.facts)
    with st.container(border=True, key=f"sheet_source_{s.key}"):
        st.markdown(f"<table class='facts'>{rows}</table>", unsafe_allow_html=True)
        st.markdown(f"**Lo que no puede hacer.** {s.limits}")
        st.markdown(f"<p class='note'>Fuentes: {_citations(s.refs)}</p>", unsafe_allow_html=True)


def _bibliography() -> None:
    """Todas las referencias citadas, cada una con su ancla y su enlace."""
    st.divider()
    st.header("Referencias", anchor="referencias")
    items = []
    for k, r in variables.REFERENCES.items():
        text = r.url.removeprefix("https://").removeprefix("doi.org/")
        link = f" <a href='{html.escape(r.url)}'>{html.escape(text)}</a>" if r.url else ""
        items.append(f"<li id='{_ref_anchor(k)}'>{_md_html(r.full)}{link}</li>")
    st.markdown(f"<ul class='bibliography'>{''.join(items)}</ul>", unsafe_allow_html=True)


def _md_html(text: str) -> str:
    """Las cursivas y el código de ``text`` (markdown) en HTML, para usarlo dentro de HTML propio.

    Solo entiende ``*cursiva*`` y ```código```: no usar negritas ni asteriscos sueltos en ``facts`` ni
    en ``Reference.full`` (la prueba de ``variables`` lo comprueba).
    """
    parts = html.escape(text).split("`")
    text = "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))
    parts = text.split("*")
    return "".join(f"<em>{p}</em>" if i % 2 else p for i, p in enumerate(parts))


def _toc() -> str:
    """El índice: cada fuente con sus grupos, y la bibliografía."""
    items = []
    for s in variables.SOURCES:
        sub = "".join(
            f"<li><a href='#{g.key}'>{g.title}</a></li>"
            for g in variables.GROUPS
            if g.source == s.key
        )
        items.append(f"<li><a href='#{s.key}'>{s.title.split(' · ')[0]}</a><ol>{sub}</ol></li>")
    items.append("<li><a href='#referencias'>Referencias</a></li>")
    return f"<nav class='toc' aria-label='En esta página'><ol>{''.join(items)}</ol></nav>"


def _body() -> bool:
    """Portada, buscador y fichas (todas, las que coinciden con la búsqueda, o una sola).

    Devuelve si se dibujó la lista completa: solo entonces existen todas las anclas del índice.
    """
    st.title("Datos", anchor="inicio")
    st.markdown(
        f"<p class='lede'>Las {len(variables.VARIABLES)} variables del proyecto, ordenadas por linaje: "
        "cada fuente cruda primero y, debajo, lo que se calcula con ella. Cada ficha dice qué es la "
        "variable, por qué importa para un mesociclón, cómo se calcula y qué cuidar en el hemisferio "
        "sur.</p>",
        unsafe_allow_html=True,
    )
    available = _available()
    focus = _focus()
    if focus is not None:
        st.button("Ver todas las variables", icon=":material/arrow_back:", on_click=_set_focus,
                  args=(None,))  # fmt: skip
        _variable(focus, available, suffix="_focus")
        _bibliography()
        return False

    state.restore("data_search")
    query = st.text_input(
        "Buscar una variable", key="data_search", icon=":material/search:",
        placeholder="CAPE, helicidad, C13, cizalle, Register…",
    )  # fmt: skip
    state.save("data_search")
    if not available:
        st.caption(
            "No hay datos preparados para el día elegido: las fichas se leen igual, pero sin el botón "
            "«Ver en Mapas»."
        )
    if query.strip():
        found = variables.search(query)
        if not found:
            st.info(
                f"Ninguna variable coincide con «{query.strip()}». Prueba con un símbolo (CAPE, C13) "
                "o una palabra (helicidad, tropopausa)."
            )
            st.button("Borrar la búsqueda", icon=":material/close:", on_click=_clear_search)
            return False
        st.caption(f"{len(found)} de {len(variables.VARIABLES)} variables.")
        for g in variables.GROUPS:
            in_group = [v for v in found if v.group == g.key]
            if in_group:
                _group(g, in_group, available)
        return False

    for s in variables.SOURCES:
        _source(s)
        for g in variables.GROUPS:
            if g.source == s.key:
                _group(g, [v for v in variables.VARIABLES if v.group == g.key], available)
    _bibliography()
    return True


def page() -> None:
    """Dibuja la página con el índice al costado (o desplegable arriba en pantallas angostas)."""
    with st.container(key="data"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key="data_body"):
            compact = st.empty()  # el índice va arriba, pero se decide después de dibujar el cuerpo
            full = _body()
        if full:
            with compact.expander("En esta página", key="toc_compact", icon=":material/toc:"):
                st.markdown(_toc(), unsafe_allow_html=True)
            with st.container(width=220, key="toc_side"):
                st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
                st.markdown(_toc(), unsafe_allow_html=True)
