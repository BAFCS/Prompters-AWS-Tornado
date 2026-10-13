"""Piezas compartidas por las páginas de lectura (Problema, Datos, Caso de estudio, Starter kit y
Referencias).

``page`` arma el armazón común: el cuerpo y el índice, que va en una columna fija a la derecha con
ancho de sobra y en un desplegable arriba en pantallas angostas. El CSS de ``theme.py`` se engancha a
las claves ``page_<nombre>`` y ``pagebody_<nombre>``, así que una página nueva no necesita CSS propio.
"""

import html
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

import streamlit as st

Color = Literal["orange", "primary"]


def section(anchor: str, title: str, subtitle: str) -> None:
    """Encabezado de sección: título con ``anchor`` para el índice y una frase de contexto."""
    st.divider()
    st.header(title, anchor=anchor)
    st.markdown(f"<p class='lede'>{subtitle}</p>", unsafe_allow_html=True)


def image(source: Path | str, description: str, key: str | None = None) -> None:
    """Conserva el visor de imagen nativo y publica su descripción para el vigía del tema.

    Un archivo usa su nombre como clave; un SVG en texto necesita ``key``.
    """
    if key is None:
        if not isinstance(source, Path):
            raise ValueError("Un SVG en texto necesita key.")
        key = source.stem
    with st.container(key=f"image_{key}"):
        st.image(str(source) if isinstance(source, Path) else source, width="stretch")
        st.html(
            f'<span class="project-image-alt" data-description="{html.escape(description, quote=True)}" hidden></span>'
        )


def cards(key: str, items: list[tuple[str, Color, str, str]], n_columns: int = 2) -> None:
    """Tarjetas en una grilla: (insignia, color de la insignia, título, texto).

    La grilla la arma el CSS de ``theme.py`` (clave ``cards<n>_``): ``n_columns`` con ancho de sobra
    y menos columnas cuando la página es angosta, en vez de columnas que solo se apilan en teléfono.
    """
    with st.container(horizontal=True, key=f"cards{n_columns}_{key}"):
        for i, (badge, color, title, text) in enumerate(items):
            with st.container(border=True, key=f"sheet_{key}_{i}"):
                st.badge(badge, color=color)
                st.markdown(f"**{title}**")
                st.markdown(text)


def md_html(text: str) -> str:
    """Las cursivas y el código de ``text`` (markdown) en HTML, para usarlo dentro de HTML propio.

    Solo entiende ``*cursiva*`` y ```código```: no usar negritas ni asteriscos sueltos en los rasgos de
    las fuentes ni en ``Reference.full`` (la prueba de ``variables`` lo comprueba).
    """
    parts = html.escape(text).split("`")
    text = "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))
    parts = text.split("*")
    return "".join(f"<em>{p}</em>" if i % 2 else p for i, p in enumerate(parts))


def scroll_to(element_id: str) -> None:
    """Desplaza la página hasta ``element_id`` cuando ya está dibujado (Streamlit lo va armando)."""
    st.html(
        "<script>(() => { let n = 0; const t = setInterval(() => {"
        f"const el = document.getElementById('{element_id}');"
        "if (el) { el.scrollIntoView(); clearInterval(t); } else if (++n > 50) clearInterval(t);"
        "}, 100); })();</script>",
        unsafe_allow_javascript=True,
    )


def toc(sections: Iterable[tuple[str, str]]) -> str:
    """Un índice plano: cada (ancla, texto) como enlace."""
    links = "".join(f"<li><a href='#{anchor}'>{text}</a></li>" for anchor, text in sections)
    return f"<nav class='toc' aria-label='En esta página'><ol>{links}</ol></nav>"


def page(name: str, index: str, body: Callable[[], None]) -> None:
    """Dibuja ``body`` con el índice ``index`` (HTML) al costado o en un desplegable arriba.

    El CSS de ``theme.py`` elige cuál de los dos mostrar según el ancho de ``.st-key-page_<name>``
    (880 px).
    """
    with st.container(key=f"page_{name}"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key=f"pagebody_{name}"):
            with st.expander("En esta página", key="toc_compact", icon=":material/toc:"):
                st.markdown(index, unsafe_allow_html=True)
            body()
        with st.container(width=220, key="toc_side"):
            st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(index, unsafe_allow_html=True)
