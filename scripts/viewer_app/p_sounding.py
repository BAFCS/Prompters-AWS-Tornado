"""Página «Sondeo»: perfil vertical (Skew-T) e hodógrafo de ERA5 en el punto elegido."""

import html

import metpy.calc as mpcalc
import numpy as np
import pandas as pd
import streamlit as st
import xarray as xr
from metpy.units import units

import common
from viewer_app import charts, components, data, state, texts, theme, variables


def _column(ds: xr.Dataset, t: pd.Timestamp, p: state.Point) -> xr.Dataset:
    """La columna de ``ds`` en la hora y el punto de grilla más cercanos."""
    return ds.sel(time=t, method="nearest").sel(latitude=p.lat, longitude=p.lon, method="nearest")


# Fichas de Datos de lo que muestra la página: los dos gráficos, la CAPE y la CIN y los índices de la tabla.
SHEETS = tuple(
    dict.fromkeys(("hodografo", "bunkers", "cape", "cin", *components.SCORECARD_INDICES))
)


def _on_sheet() -> None:
    """Callback de las píldoras de fichas: abre la ficha elegida en Datos."""
    key = st.session_state["sounding_sheet"]
    st.session_state["sounding_sheet"] = None
    if key:
        state.go_to_variable(key)


def page() -> None:
    """Dibuja la página."""
    ctx = state.context()
    t, p = state.current_time(), state.point()
    st.title("Sondeo")
    st.markdown(
        "Perfil vertical estimado con ERA5 en el punto seleccionado. "
        "Representa una celda de unos 31 km y puede suavizar los extremos; no es un radiosondeo observado."
    )
    if p is None or t is None:
        st.info(
            "Elige un evento en la barra lateral o haz clic en un panel de Mapas cuando haya datos ERA5."
        )
        return
    if ctx.day.pl is None or ctx.day.sfc is None:
        st.info(
            "El perfil requiere ERA5 de niveles de presión y de superficie. Selecciona otro día disponible. Para preparar este día, ejecuta "
            f"`uv run python scripts/download_era5.py --start {ctx.day.date:%Y-%m-%d}`."
        )
        return
    missing = {"u", "v", "t", "z", "r"} - set(data.open_nc(ctx.day.pl).data_vars)
    missing |= {"sp", "2t", "2d", "10u", "10v"} - set(data.open_nc(ctx.day.sfc).data_vars)
    if missing:
        st.info(
            "Los archivos ERA5 de este día están incompletos para calcular el perfil. Selecciona otro día o vuelve a "
            f"ejecutar `uv run python scripts/download_era5.py --start {ctx.day.date:%Y-%m-%d}` para completar las variables faltantes."
        )
        return
    t = pd.Timestamp(t)
    pl = _column(data.open_nc(ctx.day.pl), t, p).load().sortby("level", ascending=False)
    sfc = _column(data.open_nc(ctx.day.sfc), t, p).load()
    hour = data.to_timestamp(pl["time"])
    la, lo = float(pl["latitude"]), float(pl["longitude"])
    st.html(
        f"<p class='lede'>{html.escape(p.name)} · ERA5 {hour:%H:%M} UTC en el punto de grilla "
        f"<span class='mono'>{components.coord(la, lo)}</span> (celdas de ~31 km).</p>"
    )

    # Perfil termodinámico: superficie + niveles por encima del suelo.
    sp = float(sfc["sp"]) / 100
    above = pl["level"].values < sp
    pres = np.r_[sp, pl["level"].values[above]] * units.hPa
    temp = np.r_[float(sfc["2t"]), pl["t"].values[above]] * units.K
    td_pl = mpcalc.dewpoint_from_relative_humidity(
        pl["t"].values[above] * units.K, np.clip(pl["r"].values[above], 1, 100) * units.percent
    )
    dewpoint = np.r_[(float(sfc["2d"]) * units.K).to("degC").m, td_pl.to("degC").m] * units.degC
    parcel = mpcalc.parcel_profile(pres, temp[0], dewpoint[0]).to("degC")
    p_lcl, _ = mpcalc.lcl(pres[0], temp[0], dewpoint[0])
    sbcape, sbcin = mpcalc.surface_based_cape_cin(pres, temp, dewpoint)

    # Viento por altura sobre el suelo, del suelo (10 m) a 10 km.
    if ctx.day.idx is not None:  # altura del terreno calculada por process_era5.py
        h_sfc = float(_column(data.open_nc(ctx.day.idx), t, p)["sfc_height"])
    else:
        lnp, z = np.log(pl["level"].values[::-1]), (pl["z"].values / common.G)[::-1]
        h_sfc = float(np.interp(np.log(sp), lnp, z))
    agl = pl["z"].values[above] / common.G - h_sfc
    alt = np.r_[10.0, agl]
    u = np.r_[float(sfc["10u"]), pl["u"].values[above]]
    v = np.r_[float(sfc["10v"]), pl["v"].values[above]]
    k = alt <= 10000
    rm, lm, mean = mpcalc.bunkers_storm_motion(
        pres, u * units("m/s"), v * units("m/s"), alt * units.m
    )

    left, right = theme.columns(2, "sounding_charts")
    with left:
        st.plotly_chart(
            charts.skewt(
                pres.m, temp.to("degC").m, dewpoint.m, parcel.m, float(p_lcl.m),
                "Temperatura, punto de rocío y parcela de superficie",
            ),
            width="stretch", theme=None,
        )  # fmt: skip
    with right:
        st.plotly_chart(
            charts.hodograph(
                alt[k], u[k], v[k], (lm[0].m, lm[1].m), (rm[0].m, rm[1].m),
                (mean[0].m, mean[1].m), "Hodógrafo 0–10 km · u y v en m/s",
            ),
            width="stretch", theme=None,
        )  # fmt: skip

    left, right = theme.columns([3, 2], "sounding_indices")
    with left:
        st.subheader("Índices en este punto")
        rows = [
            components.Row("CAPE de superficie (MetPy)", "J/kg", float(sbcape.m), None, None, None),
            components.Row("CIN de superficie (MetPy)", "J/kg", float(sbcin.m), None, None, None),
        ]
        if ctx.day.idx is not None:
            rows += components.index_rows(
                data.open_nc(ctx.day.idx), np.datetime64(t), (la, lo), None
            )
        st.html(components.scorecard(rows, "valor", None))
        if ctx.day.idx is not None:
            st.caption(texts.STP_NOTE)
    with right:
        st.subheader("Cómo leerlo")
        st.markdown(
            "**Skew-T.** El diagrama representa temperatura y presión; las líneas de igual "
            "temperatura están inclinadas. El punto de rocío indica la temperatura a la que el "
            "aire alcanzaría la saturación. La línea de parcela muestra cómo cambiaría la "
            "temperatura de una porción de aire al ascender desde la superficie. Compararla "
            "con el entorno ayuda a calcular la energía potencial convectiva disponible "
            "(CAPE) y la inhibición convectiva (CIN), una barrera energética para iniciar el ascenso."
        )
        st.markdown(
            "Una pequeña diferencia entre temperatura y punto de rocío cerca del suelo es "
            "compatible con una base de nube baja. El nivel de condensación por ascenso (LCL) "
            "estima dónde el aire que asciende comienza a condensarse."
        )
        st.markdown(
            "**Hodógrafo.** Muestra cómo cambia el viento con la altura. Cada punto representa "
            "sus componentes este-oeste (u) y norte-sur (v), en m/s; la curva une distintos niveles. "
            "Las marcas de Bunkers son estimaciones del movimiento de dos posibles ramas de la "
            "tormenta. La rama left-mover se mueve hacia la izquierda del viento medio y la "
            "right-mover hacia la derecha. La helicidad relativa a la tormenta (SRH) se calcula "
            "usando el perfil y una de esas estimaciones; los índices de esta app utilizan la rama left-mover."
        )
        st.pills(
            "Fichas en Datos", list(SHEETS), key="sounding_sheet", on_change=_on_sheet,
            format_func=lambda k: variables.BY_KEY[k].symbol,
            help="Qué es cada índice, su fórmula, el criterio chileno y sus fuentes.",
        )  # fmt: skip
