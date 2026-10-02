"""Estado compartido entre páginas: día, hora, punto elegido, recorrido y opciones de cada página.

Streamlit borra el valor de un widget cuando su página deja de mostrarse. Para que las opciones de
una página sobrevivan a un cambio de página, ``recuerda`` guarda una copia bajo ``_<clave>`` y la
restaura antes de dibujar el widget. El recorrido escribe en esas mismas claves desde un callback,
que corre antes de que se dibuje ningún widget.
"""

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.navigation.page import Page

import comun
from visor_app import datos, textos


@dataclass(frozen=True)
class Contexto:
    """Lo que la barra lateral eligió y todas las páginas necesitan: región, día y eventos."""

    nombre: str
    reg: comun.Region
    dia: datos.Dia
    eventos: pd.DataFrame


def pagina(nombre: str) -> Page:
    """La página ``nombre`` ("caso", "mapas", "sondeo" o "series"), para ``st.page_link``."""
    return st.session_state["paginas"][nombre]


def contexto() -> Contexto:
    """El contexto publicado por la página de entrada en esta ejecución."""
    return st.session_state["ctx"]


@dataclass(frozen=True)
class Punto:
    """Un lugar elegido: coordenadas y un nombre para mostrar (evento del catálogo o clic)."""

    lat: float
    lon: float
    nombre: str
    evento: str | None = None  # id del evento en ``datos.eventos`` si viene del catálogo


def recuerda(clave: str) -> None:
    """Restaura el valor guardado de ``clave`` antes de dibujar su widget en otra página."""
    if clave not in st.session_state and f"_{clave}" in st.session_state:
        st.session_state[clave] = st.session_state[f"_{clave}"]


def guarda(clave: str) -> None:
    """Guarda el valor actual del widget ``clave`` para que sobreviva a un cambio de página."""
    if clave in st.session_state:
        st.session_state[f"_{clave}"] = st.session_state[clave]


def fija(clave: str, valor: object) -> None:
    """Escribe ``valor`` en el widget ``clave`` y en su copia persistente (solo desde callbacks)."""
    st.session_state[clave] = valor
    st.session_state[f"_{clave}"] = valor


def tiempos() -> list[np.datetime64]:
    """Eje de tiempo del día actual (lo publica la página de entrada en cada ejecución)."""
    return st.session_state.get("tiempos", [])


def t_actual() -> np.datetime64 | None:
    """Hora elegida en la regla de tiempo, o ``None`` si el día no tiene datos con hora."""
    ts = tiempos()
    if not ts:
        return None
    return ts[min(st.session_state.get("t_idx", 0), len(ts) - 1)]


def indice_de(hora: pd.Timestamp) -> int:
    """Posición en el eje de tiempo más cercana a ``hora``."""
    ts = tiempos()
    return int(np.argmin([abs(pd.Timestamp(t) - hora) for t in ts])) if ts else 0


def punto() -> Punto | None:
    """El punto elegido (por evento, clic en el mapa o recorrido), si hay uno."""
    return st.session_state.get("punto")


def elige_punto(p: Punto) -> None:
    """Fija ``p`` como punto elegido en todas las páginas."""
    st.session_state["punto"] = p


def ir_a_evento(ev: pd.Series) -> None:
    """Callback: lleva la regla de tiempo a la hora del evento ``ev`` y lo fija como punto."""
    elige_punto(Punto(float(ev["lat"]), float(ev["lon"]), str(ev["lugar"]), str(ev["id"])))
    if ev["hora"] is not None and not pd.isna(ev["hora"]):
        fija("t_idx", indice_de(pd.Timestamp(ev["hora"])))


# --- Recorrido guiado ----------------------------------------------------------------------------
def recorrido(dia: dt.date) -> tuple[textos.Paso, ...]:
    """Pasos del recorrido de ``dia`` (vacío si el día no tiene uno escrito)."""
    return textos.RECORRIDOS.get(dia, ())


def paso_actual() -> int | None:
    """Índice del paso del recorrido en curso, o ``None`` si no hay recorrido activo."""
    return st.session_state.get("paso")


def aplica_paso(dia: dt.date, k: int | None, eventos: pd.DataFrame) -> None:
    """Callback: activa el paso ``k`` del recorrido (o lo termina con ``None``).

    Mueve la hora, el punto, las capas de la página Mapas y pide el cambio de página; el cambio
    efectivo lo hace la página de entrada (``st.switch_page`` no funciona dentro de un callback).
    """
    pasos = recorrido(dia)
    if k is None or not pasos:
        st.session_state["paso"] = None
        return
    k = max(0, min(k, len(pasos) - 1))
    p = pasos[k]
    st.session_state["paso"] = k
    hh, mm = (int(x) for x in p.hora.split(":"))
    fija("t_idx", indice_de(pd.Timestamp(dt.datetime.combine(dia, dt.time(hh, mm)))))
    if p.evento and not eventos.empty:
        filas = eventos[eventos["lugar"].str.contains(p.evento, case=False, regex=False)]
        if len(filas):
            ev = filas.iloc[0]
            elige_punto(Punto(float(ev["lat"]), float(ev["lon"]), str(ev["lugar"]), str(ev["id"])))
    if p.era5:
        fija("era5_var", p.era5)
    if p.goes:
        fija("goes_prod", p.goes)
    st.session_state["ir_a"] = p.pagina
