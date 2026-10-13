"""Página «Referencias»: toda la bibliografía del visor, agrupada por tema.

Las referencias viven en ``variables.REFERENCES``. Las citas de Datos abren esta página en otra pestaña
con ``?ref=<clave>``, que la desplaza hasta esa referencia. No usa datos: se muestra aunque no haya
recortes.
"""

import html

import streamlit as st

from viewer_app import layout, variables

# Grupos por tema: (ancla, título, claves de ``variables.REFERENCES``). Cada clave va en un solo grupo.
GROUPS = (
    ("chile", "El catálogo y los tornados en Chile", ("bastias", "vicencio2021", "barrett2020",
                                                      "marin2024", "caballero2025", "marin2026")),
    ("fisica", "Física de las tormentas con rotación", ("weisman1982", "markowski2010", "rasmussen1998",
                                                        "bunkers2000")),
    ("indices", "Entornos de convección severa e índices", ("brooks2003", "sherburn2014", "thompson2003",
                                                            "thompson2012")),
    ("satelite", "Satélite y rayos", ("goes-abi", "cintineo2014", "bedka2018", "schultz2009")),
    ("aprendizaje", "Aprendizaje automático", ("lagerquist2020", "elkan2008")),
    ("datos", "Datos y herramientas", ("documento", "hersbach2020", "era5-ncar", "era5-doc", "goes-aws",
                                       "metpy")),
    ("prensa", "Prensa y divulgación", ("jerez2026", "meteored2022", "t13-2025", "mostrador2025",
                                        "uv2025")),
)  # fmt: skip

SECTIONS = (("inicio", "Inicio"), *((anchor, title) for anchor, title, _ in GROUPS))


def link(key: str) -> str:
    """Enlace HTML a la referencia ``key`` en esta página, en otra pestaña para no perder la sesión."""
    short = html.escape(variables.REFERENCES[key].short)
    return f"<a href='referencias?ref={key}' target='_blank'>{short}</a>"


def _group(anchor: str, title: str, keys: tuple[str, ...]) -> None:
    """Un tema con sus referencias, cada una con su ancla ``ref-<clave>`` y su enlace."""
    st.divider()
    st.header(title, anchor=anchor)
    items = []
    for k in keys:
        r = variables.REFERENCES[k]
        text = r.url.removeprefix("https://").removeprefix("doi.org/")
        url = f" <a href='{html.escape(r.url)}'>{html.escape(text)}</a>" if r.url else ""
        items.append(f"<li id='ref-{k}'>{layout.md_html(r.full)}{url}</li>")
    st.markdown(f"<ul class='bibliography'>{''.join(items)}</ul>", unsafe_allow_html=True)


def _body() -> None:
    """Portada y todos los grupos."""
    st.title("Referencias", anchor="inicio")
    st.markdown(
        "<p class='lede'>Los trabajos, datos y notas que citan las páginas del visor, agrupados por "
        "tema. La sección 10 del documento suma los análogos de costa occidental (Australia, "
        "California, Inglaterra) y los textos básicos de física.</p>",
        unsafe_allow_html=True,
    )
    for group in GROUPS:
        _group(*group)
    requested = st.query_params.get("ref")
    if requested in variables.REFERENCES:
        layout.scroll_to(f"ref-{requested}")


def page() -> None:
    """Dibuja la página con su índice."""
    layout.page("references", layout.toc(SECTIONS), _body)
