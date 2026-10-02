"""Página «El caso»: qué pasó, cuándo y dónde, y cómo estaba el entorno contra el umbral chileno."""

import pandas as pd
import streamlit as st

from visor_app import componentes, datos, estado, graficos, tema, textos


def _al_elegir_fila() -> None:
    """Callback de la bitácora: la fila elegida fija la hora y el punto en todas las páginas."""
    sel = st.session_state["bitacora"].selection.rows
    ev = estado.contexto().eventos
    if sel:
        estado.ir_a_evento(ev.iloc[sel[0]])


def _mapa(ctx: estado.Contexto, t: pd.Timestamp | None) -> None:
    """Mapa de la zona de los eventos: GOES C13 a la hora elegida (o el VGP si no hay GOES)."""
    enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg, margen=1.3)
    costa = datos.costa(ctx.reg)
    img = datos.imagen_en(ctx.dia, t) if t is not None else None
    if img is not None:
        ruta, ti = img
        ds = datos.abre(ruta)
        z = ds["C13"].sel(time=ti).values
        fig = graficos.mapa(
            z, ds["latitude"].values, ds["longitude"].values, enc, costa,
            titulo=f"GOES-16 · infrarrojo 10,3 µm · {pd.Timestamp(ti):%H:%M} UTC",
            unidad="K", escala=tema.IR, rango=(190.0, 300.0), eventos=ctx.eventos,
            punto=estado.punto(), alto=560,
        )  # fmt: skip
        st.plotly_chart(fig, width="stretch", theme=None, key="mapa_caso")
        st.caption(
            "Topes fríos en azul: más fríos, más altos. Triángulos rojos: eventos del catálogo; "
            "círculo verde: el punto elegido. Sin corrección de paralaje."
        )
    elif ctx.dia.idx is not None and t is not None:
        ds = datos.abre(ctx.dia.idx)
        h = ds["vgp_01"].sel(time=t, method="nearest")
        fig = graficos.mapa(
            h.values, ds["latitude"].values, ds["longitude"].values, enc, costa,
            titulo=f"ERA5 · VGP₀₋₁ · {datos.instante(h['time']):%H:%M} UTC",
            unidad="m/s²", escala=tema.SECUENCIAL, rango=(0.0, 0.3), eventos=ctx.eventos,
            punto=estado.punto(), umbral=0.1, alto=560,
        )  # fmt: skip
        st.plotly_chart(fig, width="stretch", theme=None, key="mapa_caso")
    else:
        st.info("Este día no tiene GOES ni índices ERA5 para dibujar el mapa.")


def _bitacora(ctx: estado.Contexto) -> None:
    """Tabla de eventos del día, seleccionable."""
    st.subheader("Bitácora")
    if ctx.eventos.empty:
        st.markdown(
            "<p class='nota'>El catálogo no tiene eventos este día. Recuerda que solo trae positivos: "
            "un día sin eventos no es un día sin tormentas.</p>",
            unsafe_allow_html=True,
        )
        return
    tabla = pd.DataFrame(
        {
            "UTC": ctx.eventos["hora_txt"],
            "Lugar": ctx.eventos["lugar"],
            "EF": ctx.eventos["ef"],
            "Tipo": ctx.eventos["tipo"],
        }
    )
    st.dataframe(
        tabla, hide_index=True, width="stretch", key="bitacora", on_select=_al_elegir_fila,
        selection_mode="single-row",
        column_config={"UTC": st.column_config.TextColumn(width=66),
                       "Lugar": st.column_config.TextColumn(width=195),
                       "EF": st.column_config.TextColumn(width=40),
                       "Tipo": st.column_config.TextColumn(width=80)},
    )  # fmt: skip
    st.caption("Elige una fila para llevar la hora y el punto a ese evento en todas las páginas.")


def _ficha(ctx: estado.Contexto, t: pd.Timestamp | None) -> None:
    """Ficha «entorno contra umbral chileno» para la hora ERA5 más cercana."""
    st.subheader("Entorno contra umbral chileno")
    if ctx.dia.idx is None or t is None:
        st.markdown(
            "<p class='nota'>Faltan los índices de este día. Corre "
            "<code>uv run python scripts/procesa_era5.py --inicio "
            f"{ctx.dia.fecha:%Y-%m-%d}</code> cuando ERA5 esté descargado.</p>",
            unsafe_allow_html=True,
        )
        return
    ds = datos.abre(ctx.dia.idx)
    enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg, margen=0.5)
    p = estado.punto()
    filas = componentes.filas_indices(
        ds, t, (p.lat, p.lon) if p else None, (enc.norte, enc.sur, enc.oeste, enc.este)
    )
    hora = datos.instante(ds["time"].sel(time=t, method="nearest"))
    st.html(componentes.ficha(filas, p.nombre if p else "punto", "extremo zona"))
    st.caption(
        f"ERA5 {hora:%H:%M} UTC. «Extremo zona»: el valor más peligroso a menos de 0,5° de los "
        "eventos (máximo, o mínimo si el umbral es negativo); la marca «supera» compara esa "
        "columna con el umbral chileno. Solo VGP₀₋₁, cizalle 0–1 km y STP tienen umbral "
        "calibrado para Chile; el resto lleva una referencia del caso 2019. " + textos.NOTA_AUSTRAL
    )


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    c = textos.caso(ctx.dia.fecha, len(ctx.eventos))
    t = estado.t_actual()
    st.title(c.titulo)
    st.html(f"<p class='lede'>{c.lede}</p>")
    pasos = estado.recorrido(ctx.dia.fecha)
    if pasos and estado.paso_actual() is None:
        st.button(
            "Empezar recorrido guiado", icon=":material/play_arrow:", key="recorrido_caso",
            on_click=estado.aplica_paso, args=(ctx.dia.fecha, 0, ctx.eventos),
        )  # fmt: skip

    izq, der = st.columns(2, gap="large")
    with izq:
        _mapa(ctx, None if t is None else pd.Timestamp(t))
    with der:
        _bitacora(ctx)
        _ficha(ctx, None if t is None else pd.Timestamp(t))

    st.divider()
    izq, der = st.columns([3, 2], gap="large")
    with izq:
        if c.contexto:
            st.subheader("Contexto")
            for parrafo in c.contexto:
                st.markdown(parrafo)
    with der:
        st.subheader("Para seguir")
        st.page_link(
            estado.pagina("mapas"), label="Mapas: entorno y tormenta lado a lado",
            icon=":material/map:",
        )  # fmt: skip
        st.page_link(
            estado.pagina("sondeo"), label="Sondeo: perfil e hodógrafo del punto",
            icon=":material/stacked_line_chart:",
        )  # fmt: skip
        st.page_link(
            estado.pagina("series"), label="Series: la evolución alrededor del evento",
            icon=":material/timeline:",
        )  # fmt: skip
        st.markdown(
            "<p class='nota'>ERA5 (31 km, horario) describe el entorno; no resuelve un mesociclón. "
            "GOES (2 km, cada 10 min) muestra la tormenta. El catálogo solo trae tornados "
            "reportados: hay sesgo hacia donde vive gente.</p>",
            unsafe_allow_html=True,
        )
