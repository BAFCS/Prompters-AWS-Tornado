"""Página «Mapas»: una grilla de 1 a 6 paneles (ERA5, bandas GOES o RGB) con el zoom sincronizado."""

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from viewer_app import charts, colorscales, components, data, layers, products, state, texts, theme

ANIMATION_STEP = 3  # se dibuja uno de cada 3 píxeles GOES al animar
MAX_ANIMATED = 3  # paneles GOES que se animan a la vez


def _on_click() -> None:
    """Callback de la grilla: el nodo ERA5 más cercano al clic pasa a ser el punto elegido.

    Es el nodo que leen Sondeo y Series; sin ERA5 esas páginas no tienen qué mostrar y el clic se ignora.
    """
    points = st.session_state["grid"].selection.points
    ref = data.era5_ref(state.context().day)
    if points and ref is not None:
        node = ref.sel(latitude=points[0]["y"], longitude=points[0]["x"], method="nearest")
        la, lo = float(node["latitude"]), float(node["longitude"])
        state.select_point(state.Point(la, lo, components.coord(la, lo)))


def _on_change(id_: int, field: str, widget_key: str) -> None:
    """Callback de los widgets de un panel: copia su valor al panel (``"—"`` significa ninguno)."""
    v = st.session_state[widget_key]
    state.change_panel(id_, **{field: None if v == "—" else v})


def _on_add(widget_key: str) -> None:
    """Callback de «Agregar panel»: agrega el producto elegido y deja el widget en blanco."""
    key = st.session_state[widget_key]
    if key:
        state.add_panel(key)
    st.session_state[widget_key] = None


def _add_popover(cat: dict[str, products.Product], n: int) -> None:
    """Popover para agregar un panel: botonera de favoritos y la lista completa."""
    full = n >= state.MAX_PANELS
    with st.popover("Agregar panel", icon=":material/add:", disabled=full, width="content",
                    help=f"Hasta {state.MAX_PANELS} paneles." if full else None):  # fmt: skip
        st.caption("Elige qué quieres comparar. La lista completa sigue disponible abajo.")
        for label, keys in products.FAVORITE_GROUPS:
            options = [k for k in keys if k in cat]
            if options:
                key = f"add_{keys[0]}"
                st.pills(label, options, key=key, format_func=lambda k: cat[k].short,
                         on_change=_on_add, args=(key,))  # fmt: skip
        st.selectbox(
            "Otra variable o imagen", products.sorted_keys(cat), index=None, key="add_other",
            placeholder="Escribe para buscar…", format_func=lambda k: cat[k].label,
            on_change=_on_add, args=("add_other",),
        )  # fmt: skip


def _controls(p: state.Panel, n: int, cat: dict[str, products.Product], d: data.Day) -> None:
    """Fila de controles del panel ``n``: producto, ◀ ▶, opciones y quitar."""
    prod = cat[p.key]
    k_key = f"p{p.id}_key"
    st.session_state[k_key] = p.key  # el panel es la fuente de verdad; el widget lo refleja
    # Contenedor horizontal: en pantallas angostas los botones bajan juntos en una sola fila.
    row = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
    row.selectbox(
        f"Panel {n}", products.sorted_keys(cat), key=k_key,
        format_func=lambda k: cat[k].label,
        on_change=_on_change, args=(p.id, "key", k_key), width="stretch",
    )  # fmt: skip
    buttons = row.container(horizontal=True, gap="small", width="content")
    for step, icon, tip in ((-1, ":material/chevron_left:", "Anterior"),
                               (+1, ":material/chevron_right:", "Siguiente")):  # fmt: skip
        buttons.button(
            f"{tip} · {n}", icon=icon, key=f"p{p.id}_{step}", help=f"{tip} en «{prod.group}»",
            on_click=state.change_panel, args=(p.id,),
            kwargs={"key": products.neighbor(p.key, cat, step)},
        )  # fmt: skip
    indices = [k for k in cat if k.startswith("idx:")]
    if prod.kind is not None or prod.source == "pl" or (prod.is_goes and indices):
        with buttons.popover(
            f"Opciones · {n}", icon=":material/tune:", help="Escala de color, nivel o contornos"
        ):
            if prod.kind is not None:
                ops = colorscales.KINDS[prod.kind]
                k_scale = f"p{p.id}_colorscale"
                st.session_state[k_scale] = colorscales.pick(prod.kind, p.colorscale).name
                st.selectbox(
                    "Escala de color", [e.name for e in ops], key=k_scale,
                    format_func=lambda name: colorscales.pick(str(prod.kind), name).display_label,
                    on_change=_on_change, args=(p.id, "colorscale", k_scale),
                    help="Escalas estándar para este tipo de dato. La primera es la predeterminada.",
                )  # fmt: skip
            if prod.source == "pl":
                nv = layers.levels(d)
                k_level = f"p{p.id}_level"
                st.session_state[k_level] = (
                    p.level if p.level in nv else (850.0 if 850.0 in nv else nv[0])
                )
                st.select_slider("Nivel (hPa)", options=nv, key=k_level, on_change=_on_change,
                                 args=(p.id, "level", k_level),
                                 help="Nivel de presión, expresado en hectopascales (hPa).")  # fmt: skip
            elif prod.is_goes and indices:
                k_cont = f"p{p.id}_cont"
                st.session_state[k_cont] = p.contour or "—"
                st.selectbox(
                    "Contornos ERA5", ["—", *indices], key=k_cont,
                    format_func=lambda k: "Sin contornos" if k == "—" else cat[k].short,
                    on_change=_on_change, args=(p.id, "contour", k_cont),
                    help="Líneas que unen lugares con el mismo valor del índice. El valor de comparación se muestra en rojo.",
                )  # fmt: skip
    buttons.button(f"Quitar · {n}", icon=":material/close:", key=f"p{p.id}_x", help=f"Quitar el panel {n}",
              on_click=state.remove_panel, args=(p.id,))  # fmt: skip


def _panel_layer(
    p: state.Panel, n: int, cat: dict[str, products.Product], d: data.Day, t: pd.Timestamp,
    enc: charts.Extent, sub: int,
) -> layers.Layer:  # fmt: skip
    """La capa del panel ``n`` con su número en el título (vacía si falta la imagen anterior)."""
    prod = cat[p.key]
    c = layers.layer(d, prod, t, sub=sub, level=p.level)
    if c is None:
        return layers.empty_layer(f"{n} · {prod.short} · sin imagen anterior", enc)
    return dataclasses.replace(c.with_colorscale(p.colorscale), title=f"{n} · {c.title}")


def _animate(
    fig: go.Figure, backgrounds: list[int], animated: list[int], visible: list[state.Panel],
    cat: dict[str, products.Product], d: data.Day, t: pd.Timestamp,
) -> int:  # fmt: skip
    """Agrega a ``fig`` un cuadro por imagen GOES en ±1 h para los paneles ``animated``.

    Devuelve cuántos cuadros quedaron (0 o 1 = no se anima).
    """
    nearby = [ti for ti, _ in data.images(d) if abs(pd.Timestamp(ti) - t) <= pd.Timedelta("1h")]
    titles = fig.to_dict()["layout"].get("annotations", [])
    frames, labels = [], []
    for ti in nearby:
        cs = {i: layers.layer(d, cat[visible[i].key], pd.Timestamp(ti), sub=ANIMATION_STEP)
              for i in animated}  # fmt: skip
        if any(c is None for c in cs.values()):
            continue
        annots = [dict(a) for a in titles]
        frame_data, traces = [], []
        for i, c in cs.items():
            assert c is not None
            annots[i]["text"] = f"{i + 1} · {c.title}"
            bg = charts.background(c.with_colorscale(visible[i].colorscale))
            frame_data += bg
            traces += range(backgrounds[i], backgrounds[i] + len(bg))
        frames.append(go.Frame(data=frame_data, traces=traces, name=str(len(frames)),
                                layout={"annotations": annots}))  # fmt: skip
        labels.append(pd.Timestamp(ti).strftime("%H:%M"))
    if len(frames) < 2:
        return len(frames)
    fig.frames = frames
    play = {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True,
             "transition": {"duration": 0}}  # fmt: skip
    fig.update_layout(
        updatemenus=[{
            "type": "buttons", "direction": "left", "x": 0, "y": -0.04, "xanchor": "left",
            "yanchor": "top", "showactive": False, "bgcolor": theme.colors().SURFACE_2,
            "bordercolor": theme.colors().LINE, "font": {"family": theme.SANS, "size": 12},
            "buttons": [
                {"label": "Reproducir", "method": "animate", "args": [None, play]},
                {"label": "Pausa", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0}, "mode": "immediate"}]},
            ],
        }],
        sliders=[{
            "x": 0.32, "len": 0.68, "y": -0.02, "currentvalue": {"visible": False},
            "bordercolor": theme.colors().LINE, "tickcolor": theme.colors().LINE, "font": {"family": theme.MONO, "size": 10},
            "steps": [{"label": e, "method": "animate",
                       "args": [[str(i)], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}]}
                      for i, e in enumerate(labels)],
        }],
        margin={"b": 70},
    )  # fmt: skip
    return len(frames)


def page() -> None:
    """Dibuja la página."""
    ctx = state.context()
    t = state.current_time()
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
    cat = products.catalog(ctx.day)
    if not cat:
        st.info(
            "No hay datos ERA5 ni GOES preparados para esta selección. Elige otra región o fecha disponible."
        )
        return
    if state.panels() is None:  # primera visita: un panel RGB, o el primer índice si no hay GOES
        initial = "rgb:airmass" if "rgb:airmass" in cat else products.sorted_keys(cat)[0]
        state.set_panels([state.new_panel(initial)])
    ps = state.panels() or []

    for key, default in (("extent", "Zona de eventos"), ("wind", False), ("sub", 2),
                           ("animate", False)):  # fmt: skip
        state.restore(key)
        st.session_state.setdefault(key, default)
    # Fila horizontal: cada control toma el ancho de su rótulo y la fila se parte en pantallas angostas.
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        _add_popover(cat, len(ps))
        with st.popover("Elegir punto", icon=":material/location_on:"):
            p = state.point()
            st.caption(
                "Elige cualquier lugar de la región para Sondeo y Series, también con teclado."
            )
            with st.form("coordinates"):
                lat = st.number_input(
                    "Latitud (°)",
                    min_value=float(ctx.reg.south),
                    max_value=float(ctx.reg.north),
                    value=float(
                        min(
                            ctx.reg.north,
                            max(ctx.reg.south, p.lat if p else (ctx.reg.north + ctx.reg.south) / 2),
                        )
                    ),
                    format="%.2f",
                )
                lon = st.number_input(
                    "Longitud (°)",
                    min_value=float(ctx.reg.west),
                    max_value=float(ctx.reg.east),
                    value=float(
                        min(
                            ctx.reg.east,
                            max(ctx.reg.west, p.lon if p else (ctx.reg.west + ctx.reg.east) / 2),
                        )
                    ),
                    format="%.2f",
                )
                if st.form_submit_button("Usar este punto", type="primary"):
                    try:
                        state.select_point(state.Point(lat, lon, "Punto por coordenadas"), ctx.reg)
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        st.rerun()
    settings = st.expander("Ajustes de mapas")
    with settings, st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        view = st.segmented_control(
            "Encuadre", ["Zona de eventos", "Región completa"], key="extent", width="content"
        )
        st.toggle("Viento 850 hPa", key="wind", disabled=ctx.day.pl is None, width="content",
                  help="Flechas del viento en 850 hPa sobre todos los paneles (requiere niveles de presión).")  # fmt: skip
        st.toggle("Animar GOES ±1 h", key="animate", disabled=not ctx.day.goes, width="content",
                  help=f"Animación de los paneles GOES (hasta {MAX_ANIMATED}) de una hora antes a una hora después.")  # fmt: skip
        st.select_slider("Densidad de píxeles GOES", options=[1, 2, 3, 4], key="sub", width=220,
                         format_func=lambda s: {1: "máxima", 2: "alta", 3: "media", 4: "baja"}[s],
                         help="Una menor densidad muestra menos píxeles y reduce el tiempo de dibujo. No cambia los archivos originales.")  # fmt: skip
    for key in ("extent", "wind", "sub", "animate"):
        state.save(key)
    if view == "Región completa" or ctx.events.empty:
        enc = charts.Extent(ctx.reg.north, ctx.reg.south, ctx.reg.west, ctx.reg.east)
    else:
        enc = charts.events_extent(ctx.events, ctx.reg)

    visible = [p for p in ps if p.key in cat]
    missing = [p for p in ps if p.key not in cat]
    if missing:
        names = []
        for panel in missing:
            variable = panel.key.partition(":")[2]
            name = products.DERIVED.get(panel.key, (None, set()))[0]
            names.append(name or components.SHORT_NAMES.get(variable, variable))
        st.info(
            "Sin datos este día: "
            + ", ".join(names)
            + ". Selecciona otra fecha o sustituye esos paneles."
        )

    if not visible:
        st.info(
            "No hay paneles. Agrega uno con «Agregar panel»: el RGB Airmass es un buen comienzo."
        )
        return
    rows, cols = charts.grid_shape(len(visible), theme.map_columns())
    for f in range(rows):
        columns = st.columns(cols, gap="medium")
        for j, p in enumerate(visible[f * cols : (f + 1) * cols]):
            with columns[j]:
                _controls(p, f * cols + j + 1, cat, ctx.day)

    animate = bool(st.session_state.get("animate"))
    goes_idx = [i for i, p in enumerate(visible) if cat[p.key].is_goes]
    animated = goes_idx[:MAX_ANIMATED] if animate else []
    sub = int(st.session_state.get("sub", 2))
    layer_list = [
        _panel_layer(p, i + 1, cat, ctx.day, t, enc, ANIMATION_STEP if i in animated else sub)
        for i, p in enumerate(visible)
    ]
    contours = [
        layers.layer(ctx.day, cat[p.contour], t)
        if p.contour in cat and cat[p.key].is_goes
        else None
        for p in visible
    ]
    ref = data.era5_ref(ctx.day)
    fig, backgrounds = charts.grid(
        layer_list, contours, enc, data.coast(ctx.reg), events=ctx.events, point=state.point(),
        wind=layers.wind_850(ctx.day, t, enc) if st.session_state.get("wind") else None,
        columns=cols,
    )  # fmt: skip
    n_frames = _animate(fig, backgrounds, animated, visible, cat, ctx.day, t) if animated else 0
    st.caption(
        "Compara el entorno y las nubes cerca del evento. Todos los mapas comparten el encuadre."
    )
    if ref is not None:
        st.caption("«Elegir punto» acepta coordenadas con teclado. También puedes tocar el mapa.")
    st.plotly_chart(
        fig, width="stretch", theme=None, key="grid", on_select=_on_click,
        selection_mode="points", config={"scrollZoom": True},
    )  # fmt: skip

    if any(c.threshold is not None for c in [*layer_list, *[c for c in contours if c]]):
        st.caption(
            "La línea roja marca el valor de comparación del índice; no confirma un tornado."
        )
    if goes_idx:
        st.caption(
            "GOES muestra la hora de inicio del barrido. Las imágenes no tienen corrección de "
            "paralaje: el ángulo de observación puede desplazar la posición aparente de las nubes. "
            "Temperatura de brillo en K: °C = K − 273,15."
        )
    for note in sorted({c.note for c in layer_list if c.note}):
        st.caption(note)
    if animate and animated:
        st.caption(
            f"Animación: {n_frames} imágenes disponibles; se muestra un píxel de cada {ANIMATION_STEP}. "
            "Consulta las horas de los cuadros para conocer el intervalo."
            if n_frames >= 2
            else "No hay suficientes imágenes alrededor de esta hora para animar."
        )
        if len(goes_idx) > MAX_ANIMATED:
            st.caption(f"Se animan los primeros {MAX_ANIMATED} paneles GOES.")

    seen = dict.fromkeys(
        [cat[p.key].variable for p in visible] + [cat[p.contour].variable for p in visible
                                                     if p.contour in cat]
    )  # fmt: skip
    tips = [texts.HELP[v] for v in seen if v in texts.HELP]
    if tips:
        with st.expander("Qué estás viendo", expanded=state.current_step() is not None):
            for a in tips:
                st.markdown(a)
            st.caption(texts.SOUTHERN_NOTE)
