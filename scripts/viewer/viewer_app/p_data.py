"""Página «Datos»: el catálogo de datos, una ficha por variable, ordenadas por fuente y linaje.

Los textos viven en ``variables.py``. Esta página no necesita datos: sin recortes muestra todas las
fichas; con recortes, cada ficha cuyo producto existe el día elegido trae un botón «Ver en Mapas».
La página siempre muestra todas las fichas: ``?v=<clave>`` en la URL, o la ayuda de Mapas
(``state.go_to_variable``), lleva a la ficha pedida desplazando la página hasta ella.
"""

import html

import streamlit as st

from viewer_app import layout, products, state, theme, variables
from viewer_app.variables import Variable


def _citations(keys: list[str] | tuple[str, ...]) -> str:
    """Las citas cortas de ``keys``, enlazadas a la bibliografía del final de la página."""
    return " · ".join(
        f"<a href='#ref-{k}'>{html.escape(variables.REFERENCES[k].short)}</a>" for k in keys
    )


def _scroll_target() -> str | None:
    """La clave de la ficha a la que ir: la pedida por la URL o por otra página, si existe."""
    requested = st.session_state.pop("data_focus", None) or st.query_params.get("v")
    st.query_params.pop("v", None)
    return requested if requested in variables.BY_KEY else None


def _scroll_to(key: str) -> None:
    """Desplaza la página hasta la ficha ``key`` cuando ya está dibujada (Streamlit la va armando)."""
    st.html(
        "<script>(() => { let n = 0; const t = setInterval(() => {"
        f"const el = document.getElementById('{key}');"
        "if (el) { el.scrollIntoView(); clearInterval(t); } else if (++n > 50) clearInterval(t);"
        "}, 100); })();</script>",
        unsafe_allow_javascript=True,
    )


def _available() -> set[str]:
    """Claves de producto del día elegido en la barra lateral; vacío si no hay datos."""
    ctx = st.session_state.get("ctx")
    return set(products.catalog(ctx.day)) if ctx is not None else set()


def _variable(v: Variable, available: set[str]) -> None:
    """Dibuja la ficha de ``v``: un riel (identidad y enlaces) junto al cuerpo."""
    k = v.key
    in_maps = next((p for p in v.products if p in available), None)
    with st.container(border=True, key=f"sheet_v_{k}", gap="small"):
        with st.container(key=f"rail_{k}", gap="small"):
            meta = " · ".join(html.escape(x) for x in (v.symbol, v.unit) if x)
            # Streamlit reescribe el id de los encabezados con su texto: el ancla va en un span aparte.
            st.markdown(
                f"<span class='var-anchor' id='{html.escape(v.key)}'></span>"
                f"<h4 class='var-name'>{html.escape(v.name)}</h4>"
                f"<p class='var-meta mono'>{meta}</p>",
                unsafe_allow_html=True,
            )
            if v.inputs:
                links = " ".join(
                    f"<a class='go' href='#{c}' title='Ir a la ficha de {html.escape(variables.BY_KEY[c].name)}'>"
                    f"{html.escape(variables.BY_KEY[c].symbol)}</a>"
                    for c in v.inputs
                )
                st.markdown(
                    f"<p class='var-inputs'><span class='note'>Se calcula con</span> {links}</p>",
                    unsafe_allow_html=True,
                )
            if in_maps is not None:
                st.button(
                    "Ver en Mapas", key=f"map_{k}", icon=":material/map:", type="tertiary",
                    on_click=state.open_in_maps, args=(in_maps, v.level),
                )  # fmt: skip
        with st.container(key=f"body_{k}", gap="small"):
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
            st.markdown(
                f"<p class='note var-refs'>Fuentes: {_citations(variables.references_of(v))}</p>",
                unsafe_allow_html=True,
            )


def _group(g: variables.Group, vs: list[Variable], available: set[str]) -> None:
    """Encabezado del grupo ``g`` y sus fichas."""
    st.subheader(g.title, anchor=g.key)
    st.markdown(f"<p class='note'>{g.lede}</p>", unsafe_allow_html=True)
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
    cited = {k for v in variables.VARIABLES for k in variables.references_of(v)}
    cited |= {k for s in variables.SOURCES for k in s.refs}
    for k, r in variables.REFERENCES.items():
        if k not in cited:  # las notas de prensa solo se enlazan en Problema
            continue
        text = r.url.removeprefix("https://").removeprefix("doi.org/")
        link = f" <a href='{html.escape(r.url)}'>{html.escape(text)}</a>" if r.url else ""
        items.append(f"<li id='ref-{k}'>{_md_html(r.full)}{link}</li>")
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


_INTRO = (
    (
        "ERA5",
        "El reanálisis global del ECMWF: una reconstrucción de la atmósfera hora a hora desde 1940, "
        "que combina un modelo con observaciones de radiosondas, satélites, aviones y estaciones. "
        "Entrega viento, temperatura, humedad y energía disponible en una grilla de ~31 km. Sus "
        "celdas son demasiado grandes para ver una tormenta, pero muestran el ambiente en que se forma.",
    ),
    (
        "GOES",
        "Un satélite geoestacionario sobre 75,2° O. Su radiómetro ABI mide 16 bandas, del visible al "
        "infrarrojo, cada 10 minutos y con píxeles de 2 km. De ahí salen la altura del tope de las "
        "nubes y su evolución. Ve la nube, pero no el giro dentro de ella.",
    ),
    (
        "Catálogo",
        "102 tornados y trombas marinas en Chile entre 1554 y 2025, reunidos desde crónicas, prensa y "
        "literatura científica (Bastías-Curivil et al.). Son los eventos con los que se comparan ERA5 "
        "y GOES. Solo incluye eventos que ocurrieron: faltan ejemplos de días de tormenta sin tornado, "
        "que un modelo necesita para aprender.",
    ),
)


def _intro() -> None:
    """Qué es cada fuente, en pocas líneas, antes de entrar a las fichas."""
    cols = theme.columns([1, 1, 1], "sources_intro")
    for col, (title, text) in zip(cols, _INTRO, strict=True):
        with (
            col,
            st.container(border=True, key=f"sheet_intro_{title.split()[0].lower()}", gap="small"),
        ):
            st.markdown(f"**{title}**")
            st.markdown(text)


def _index() -> None:
    """Tabla origen | categoría | variables | ir a: una fila por variable, con su botón a la ficha."""
    st.subheader("Ir a una variable", anchor=False)
    rows = []
    for s in variables.SOURCES:
        first_in_source = True
        n_source = sum(
            v.group == g.key
            for g in variables.GROUPS
            if g.source == s.key
            for v in variables.VARIABLES
        )
        for g in variables.GROUPS:
            if g.source != s.key:
                continue
            vs = [v for v in variables.VARIABLES if v.group == g.key]
            for i, v in enumerate(vs):
                cells = ""
                if first_in_source:
                    cells += f"<td rowspan='{n_source}'>{html.escape(s.title.split(' · ')[0])}</td>"
                    first_in_source = False
                if i == 0:
                    cells += f"<td rowspan='{len(vs)}'>{html.escape(g.title)}</td>"
                cells += f"<td>{html.escape(v.name)}</td><td><a class='go' href='#{v.key}' title='Ir a la ficha de {html.escape(v.name)}'>{html.escape(v.symbol)}</a></td>"
                rows.append(f"<tr>{cells}</tr>")
    head = "<tr><th>Origen</th><th>Categoría</th><th>Variable</th><th>Ir a</th></tr>"
    st.markdown(
        f"<div class='var-table-wrap'><table class='var-table'>{head}{''.join(rows)}</table></div>",
        unsafe_allow_html=True,
    )


def _body() -> None:
    """Portada, índice y todas las fichas."""
    st.title("Datos", anchor="inicio")
    st.markdown(
        f"<p class='lede'>El proyecto usa {len(variables.VARIABLES)} variables. Casi todas salen de "
        "tres fuentes: ERA5, GOES y el catálogo de tornados. Cada fuente va primero, con sus datos tal "
        "como llegan, y debajo lo que se calcula a partir de ellos. Cada ficha explica qué es la "
        "variable, por qué importa para un mesociclón, cómo se calcula y qué cuidar en el hemisferio "
        "sur.</p>",
        unsafe_allow_html=True,
    )
    _intro()
    available = _available()
    target = _scroll_target()
    _index()
    if not available:
        st.caption(
            "No hay datos preparados para el día elegido: las fichas se leen igual, pero sin el botón "
            "«Ver en Mapas»."
        )
    for s in variables.SOURCES:
        _source(s)
        for g in variables.GROUPS:
            if g.source == s.key:
                _group(g, [v for v in variables.VARIABLES if v.group == g.key], available)
    _bibliography()
    if target:
        _scroll_to(target)


def page() -> None:
    """Dibuja la página con el índice al costado (o desplegable arriba en pantallas angostas)."""
    layout.page("data", _toc(), _body)
