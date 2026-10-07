#!/usr/bin/env python3
"""Calcula índices de tiempo severo desde los recortes ERA5, con los signos del hemisferio sur.

Para cada columna de la grilla y cada hora arma un perfil vertical (superficie + niveles de presión
sobre el terreno), lo interpola cada 100 m y calcula cizalle, movimiento de Bunkers, helicidad y los
índices compuestos que el documento propone para Chile. Las fórmulas siguen a MetPy
(``bunkers_storm_motion``, ``storm_relative_helicity``) pero vectorizadas sobre la grilla, porque
MetPy solo trabaja con perfiles 1D.

Convenciones australes (ver docs/mesociclones_chile.md, secciones 2.5 y 5):

- La tormenta de referencia es la *left-mover* de Bunkers, la supercélula favorecida en el sur.
- La SRH se guarda con su signo físico: los casos tornádicos chilenos dan SRH **negativa**.
- El STP usa la rama *left-mover*, así que también es negativo; el umbral chileno es ≤ −0,3.

Simplificaciones: el CAPE es el de ERA5 (no el de capa mezclada), el STP no lleva el término de CIN
y el índice de Sherburn es SHERBS3 (cizalle 0–3 km), no SHERBE (capa efectiva).

Entrada y salida::

    data/recortes/<region>/era5_pl/era5_pl_AAAAMMDD.nc       (u, v, t, z por nivel)
    data/recortes/<region>/era5_sfc/era5_sfc_AAAAMMDD.nc     (10u, 10v, 2t, 2d, sp, cape)
    data/recortes/<region>/era5_indices/era5_idx_AAAAMMDD.nc (time, latitude, longitude)

Uso::

    uv run python scripts/procesa_era5.py --inicio 2019-05-30
    uv run python scripts/procesa_era5.py --inicio 2019-05-30 --fin 2019-05-31 --forzar
"""

import datetime as dt
import time

import numpy as np
import xarray as xr

import comun

PASO = 100.0  # m, resolución del perfil interpolado
TOPE = 6000.0  # m, altura máxima del perfil interpolado
DESVIO_BUNKERS = 7.5  # m/s, desviación de la tormenta respecto del viento medio 0–6 km
SUELO = 10.0  # m, altura asignada a los datos de superficie (viento a 10 m)

# Atributos de cada índice: descripción, unidad, umbral chileno (solo los que
# docs/mesociclones_chile.md da como calibrados para Chile), sentido del peligro ("<" si los valores
# más bajos son los peligrosos) y una referencia en texto para los que no tienen umbral.
ATRIBUTOS = {
    "cizalle_01": ("Cizalle 0–1 km (magnitud de la diferencia vectorial)", "m s-1", 12.0, ">", None),
    "cizalle_03": ("Cizalle 0–3 km", "m s-1", None, None, None),
    "cizalle_06": ("Cizalle 0–6 km", "m s-1", None, ">", "Sin criterio local de decisión"),
    "u_lm": ("Movimiento Bunkers left-mover, componente u", "m s-1", None, None, None),
    "v_lm": ("Movimiento Bunkers left-mover, componente v", "m s-1", None, None, None),
    "u_rm": ("Movimiento Bunkers right-mover, componente u", "m s-1", None, None, None),
    "v_rm": ("Movimiento Bunkers right-mover, componente v", "m s-1", None, None, None),
    "u_06": ("Viento medio 0–6 km, componente u", "m s-1", None, None, None),
    "v_06": ("Viento medio 0–6 km, componente v", "m s-1", None, None, None),
    "srh_01": ("Helicidad relativa a la tormenta 0–1 km (left-mover)", "m2 s-2", None, "<",
               "2019: −100 a −250"),
    "srh_03": ("Helicidad relativa a la tormenta 0–3 km (left-mover)", "m2 s-2", None, "<",
               "2019: −253 a −688"),
    "lcl": ("Altura del nivel de condensación por ascenso (Espy)", "m", None, "<",
            "2019: < 650–713"),
    "gamma_03": ("Gradiente térmico 0–3 km", "K km-1", None, None, None),
    "gamma_75": ("Gradiente térmico 700–500 hPa", "K km-1", None, None, None),
    "vgp_01": ("Parámetro de generación de vorticidad 0–1 km (VGP)", "m s-2", 0.1, ">", None),
    "stp_lm": ("Significant Tornado Parameter, rama left-mover (sin CIN)", "1", -0.3, "<", None),
    "sherbs3": ("SHERBS3 (Sherburn y Parker 2014, cizalle 0–3 km)", "1", None, ">",
                "SHERBE ≥ 1 corresponde a otra variante; no es un umbral de SHERBS3"),
    "altura_sfc": ("Altura del terreno estimada desde la presión de superficie", "m", None, None,
                   None),
}  # fmt: skip


def interpola(x: np.ndarray, y: np.ndarray, x0: np.ndarray | float) -> np.ndarray:
    """Interpola linealmente ``y`` en ``x0`` a lo largo del eje 0, con ``x`` creciente en ese eje.

    ``x`` e ``y`` tienen forma ``(L, ...)`` y ``x0`` la forma del resto (o es un escalar). Fuera del
    rango de ``x`` extrapola con el primer o último tramo.
    """
    x0 = np.broadcast_to(x0, x.shape[1:])
    k = np.clip((x <= x0).sum(axis=0), 1, x.shape[0] - 1)
    x1, x2 = np.take_along_axis(x, k[None] - 1, 0)[0], np.take_along_axis(x, k[None], 0)[0]
    y1, y2 = np.take_along_axis(y, k[None] - 1, 0)[0], np.take_along_axis(y, k[None], 0)[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(x2 > x1, (x0 - x1) / (x2 - x1), 0.0)
    return y1 + w * (y2 - y1)


def perfil(agl: np.ndarray, campo: np.ndarray, sfc: np.ndarray, alturas: np.ndarray) -> np.ndarray:
    """Valores de ``campo`` en ``alturas`` sobre el suelo, usando ``sfc`` como dato a 10 m.

    Los niveles bajo tierra (o por debajo de 10 m) se reemplazan por el valor de superficie a 10 m,
    así que el perfil arranca en el suelo y nunca usa datos extrapolados bajo los Andes.
    """
    arriba = agl > SUELO
    x = np.where(arriba, agl, SUELO)
    y = np.where(arriba, campo, sfc[None])
    return np.stack([interpola(x, y, h) for h in alturas])


def indices_hora(pl: xr.Dataset, sfc: xr.Dataset) -> dict[str, np.ndarray]:
    """Todos los índices de ``ATRIBUTOS`` para una hora (``pl`` y ``sfc`` sin dimensión de tiempo)."""
    pl = pl.sortby("level", ascending=False)  # de 1000 hPa hacia arriba: altura creciente
    niveles = pl["level"].values.astype(float)
    lnp = -np.log(niveles * 100.0)[:, None, None] * np.ones(pl["z"].shape)
    hgt = pl["z"].values / comun.G
    sp = sfc["sp"].values
    h_sfc = interpola(lnp, hgt, -np.log(sp))
    agl = hgt - h_sfc[None]

    alturas = np.arange(SUELO, TOPE + PASO / 2, PASO)
    alturas[1:] = np.round(alturas[1:] / PASO) * PASO  # 10, 100, 200, …, 6000 m
    u = perfil(agl, pl["u"].values, sfc["10u"].values, alturas)
    v = perfil(agl, pl["v"].values, sfc["10v"].values, alturas)
    t = perfil(agl, pl["t"].values, sfc["2t"].values, alturas)

    def nivel(h: float) -> int:
        """Índice del perfil interpolado más cercano a la altura ``h`` en metros."""
        return int(np.argmin(np.abs(alturas - h)))

    def cizalle(h: float) -> np.ndarray:
        """Magnitud de la diferencia vectorial del viento entre 10 m y ``h`` metros."""
        k = nivel(h)
        return np.hypot(u[k] - u[0], v[k] - v[0])

    def media(h0: float, h1: float) -> tuple[np.ndarray, np.ndarray]:
        """Viento medio (no ponderado por presión) entre ``h0`` y ``h1`` metros."""
        s = slice(nivel(h0), nivel(h1) + 1)
        return u[s].mean(axis=0), v[s].mean(axis=0)

    # Bunkers (2000): viento medio 0–6 km ± 7,5 m/s perpendicular al cizalle (0–0,5 → 5,5–6 km).
    um, vm = media(SUELO, 6000)
    ub, vb = media(SUELO, 500)
    ut, vt = media(5500, 6000)
    su, sv = ut - ub, vt - vb
    mod = np.maximum(np.hypot(su, sv), 1e-6)
    u_rm, v_rm = um + DESVIO_BUNKERS * sv / mod, vm - DESVIO_BUNKERS * su / mod
    u_lm, v_lm = um - DESVIO_BUNKERS * sv / mod, vm + DESVIO_BUNKERS * su / mod

    def srh(h: float) -> np.ndarray:
        """Helicidad relativa a la left-mover entre el suelo y ``h`` metros (fórmula de MetPy)."""
        k = nivel(h) + 1
        ru, rv = u[:k] - u_lm, v[:k] - v_lm
        return (ru[1:] * rv[:-1] - ru[:-1] * rv[1:]).sum(axis=0)

    cape = np.maximum(sfc["cape"].values, 0.0)
    c01, c03, c06 = cizalle(1000), cizalle(3000), cizalle(6000)
    s01 = srh(1000)
    lcl = np.maximum(125.0 * (sfc["2t"].values - sfc["2d"].values), 0.0)
    g03 = (t[0] - t[nivel(3000)]) / ((alturas[nivel(3000)] - SUELO) / 1000)
    i7, i5 = int(np.argmin(np.abs(niveles - 700))), int(np.argmin(np.abs(niveles - 500)))
    g75 = (pl["t"].values[i7] - pl["t"].values[i5]) / ((hgt[i5] - hgt[i7]) / 1000)

    # STP (Thompson et al. 2003/2012) sin CIN; la SRH left-mover lo vuelve negativo en el sur.
    t_lcl = np.clip((2000.0 - lcl) / 1000.0, 0.0, 1.0)
    t_cizalle = np.where(c06 < 12.5, 0.0, np.minimum(c06, 30.0) / 20.0)
    stp = (cape / 1500.0) * t_lcl * (s01 / 150.0) * t_cizalle

    return {
        "cizalle_01": c01,
        "cizalle_03": c03,
        "cizalle_06": c06,
        "u_lm": u_lm,
        "v_lm": v_lm,
        "u_rm": u_rm,
        "v_rm": v_rm,
        "u_06": um,
        "v_06": vm,
        "srh_01": s01,
        "srh_03": srh(3000),
        "lcl": lcl,
        "gamma_03": g03,
        "gamma_75": g75,
        "vgp_01": np.sqrt(cape) * c01 / 1000.0,  # √CAPE × (ΔV / Δz) en m/s²
        "stp_lm": stp,
        # Sherburn y Parker (2014): 26 m/s con el cizalle 0–3 km; 27 m/s es el de SHERBE (capa efectiva).
        "sherbs3": (c03 / 26.0) * (g03 / 5.2) * (g75 / 5.6),
        "altura_sfc": h_sfc,
    }


def procesa_dia(pl: xr.Dataset, sfc: xr.Dataset, reg: comun.Region) -> xr.Dataset:
    """Calcula los índices de cada hora común a ``pl`` y ``sfc`` y los junta en un Dataset."""
    tiempos = np.intersect1d(pl["time"].values, sfc["time"].values)
    horas = [indices_hora(pl.sel(time=t).load(), sfc.sel(time=t).load()) for t in tiempos]
    dims = ("time", "latitude", "longitude")
    datos = {}
    claves = ("long_name", "units", "umbral_chile", "umbral_sentido", "referencia")
    for v, valores in ATRIBUTOS.items():
        attrs = {k: x for k, x in zip(claves, valores, strict=True) if x is not None}
        datos[v] = (dims, np.stack([h[v] for h in horas]).astype("f4"), attrs)
    return xr.Dataset(
        datos,
        coords={"time": tiempos, "latitude": pl["latitude"], "longitude": pl["longitude"]},
        attrs={
            "fuente": "índices calculados por scripts/procesa_era5.py desde ERA5 (NSF NCAR)",
            "region": f"{reg.nombre}: {reg.norte}..{reg.sur} lat, {reg.oeste}..{reg.este} lon",
            "nota": "hemisferio sur: tormenta left-mover, SRH y STP negativos en casos tornádicos",
            "creado": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
    )


def main() -> None:
    """Punto de entrada: calcula los índices de cada día que tenga ERA5 de presión y de superficie."""
    p = comun.parser(__doc__, "los días")
    a = p.parse_args()
    reg = comun.region_de(a)
    base = comun.RECORTES / reg.nombre

    for dia in comun.dias(a):
        f_pl = base / "era5_pl" / f"era5_pl_{dia:%Y%m%d}.nc"
        f_sfc = base / "era5_sfc" / f"era5_sfc_{dia:%Y%m%d}.nc"
        salida = comun.carpeta(reg.nombre, "era5_indices") / f"era5_idx_{dia:%Y%m%d}.nc"
        if salida.exists() and not a.forzar:
            print(f"{salida.name}: ya existe", flush=True)
            continue
        if not (f_pl.exists() and f_sfc.exists()):
            print(f"{dia}: falta {f_pl.name} o {f_sfc.name} (corre descarga_era5.py)", flush=True)
            continue
        t0 = time.time()
        with (
            xr.open_dataset(f_pl, engine="h5netcdf") as pl,
            xr.open_dataset(f_sfc, engine="h5netcdf") as sfc,
        ):
            faltan = {"u", "v", "t", "z"} - set(pl.data_vars)
            faltan |= {"10u", "10v", "2t", "2d", "sp", "cape"} - set(sfc.data_vars)
            if faltan:
                print(f"{dia}: faltan variables {sorted(faltan)}; descárgalas antes", flush=True)
                continue
            out = procesa_dia(pl, sfc, reg)
        comun.escribe(out, salida)
        print(f"{salida.name}: {out.sizes['time']} horas en {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
