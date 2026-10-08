"""Página «Caso de estudio»: eventos reportados y comparación de su entorno atmosférico."""

import dataclasses

import pandas as pd
import streamlit as st

from viewer_app import charts, colorscales, components, data, layers, products, state, texts


def _on_row_select() -> None:
    """Callback de la bitácora: la fila elegida fija la hora y el punto en todas las páginas."""
    sel = st.session_state["event_log"].selection.rows
    ev = state.context().events
    if sel:
        state.go_to_event(ev.iloc[sel[0]])


def _colorscale_picker(kind: str, key: str) -> str:
    """Selector de la escala de color de un mapa: las estándar de su tipo de dato, recordada por página."""
    ops = colorscales.KINDS[kind]
    state.restore(key)
    if st.session_state.get(key) not in [e.name for e in ops]:
        st.session_state[key] = ops[0].name
    name = st.selectbox(
        "Escala de color", [e.name for e in ops], key=key, width=420,
        format_func=lambda n: colorscales.pick(kind, n).display_label,
    )  # fmt: skip
    state.save(key)
    return str(name)


def _map(ctx: state.Context, t: pd.Timestamp | None) -> None:
    """Mapa de la zona de los eventos: GOES C13 a la hora elegida (o el VGP si no hay GOES)."""
    cat = products.catalog(ctx.day)
    c = layers.layer(ctx.day, cat["goes:C13"], t) if t is not None and "goes:C13" in cat else None
    is_goes = c is not None  # si no, se intenta el VGP y la escala es la secuencial
    if c is None and t is not None and "idx:vgp_01" in cat:
        c = layers.layer(ctx.day, cat["idx:vgp_01"], t)
    if (
        c is None or c.kind is None
    ):  # tipo es None solo en RGB; la guarda acota el tipo para pyright
        st.info("Este día no tiene GOES ni índices ERA5 para dibujar el mapa.")
        return
    c = c.with_colorscale(
        _colorscale_picker(c.kind, "case_colorscale_ir" if is_goes else "case_colorscale_seq")
    )
    c = dataclasses.replace(c, title=f"{c.title} UTC")
    enc = charts.events_extent(ctx.events, ctx.reg, margin=1.3)
    fig, _ = charts.grid(
        [c], [None], enc, data.coast(ctx.reg), events=ctx.events, point=state.point(), height=560
    )
    st.plotly_chart(fig, width="stretch", theme=None, key="case_map")
    if is_goes:
        st.caption(
            "Las temperaturas de brillo más bajas (en la escala de grises, los tonos más blancos) "
            "pueden asociarse a nubes más altas; no miden directamente su altura. Triángulos "
            "rojos: eventos del catálogo; doble anillo: el punto elegido. Sin corrección de paralaje."
        )


def _event_log(ctx: state.Context) -> None:
    """Tabla de eventos del día, seleccionable."""
    st.header("Eventos reportados del día", anchor="eventos")
    if ctx.events.empty:
        st.caption(
            "El catálogo no contiene reportes de tornados o trombas marinas "
            "para este día. Esto no permite confirmar su ausencia. Puedes explorar las "
            "condiciones atmosféricas, pero el día no debe considerarse automáticamente "
            "un caso negativo."
        )
        return
    table = pd.DataFrame(
        {
            "UTC": ctx.events["hour_txt"],
            "Lugar": ctx.events["place"],
            "EF": ctx.events["ef"],
            "Tipo": ctx.events["kind"],
        }
    )
    st.dataframe(
        table, hide_index=True, width="stretch", key="event_log", on_select=_on_row_select,
        selection_mode="single-row",
        column_config={"UTC": st.column_config.TextColumn(width=66),
                       "Lugar": st.column_config.TextColumn(width=195),
                       "EF": st.column_config.TextColumn(width=40),
                       "Tipo": st.column_config.TextColumn(width=80)},
    )  # fmt: skip
    st.caption("Elige una fila para llevar la hora y el punto a ese evento en todas las páginas.")


def _scorecard(ctx: state.Context, t: pd.Timestamp | None) -> None:
    """Compara índices con criterios y referencias para la hora ERA5 más cercana."""
    st.header("Índices del entorno y referencias", anchor="indices")
    if ctx.day.idx is None or t is None:
        st.caption(
            "No hay índices preparados para este día. Elige otra fecha "
            "disponible o consulta cómo preparar los datos."
        )
        return
    ds = data.open_nc(ctx.day.idx)
    enc = charts.events_extent(ctx.events, ctx.reg, margin=0.5)
    p = state.point()
    rows = components.index_rows(
        ds, t, (p.lat, p.lon) if p else None, (enc.north, enc.south, enc.west, enc.east)
    )
    hour = data.to_timestamp(ds["time"].sel(time=t, method="nearest"))
    st.html(components.scorecard(rows, p.name if p else "punto", "Extremo del área"))
    st.caption(
        f"ERA5 {hour:%H:%M} UTC. La columna del punto corresponde a la celda ERA5 más cercana "
        "al lugar elegido. «Extremo del área» es el máximo o mínimo de cada índice dentro "
        "del rectángulo que abarca los eventos y sus márgenes; no es un radio alrededor "
        "de cada evento. Las marcas comparan esa columna con el criterio indicado. "
        "Las referencias del caso de 2019 no son umbrales de decisión. Cumplir un criterio "
        "describe el entorno y no confirma un tornado. " + texts.SOUTHERN_NOTE
    )
    st.caption(texts.STP_NOTE)


def _toc(has_context: bool) -> str:
    """El índice de la página como lista de enlaces a sus secciones."""
    items = [("resumen", "Resumen")]
    if has_context:
        items.append(("contexto", "Qué pasó"))
    items += [
        ("mapa", "Mapa"),
        ("eventos", "Eventos reportados"),
        ("indices", "Índices del entorno"),
        ("limites", "Límites de este análisis"),
    ]
    links = "".join(f"<li><a href='#{a}'>{t}</a></li>" for a, t in items)
    return f"<nav class='toc' aria-label='En esta página'><ol>{links}</ol></nav>"


def _summary(ctx: state.Context) -> None:
    """Cifras del día: eventos, EF máximo y primer y último reporte (UTC)."""
    ev = ctx.events
    st.header("Resumen del día", anchor="resumen")
    if ev.empty:
        st.caption("El catálogo no tiene reportes para este día.")
        return
    grades = pd.to_numeric(ev["ef"].str.extract(r"(\d)")[0], errors="coerce").dropna()
    timed = ev[ev["hour"].map(pd.notna).astype(bool)]  # ya vienen ordenadas por hora
    hours = timed["hour_txt"].tolist()
    cols = st.columns(4)  # cifras cortas: caben en 4 columnas aun con el cuerpo angosto
    for col, (label, value) in zip(
        cols,
        [
            ("Eventos", str(len(ev))),
            ("EF máximo", f"EF{int(grades.max())}" if len(grades) else "—"),
            ("Primer reporte (UTC)", hours[0].split("-")[0] if hours else "—"),
            ("Último reporte (UTC)", hours[-1].split("-")[-1] if hours else "—"),
        ],
        strict=True,
    ):
        col.metric(label, value, border=True)


def _limits() -> None:
    """Lo que ERA5, GOES y el catálogo no permiten concluir, visible al cierre."""
    st.header("Límites de este análisis", anchor="limites")
    st.markdown(
        "- **ERA5** tiene una resolución de unos 31 km y datos horarios, por lo que no representa "
        "directamente un mesociclón.\n"
        "- **GOES**: una imagen satelital tampoco confirma por sí sola un tornado.\n"
        "- **El catálogo** reúne tornados y trombas marinas reportados y no proporciona una "
        "etiqueta directa de mesociclón. En la tabla, EF es una clasificación de intensidad "
        "basada en los daños observados."
    )


def _body(ctx: state.Context, c: texts.Case, t: pd.Timestamp | None) -> None:
    """Título, resumen, contexto, mapa con los eventos debajo, índices y límites."""
    steps = texts.TOURS.get(ctx.day.date, ())
    st.title(c.title, anchor="inicio")
    st.html(f"<p class='lede'>{c.lede}</p>")
    st.markdown(
        "Esta página explora un caso histórico: compara eventos reportados con el entorno "
        "estimado por ERA5 y las nubes observadas por GOES. La capacidad de predicción "
        "del proyecto está pendiente de evaluación."
    )
    if steps and state.current_step() is None:
        st.button(
            "Empezar recorrido guiado", icon=":material/play_arrow:", key="case_tour",
            on_click=state.apply_step, args=(ctx.day.date, 0, ctx.events),
        )  # fmt: skip
    _summary(ctx)
    if c.context:
        st.header("Qué pasó", anchor="contexto")
        for paragraph in c.context:
            st.markdown(paragraph)
    st.header("Mapa", anchor="mapa")
    _map(ctx, t)
    _event_log(ctx)
    _scorecard(ctx, t)
    _limits()
    st.divider()
    st.page_link(
        state.page("maps"), label="Seguir en Mapas: el entorno y la tormenta lado a lado",
        icon=":material/map:",
    )  # fmt: skip


def page() -> None:
    """Dibuja la página con el índice al costado (o desplegable arriba en pantallas angostas)."""
    ctx = state.context()
    c = texts.case_for(ctx.day.date, len(ctx.events))
    t = state.current_time()
    toc = _toc(bool(c.context))
    with st.container(key="case"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key="case_body"):
            with st.expander("En esta página", key="toc_compact", icon=":material/toc:"):
                st.markdown(toc, unsafe_allow_html=True)
            _body(ctx, c, None if t is None else pd.Timestamp(t))
        with st.container(width=220, key="toc_side"):
            st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(toc, unsafe_allow_html=True)
