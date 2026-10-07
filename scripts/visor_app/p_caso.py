"""Página «El caso»: eventos reportados y comparación de su entorno atmosférico."""

import pandas as pd
import streamlit as st

from visor_app import componentes, datos, escalas, estado, graficos, tema, textos


def _al_elegir_fila() -> None:
    """Callback de la bitácora: la fila elegida fija la hora y el punto en todas las páginas."""
    sel = st.session_state["bitacora"].selection.rows
    ev = estado.contexto().eventos
    if sel:
        estado.ir_a_evento(ev.iloc[sel[0]])


def _escala(tipo: str, clave: str) -> str:
    """Selector de la escala de color de un mapa: las estándar de su tipo de dato, recordada por página."""
    ops = escalas.TIPOS[tipo]
    estado.recuerda(clave)
    if st.session_state.get(clave) not in [e.nombre for e in ops]:
        st.session_state[clave] = ops[0].nombre
    nombre = st.selectbox(
        "Escala de color", [e.nombre for e in ops], key=clave, width=420,
        format_func=lambda n: escalas.elige(tipo, n).rotulo,
    )  # fmt: skip
    estado.guarda(clave)
    return str(nombre)


def _mapa(ctx: estado.Contexto, t: pd.Timestamp | None) -> None:
    """Mapa de la zona de los eventos: GOES C13 a la hora elegida (o el VGP si no hay GOES)."""
    enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg, margen=1.3)
    costa = datos.costa(ctx.reg)
    img = datos.imagen_en(ctx.dia, t) if t is not None else None
    if img is not None:
        ruta, ti = img
        ds = datos.abre(ruta)
        z = ds["C13"].sel(time=ti).values
        escala = _escala("infrarrojo", "escala_caso_ir")
        fig = graficos.mapa(
            z, ds["latitude"].values, ds["longitude"].values, enc, costa,
            titulo=f"GOES-16 · infrarrojo 10,3 µm · {pd.Timestamp(ti):%H:%M} UTC",
            unidad="K", escala=escala, rango=(190.0, 300.0), eventos=ctx.eventos,
            punto=estado.punto(), alto=560,
        )  # fmt: skip
        st.plotly_chart(fig, width="stretch", theme=None, key="mapa_caso")
        st.caption(
            "Las temperaturas de brillo más bajas (en la escala de grises, los tonos más blancos) "
            "pueden asociarse a nubes más altas; no miden directamente su altura. Triángulos "
            "rojos: eventos del catálogo; doble anillo: el punto elegido. Sin corrección de paralaje."
        )
    elif ctx.dia.idx is not None and t is not None:
        ds = datos.abre(ctx.dia.idx)
        h = ds["vgp_01"].sel(time=t, method="nearest")
        escala = _escala("secuencial", "escala_caso_sec")
        fig = graficos.mapa(
            h.values, ds["latitude"].values, ds["longitude"].values, enc, costa,
            titulo=f"ERA5 · VGP₀₋₁ · {datos.instante(h['time']):%H:%M} UTC",
            unidad="m/s²", escala=escala, rango=(0.0, 0.3), eventos=ctx.eventos,
            punto=estado.punto(), umbral=0.1, alto=560,
        )  # fmt: skip
        st.plotly_chart(fig, width="stretch", theme=None, key="mapa_caso")
    else:
        st.info("Este día no tiene GOES ni índices ERA5 para dibujar el mapa.")


def _bitacora(ctx: estado.Contexto) -> None:
    """Tabla de eventos del día, seleccionable."""
    st.subheader("Eventos reportados del día")
    if ctx.eventos.empty:
        st.markdown(
            "<p class='nota'>El catálogo no contiene reportes de tornados o trombas marinas "
            "para este día. Esto no permite confirmar su ausencia. Puedes explorar las "
            "condiciones atmosféricas, pero el día no debe considerarse automáticamente "
            "un caso negativo.</p>",
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
    """Compara índices con criterios y referencias para la hora ERA5 más cercana."""
    st.subheader("Índices del entorno y referencias")
    if ctx.dia.idx is None or t is None:
        st.markdown(
            "<p class='nota'>No hay índices preparados para este día. Elige otra fecha "
            "disponible o consulta cómo preparar los datos.</p>",
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
    st.html(componentes.ficha(filas, p.nombre if p else "punto", "extremo del área"))
    st.caption(
        f"ERA5 {hora:%H:%M} UTC. La columna del punto corresponde a la celda ERA5 más cercana "
        "al lugar elegido. «Extremo del área» es el máximo o mínimo de cada índice dentro "
        "del rectángulo que abarca los eventos y sus márgenes; no es un radio alrededor "
        "de cada evento. Las marcas comparan esa columna con el criterio indicado. "
        "Las referencias del caso de 2019 no son umbrales de decisión. Cumplir un criterio "
        "describe el entorno y no confirma un tornado. " + textos.NOTA_AUSTRAL
    )
    st.caption(textos.NOTA_STP)


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    c = textos.caso(ctx.dia.fecha, len(ctx.eventos))
    t = estado.t_actual()
    st.title(c.titulo)
    st.html(f"<p class='lede'>{c.lede}</p>")
    st.markdown(
        "Esta página explora un caso histórico: compara eventos reportados con el entorno "
        "estimado por ERA5 y las nubes observadas por GOES. La capacidad de predicción "
        "del proyecto está pendiente de evaluación."
    )
    st.caption(
        "ERA5 tiene una resolución espacial de unos 31 km y datos horarios, "
        "por lo que no representa directamente un mesociclón; una imagen satelital "
        "tampoco confirma por sí sola un tornado. El catálogo reúne tornados y trombas "
        "marinas reportados y no proporciona una etiqueta directa de mesociclón. "
        "En la tabla, EF es una clasificación de intensidad basada en los daños observados."
    )
    pasos = estado.recorrido(ctx.dia.fecha)
    if pasos and estado.paso_actual() is None:
        st.button(
            "Empezar recorrido guiado", icon=":material/play_arrow:", key="recorrido_caso",
            on_click=estado.aplica_paso, args=(ctx.dia.fecha, 0, ctx.eventos),
        )  # fmt: skip

    izq, der = tema.columnas(2, "caso_mapa")
    with izq:
        _mapa(ctx, None if t is None else pd.Timestamp(t))
    with der:
        _bitacora(ctx)
        _ficha(ctx, None if t is None else pd.Timestamp(t))

    st.divider()
    izq, der = tema.columnas([3, 2], "caso_contexto")
    with izq:
        if c.contexto:
            st.subheader("Contexto")
            for parrafo in c.contexto:
                st.markdown(parrafo)
        detalles = textos.DETALLES_CASOS.get(ctx.dia.fecha)
        if detalles:
            with st.expander("Detalles meteorológicos y referencias pendientes de aclaración"):
                for parrafo in detalles:
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
