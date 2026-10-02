"""Página «Sondeo»: perfil vertical (Skew-T) e hodógrafo de ERA5 en el punto elegido."""

import metpy.calc as mpcalc
import numpy as np
import pandas as pd
import streamlit as st
import xarray as xr
from metpy.units import units

from visor_app import componentes, datos, estado, graficos, textos

G = 9.80665


def _columna(ds: xr.Dataset, t: pd.Timestamp, p: estado.Punto) -> xr.Dataset:
    """La columna de ``ds`` en la hora y el punto de grilla más cercanos."""
    return ds.sel(time=t, method="nearest").sel(latitude=p.lat, longitude=p.lon, method="nearest")


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    t, p = estado.t_actual(), estado.punto()
    st.title("Sondeo")
    if p is None or t is None:
        st.info(
            "Elige un evento en la barra lateral o haz clic en el mapa ERA5 de la página Mapas."
        )
        return
    if ctx.dia.pl is None or ctx.dia.sfc is None:
        st.info(
            "El sondeo necesita ERA5 de niveles de presión y de superficie de este día. Corre "
            f"`uv run python scripts/descarga_era5.py --inicio {ctx.dia.fecha:%Y-%m-%d}`."
        )
        return
    faltan = {"u", "v", "t", "z", "r"} - set(datos.abre(ctx.dia.pl).data_vars)
    faltan |= {"sp", "2t", "2d", "10u", "10v"} - set(datos.abre(ctx.dia.sfc).data_vars)
    if faltan:
        st.info(
            f"A los archivos ERA5 de este día les faltan {', '.join(sorted(faltan))}. Vuelve a "
            f"correr `descarga_era5.py --inicio {ctx.dia.fecha:%Y-%m-%d}` (completa lo que falta)."
        )
        return
    t = pd.Timestamp(t)
    pl = _columna(datos.abre(ctx.dia.pl), t, p).load().sortby("level", ascending=False)
    sfc = _columna(datos.abre(ctx.dia.sfc), t, p).load()
    hora = datos.instante(pl["time"])
    la, lo = float(pl["latitude"]), float(pl["longitude"])
    st.html(
        f"<p class='lede'>{p.nombre} · ERA5 {hora:%H:%M} UTC en el punto de grilla "
        f"<span class='mono'>{la:.2f}°, {lo:.2f}°</span> (celdas de ~31 km).</p>"
    )

    # Perfil termodinámico: superficie + niveles por encima del suelo.
    sp = float(sfc["sp"]) / 100
    arriba = pl["level"].values < sp
    pres = np.r_[sp, pl["level"].values[arriba]] * units.hPa
    temp = np.r_[float(sfc["2t"]), pl["t"].values[arriba]] * units.K
    td_pl = mpcalc.dewpoint_from_relative_humidity(
        pl["t"].values[arriba] * units.K, np.clip(pl["r"].values[arriba], 1, 100) * units.percent
    )
    rocio = np.r_[(float(sfc["2d"]) * units.K).to("degC").m, td_pl.to("degC").m] * units.degC
    parcela = mpcalc.parcel_profile(pres, temp[0], rocio[0]).to("degC")
    p_lcl, _ = mpcalc.lcl(pres[0], temp[0], rocio[0])
    sbcape, sbcin = mpcalc.surface_based_cape_cin(pres, temp, rocio)

    # Viento por altura sobre el suelo, del suelo (10 m) a 10 km.
    if ctx.dia.idx is not None:  # altura del terreno calculada por procesa_era5.py
        h_sfc = float(_columna(datos.abre(ctx.dia.idx), t, p)["altura_sfc"])
    else:
        lnp, z = np.log(pl["level"].values[::-1]), (pl["z"].values / G)[::-1]
        h_sfc = float(np.interp(np.log(sp), lnp, z))
    agl = pl["z"].values[arriba] / G - h_sfc
    alt = np.r_[10.0, agl]
    u = np.r_[float(sfc["10u"]), pl["u"].values[arriba]]
    v = np.r_[float(sfc["10v"]), pl["v"].values[arriba]]
    k = alt <= 10000
    rm, lm, media = mpcalc.bunkers_storm_motion(
        pres, u * units("m/s"), v * units("m/s"), alt * units.m
    )

    izq, der = st.columns(2, gap="large")
    with izq:
        st.plotly_chart(
            graficos.skewt(
                pres.m, temp.to("degC").m, rocio.m, parcela.m, float(p_lcl.m),
                "Temperatura, punto de rocío y parcela de superficie",
            ),
            width="stretch", theme=None,
        )  # fmt: skip
    with der:
        st.plotly_chart(
            graficos.hodografo(
                alt[k], u[k], v[k], (lm[0].m, lm[1].m), (rm[0].m, rm[1].m),
                (media[0].m, media[1].m), "Hodógrafo 0–10 km · u y v en m/s",
            ),
            width="stretch", theme=None,
        )  # fmt: skip

    izq, der = st.columns([3, 2], gap="large")
    with izq:
        st.subheader("Índices en este punto")
        filas = [
            componentes.Fila(
                "CAPE de superficie (MetPy)", "J/kg", float(sbcape.m), None, None, None
            ),
            componentes.Fila("CIN de superficie (MetPy)", "J/kg", float(sbcin.m), None, None, None),
        ]
        if ctx.dia.idx is not None:
            filas += componentes.filas_indices(
                datos.abre(ctx.dia.idx), np.datetime64(t), (la, lo), None
            )
        st.html(componentes.ficha(filas, "valor", None))
    with der:
        st.subheader("Cómo leerlo")
        st.markdown(
            "**Skew-T.** Las isotermas van inclinadas. Donde la parcela (rayas) queda a la derecha "
            "de la temperatura, flota: esa área es el CAPE. Temperatura y rocío juntos cerca del "
            "suelo = aire húmedo y base de nube baja (LCL)."
        )
        st.markdown(
            "**Hodógrafo.** La punta del viento a cada altura. Una curva larga es mucho cizalle; "
            "el área barrida respecto del movimiento de la tormenta es la helicidad. "
            + textos.NOTA_AUSTRAL
        )
        st.markdown(
            "<p class='nota'>Perfil de ERA5, no un radiosondeo: suaviza los extremos y representa "
            "una celda de ~31 km.</p>",
            unsafe_allow_html=True,
        )
