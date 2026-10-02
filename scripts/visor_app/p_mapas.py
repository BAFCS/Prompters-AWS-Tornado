"""Página «Mapas»: el entorno ERA5 (crudo o índices australes) y la tormenta en GOES, lado a lado."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import xarray as xr

from visor_app import componentes, datos, estado, graficos, tema, textos

DIVERGENTES = {"u", "v", "w", "vo", "d", "10u", "10v", "100u", "100v", "srh_01", "srh_03", "stp_lm"}
OCULTOS = {"u_lm", "v_lm", "u_rm", "v_rm", "u_06", "v_06", "altura_sfc"}
RANGOS = {  # rangos fijos para comparar horas y días; el resto usa percentiles 1–99
    "vgp_01": (0.0, 0.3), "srh_01": (-300.0, 300.0), "srh_03": (-600.0, 600.0),
    "cizalle_01": (0.0, 25.0), "cizalle_03": (0.0, 35.0), "cizalle_06": (0.0, 45.0),
    "stp_lm": (-1.5, 1.5), "sherbs3": (0.0, 2.0), "lcl": (0.0, 2500.0),
}  # fmt: skip
RANGO_GOES = {
    **dict.fromkeys(range(1, 7), (0.0, 1.0)),
    7: (200.0, 320.0), 8: (200.0, 250.0), 9: (205.0, 265.0), 10: (210.0, 275.0),
    **dict.fromkeys(range(11, 17), (190.0, 300.0)),
}  # fmt: skip
DERIVADOS = {
    "dT": "Enfriamiento del tope en 10 min (ΔC13)",
    "C08-C13": "C08 − C13 (tope en la tropopausa)",
}
PASO_ANIMACION = 3  # se dibuja uno de cada 3 píxeles GOES al animar


def _rango(z: np.ndarray, centro: bool) -> tuple[float, float]:
    """Rango de color entre los percentiles 1 y 99 de ``z`` (simétrico si ``centro``)."""
    lo, hi = np.nanpercentile(z, [1, 99])
    if centro:
        m = float(max(abs(lo), abs(hi)))
        return -m, m
    return float(lo), float(hi)


def _opciones_era5(d: datos.Dia) -> dict[str, str]:
    """Campos ERA5 elegibles: clave → etiqueta. Índices primero, luego superficie y presión."""
    out = {}
    for prefijo, ruta, grupo in (("", d.idx, "Índice"), ("sfc:", d.sfc, "Superficie"),
                                 ("pl:", d.pl, "Presión")):  # fmt: skip
        if ruta is None:
            continue
        ds = datos.abre(ruta)
        for v in ds.data_vars:
            if v in OCULTOS:
                continue
            a = ds[v].attrs
            out[f"{prefijo}{v}"] = (
                f"{grupo} · {a.get('long_name', v)} [{componentes.unidad(a.get('units', ''))}]"
            )
    return out


def _al_clic(clave: str) -> None:
    """Callback del mapa ERA5: el punto clicado pasa a ser el punto elegido."""
    puntos = st.session_state[clave].selection.points
    if puntos:
        la, lo = float(puntos[0]["y"]), float(puntos[0]["x"])
        estado.elige_punto(estado.Punto(la, lo, f"{la:.2f}°, {lo:.2f}°"))


def _vectores(fig: go.Figure, ds: xr.Dataset, t: pd.Timestamp, enc: graficos.Encuadre) -> None:
    """Agrega flechas de viento en 850 hPa (una de cada tres celdas) sobre ``fig``."""
    h = ds.sel(time=t, method="nearest").sel(level=850, method="nearest")
    h = h.sel(latitude=slice(enc.norte, enc.sur), longitude=slice(enc.oeste, enc.este))
    u, v = h["u"].values[::3, ::3], h["v"].values[::3, ::3]
    LA, LO = np.meshgrid(h["latitude"].values[::3], h["longitude"].values[::3], indexing="ij")
    k = 0.018  # grados por m/s
    xs, ys = [], []
    for x0, y0, du, dv in zip(LO.ravel(), LA.ravel(), u.ravel(), v.ravel(), strict=True):
        x1, y1 = x0 + du * k, y0 + dv * k
        ang = np.arctan2(dv, du)
        ala = 0.25 * np.hypot(du, dv) * k
        xs += [x0, x1, x1 - ala * np.cos(ang - 0.45), None, x1, x1 - ala * np.cos(ang + 0.45), None]
        ys += [y0, y1, y1 - ala * np.sin(ang - 0.45), None, y1, y1 - ala * np.sin(ang + 0.45), None]
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="lines", hoverinfo="skip", name="viento 850 hPa",
            line={"color": tema.INK_2, "width": 1},
        )
    )  # fmt: skip


def _era5(ctx: estado.Contexto, t: pd.Timestamp, enc: graficos.Encuadre) -> str | None:
    """Columna ERA5. Devuelve la clave del campo dibujado (para la ayuda) o ``None``."""
    opciones = _opciones_era5(ctx.dia)
    if not opciones:
        st.info("Este día no tiene ERA5. Corre `descarga_era5.py` (y `procesa_era5.py`).")
        return None
    claves = list(opciones)
    estado.recuerda("era5_var")
    if st.session_state.get("era5_var") not in claves:
        st.session_state["era5_var"] = "vgp_01" if "vgp_01" in claves else claves[0]
    clave = st.selectbox(
        "Entorno (ERA5)", claves, key="era5_var", format_func=lambda k: opciones[k]
    )
    estado.guarda("era5_var")

    fuente, _, v = clave.rpartition(":")
    ruta = {"": ctx.dia.idx, "sfc": ctx.dia.sfc, "pl": ctx.dia.pl}[fuente]
    assert ruta is not None
    ds = datos.abre(ruta)
    da = ds[v].sel(time=t, method="nearest")
    hora = datos.instante(da["time"])
    nombre_v = componentes.CORTOS.get(v) or str(ds[v].attrs.get("long_name", v))
    titulo = f"ERA5 · {nombre_v} · {hora:%H:%M} UTC"
    if "level" in da.dims:
        niveles = sorted(ds["level"].values.tolist(), reverse=True)
        estado.recuerda("nivel")
        if st.session_state.get("nivel") not in niveles:
            st.session_state["nivel"] = 850 if 850 in niveles else niveles[0]
        nivel = st.select_slider("Nivel (hPa)", options=niveles, key="nivel")
        estado.guarda("nivel")
        da = da.sel(level=nivel)
        titulo += f" · {nivel:g} hPa"
    centro = v in DIVERGENTES
    z = da.values
    umbral = ds[v].attrs.get("umbral_chile")
    fig = graficos.mapa(
        z, ds["latitude"].values, ds["longitude"].values, enc, datos.costa(ctx.reg),
        titulo=titulo, unidad=componentes.unidad(ds[v].attrs.get("units", "")),
        escala=tema.DIVERGENTE if centro else tema.SECUENCIAL,
        rango=RANGOS.get(v) or _rango(z, centro), centro=centro, eventos=ctx.eventos,
        punto=estado.punto(), umbral=None if umbral is None else float(umbral), clic=True,
    )  # fmt: skip
    if st.session_state.get("viento") and ctx.dia.pl is not None:
        _vectores(fig, datos.abre(ctx.dia.pl), t, enc)
    st.plotly_chart(
        fig, width="stretch", theme=None, key="mapa_era5", on_select=lambda: _al_clic("mapa_era5"),
        selection_mode="points",
    )  # fmt: skip
    notas = ["Clic en el mapa para elegir un punto (sondeo y series)."]
    if umbral is not None:
        notas.append(
            f"Línea roja: umbral chileno ({ds[v].attrs.get('umbral_sentido', '')} {str(umbral).replace('.', ',')})."
        )
    if fuente == "pl":
        notas.append("Sobre los Andes los niveles bajos están bajo tierra (valores extrapolados).")
    st.caption(" ".join(notas))
    return v


def _goes_figura(
    ctx: estado.Contexto, prod: str, t: pd.Timestamp, enc: graficos.Encuadre, sub: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, list, tuple[float, float], bool, str] | None:
    """Datos del producto GOES ``prod`` en la imagen más cercana a ``t``, submuestreados ``sub``.

    Devuelve (z, lat, lon, título, escala, rango, centrado, unidad) o ``None`` si falta una imagen.
    """
    img = datos.imagen_en(ctx.dia, np.datetime64(t))
    if img is None:
        return None
    ruta, ti = img
    ds = datos.abre(ruta)
    lat, lon = ds["latitude"].values[::sub], ds["longitude"].values[::sub]
    hora = pd.Timestamp(ti)
    if prod == "dT":
        prev = datos.anterior(ctx.dia, ti)
        if prev is None:
            return None
        r0, t0 = prev
        z = ds["C13"].sel(time=ti).values - datos.abre(r0)["C13"].sel(time=t0).values
        minutos = (hora - pd.Timestamp(t0)).total_seconds() / 60
        titulo = f"GOES · ΔC13 en {minutos:.0f} min · {hora:%H:%M} UTC"
        return z[::sub, ::sub], lat, lon, titulo, tema.DIVERGENTE, (-15.0, 15.0), True, "K"
    if prod == "C08-C13":
        z = ds["C08"].sel(time=ti).values - ds["C13"].sel(time=ti).values
        escala = [[0.0, tema.SURFACE], [0.7, tema.COLD], [0.89, tema.INK], [1.0, tema.WARM]]
        titulo = f"GOES · C08 − C13 · {hora:%H:%M} UTC"
        return z[::sub, ::sub], lat, lon, titulo, escala, (-40.0, 5.0), False, "K"
    n = int(prod[1:])
    z = ds[prod].sel(time=ti).values[::sub, ::sub]
    um = str(ds[prod].attrs.get("longitud_onda_um", "")).replace(".", ",")
    titulo = f"GOES · {prod} {um} µm · {hora:%H:%M} UTC"
    escala = tema.VISIBLE if n <= 6 else tema.IR
    return (
        z,
        lat,
        lon,
        titulo,
        escala,
        RANGO_GOES[n],
        False,
        componentes.unidad(ds[prod].attrs.get("units", "")),
    )


def _animacion(ctx: estado.Contexto, prod: str, t: pd.Timestamp, enc: graficos.Encuadre) -> None:
    """Loop de las imágenes GOES en ±1 hora alrededor de ``t``, con botón de reproducción."""
    cerca = [
        ti for ti, _ in datos.imagenes(ctx.dia) if abs(pd.Timestamp(ti) - t) <= pd.Timedelta("1h")
    ]
    cuadros = [
        c for ti in cerca if (c := _goes_figura(ctx, prod, pd.Timestamp(ti), enc, PASO_ANIMACION))
    ]
    if len(cuadros) < 2:
        st.info("No hay suficientes imágenes alrededor de esta hora para animar.")
        return
    z, lat, lon, titulo, escala, rango, centro, unidad = cuadros[0]
    fig = graficos.mapa(
        z, lat, lon, enc, datos.costa(ctx.reg), titulo=titulo, unidad=unidad, escala=escala,
        rango=rango, centro=centro, eventos=ctx.eventos, punto=estado.punto(),
    )  # fmt: skip
    fig.frames = [
        go.Frame(
            data=[go.Heatmap(z=c[0])], traces=[0], name=str(i), layout={"title": {"text": c[3]}}
        )
        for i, c in enumerate(cuadros)
    ]
    boton = {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True,
             "transition": {"duration": 0}}  # fmt: skip
    fig.update_layout(
        updatemenus=[{
            "type": "buttons", "direction": "left", "x": 0, "y": -0.04, "xanchor": "left",
            "yanchor": "top", "showactive": False, "bgcolor": tema.SURFACE_2,
            "bordercolor": tema.LINE, "font": {"family": tema.SANS, "size": 12},
            "buttons": [
                {"label": "Reproducir", "method": "animate", "args": [None, boton]},
                {"label": "Pausa", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0}, "mode": "immediate"}]},
            ],
        }],
        sliders=[{
            "x": 0.32, "len": 0.68, "y": -0.02, "currentvalue": {"visible": False},
            "bordercolor": tema.LINE, "tickcolor": tema.LINE, "font": {"family": tema.MONO, "size": 10},
            "steps": [{"label": pd.Timestamp(ti).strftime("%H:%M"), "method": "animate",
                       "args": [[str(i)], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}]}
                      for i, ti in enumerate(cerca[: len(cuadros)])],
        }],
        margin={"b": 70},
    )  # fmt: skip
    st.plotly_chart(fig, width="stretch", theme=None, key="mapa_goes_anim")
    st.caption(
        f"{len(cuadros)} imágenes cada 10 min, un píxel de cada {PASO_ANIMACION} para que fluya."
    )


def _goes(ctx: estado.Contexto, t: pd.Timestamp, enc: graficos.Encuadre) -> str | None:
    """Columna GOES. Devuelve la clave del producto dibujado (para la ayuda) o ``None``."""
    if not ctx.dia.goes:
        st.info("Este día no tiene GOES. Corre `descarga_goes.py` y `procesa_goes.py`.")
        return None
    bandas = [str(b) for b in datos.abre(ctx.dia.goes[0]).data_vars]
    productos = [*bandas, *[k for k in DERIVADOS if {"C13", "C08"} <= set(bandas)]]
    estado.recuerda("goes_prod")
    if st.session_state.get("goes_prod") not in productos:
        st.session_state["goes_prod"] = "C13" if "C13" in productos else productos[0]
    ds0 = datos.abre(ctx.dia.goes[0])
    prod = st.selectbox(
        "Tormenta (GOES)", productos, key="goes_prod",
        format_func=lambda x: DERIVADOS.get(x) or f"{x} · {str(ds0[x].attrs.get('longitud_onda_um', '')).replace('.', ',')} µm",
    )  # fmt: skip
    estado.guarda("goes_prod")
    if st.session_state.get("animar"):
        _animacion(ctx, prod, t, enc)
        return prod
    sub = int(st.session_state.get("sub", 2))
    datos_fig = _goes_figura(ctx, prod, t, enc, sub)
    if datos_fig is None:
        st.info("No hay imagen anterior para calcular la tendencia a esta hora.")
        return prod
    z, lat, lon, titulo, escala, rango, centro, unidad = datos_fig
    fig = graficos.mapa(
        z, lat, lon, enc, datos.costa(ctx.reg), titulo=titulo, unidad=unidad, escala=escala,
        rango=rango, centro=centro, eventos=ctx.eventos, punto=estado.punto(),
    )  # fmt: skip
    st.plotly_chart(fig, width="stretch", theme=None, key="mapa_goes")
    st.caption(
        "Hora de inicio del barrido; sin corrección de paralaje (topes desplazados 10–20 km "
        "hacia el sur-suroeste)."
    )
    return prod


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    t = estado.t_actual()
    st.title("Mapas")
    if t is None:
        st.info("Este día no tiene datos con hora.")
        return
    t = pd.Timestamp(t)

    for clave, defecto in (("encuadre", "Zona de eventos"), ("viento", False), ("sub", 2),
                           ("animar", False)):  # fmt: skip
        estado.recuerda(clave)
        st.session_state.setdefault(clave, defecto)
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1.3], vertical_alignment="bottom")
    vista = c1.segmented_control("Encuadre", ["Zona de eventos", "Región completa"], key="encuadre")
    c2.toggle("Viento 850 hPa", key="viento", disabled=ctx.dia.pl is None,
              help="Flechas del viento en 850 hPa sobre el mapa ERA5 (requiere niveles de presión).")  # fmt: skip
    c3.toggle("Animar GOES ±1 h", key="animar", disabled=not ctx.dia.goes,
              help="Loop de las imágenes de una hora antes a una hora después de la regla.")  # fmt: skip
    c4.select_slider("Detalle GOES", options=[1, 2, 3, 4], key="sub",
                     format_func=lambda s: {1: "máximo", 2: "alto", 3: "medio", 4: "bajo"}[s])  # fmt: skip
    for clave in ("encuadre", "viento", "sub", "animar"):
        estado.guarda(clave)
    if vista == "Región completa" or ctx.eventos.empty:
        enc = graficos.Encuadre(ctx.reg.norte, ctx.reg.sur, ctx.reg.oeste, ctx.reg.este)
    else:
        enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg)

    izq, der = st.columns(2, gap="medium")
    with izq:
        v = _era5(ctx, t, enc)
    with der:
        g = _goes(ctx, t, enc)

    ayudas = [textos.AYUDA[k] for k in (v, g) if k in textos.AYUDA]
    if ayudas:
        with st.expander("Qué estás viendo", expanded=estado.paso_actual() is not None):
            for a in ayudas:
                st.markdown(a)
            st.caption(textos.NOTA_AUSTRAL)
