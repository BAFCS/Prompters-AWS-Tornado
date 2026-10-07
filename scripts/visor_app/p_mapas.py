"""Página «Mapas»: una grilla de 1 a 6 paneles (ERA5, bandas GOES o RGB) con el zoom sincronizado."""

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from visor_app import (
    capas,
    componentes,
    datos,
    escalas,
    estado,
    graficos,
    productos,
    tema,
    textos,
    variables,
)

PASO_ANIMACION = 3  # se dibuja uno de cada 3 píxeles GOES al animar
MAX_ANIMADOS = 3  # paneles GOES que se animan a la vez


def _al_clic() -> None:
    """Callback de la grilla: el punto clicado en cualquier panel pasa a ser el punto elegido."""
    puntos = st.session_state["grilla"].selection.points
    if puntos:
        la, lo = float(puntos[0]["y"]), float(puntos[0]["x"])
        estado.elige_punto(estado.Punto(la, lo, componentes.coord(la, lo)))


def _al_cambiar(id_: int, campo: str, clave_widget: str) -> None:
    """Callback de los widgets de un panel: copia su valor al panel (``"—"`` significa ninguno)."""
    v = st.session_state[clave_widget]
    estado.cambia_panel(id_, **{campo: None if v == "—" else v})


def _al_agregar(clave_widget: str) -> None:
    """Callback de «Agregar panel»: agrega el producto elegido y deja el widget en blanco."""
    clave = st.session_state[clave_widget]
    if clave:
        estado.agrega_panel(clave)
    st.session_state[clave_widget] = None


def _agregar(cat: dict[str, productos.Producto], n: int) -> None:
    """Popover para agregar un panel: botonera de favoritos y la lista completa."""
    lleno = n >= estado.MAX_PANELES
    with st.popover("Agregar panel", icon=":material/add:", disabled=lleno, width="content",
                    help=f"Hasta {estado.MAX_PANELES} paneles." if lleno else None):  # fmt: skip
        st.pills(
            "Selección sugerida", [k for k in productos.FAVORITOS if k in cat], key="agrega_fav",
            format_func=lambda k: cat[k].corta, on_change=_al_agregar, args=("agrega_fav",),
        )  # fmt: skip
        st.selectbox(
            "Otra variable o imagen", productos.ordenados(cat), index=None, key="agrega_otro",
            placeholder="Escribe para buscar…", format_func=lambda k: cat[k].etiqueta,
            on_change=_al_agregar, args=("agrega_otro",),
        )  # fmt: skip


def _controles(p: estado.Panel, n: int, cat: dict[str, productos.Producto], d: datos.Dia) -> None:
    """Fila de controles del panel ``n``: producto, ◀ ▶, opciones y quitar."""
    prod = cat[p.clave]
    k_clave = f"p{p.id}_clave"
    st.session_state[k_clave] = p.clave  # el panel es la fuente de verdad; el widget lo refleja
    # Contenedor horizontal: en pantallas angostas los botones bajan juntos en una sola fila.
    fila = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
    fila.selectbox(
        f"Panel {n}", productos.ordenados(cat), key=k_clave,
        format_func=lambda k: cat[k].etiqueta,
        on_change=_al_cambiar, args=(p.id, "clave", k_clave), width="stretch",
    )  # fmt: skip
    botones = fila.container(horizontal=True, gap="small", width="content")
    for paso, icono, ayuda in ((-1, ":material/chevron_left:", "Anterior"),
                               (+1, ":material/chevron_right:", "Siguiente")):  # fmt: skip
        botones.button(
            "", icon=icono, key=f"p{p.id}_{paso}", help=f"{ayuda} en «{prod.grupo}»",
            on_click=estado.cambia_panel, args=(p.id,),
            kwargs={"clave": productos.vecino(p.clave, cat, paso)},
        )  # fmt: skip
    indices = [k for k in cat if k.startswith("idx:")]
    if prod.tipo is not None or prod.fuente == "pl" or (prod.es_goes and indices):
        with botones.popover("", icon=":material/tune:", help="Escala de color, nivel o contornos"):
            if prod.tipo is not None:
                ops = escalas.TIPOS[prod.tipo]
                k_esc = f"p{p.id}_escala"
                st.session_state[k_esc] = escalas.elige(prod.tipo, p.escala).nombre
                st.selectbox(
                    "Escala de color", [e.nombre for e in ops], key=k_esc,
                    format_func=lambda nombre: escalas.elige(str(prod.tipo), nombre).rotulo,
                    on_change=_al_cambiar, args=(p.id, "escala", k_esc),
                    help="Escalas estándar para este tipo de dato. La primera es la predeterminada.",
                )  # fmt: skip
            if prod.fuente == "pl":
                nv = capas.niveles(d)
                k_nivel = f"p{p.id}_nivel"
                st.session_state[k_nivel] = (
                    p.nivel if p.nivel in nv else (850.0 if 850.0 in nv else nv[0])
                )
                st.select_slider("Nivel (hPa)", options=nv, key=k_nivel, on_change=_al_cambiar,
                                 args=(p.id, "nivel", k_nivel),
                                 help="Nivel de presión, expresado en hectopascales (hPa).")  # fmt: skip
            elif prod.es_goes and indices:
                k_cont = f"p{p.id}_cont"
                st.session_state[k_cont] = p.contorno or "—"
                st.selectbox(
                    "Contornos ERA5", ["—", *indices], key=k_cont,
                    format_func=lambda k: "Sin contornos" if k == "—" else cat[k].corta,
                    on_change=_al_cambiar, args=(p.id, "contorno", k_cont),
                    help="Líneas que unen lugares con el mismo valor del índice. El valor de comparación se muestra en rojo.",
                )  # fmt: skip
    botones.button("", icon=":material/close:", key=f"p{p.id}_x", help="Quitar el panel",
              on_click=estado.quita_panel, args=(p.id,))  # fmt: skip


def _capa_panel(
    p: estado.Panel, n: int, cat: dict[str, productos.Producto], d: datos.Dia, t: pd.Timestamp,
    enc: graficos.Encuadre, sub: int,
) -> capas.Capa:  # fmt: skip
    """La capa del panel ``n`` con su número en el título (vacía si falta la imagen anterior)."""
    prod = cat[p.clave]
    c = capas.capa(d, prod, t, sub=sub, nivel=p.nivel)
    if c is None:
        return capas.vacia(f"{n} · {prod.corta} · sin imagen anterior", enc)
    return dataclasses.replace(c.con_escala(p.escala), titulo=f"{n} · {c.titulo}")


def _animar(
    fig: go.Figure, fondos: list[int], animados: list[int], visibles: list[estado.Panel],
    cat: dict[str, productos.Producto], d: datos.Dia, t: pd.Timestamp,
) -> int:  # fmt: skip
    """Agrega a ``fig`` un cuadro por imagen GOES en ±1 h para los paneles ``animados``.

    Devuelve cuántos cuadros quedaron (0 o 1 = no se anima).
    """
    cerca = [ti for ti, _ in datos.imagenes(d) if abs(pd.Timestamp(ti) - t) <= pd.Timedelta("1h")]
    titulos = fig.to_dict()["layout"].get("annotations", [])
    cuadros, etiquetas = [], []
    for ti in cerca:
        cs = {i: capas.capa(d, cat[visibles[i].clave], pd.Timestamp(ti), sub=PASO_ANIMACION)
              for i in animados}  # fmt: skip
        if any(c is None for c in cs.values()):
            continue
        anots = [dict(a) for a in titulos]
        datos_cuadro = []
        for i, c in cs.items():
            assert c is not None
            anots[i]["text"] = f"{i + 1} · {c.titulo}"
            z = graficos.z_fondo(c)
            datos_cuadro.append(go.Image(z=z) if c.es_rgb else go.Heatmap(z=z))
        cuadros.append(go.Frame(data=datos_cuadro, traces=[fondos[i] for i in cs],
                                name=str(len(cuadros)), layout={"annotations": anots}))  # fmt: skip
        etiquetas.append(pd.Timestamp(ti).strftime("%H:%M"))
    if len(cuadros) < 2:
        return len(cuadros)
    fig.frames = cuadros
    boton = {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True,
             "transition": {"duration": 0}}  # fmt: skip
    fig.update_layout(
        updatemenus=[{
            "type": "buttons", "direction": "left", "x": 0, "y": -0.04, "xanchor": "left",
            "yanchor": "top", "showactive": False, "bgcolor": tema.colores().SURFACE_2,
            "bordercolor": tema.colores().LINE, "font": {"family": tema.SANS, "size": 12},
            "buttons": [
                {"label": "Reproducir", "method": "animate", "args": [None, boton]},
                {"label": "Pausa", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0}, "mode": "immediate"}]},
            ],
        }],
        sliders=[{
            "x": 0.32, "len": 0.68, "y": -0.02, "currentvalue": {"visible": False},
            "bordercolor": tema.colores().LINE, "tickcolor": tema.colores().LINE, "font": {"family": tema.MONO, "size": 10},
            "steps": [{"label": e, "method": "animate",
                       "args": [[str(i)], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}]}
                      for i, e in enumerate(etiquetas)],
        }],
        margin={"b": 70},
    )  # fmt: skip
    return len(cuadros)


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    t = estado.t_actual()
    st.title("Mapas")
    st.markdown(
        "Compara mapas del entorno ERA5 con imágenes GOES para la hora seleccionada. "
        "Cada panel muestra una variable o imagen; el acercamiento se comparte entre todos los paneles."
    )
    if t is None:
        st.info(
            "No hay datos con hora para este día. Selecciona otra fecha disponible en la barra lateral."
        )
        return
    t = pd.Timestamp(t)
    cat = productos.catalogo(ctx.dia)
    if not cat:
        st.info(
            "No hay datos ERA5 ni GOES preparados para esta selección. Elige otra región o fecha disponible."
        )
        return
    if estado.paneles() is None:  # primera visita: un panel RGB, o el primer índice si no hay GOES
        inicial = "rgb:airmass" if "rgb:airmass" in cat else productos.ordenados(cat)[0]
        estado.fija_paneles([estado.nuevo_panel(inicial)])
    ps = estado.paneles() or []

    for clave, defecto in (("encuadre", "Zona de eventos"), ("viento", False), ("sub", 2),
                           ("animar", False)):  # fmt: skip
        estado.recuerda(clave)
        st.session_state.setdefault(clave, defecto)
    # Fila horizontal: cada control toma el ancho de su rótulo y la fila se parte en pantallas angostas.
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        vista = st.segmented_control(
            "Encuadre", ["Zona de eventos", "Región completa"], key="encuadre", width="content"
        )
        _agregar(cat, len(ps))
        st.toggle("Viento 850 hPa", key="viento", disabled=ctx.dia.pl is None, width="content",
                  help="Flechas del viento en 850 hPa sobre todos los paneles (requiere niveles de presión).")  # fmt: skip
        st.toggle("Animar GOES ±1 h", key="animar", disabled=not ctx.dia.goes, width="content",
                  help=f"Animación de los paneles GOES (hasta {MAX_ANIMADOS}) de una hora antes a una hora después.")  # fmt: skip
        st.select_slider("Densidad de píxeles GOES", options=[1, 2, 3, 4], key="sub", width=220,
                         format_func=lambda s: {1: "máxima", 2: "alta", 3: "media", 4: "baja"}[s],
                         help="Una menor densidad muestra menos píxeles y reduce el tiempo de dibujo. No cambia los archivos originales.")  # fmt: skip
    for clave in ("encuadre", "viento", "sub", "animar"):
        estado.guarda(clave)
    if vista == "Región completa" or ctx.eventos.empty:
        enc = graficos.Encuadre(ctx.reg.norte, ctx.reg.sur, ctx.reg.oeste, ctx.reg.este)
    else:
        enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg)

    visibles = [p for p in ps if p.clave in cat]
    faltan = [p for p in ps if p.clave not in cat]
    if faltan:
        nombres = []
        for panel in faltan:
            variable = panel.clave.partition(":")[2]
            nombre = productos.DERIVADOS.get(panel.clave, (None, set()))[0]
            nombres.append(nombre or componentes.CORTOS.get(variable, variable))
        st.info(
            "Sin datos este día: "
            + ", ".join(nombres)
            + ". Selecciona otra fecha o sustituye esos paneles."
        )

    if not visibles:
        st.info(
            "No hay paneles. Agrega uno con «Agregar panel»: el RGB Airmass es un buen comienzo."
        )
        return
    filas, cols = graficos.disposicion(len(visibles))
    for f in range(filas):
        columnas = st.columns(cols, gap="medium")
        for j, p in enumerate(visibles[f * cols : (f + 1) * cols]):
            with columnas[j]:
                _controles(p, f * cols + j + 1, cat, ctx.dia)

    animar = bool(st.session_state.get("animar"))
    goes_idx = [i for i, p in enumerate(visibles) if cat[p.clave].es_goes]
    animados = goes_idx[:MAX_ANIMADOS] if animar else []
    sub = int(st.session_state.get("sub", 2))
    lista = [
        _capa_panel(p, i + 1, cat, ctx.dia, t, enc, PASO_ANIMACION if i in animados else sub)
        for i, p in enumerate(visibles)
    ]
    contornos = [
        capas.capa(ctx.dia, cat[p.contorno], t)
        if p.contorno in cat and cat[p.clave].es_goes
        else None
        for p in visibles
    ]
    ref = datos.era5_ref(ctx.dia)
    fig, fondos = graficos.grilla(
        lista, contornos, enc, datos.costa(ctx.reg), eventos=ctx.eventos, punto=estado.punto(),
        clic=None if ref is None else (ref["latitude"].values, ref["longitude"].values),
        viento=capas.viento_850(ctx.dia, t, enc) if st.session_state.get("viento") else None,
    )  # fmt: skip
    n_cuadros = _animar(fig, fondos, animados, visibles, cat, ctx.dia, t) if animados else 0
    st.caption(
        "Usa la rueda del ratón o los botones del gráfico para acercar la vista. "
        "Todos los paneles se mueven juntos."
    )
    if ref is not None:
        st.caption(
            "Haz clic en cualquier panel para seleccionar el punto que se usará en Sondeo y Series."
        )
    st.plotly_chart(
        fig, width="stretch", theme=None, key="grilla", on_select=_al_clic,
        selection_mode="points", config={"scrollZoom": True},
    )  # fmt: skip

    if any(c.umbral is not None for c in [*lista, *[c for c in contornos if c]]):
        st.caption(
            "La línea roja marca el valor de comparación del índice; no confirma un tornado."
        )
    if goes_idx:
        st.caption(
            "GOES muestra la hora de inicio del barrido. Las imágenes no tienen corrección de "
            "paralaje: el ángulo de observación puede desplazar la posición aparente de las nubes."
        )
    for nota in sorted({c.nota for c in lista if c.nota}):
        st.caption(nota)
    if animar and animados:
        st.caption(
            f"Animación: {n_cuadros} imágenes disponibles; se muestra un píxel de cada {PASO_ANIMACION}. "
            "Consulta las horas de los cuadros para conocer el intervalo."
            if n_cuadros >= 2
            else "No hay suficientes imágenes alrededor de esta hora para animar."
        )
        if len(goes_idx) > MAX_ANIMADOS:
            st.caption(f"Se animan los primeros {MAX_ANIMADOS} paneles GOES.")

    vistos = [p.clave for p in visibles] + [p.contorno for p in visibles if p.contorno in cat]
    fichas = list(
        dict.fromkeys(variables.POR_PRODUCTO[k] for k in vistos if k in variables.POR_PRODUCTO)
    )
    if fichas:
        with st.expander("Qué estás viendo", expanded=estado.paso_actual() is not None):
            for v in fichas:
                st.markdown(variables.resumen(v))
                st.button(
                    f"Ficha completa de {v.simbolo}", key=f"ficha_{v.clave}", type="tertiary",
                    icon=":material/arrow_forward:", on_click=estado.ir_a_ficha, args=(v.clave,),
                )  # fmt: skip
            st.caption(textos.NOTA_AUSTRAL)
