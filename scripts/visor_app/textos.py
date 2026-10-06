"""Textos del visor: ayuda en contexto por variable, contexto de cada caso y el recorrido guiado.

Todo sale de ``docs/mesociclones_chile.md``; si se corrige allá, hay que corregirlo aquí.
"""

import datetime as dt
from dataclasses import dataclass, field

# --- Ayuda en contexto: qué mide, y qué valor importa en Chile -----------------------------------
AYUDA = {
    "vgp_01": (
        "**VGP₀₋₁ = √CAPE × cizalle 0–1 km.** Mide cuánta vorticidad horizontal de niveles bajos "
        "puede inclinar la corriente ascendente. Es el mejor discriminante conocido para Chile: los "
        "cinco días tornádicos analizados (2008–2019) superan **0,1 m/s²** y Los Ángeles 2019 supera "
        "0,2 (Vicencio et al. 2021)."
    ),
    "srh_01": (
        "**Helicidad relativa a la tormenta 0–1 km**, respecto de la supercélula *left-mover* de "
        "Bunkers. Mide la vorticidad alineada con el flujo que entra a la tormenta. **En el "
        "hemisferio sur los casos tornádicos dan SRH negativa**: en 2019 estuvo entre −100 y "
        "−250 m²/s², con parches de −600."
    ),
    "srh_03": (
        "**Helicidad 0–3 km** (*left-mover*). Más ligada a la organización de la supercélula que al "
        "tornado. En 2019: −253 a −688 m²/s². Negativa = favorable en el sur."
    ),
    "cizalle_01": (
        "**Cizalle 0–1 km**: diferencia vectorial del viento entre 10 m y 1 km. En Chile **es el "
        "cizalle que discrimina**: supera 12 m/s en los días tornádicos. Sobre el océano suele ser de "
        "5–10 m/s y tierra adentro de 10–20 m/s, por eso la franja costera es crítica."
    ),
    "cizalle_03": "**Cizalle 0–3 km**: diferencia vectorial del viento entre 10 m y 3 km.",
    "cizalle_06": (
        "**Cizalle 0–6 km**: el discriminante clásico entre tormentas ordinarias y organizadas. "
        "En Chile **no discrimina**: en invierno casi siempre supera 18 m/s."
    ),
    "stp_lm": (
        "**STP, rama left-mover.** El índice tornádico más usado en EE.UU., con la SRH austral: "
        "aquí es negativo, y el umbral chileno es **≤ −0,3** (percentil 99 de 1959–2021, Marín et al. "
        "2024), no +1. Versión aproximada: CAPE de ERA5 y sin término de CIN."
    ),
    "sherbs3": (
        "**SHERBS3** (Sherburn y Parker 2014): índice para entornos de mucho cizalle y poco CAPE "
        "(HSLC), el régimen chileno. Combina el cizalle 0–3 km con los gradientes térmicos 0–3 km y "
        "700–500 hPa. El umbral chileno (≥ 1) está definido para SHERBE, su variante con capa "
        "efectiva: tómalo como referencia."
    ),
    "lcl": (
        "**Altura del LCL**, la base de la nube, estimada con la fórmula de Espy (125 m por grado de "
        "diferencia entre temperatura y punto de rocío). Un LCL bajo es de los discriminantes "
        "tornádicos más robustos; en 2019 estuvo por debajo de 650–713 m."
    ),
    "gamma_03": "**Gradiente térmico 0–3 km**: cuánto se enfría el aire por km de ascenso.",
    "gamma_75": "**Gradiente térmico 700–500 hPa**: inestabilidad de niveles medios.",
    "cape": (
        "**CAPE** de ERA5: energía disponible para la convección. En Chile es bajo para estándares "
        "norteamericanos (200–500 J/kg en 2019), pero el promedio de fines de mayo en el Biobío es "
        "de 15–45 J/kg: los días tornádicos son los días en que aparece algo."
    ),
    "C13": (
        "**GOES banda 13 (10,3 µm)**: infrarrojo de ventana, la temperatura de brillo del tope. Más "
        "frío = más alto = ascenso más potente. Las imágenes no tienen corrección de paralaje: los "
        "topes aparecen desplazados 10–20 km hacia el sur-suroeste."
    ),
    "dT": (
        "**Enfriamiento del tope en 10 minutos** (C13 ahora menos C13 en la imagen anterior). "
        "Valores negativos: el tope sube. Enfriamientos más rápidos que −4 K en 15 min indican "
        "convección en rápido desarrollo."
    ),
    "C08-C13": (
        "**C08 − C13 (vapor de agua menos ventana)**. Cerca de 0 o positivo: el tope alcanza o "
        "supera la tropopausa (topes penetrantes). Muy negativo: nube baja o aire seco en altura."
    ),
    "airmass": (
        "**RGB Airmass**: rojo = C08 − C10, verde = C12 − C13, azul = C08 invertido. Solo usa "
        "infrarrojo, así que sirve de día y de noche. Rojizo: aire seco bajado de la estratósfera "
        "(intrusión seca, cerca del chorro). Verde oliva: masa de aire cálida y húmeda. Azul y "
        "violeta: aire frío polar. Blanco: topes altos y fríos. Sirve para ubicar la nube coma y el "
        "borde de la intrusión seca, donde suele organizarse la convección."
    ),
}

NOTA_AUSTRAL = (
    "En el hemisferio sur la supercélula favorecida es la *left-mover* y la SRH tornádica es "
    "**negativa**. MetPy o SHARPpy usados tal cual devuelven índices con el signo del norte."
)


# --- Contexto de cada caso -----------------------------------------------------------------------
@dataclass(frozen=True)
class Caso:
    """Título y contexto de un día de la base de datos."""

    titulo: str
    lede: str
    contexto: tuple[str, ...] = ()


CASOS = {
    dt.date(2019, 5, 30): Caso(
        "30 de mayo de 2019 · Biobío",
        "El primer día del brote: cinco tornados reportados entre Ñuble y la Araucanía en la "
        "tarde, entre ellos el EF2 que cruzó Los Ángeles a las 21:57 UTC.",
        (
            "Una baja ocluida de ~995 hPa, casi inmóvil frente a la costa desde el 28 de mayo, "
            "sostenía advección cálida del noroeste y un jet de bajo nivel de 20–25 m/s en 850 hPa.",
            "El régimen fue de mucho cizalle y poco CAPE (HSLC): CAPE de 200–1.000 J/kg, cizalle "
            "0–1 km de 12–20 m/s, SRH 0–1 km de −100 a −250 m²/s² y LCL muy bajo.",
            "Chile no tenía radar meteorológico: que fueron supercélulas se reconstruyó después con "
            "GOES-16 cada 10 minutos, rayos, aviones y simulaciones WRF (Vicencio et al. 2021).",
        ),
    ),
    dt.date(2019, 5, 31): Caso(
        "31 de mayo de 2019 · Concepción",
        "El segundo día: el tornado que nació como tromba marina y entró a Talcahuano a las "
        "18:00 UTC, con 17 km de trayecto, y otro en Chanco.",
        (
            "Una nube coma con una mesobaja disparó una banda de celdas sobre el océano, separadas "
            "unos 50 km, que fueron entrando a tierra una tras otra.",
            "El tornado de Talcahuano pasó a 400–450 m de dos estaciones del aeropuerto Carriel "
            "Sur, que registraron una caída de presión de 2,1 hPa en 6 minutos.",
        ),
    ),
}


def caso(dia: dt.date, n_eventos: int) -> Caso:
    """El contexto de ``dia``; si no está escrito, uno genérico con el número de eventos."""
    if dia in CASOS:
        return CASOS[dia]
    return Caso(
        f"{dia:%d-%m-%Y}",
        f"{n_eventos} eventos del catálogo este día."
        if n_eventos
        else "Sin eventos en el catálogo.",
    )


# --- Recorrido guiado ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Paso:
    """Un paso del recorrido: a qué página, hora, capa y punto lleva el visor, y qué contar."""

    pagina: str  # "caso", "mapas", "sondeo" o "series"
    hora: str  # "HH:MM" UTC; se usa la imagen o la hora ERA5 más cercana
    texto: str
    evento: str | None = None  # parte del nombre del lugar en el catálogo
    paneles: tuple[str, ...] = ()  # claves de productos.catalogo para la grilla de Mapas
    extra: dict[str, str] = field(default_factory=dict)


RECORRIDOS = {
    dt.date(2019, 5, 30): (
        Paso(
            "caso", "18:30",
            "Cinco tornados en cuatro horas, todos en la ventana del calentamiento diurno. La "
            "bitácora los ordena por hora; cada fila lleva el visor a ese momento y lugar.",
        ),
        Paso(
            "mapas", "18:30",
            "El cizalle 0–1 km es el que discrimina en Chile. Busca la franja sobre 12 m/s (línea "
            "roja) pegada a la costa y al pie de monte, donde ocurrirán los tornados.",
            evento="Ángeles", paneles=("idx:cizalle_01", "goes:C13"),
        ),
        Paso(
            "mapas", "19:00",
            "Con algo de CAPE, el cizalle se vuelve VGP: donde supera 0,1 m/s² hay vorticidad lista "
            "para ser inclinada. A esta hora se reporta el primer tornado, en Quilelto.",
            evento="Quilelto", paneles=("idx:vgp_01", "goes:C13"),
        ),
        Paso(
            "sondeo", "20:00",
            "El perfil sobre Coihueco: poca energía, base de nube baja y una hodógrafa larga. La "
            "tormenta de referencia es la left-mover; la helicidad respecto de ella sale negativa.",
            evento="Coihueco",
        ),
        Paso(
            "mapas", "21:50",
            "Siete minutos antes del EF2 de Los Ángeles. A la derecha, el enfriamiento del tope en "
            "10 minutos: los azules marcan topes que todavía suben.",
            evento="Ángeles", paneles=("idx:srh_01", "goes:dT"),
        ),
        Paso(
            "series", "21:50",
            "La evolución alrededor de Los Ángeles: entorno ERA5 hora a hora y la temperatura del "
            "tope cada 10 minutos, con la hora del tornado marcada. ¿Qué cambió antes?",
            evento="Ángeles",
        ),
    ),
}  # fmt: skip
