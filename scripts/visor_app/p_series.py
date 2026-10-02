"""Página «Series»: el entorno ERA5 hora a hora y los topes GOES cada 10 minutos alrededor del punto."""

import pandas as pd
import streamlit as st

from visor_app import datos, estado, graficos, tema


def _serie_era5(
    ctx: estado.Contexto, v: str, p: estado.Punto, radio: float, peor: str
) -> tuple[pd.Series, pd.Series]:
    """Serie de la variable ``v`` en el punto y su extremo en el cuadrado de ±``radio``°."""
    assert ctx.dia.idx is not None
    da = datos.abre(ctx.dia.idx)[v]
    en_punto = da.sel(latitude=p.lat, longitude=p.lon, method="nearest").to_series()
    caja = datos.ventana(da, p.lat, p.lon, radio)
    extremo = (
        caja.min(dim=["latitude", "longitude"])
        if peor == "<"
        else caja.max(dim=["latitude", "longitude"])
    )
    return en_punto, extremo.to_series()


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    p = estado.punto()
    st.title("Series")
    if p is None:
        st.info(
            "Elige un evento en la barra lateral o haz clic en el mapa ERA5 de la página Mapas."
        )
        return
    estado.recuerda("radio")
    st.session_state.setdefault("radio", 0.5)
    radio = st.select_slider(
        "Ventana alrededor del punto", options=[0.25, 0.5, 0.75, 1.0], key="radio",
        format_func=lambda r: f"±{r:g}° (~{r * 111:.0f} km)",
    )  # fmt: skip
    estado.guarda("radio")
    st.html(
        f"<p class='lede'>{p.nombre} · <span class='mono'>{p.lat:.2f}°, {p.lon:.2f}°</span>. "
        "«Punto»: la celda ERA5 más cercana. «Ventana»: el valor más peligroso dentro del "
        "cuadrado elegido, útil porque ERA5 y el catálogo no coinciden al kilómetro.</p>"
    )

    filas: list[graficos.Serie] = []
    tabla = {}
    if ctx.dia.idx is not None:
        for v, titulo, unidad, umbral, peor in (
            ("vgp_01", "VGP₀₋₁", "m/s²", 0.1, ">"),
            ("srh_01", "SRH₀₋₁ left-mover", "m²/s²", None, "<"),
            ("cizalle_01", "Cizalle 0–1 km", "m/s", 12.0, ">"),
        ):
            s_p, s_v = _serie_era5(ctx, v, p, radio, peor)
            filas.append(graficos.Serie(titulo, unidad, ((s_p, "punto", tema.ACCENT),
                                                         (s_v, "ventana", tema.INK_2)), umbral))  # fmt: skip
            tabla[f"{v}_punto"], tabla[f"{v}_ventana"] = s_p, s_v
    else:
        st.info(
            "Faltan los índices ERA5 de este día: corre "
            f"`uv run python scripts/procesa_era5.py --inicio {ctx.dia.fecha:%Y-%m-%d}`."
        )
    if ctx.dia.goes:
        g = pd.concat([datos.serie_goes(r, p.lat, p.lon, radio) for r in ctx.dia.goes])
        # Grilla regular de 10 min: las horas sin descargar quedan como huecos, no como rectas.
        g["time"] = g["time"].dt.floor("10min")
        g = g.drop_duplicates("time").set_index("time").sort_index()
        t0, t1 = g.index.min().floor("h"), g.index.max()
        g = g.reindex(pd.date_range(t0, t1, freq="10min"))
        tb = g["tb_min"] - 273.15
        filas.append(
            graficos.Serie("Temperatura mínima del tope (C13)", "°C", ((tb, "ventana", tema.COLD),))
        )
        filas.append(
            graficos.Serie(
                "Área de topes más fríos que −50 °C", "km²", ((g["area_50"], "ventana", tema.COLD),)
            )
        )
        tabla["tb_min_c13_C"], tabla["area_bajo_menos50_km2"] = tb, g["area_50"]
    if not filas:
        st.info("Este día no tiene índices ni imágenes para armar series.")
        return

    fig = graficos.series(filas, ctx.eventos, p.evento)
    t = estado.t_actual()
    if t is not None:
        fig.add_vline(x=pd.Timestamp(t), line={"color": tema.ACCENT, "width": 1})
    st.plotly_chart(fig, width="stretch", theme=None)
    st.caption(
        "Rojo continuo: la hora del evento elegido; punteado: los demás eventos del día. Línea "
        "verde: la hora de la regla. Rayas rojas: umbral chileno (VGP y cizalle 0–1 km; la SRH no "
        "tiene uno calibrado). Horas en UTC; las horas GOES sin descargar quedan como huecos. "
        "Aquí la temperatura va en °C; en los mapas, en K (°C = K − 273,15)."
    )
    datos_csv = pd.DataFrame(tabla)
    datos_csv.index.name = "time_utc"
    st.download_button(
        "Descargar series (CSV)", datos_csv.to_csv().encode(), icon=":material/download:",
        file_name=f"series_{ctx.dia.fecha:%Y%m%d}_{p.lat:.2f}_{p.lon:.2f}.csv", mime="text/csv",
    )  # fmt: skip
