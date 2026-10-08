"""Página «Series»: el entorno ERA5 hora a hora y las temperaturas de brillo GOES alrededor del punto."""

import html

import pandas as pd
import streamlit as st

from viewer_app import charts, components, data, state, theme


def _era5_series(
    ctx: state.Context, v: str, p: state.Point, radius: float, sense: str
) -> tuple[pd.Series, pd.Series]:
    """Serie de la variable ``v`` en el punto y su extremo en el cuadrado de ±``radius``°."""
    assert ctx.day.idx is not None
    da = data.open_nc(ctx.day.idx)[v]
    at_point = da.sel(latitude=p.lat, longitude=p.lon, method="nearest").to_series()
    square = data.window(da, p.lat, p.lon, radius)
    extreme = (
        square.min(dim=["latitude", "longitude"])
        if sense == "<"
        else square.max(dim=["latitude", "longitude"])
    )
    return at_point, extreme.to_series()


def page() -> None:
    """Dibuja la página."""
    ctx = state.context()
    p = state.point()
    st.title("Series")
    if p is None:
        st.info(
            "Elige un evento en la barra lateral o usa «Elegir punto» en Mapas cuando haya datos ERA5."
        )
        return
    state.restore("radius")
    st.session_state.setdefault("radius", 0.5)
    radius = st.select_slider(
        "Área de comparación alrededor del punto", options=[0.25, 0.5, 0.75, 1.0], key="radius",
        format_func=lambda r: f"±{r:g}°".replace(".", ","),
        help="Rectángulo que se extiende los grados elegidos en latitud y longitud. La distancia este-oeste depende de la latitud.",
    )  # fmt: skip
    state.save("radius")
    st.html(
        f"<p class='lede'>{html.escape(p.name)} · <span class='mono'>{components.coord(p.lat, p.lon)}</span>. "
        "«Punto» es la celda ERA5 más cercana. «Área» muestra el máximo de VGP y cizalladura, "
        "o el mínimo de SRH, dentro del rectángulo elegido. La comparación permite explorar "
        "diferencias espaciales alrededor del lugar reportado.</p>"
    )

    st.markdown(
        "Las series GOES resumen una zona fija; no siguen automáticamente una misma nube. "
        "El desplazamiento de tormentas puede cambiar los valores."
    )

    rows: list[charts.SeriesRow] = []
    table = {}
    if ctx.day.idx is not None:
        for v, title, unit, threshold, sense in (
            ("vgp_01", "VGP₀₋₁", "m/s²", 0.1, ">"),
            ("srh_01", "SRH₀₋₁ left-mover", "m²/s²", None, "<"),
            ("shear_01", "Cizalladura 0–1 km", "m/s", 12.0, ">"),
        ):
            s_p, s_v = _era5_series(ctx, v, p, radius, sense)
            rows.append(charts.SeriesRow(title, unit, ((s_p, "punto", theme.colors().SELECTION),
                                                         (s_v, "área", theme.colors().INK_2)), threshold))  # fmt: skip
            table[f"{v}_point"], table[f"{v}_area"] = s_p, s_v
    else:
        st.info(
            "No hay índices ERA5 preparados para este día. Elige otro día disponible. Si ya descargaste ERA5, puedes calcularlos con "
            f"`uv run python scripts/process_era5.py --start {ctx.day.date:%Y-%m-%d}`."
        )
    if ctx.day.goes:
        g = pd.concat([data.goes_series(r, p.lat, p.lon, radius) for r in ctx.day.goes])
        # Grilla regular de 10 min: las horas sin descargar quedan como huecos, no como rectas.
        g["time"] = g["time"].dt.floor("10min")
        g = g.drop_duplicates("time").set_index("time").sort_index()
        t0, t1 = g.index.min().floor("h"), g.index.max()
        g = g.reindex(pd.date_range(t0, t1, freq="10min"))
        tb = g["tb_min"] - 273.15
        rows.append(
            charts.SeriesRow(
                "Temperatura de brillo mínima de C13 dentro del área",
                "°C",
                ((tb, "área GOES", theme.colors().WARM),),
            )
        )
        rows.append(
            charts.SeriesRow(
                "Área con temperatura de brillo inferior a −50 °C",
                "km²",
                ((g["area_50"], "área GOES", theme.colors().WARM),),
            )
        )
        table["tb_min_c13_C"], table["area_below_minus50_km2"] = tb, g["area_50"]
    if not rows:
        st.info(
            "No hay índices ni imágenes preparados para esta selección. Elige otra región o fecha disponible."
        )
        return

    fig = charts.series(rows, ctx.events, p.event)
    t = state.current_time()
    if t is not None:
        fig.add_vline(x=pd.Timestamp(t), line={"color": theme.colors().SELECTION, "width": 1})
    st.plotly_chart(fig, width="stretch", theme=None)
    st.caption(
        "Rojo continuo: la hora del evento elegido; punteado: los demás eventos del día. Línea "
        "azul: la hora seleccionada. Rayas rojas: valores de comparación de VGP y cizalladura 0–1 km. "
        "Para SRH no se dibuja un valor de comparación. Cumplir estos criterios no confirma un tornado."
    )
    st.caption(
        "Horas en tiempo universal coordinado (UTC). Las horas GOES sin descargar quedan como huecos. "
        "Aquí la temperatura de brillo se expresa en °C; en los mapas, en K (°C = K − 273,15)."
    )
    csv_data = pd.DataFrame(table)
    csv_data.index.name = "time_utc"
    st.download_button(
        "Descargar series (CSV)", csv_data.to_csv().encode(), icon=":material/download:",
        file_name=f"series_{ctx.day.date:%Y%m%d}_{p.lat:.2f}_{p.lon:.2f}.csv", mime="text/csv",
    )  # fmt: skip
