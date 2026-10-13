"""Estado compartido entre páginas: día, hora, punto elegido, recorrido y opciones de cada página.

Streamlit borra el valor de un widget cuando su página deja de mostrarse. Para que las opciones de
una página sobrevivan a un cambio de página, ``restore`` guarda una copia bajo ``_<key>`` y la
restaura antes de dibujar el widget. El recorrido escribe en esas mismas claves desde un callback,
que corre antes de que se dibuje ningún widget.
"""

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.navigation.page import Page

import common
from viewer_app import data, texts


@dataclass(frozen=True)
class Context:
    """Lo que la barra lateral eligió y todas las páginas necesitan: región, día y eventos."""

    name: str
    reg: common.Region
    day: data.Day
    events: pd.DataFrame


def page(name: str) -> Page:
    """La página ``name`` (una clave de ``PAGES`` en ``viewer.py``), para ``st.page_link``."""
    return st.session_state["pages"][name]


def context() -> Context:
    """El contexto publicado por la página de entrada en esta ejecución."""
    return st.session_state["ctx"]


@dataclass(frozen=True)
class Point:
    """Un lugar elegido: coordenadas y un nombre para mostrar (evento del catálogo o clic)."""

    lat: float
    lon: float
    name: str
    event: str | None = None  # id del evento en ``data.events`` si viene del catálogo

    @classmethod
    def from_event(cls, ev: pd.Series) -> "Point":
        """El punto de la fila ``ev`` de ``data.events``."""
        return cls(float(ev["lat"]), float(ev["lon"]), str(ev["place"]), str(ev["id"]))


def restore(key: str) -> None:
    """Restaura el valor guardado de ``key`` antes de dibujar su widget en otra página."""
    if key not in st.session_state and f"_{key}" in st.session_state:
        st.session_state[key] = st.session_state[f"_{key}"]


def save(key: str) -> None:
    """Guarda el valor actual del widget ``key`` para que sobreviva a un cambio de página."""
    if key in st.session_state:
        st.session_state[f"_{key}"] = st.session_state[key]


def set_widget(key: str, value: object) -> None:
    """Escribe ``value`` en el widget ``key`` y en su copia persistente (solo desde callbacks)."""
    st.session_state[key] = value
    st.session_state[f"_{key}"] = value


def times() -> list[np.datetime64]:
    """Eje de tiempo del día actual (lo publica la página de entrada en cada ejecución)."""
    return st.session_state.get("times", [])


def current_time() -> np.datetime64 | None:
    """Hora elegida en la regla de tiempo, o ``None`` si el día no tiene datos con hora."""
    ts = times()
    if not ts:
        return None
    return ts[min(st.session_state.get("t_idx", 0), len(ts) - 1)]


def index_of(hour: pd.Timestamp) -> int:
    """Posición en el eje de tiempo más cercana a ``hour``."""
    ts = times()
    return int(np.argmin([abs(pd.Timestamp(t) - hour) for t in ts])) if ts else 0


def point() -> Point | None:
    """El punto elegido (por evento, clic en el mapa o recorrido), si hay uno."""
    return st.session_state.get("point")


def select_point(p: Point, reg: common.Region | None = None) -> None:
    """Fija ``p`` como punto elegido en todas las páginas; con ``reg``, debe caer dentro de ella."""
    if not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180):
        raise ValueError("La latitud debe estar entre −90 y 90°, y la longitud entre −180 y 180°.")
    if reg is not None and not (reg.south <= p.lat <= reg.north and reg.west <= p.lon <= reg.east):
        raise ValueError("El punto debe estar dentro de la región elegida.")
    st.session_state["point"] = p


# --- Paneles de la página Mapas ------------------------------------------------------------------
MAX_PANELS = 6


@dataclass(frozen=True)
class Panel:
    """Un panel de la grilla de Mapas: producto del catálogo y sus opciones."""

    id: int  # estable mientras el panel existe: nombra las claves de sus widgets
    key: str  # clave de ``products.catalog``
    level: float | None = None  # hPa, solo productos de niveles de presión
    contour: str | None = None  # clave ERA5 dibujada como isolíneas (solo paneles GOES)
    colorscale: str | None = (
        None  # escala de color estándar (``colorscales``); ``None``: la del tipo de dato
    )


def panels() -> list[Panel] | None:
    """Los paneles de la grilla, o ``None`` si todavía no se fijaron en esta sesión."""
    ps = st.session_state.get("panels")
    return None if ps is None else [_up_to_date(p) for p in ps]


def _up_to_date(p: object) -> Panel:
    """``p`` como ``Panel`` actual: los de una sesión anterior a una recarga pueden no tener ``colorscale``.

    Tras recargar el módulo, la sesión guarda objetos de la clase ``Panel`` anterior, que ya no pasan
    ``isinstance``: por eso se leen sus campos por nombre.
    """
    if isinstance(p, Panel):
        return p
    old = cast(Any, p)
    return Panel(old.id, old.key, getattr(p, "level", None), getattr(p, "contour", None),
                 getattr(p, "colorscale", None))  # fmt: skip


def set_panels(ps: list[Panel]) -> None:
    """Reemplaza los paneles de la grilla."""
    st.session_state["panels"] = list(ps)


def new_panel(key: str) -> Panel:
    """Un panel con ``key`` y un id que no se repite en la sesión."""
    n = st.session_state.get("_next_panel", 0)
    st.session_state["_next_panel"] = n + 1
    return Panel(n, key)


def add_panel(key: str) -> None:
    """Callback: agrega un panel con ``key`` al final (si no se llegó al tope)."""
    ps = panels() or []
    if len(ps) < MAX_PANELS:
        set_panels([*ps, new_panel(key)])


def remove_panel(id_: int) -> None:
    """Callback: quita el panel ``id_``."""
    set_panels([p for p in panels() or [] if p.id != id_])


def change_panel(id_: int, **changes: object) -> None:
    """Callback: cambia campos del panel ``id_`` (``key``, ``level``, ``contour`` o ``colorscale``)."""
    set_panels([dataclasses.replace(p, **changes) if p.id == id_ else p for p in panels() or []])


def open_in_maps(key: str, level: float | None = None) -> None:
    """Callback: pone el producto ``key`` en el primer panel de Mapas y pide ir a esa página."""
    ps = [dataclasses.replace(new_panel(key), level=level), *(panels() or [])]
    set_panels(ps[:MAX_PANELS])
    st.session_state["go_to"] = "maps"


def go_to_variable(key: str) -> None:
    """Callback: abre la página Datos mostrando solo la ficha ``key`` de ``variables``."""
    st.session_state["data_focus"] = key
    st.session_state["go_to"] = "data"


def go_to_event(ev: pd.Series) -> None:
    """Callback: lleva la regla de tiempo a la hora del evento ``ev`` y lo fija como punto."""
    select_point(Point.from_event(ev))
    if ev["hour"] is not None and not pd.isna(ev["hour"]):
        set_widget("t_idx", index_of(pd.Timestamp(ev["hour"])))


# --- Recorrido guiado ----------------------------------------------------------------------------
def current_step() -> int | None:
    """Índice del paso del recorrido en curso, o ``None`` si no hay recorrido activo."""
    return st.session_state.get("step")


def apply_step(day: dt.date, k: int | None, events: pd.DataFrame) -> None:
    """Callback: activa el paso ``k`` del recorrido (o lo termina con ``None``).

    Mueve la hora, el punto, los paneles de la página Mapas y pide el cambio de página; el cambio
    efectivo lo hace la página de entrada (``st.switch_page`` no funciona dentro de un callback).
    """
    steps = texts.TOURS.get(day, ())
    if k is None or not steps:
        before = st.session_state.pop("_tour_before", None)
        if before is not None:
            for key in ("panels", "point"):
                if before[key] is None:
                    st.session_state.pop(key, None)
                else:
                    st.session_state[key] = before[key]
            set_widget("t_idx", before["t_idx"])
        st.session_state["step"] = None
        return
    if current_step() is None:
        st.session_state["_tour_before"] = {
            "panels": panels(),
            "point": point(),
            "t_idx": st.session_state.get("t_idx", 0),
        }
    k = max(0, min(k, len(steps) - 1))
    p = steps[k]
    st.session_state["step"] = k
    hh, mm = (int(x) for x in p.hour.split(":"))
    set_widget("t_idx", index_of(pd.Timestamp(dt.datetime.combine(day, dt.time(hh, mm)))))
    if p.event and not events.empty:
        rows = events[events["place"].str.contains(p.event, case=False, regex=False)]
        if len(rows):
            ev = rows.iloc[0]
            select_point(Point.from_event(ev))
    if p.panels:
        set_panels([new_panel(c) for c in p.panels])
    st.session_state["go_to"] = p.page
