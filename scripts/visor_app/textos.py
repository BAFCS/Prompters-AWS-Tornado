"""Textos del visor: notas australes, contexto de cada caso y el recorrido guiado.

La ayuda por variable vive en ``variables.py``.

Todo sale de ``docs/mesociclones_chile.md``; si se corrige allá, hay que corregirlo aquí.
"""

import datetime as dt
from dataclasses import dataclass

NOTA_STP = (
    "El STP mostrado es una aproximación: usa CAPE de ERA5 y omite la inhibición convectiva "
    "(CIN), la barrera energética para iniciar el ascenso. La aplicación del criterio citado "
    "a esta variante requiere validación."
)

NOTA_AUSTRAL = (
    "El proyecto utiliza la rama *left-mover*, una estimación de movimiento hacia la "
    "izquierda del viento medio. En los casos australes descritos, la SRH de esta rama "
    "es negativa. Al calcular los índices, comprueba la rama elegida y la convención "
    "de signos; no basta con invertir todos los resultados."
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
        "El primer día del episodio: cinco tornados reportados entre Ñuble y la Araucanía en la "
        "tarde, entre ellos el EF2 que cruzó Los Ángeles a las 21:57 UTC.",
        (
            "Un sistema de baja presión permanecía casi inmóvil frente a la costa desde "
            "el 28 de mayo. El viento del noroeste transportaba aire cálido y presentaba "
            "una franja de velocidades elevadas en niveles bajos.",
            "Los datos combinan fuerte cambio del viento con la altura y energía disponible "
            "para el ascenso relativamente baja. Este régimen se denomina HSLC, por sus "
            "siglas en inglés. El estudio citado reconstruyó las tormentas mediante imágenes "
            "GOES-16, observaciones de rayos y aviones, y simulaciones atmosféricas "
            "(Vicencio et al. 2021).",
        ),
    ),
    dt.date(2019, 5, 31): Caso(
        "31 de mayo de 2019 · Concepción",
        "El segundo día: el tornado que nació como tromba marina y entró a Talcahuano a las "
        "18:00 UTC, con 17 km de trayecto, y otro en Chanco.",
        (
            "Una estructura nubosa con forma de coma y un centro de baja presión de menor "
            "escala acompañaron una banda de tormentas sobre el océano. Las tormentas, "
            "separadas unos 50 km, entraron a tierra de manera sucesiva.",
            "El tornado de Talcahuano pasó a 400–450 m de dos estaciones del aeropuerto Carriel "
            "Sur, que registraron una caída de presión de 2,1 hPa en 6 minutos.",
        ),
    ),
}

DETALLES_CASOS = {
    dt.date(2019, 5, 30): (
        "El documento describe una baja ocluida de aproximadamente 995 hPa y viento de "
        "20–25 m/s en el nivel de presión de 850 hPa. Las presiones en hPa permiten "
        "referirse a distintos niveles atmosféricos. Una baja ocluida es un sistema de "
        "baja presión cuyo frente frío ha alcanzado al cálido.",
        "Se citan cizalle 0–1 km de 12–20 m/s, SRH 0–1 km de −100 a −250 m²/s² y "
        "una altura de condensación baja. El rango de CAPE de 200–1.000 J/kg aparece "
        "en el contexto del caso, mientras que otra referencia del documento presenta "
        "200–500 J/kg. Falta aclarar la fuente, el cálculo y el ámbito de ambos rangos.",
        "El estudio utilizó simulaciones con el modelo atmosférico WRF. El alcance de "
        "la afirmación sobre la ausencia de radar meteorológico y la identificación "
        "de supercélulas requiere revisión de la fuente.",
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


RECORRIDOS = {
    dt.date(2019, 5, 30): (
        Paso(
            "caso", "18:30",
            "El catálogo reúne cinco tornados reportados para este día. Selecciona una fila "
            "en la tabla para situar el visor en la hora y el lugar del evento. Este "
            "recorrido explora un caso histórico; no demuestra una capacidad predictiva.",
        ),
        Paso(
            "mapas", "18:30",
            "Compara la franja con cizalle 0–1 km superior a 12 m/s con las ubicaciones "
            "reportadas. La línea roja marca ese valor de referencia. Revisa la hora "
            "indicada en cada panel antes de comparar las dos fuentes.",
            evento="Ángeles", paneles=("idx:cizalle_01", "goes:C13"),
        ),
        Paso(
            "mapas", "19:00",
            "VGP combina CAPE con el cambio del viento por unidad de altura. Localiza "
            "las zonas superiores a 0,1 m/s² y compáralas con el primer evento reportado, "
            "en Quilelto.",
            evento="Quilelto", paneles=("idx:vgp_01", "goes:C13"),
        ),
        Paso(
            "sondeo", "20:00",
            "En el perfil de Coihueco, observa el CAPE, la altura estimada de la base de "
            "nube y el cambio del viento con la altura. El cálculo de SRH utiliza la rama "
            "left-mover, una estimación del movimiento de la tormenta.",
            evento="Coihueco",
        ),
        Paso(
            "mapas", "21:50",
            "La hora seleccionada es anterior al reporte de Los Ángeles. A la derecha, "
            "los azules indican enfriamiento entre imágenes; comprueba el intervalo del "
            "panel y considera también el desplazamiento de las nubes.",
            evento="Ángeles", paneles=("idx:srh_01", "goes:dT"),
        ),
        Paso(
            "series", "21:50",
            "Compara VGP, cizalle, SRH y temperatura de brillo antes y después de la hora "
            "reportada para Los Ángeles. Distingue los cambios observados de las "
            "inferencias sobre la tormenta. Las series resumen un área fija; no siguen "
            "automáticamente una misma nube.",
            evento="Ángeles",
        ),
    ),
}  # fmt: skip
