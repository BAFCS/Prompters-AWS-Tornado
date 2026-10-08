"""Visor exploratorio de ERA5 y GOES para los casos de tornados en Chile (Streamlit + plotly).

Página de entrada de una app de varias páginas (``st.navigation``): dibuja la barra lateral común
(región, día, regla de tiempo, eventos y recorrido guiado), publica el contexto en
``st.session_state`` y corre la página elegida. Las páginas viven en ``scripts/viewer_app/``.

Lee lo que dejan los scripts de descarga y procesamiento::

    data/crops/<region>/era5_pl/era5_pl_AAAAMMDD.nc
    data/crops/<region>/era5_sfc/era5_sfc_AAAAMMDD.nc
    data/crops/<region>/era5_indices/era5_idx_AAAAMMDD.nc     (process_era5.py)
    data/crops/<region>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc

Uso::

    uv run streamlit run scripts/viewer.py
"""

import datetime as dt
import html
from typing import NoReturn

import numpy as np
import pandas as pd
import streamlit as st

import common
from viewer_app import (
    components,
    data,
    p_case,
    p_data,
    p_maps,
    p_project,
    p_series,
    p_sounding,
    state,
    texts,
    theme,
)

st.set_page_config(
    page_title="Mesociclones en Chile · visor", page_icon=":material/storm:", layout="wide"
)
theme.apply()

PAGES = {
    "project": st.Page(p_project.page, title="El proyecto", icon=":material/info:", default=True),
    "data": st.Page(p_data.page, title="Datos", icon=":material/dataset:", url_path="datos"),
    "case": st.Page(p_case.page, title="El caso", icon=":material/history_edu:", url_path="caso"),
    "maps": st.Page(p_maps.page, title="Mapas", icon=":material/map:", url_path="mapas"),
    "sounding": st.Page(p_sounding.page, title="Sondeo", icon=":material/stacked_line_chart:",
                      url_path="sondeo"),
    "series": st.Page(p_series.page, title="Series", icon=":material/timeline:",
                      url_path="series"),
}  # fmt: skip
st.session_state["pages"] = PAGES
navigation = st.navigation(list(PAGES.values()), position="top")

# --- Región y día --------------------------------------------------------------------------------
sidebar = st.sidebar
sidebar.markdown("## Mesociclones en Chile")
sidebar.caption(
    "Selecciona la región, el día y la hora que quieres explorar. La selección se comparte "
    "entre El caso, Mapas, Sondeo y Series. Las fechas y horas se expresan en tiempo universal "
    "coordinado (UTC), que puede diferir de la hora local de Chile."
)
theme.mode_button()


def no_data(message: str, prepare: bool = False) -> NoReturn:
    """Detiene la app sin datos: El proyecto y Datos se muestran igual; las demás avisan con ``message``."""
    if navigation.url_path in {PAGES["project"].url_path, PAGES["data"].url_path}:
        # Datos no debe ofrecer productos de un día ya no disponible.
        st.session_state.pop("ctx", None)
        navigation.run()  # no usan datos
        st.stop()
    st.error(message)
    if prepare:
        st.page_link(PAGES["project"], label="Leer El proyecto")
        with st.expander("Preparar datos en la instalación local"):
            st.markdown(
                "Desde la raíz del repositorio, descarga y procesa un día. Los archivos se guardan "
                "en `data/crops/`. Después, recarga esta página."
            )
            st.code(
                "uv run python scripts/download_era5.py --start 2019-05-30\n"
                "uv run python scripts/download_goes.py --start 2019-05-30\n"
                "uv run python scripts/process_goes.py --start 2019-05-30\n"
                "uv run python scripts/process_era5.py --start 2019-05-30",
                language="bash",
            )
    st.stop()


names = data.regions()
if not names:
    no_data(
        "No hay datos preparados para explorar. Puedes leer la descripción en El proyecto.",
        prepare=True,
    )
state.restore("region")
name = sidebar.selectbox(
    "Región", names, key="region",
    index=names.index("south-central-austral") if "south-central-austral" in names else 0,
    format_func=lambda n: (common.REGIONS[n].label if n in common.REGIONS else "") or str(n),
)  # fmt: skip
state.save("region")
days = data.days(name)
if not days:
    no_data(f"La región {name} no tiene días preparados. Elige otra región disponible.")
dates = list(days)
state.restore("day")
if st.session_state.get("day") not in dates:
    st.session_state["day"] = dt.date(2019, 5, 30) if dt.date(2019, 5, 30) in dates else dates[-1]
date = sidebar.selectbox("Día (UTC)", dates, key="day", format_func=lambda d: f"{d:%d-%m-%Y}")
state.save("day")
day = days[date]
events = data.events(date)
ts = data.times(day)
st.session_state["times"] = ts

reg = common.REGIONS.get(name)
if reg is None:  # región a medida (--bbox): se deduce de las coordenadas de los datos
    ref = data.era5_ref(day)
    if ref is None and day.goes:
        ref = data.open_nc(day.goes[0])
    if ref is None:
        no_data(
            "Los archivos disponibles no permiten determinar los límites de la región. "
            "Revisa sus coordenadas o selecciona otra región."
        )
    la, lo = ref["latitude"].values, ref["longitude"].values
    reg = common.Region(name, float(la.max()), float(la.min()), float(lo.min()), float(lo.max()))
st.session_state["ctx"] = state.Context(name, reg, day, events)

# Al cambiar de día: el evento más intenso queda elegido y la regla va a su hora.
if st.session_state.get("_previous_day") != date:
    st.session_state["_previous_day"] = date
    st.session_state["step"] = None
    st.session_state.pop("_tour_before", None)
    st.session_state.pop("point", None)
    timed = events[events["hour"].notna()] if len(events) else events
    if len(timed):
        ef = pd.to_numeric(timed["ef"].str.extract(r"(\d)")[0], errors="coerce")
        main_event = timed.iloc[int(np.argmax(ef.fillna(-1).to_numpy()))]
        state.go_to_event(main_event)
    elif ts:
        state.set_widget(
            "t_idx", state.index_of(pd.Timestamp(dt.datetime.combine(date, dt.time(21))))
        )

# --- Regla de tiempo -----------------------------------------------------------------------------
if ts:
    state.restore("t_idx")
    if st.session_state.get("t_idx", 0) >= len(ts):
        st.session_state["t_idx"] = len(ts) - 1
    sidebar.select_slider(
        "Hora (UTC)", options=list(range(len(ts))), key="t_idx",
        format_func=lambda i: pd.Timestamp(ts[i]).strftime("%H:%M"),
        help="Si hay imágenes GOES, puedes avanzar entre los barridos disponibles, normalmente "
        "separados por 10 minutos. ERA5 muestra el registro horario más cercano. Comprueba la hora "
        "indicada en cada gráfico.",
    )  # fmt: skip
    state.save("t_idx")
    t = state.current_time()
    if t is not None:
        sidebar.html(components.ruler(ts, events, t))
else:
    sidebar.info("No hay registros con hora para este día. Selecciona otro día disponible.")

# --- Eventos -------------------------------------------------------------------------------------
if len(events):
    options = ["—", *events["id"]]
    selected = state.point()

    def on_event_select() -> None:
        """Callback: lleva el visor al evento elegido en la lista."""
        k = st.session_state["event_select"]
        if k != "—":
            state.go_to_event(events[events["id"] == k].iloc[0])

    st.session_state["event_select"] = (
        selected.event if selected and selected.event in options else "—"
    )
    sidebar.selectbox(
        "Evento", options, key="event_select", on_change=on_event_select,
        format_func=lambda k: "Sin evento seleccionado" if k == "—" else
        f"{events.set_index('id').loc[k, 'hour_txt']} · {events.set_index('id').loc[k, 'place']}",
    )  # fmt: skip
p = state.point()
if p is not None:
    sidebar.html(
        f"<p class='note'>Punto elegido: <b>{html.escape(p.name)}</b> · "
        f"<span class='mono'>{components.coord(p.lat, p.lon)}</span></p>"
    )

# --- Recorrido guiado ----------------------------------------------------------------------------
steps = texts.TOURS.get(date, ())
if steps:
    sidebar.divider()
    k = state.current_step()
    if k is None:
        sidebar.button(
            "Empezar recorrido", icon=":material/play_arrow:", type="primary", width="stretch",
            on_click=state.apply_step, args=(date, 0, events),
        )  # fmt: skip
        sidebar.caption(
            f"Recorrido de {len(steps)} pasos por el caso del {date:%d-%m-%Y}. "
            "Cada paso selecciona una página, una hora y los datos que se deben observar."
        )
    else:
        step = steps[k]
        sidebar.html(
            f"<div class='step'><b>PASO {k + 1}/{len(steps)} · {step.hour} UTC</b><br>"
            f"{step.text}</div>"
        )
        c1, c2 = sidebar.columns(2)
        c1.button(
            "Anterior", icon=":material/chevron_left:", disabled=k == 0, width="stretch",
            on_click=state.apply_step, args=(date, k - 1, events),
        )  # fmt: skip
        c2.button(
            "Siguiente", icon=":material/chevron_right:", disabled=k == len(steps) - 1,
            type="primary", width="stretch", on_click=state.apply_step,
            args=(date, k + 1, events),
        )  # fmt: skip
        sidebar.button(
            "Salir del recorrido", type="tertiary", icon=":material/close:",
            on_click=state.apply_step, args=(date, None, events),
        )  # fmt: skip
        if k == len(steps) - 1:
            sidebar.caption(
                "Recorrido completo. Puedes explorar otro punto o consultar cómo participar en el proyecto."
            )
            sidebar.page_link(
                state.page("project"), label="Ver cómo participar", icon=":material/groups:"
            )

# El recorrido pide el cambio de página desde un callback; se ejecuta aquí.
target = st.session_state.pop("go_to", None)
if target in PAGES and PAGES[target].url_path != navigation.url_path:
    st.switch_page(PAGES[target])

navigation.run()
