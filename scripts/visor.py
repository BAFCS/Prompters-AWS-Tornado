"""Visor exploratorio de ERA5 y GOES para los casos de tornados en Chile (Streamlit + plotly).

Página de entrada de una app de varias páginas (``st.navigation``): dibuja la barra lateral común
(región, día, regla de tiempo, eventos y recorrido guiado), publica el contexto en
``st.session_state`` y corre la página elegida. Las páginas viven en ``scripts/visor_app/``.

Lee lo que dejan los scripts de descarga y procesamiento::

    data/recortes/<region>/era5_pl/era5_pl_AAAAMMDD.nc
    data/recortes/<region>/era5_sfc/era5_sfc_AAAAMMDD.nc
    data/recortes/<region>/era5_indices/era5_idx_AAAAMMDD.nc     (procesa_era5.py)
    data/recortes/<region>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc

Uso::

    uv run streamlit run scripts/visor.py
"""

import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st

import comun
from visor_app import componentes, datos, estado, p_caso, p_mapas, p_series, p_sondeo, tema

st.set_page_config(
    page_title="Mesociclones en Chile · visor", page_icon=":material/storm:", layout="wide"
)
tema.aplica()

PAGINAS = {
    "caso": st.Page(p_caso.pagina, title="El caso", icon=":material/history_edu:", default=True),
    "mapas": st.Page(p_mapas.pagina, title="Mapas", icon=":material/map:", url_path="mapas"),
    "sondeo": st.Page(p_sondeo.pagina, title="Sondeo", icon=":material/stacked_line_chart:",
                      url_path="sondeo"),
    "series": st.Page(p_series.pagina, title="Series", icon=":material/timeline:",
                      url_path="series"),
}  # fmt: skip
st.session_state["paginas"] = PAGINAS
navegacion = st.navigation(list(PAGINAS.values()), position="top")

# --- Región y día --------------------------------------------------------------------------------
barra = st.sidebar
barra.markdown("## Mesociclones en Chile")
nombres = datos.regiones()
if not nombres:
    st.error(
        "No hay recortes en `data/recortes/`. Descarga un día con `descarga_era5.py` y "
        "`descarga_goes.py` (ver AGENTS.md) y recarga esta página."
    )
    st.stop()
estado.recuerda("region")
nombre = barra.selectbox(
    "Región", nombres, key="region",
    index=nombres.index("centro-sur-austral") if "centro-sur-austral" in nombres else 0,
)  # fmt: skip
estado.guarda("region")
dias = datos.dias(nombre)
if not dias:
    st.error(f"La región {nombre} no tiene datos todavía.")
    st.stop()
fechas = list(dias)
estado.recuerda("dia")
if st.session_state.get("dia") not in fechas:
    st.session_state["dia"] = dt.date(2019, 5, 30) if dt.date(2019, 5, 30) in fechas else fechas[-1]
fecha = barra.selectbox("Día (UTC)", fechas, key="dia", format_func=lambda d: f"{d:%d-%m-%Y}")
estado.guarda("dia")
dia = dias[fecha]
eventos = datos.eventos(fecha)
ts = datos.tiempos(dia)
st.session_state["tiempos"] = ts

reg = datos.region(nombre)
if reg is None:  # región a medida: se deduce de las coordenadas de los datos
    ref = datos.era5_ref(dia)
    if ref is None and dia.goes:
        ref = datos.abre(dia.goes[0])
    if ref is None:
        st.error("No se pudo deducir la extensión de la región.")
        st.stop()
    la, lo = ref["latitude"].values, ref["longitude"].values
    reg = comun.Region(nombre, float(la.max()), float(la.min()), float(lo.min()), float(lo.max()))
st.session_state["ctx"] = estado.Contexto(nombre, reg, dia, eventos)

# Al cambiar de día: el evento más intenso queda elegido y la regla va a su hora.
if st.session_state.get("_dia_previo") != fecha:
    st.session_state["_dia_previo"] = fecha
    st.session_state["paso"] = None
    st.session_state.pop("punto", None)
    con_hora = eventos[eventos["hora"].notna()] if len(eventos) else eventos
    if len(con_hora):
        ef = pd.to_numeric(con_hora["ef"].str.extract(r"(\d)")[0], errors="coerce")
        principal = con_hora.iloc[int(np.argmax(ef.fillna(-1).to_numpy()))]
        estado.ir_a_evento(principal)
    elif ts:
        estado.fija(
            "t_idx", estado.indice_de(pd.Timestamp(dt.datetime.combine(fecha, dt.time(21))))
        )

# --- Regla de tiempo -----------------------------------------------------------------------------
if ts:
    estado.recuerda("t_idx")
    if st.session_state.get("t_idx", 0) >= len(ts):
        st.session_state["t_idx"] = len(ts) - 1
    barra.select_slider(
        "Hora (UTC)", options=list(range(len(ts))), key="t_idx",
        format_func=lambda i: pd.Timestamp(ts[i]).strftime("%H:%M"),
        help="Cada imagen GOES (10 min). ERA5 usa la hora en punto más cercana.",
    )  # fmt: skip
    estado.guarda("t_idx")
    t = estado.t_actual()
    if t is not None:
        barra.html(componentes.regla(ts, eventos, t))
else:
    barra.info("Este día no tiene datos con hora.")

# --- Eventos -------------------------------------------------------------------------------------
if len(eventos):
    opciones = ["—", *eventos["id"]]
    elegido = estado.punto()

    def al_elegir_evento() -> None:
        """Callback: lleva el visor al evento elegido en la lista."""
        k = st.session_state["ev_sel"]
        if k != "—":
            estado.ir_a_evento(eventos[eventos["id"] == k].iloc[0])

    st.session_state["ev_sel"] = elegido.evento if elegido and elegido.evento in opciones else "—"
    barra.selectbox(
        "Evento", opciones, key="ev_sel", on_change=al_elegir_evento,
        format_func=lambda k: "—" if k == "—" else
        f"{eventos.set_index('id').loc[k, 'hora_txt']} · {eventos.set_index('id').loc[k, 'lugar']}",
    )  # fmt: skip
p = estado.punto()
if p is not None:
    barra.html(
        f"<p class='nota'>Punto elegido: <b>{p.nombre}</b> · "
        f"<span class='mono'>{p.lat:.2f}°, {p.lon:.2f}°</span></p>"
    )

# --- Recorrido guiado ----------------------------------------------------------------------------
pasos = estado.recorrido(fecha)
if pasos:
    barra.divider()
    k = estado.paso_actual()
    if k is None:
        barra.button(
            "Empezar recorrido", icon=":material/play_arrow:", type="primary", width="stretch",
            on_click=estado.aplica_paso, args=(fecha, 0, eventos),
        )  # fmt: skip
        barra.caption(f"{len(pasos)} pasos por el caso, de la mano de la regla de tiempo.")
    else:
        paso = pasos[k]
        barra.html(
            f"<div class='paso'><b>PASO {k + 1}/{len(pasos)} · {paso.hora} UTC</b><br>"
            f"{paso.texto}</div>"
        )
        c1, c2 = barra.columns(2)
        c1.button(
            "Anterior", icon=":material/chevron_left:", disabled=k == 0, width="stretch",
            on_click=estado.aplica_paso, args=(fecha, k - 1, eventos),
        )  # fmt: skip
        c2.button(
            "Siguiente", icon=":material/chevron_right:", disabled=k == len(pasos) - 1,
            type="primary", width="stretch", on_click=estado.aplica_paso,
            args=(fecha, k + 1, eventos),
        )  # fmt: skip
        barra.button(
            "Salir del recorrido", type="tertiary", icon=":material/close:",
            on_click=estado.aplica_paso, args=(fecha, None, eventos),
        )  # fmt: skip

# El recorrido pide el cambio de página desde un callback; se ejecuta aquí.
destino = st.session_state.pop("ir_a", None)
if destino in PAGINAS and PAGINAS[destino].url_path != navegacion.url_path:
    st.switch_page(PAGINAS[destino])

navegacion.run()
