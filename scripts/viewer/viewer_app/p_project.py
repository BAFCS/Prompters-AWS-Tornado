"""Página «Problema»: la presentación del proyecto con elementos de Streamlit.

Los dos diagramas viven en ``diagrams.py``. Esta página no usa datos: se muestra aunque no haya recortes.
"""

import html
import re
import time
from pathlib import Path
from typing import Literal

import streamlit as st

import common
from viewer_app import charts, data, diagrams, state, theme

DOCUMENT = "https://github.com/fforster/aws-mesocyclonic/blob/main/docs/mesociclones_chile.md"
REPOSITORY = "https://github.com/fforster/aws-mesocyclonic"
CATALOG = "https://doi.org/10.6084/m9.figshare.25119566"
FIGS = common.ROOT / "figs"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
Color = Literal["orange", "primary"]
# Secciones del índice: (ancla del encabezado, texto del enlace).
SECTIONS = (
    ("inicio", "Inicio"),
    ("importancia", "Por qué importa"),
    ("mesociclones", "Mesociclones"),
    ("problema", "El problema"),
    ("dificultad", "Por qué es difícil"),
    ("datos", "Los datos"),
    ("participar", "Participar"),
)


def _section(anchor: str, title: str, subtitle: str) -> None:
    """Encabezado de sección: título con ``anchor`` para el índice y una frase de contexto."""
    st.divider()
    st.header(title, anchor=anchor)
    st.markdown(f"<p class='lede'>{subtitle}</p>", unsafe_allow_html=True)


def _links(key: str) -> None:
    """Botones al documento completo y al repositorio."""
    with st.container(horizontal=True, gap="small"):  # cada botón a su ancho; se parten si no caben
        st.link_button("Leer el documento completo", DOCUMENT, key=f"{key}_doc",
                       icon=":material/description:")  # fmt: skip
        st.link_button("Repositorio", REPOSITORY, key=f"{key}_repo", icon=":material/code:")


def _image(source: Path | str, description: str, key: str | None = None) -> None:
    """Conserva el visor de imagen nativo y publica su descripción para el vigía del tema."""
    key = key or (
        source.stem
        if isinstance(source, Path)
        else ("mesocyclone" if "mcSvg" in source else "cape")
    )
    with st.container(key=f"image_{key}"):
        st.image(str(source) if isinstance(source, Path) else source, width="stretch")
        st.html(
            f'<span class="project-image-alt" data-description="{html.escape(description, quote=True)}" hidden></span>'
        )


def _cards(key: str, cards: list[tuple[str, Color, str, str]], n_columns: int = 2) -> None:
    """Tarjetas en una grilla: (insignia, color de la insignia, título, texto).

    La grilla la arma el CSS de ``theme.py`` (clave ``cards<n>_``): ``n_columns`` con ancho de sobra
    y menos columnas cuando la página es angosta, en vez de columnas que solo se apilan en teléfono.
    """
    with st.container(horizontal=True, key=f"cards{n_columns}_{key}"):
        for i, (badge, color, title, text) in enumerate(cards):
            with st.container(border=True, key=f"sheet_{key}_{i}"):
                st.badge(badge, color=color)
                st.markdown(f"**{title}**")
                st.markdown(text)


def _cover() -> None:
    """Presenta el objetivo, las referencias del caso y los enlaces."""
    st.title("Predicción de tormentas mesociclónicas en el centro-sur de Chile", anchor="inicio")
    with st.container(key="hero"):
        _image(
            ASSETS / "tornado_los_angeles.webp",
            "Tornado en Los Ángeles, Chile, el 30 de mayo de 2019: el embudo toca el suelo y hay escombros en el aire.",
        )
        st.markdown(
            "<p class='note'>Tornado en Los Ángeles, 30 de mayo de 2019. "
            "Fuente: <a href='https://www.meteored.cl/noticias/ciencia/el-dia-que-marco-el-antes-y-el-despues-de-los-tornados-en-chile.html'>Vicencio Veloso (2022), Meteored</a>; la fuente no indica quién tomó la foto.</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        '<p class="lede">El 30 y 31 de mayo de 2019, en pleno otoño, el centro-sur de Chile vivió un brote histórico de tornados: al menos siete en 24 horas, con cientos de viviendas destruidas y miles de personas afectadas (<a href="https://www.biobiochile.cl/noticias/ciencia-y-tecnologia/ciencia/2026/07/11/se-cumplen-7-anos-del-historico-brote-de-tornados-en-chile-y-advierten-que-puede-volver-a-ocurrir.shtml">BioBioChile, 2026</a>). Los índices que usan los pronosticadores del hemisferio norte no fueron diseñados para este clima, y los especialistas advierten que puede volver a ocurrir. Sabemos que las tormentas que desarrollan un mesociclón son las que preceden a esos tornados. Lo que no sabemos es cómo reconocerlas antes, con los datos que ya existen para Chile.</p>'
        "<p>Este es un proyecto abierto para la hackathon AWS Breaking Barriers. Tenemos 102 eventos documentados, el reanálisis ERA5 y las imágenes del satélite GOES. Falta entender qué distingue a las tormentas que rotan de las que no, y esa pregunta puede responderla cualquier persona que sepa mirar datos, con o sin formación en meteorología.</p>",
        unsafe_allow_html=True,
    )
    st.page_link(
        state.page("case"), label="Explorar el caso de mayo de 2019", icon=":material/map:"
    )
    st.markdown(
        "<p>El catálogo utilizado por el proyecto reúne 102 eventos de tornados y trombas marinas entre 1554 y 2025. Los registros dependen de las observaciones y los reportes disponibles, por lo que pueden faltar eventos.</p>\n<p>El objetivo del proyecto es estimar qué tormentas del centro-sur de Chile pueden desarrollar un mesociclón mediante datos de ERA5 y GOES. También se propone explorar el archivo histórico para identificar situaciones que merezcan una revisión por posible subregistro.</p>",
        unsafe_allow_html=True,
    )
    stats = (("102", "eventos catalogados, 1554–2025", ""), ("7", "tornados en 24 h, mayo 2019", " sev"),
              ("10 min", "frecuencia nominal de GOES", ""), ("0", "registros al sur de 42,4°S", ""))  # fmt: skip
    cells = "".join(f"<div class='stat{c}'><b>{v}</b><span>{r}</span></div>" for v, r, c in stats)
    st.markdown(f"<div class='stats'>{cells}</div>", unsafe_allow_html=True)
    _links("cover")


def _importance() -> None:
    """Por qué importa: sin radares ni alertas, muchos tornados pasan desapercibidos."""
    _section(
        "importancia",
        "Por qué importa",
        "Un radar meteorológico mide dónde llueve y, con el efecto Doppler, hacia dónde se mueve la lluvia. Con eso se ve cómo gira una tormenta antes de que baje un tornado. Chile no tiene hoy una red de radares, así que esa información no existe ni para avisar ni para estudiar lo ocurrido.",
    )
    with st.container(key="hero_radar"):
        _image(
            ASSETS / "weather_station.webp",
            "Radar meteorológico con su cúpula blanca sobre una ladera boscosa de montaña.",
        )
        st.markdown(
            "<p class='note'>Radar meteorológico en una montaña de Turquía; imagen ilustrativa. "
            "Fuente: <a href='https://www.pexels.com/photo/scenic-view-of-weather-station-in-turkish-mountains-30617293/'>Pexels</a>.</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<p>En 2019 Chile no tenía radares meteorológicos ni un sistema de alerta de tornados "
        "(Vicencio et al., 2021). En noviembre de 2025 la Universidad de Valparaíso "
        "<a href='https://www.uv.cl/archivo-noticias-uv/28540-chile-tendra-su-primer-radar-meteorologico-universidad-de-valparaiso-lidera-el-proyecto-que-transformara-la-investigacion-y-la-gestion-climatica-del-pais'>anunció la adjudicación del primer radar</a>, móvil, pero eso no equivale a una red permanente "
        "con cobertura nacional, y los expertos siguen <a href='https://www.cr2.cl/chile-pais-de-tornados-expertos-insiste-en-instalar-radares-ante-nueva-realidad-t13/'>insistiendo en instalar radares</a> "
        "(T13, 2025).</p>"
        "<p>Sin radar, un tornado débil o breve se conoce solo si alguien lo ve y lo reporta. En zonas poco pobladas "
        "puede no quedar registro: el subregistro por baja densidad de población es la explicación que plantean "
        "Caballero-Morán y Rondanelli (2025) para zonas del sur con condiciones favorables "
        "y sin eventos documentados. Y aun con radar, algunos tornados serían difíciles de ver "
        "(lo explicamos más abajo, en «Por qué es difícil»).</p>"
        "<p>Además, los tornados "
        "<a href='https://www.cr2.cl/tornados-no-estarian-catalogados-como-una-amenaza-climatica-en-chile-el-mostrador/'>no figuran como una amenaza climática en el país</a>, "
        "así que no hay un marco que obligue a medirlos (Rondanelli, 2025).</p>"
        "<p>Por eso el catálogo de 102 eventos es una muestra de lo que se vio, no de lo que ocurrió. Un modelo que "
        "reconozca desde datos públicos (ERA5 y GOES) qué tormentas desarrollan rotación no reemplaza a un radar ni "
        "emite alertas, pero sirve para estudiar los entornos favorables, revisar casos históricos que nadie "
        "reportó y decidir mejor dónde observar.</p>",
        unsafe_allow_html=True,
    )


_PLAY_SECONDS = 4  # segundos por etapa al reproducir
_SCALE_ALT = (
    "Una celda cuadrada de ERA5 de 31 km por lado, con una cuadrícula de píxeles de GOES de 2 km y, dentro, "
    "un círculo de 2 a 10 km de diámetro que representa un mesociclón."
)


def _restart_play() -> None:
    """Al activar la reproducción, empieza en la etapa 1."""
    st.session_state["project_t0"] = time.monotonic()


def _step_stage(delta: int) -> None:
    """Mueve la etapa elegida ``delta`` pasos, sin salirse de 1–4."""
    st.session_state["project_stage"] = min(4, max(1, (st.session_state.get("project_stage") or 1) + delta))


def _stages() -> None:
    """Selector de etapa, esquema y explicación. Con la reproducción activa, la etapa sigue al reloj."""
    playing = bool(st.session_state.get("project_play"))
    if playing:
        elapsed = time.monotonic() - st.session_state.get("project_t0", time.monotonic())
        st.session_state["project_stage"] = int(elapsed // _PLAY_SECONDS) % 4 + 1
    st.session_state.setdefault("project_stage", 1)
    with st.container(horizontal=True, vertical_alignment="center", key="stage_controls"):
        stage = st.pills(
            "Etapa", [1, 2, 3, 4], key="project_stage", label_visibility="collapsed", disabled=playing,
            format_func=lambda k: ("Cizalladura", "Inclinación", "Estiramiento", "Mesociclón")[k - 1],
        )  # fmt: skip
        st.button("Anterior", key="stage_prev", icon=":material/chevron_left:", disabled=playing or stage == 1,
                  on_click=_step_stage, args=(-1,))  # fmt: skip
        st.button("Siguiente", key="stage_next", icon=":material/chevron_right:", disabled=playing or stage == 4,
                  on_click=_step_stage, args=(1,))  # fmt: skip
    stage = stage or 1
    title, text = diagrams.STAGES[stage - 1]
    # Con poco ancho las columnas se apilan: el esquema queda arriba y la descripción debajo.
    picture, words = theme.columns([3, 2], "stages")
    with picture:
        _image(diagrams.mesocyclone(stage), f"Formación de un mesociclón. Etapa {title}. {text}")
    with words:
        st.markdown(f"**:primary[{title}]**")
        st.markdown(text)
    if stage == 4:
        with st.container(key="hero_plan"):
            _image(diagrams.plan_view(), _PLAN_ALT, key="plan")
            st.markdown(
                "<p class='note'>Visto desde arriba, el mesociclón ciclónico de Chile gira en sentido horario y se asocia "
                "a una tormenta <em>left-mover</em>. En Estados Unidos ocurre al revés. Por eso los signos de los índices "
                "cambian.</p>",
                unsafe_allow_html=True,
            )
    st.markdown(
        '<p class="note">El esquema muestra cómo la rotación horizontal del entorno puede contribuir a la rotación dentro de una tormenta. La formación de un tornado requiere procesos adicionales cerca de la superficie; un mesociclón puede persistir sin producirlo.</p>',
        unsafe_allow_html=True,
    )


_PLAN_ALT = (
    "Vista desde arriba: en Chile la tormenta left-mover se desvía a la izquierda del viento medio y gira en sentido "
    "horario; en las Grandes Llanuras la right-mover se desvía a la derecha y gira en sentido antihorario."
)


def _animation() -> None:
    """Mesociclogénesis en cuatro etapas: el usuario elige la etapa; los rodillos giran solos."""
    st.header("Mesociclones, supercélulas y tornados", anchor="mesociclones")
    st.markdown(
        "Un mesociclón es una región de aire en rotación organizada dentro de una tormenta, de unos 2 a 10 km de diámetro. Una tormenta con un mesociclón persistente se denomina supercélula. Un tornado es un fenómeno de menor escala cuya circulación alcanza la superficie. Una supercélula puede desarrollar un tornado, pero esa evolución no es inevitable.",
    )
    with st.container(border=True, key="sheet_animation"):
        st.subheader("Cómo se organiza la rotación dentro de una tormenta", anchor=False)
        st.caption("Formación de un mesociclón: esquema simplificado en cuatro etapas")
        st.toggle("Reproducir en bucle", key="project_play", on_change=_restart_play)
        # El fragmento se repite solo mientras se reproduce; cambiar de etapa no recarga la página.
        st.fragment(run_every=_PLAY_SECONDS if st.session_state.get("project_play") else None)(_stages)()


CASE_TEXT = (
    '<p>El <strong>30 y 31 de mayo de 2019</strong>, siete tornados golpearon en menos de 24 horas la zona entre Ñuble y La Araucanía. Dos entraron en ciudades: <strong>Los Ángeles</strong> (EF2) y <strong>Talcahuano–Concepción</strong> (EF1–EF2, 17 km de trayecto, una persona fallecida, 50.000 clientes sin electricidad). La escala Fujita mejorada (EF) clasifica la intensidad según los daños observados. Este episodio es el caso de referencia del proyecto para estudiar las condiciones atmosféricas asociadas a los tornados del centro-sur de Chile.</p>\n<p>Existe un catálogo formal y publicado: la base <a href="https://doi.org/10.6084/m9.figshare.25119566">Tornadoes and Waterspouts in Chile</a> (Bastías-Curivil, Rondanelli, Vicencio et al., CC BY 4.0), con <strong>102 eventos entre 1554 y 2025</strong>. Incluye tornados, trombas marinas y eventos clasificados en ambas categorías. Según el resumen disponible, todos tienen coordenadas y el 89 % tiene hora UTC, un dato necesario para compararlos con imágenes satelitales. UTC significa tiempo universal coordinado y puede diferir de la hora local de Chile.</p>\n<p>En la copia del catálogo usada aquí, 70 registros están marcados como tornado, 45 como tromba marina y 19 en ambas categorías. Otros 6 no están marcados en ninguna de las dos; su clasificación debe revisarse. Los conteos de tornados y trombas se solapan y no deben sumarse para obtener el total.</p>\n<p>La cobertura del catálogo depende de que los eventos hayan sido observados, documentados e incorporados a la base. Esto puede favorecer los registros de zonas pobladas y dejar menos información sobre zonas rurales, el mar o eventos nocturnos. Es un sesgo de reporte que debe considerarse al analizar los datos. El catálogo no contiene registros al sur de los 42,4°S; esa ausencia no confirma que allí no hayan ocurrido eventos.</p>\n<p>Una línea de trabajo consiste en identificar días y lugares con condiciones similares a las de eventos documentados. Esos resultados serían candidatos para una revisión posterior; la similitud del entorno no confirma que haya ocurrido un tornado ni que se haya formado un mesociclón.</p>'
)


def _problem() -> None:
    """Explica el caso de referencia y las limitaciones del catálogo."""
    _section(
        "problema",
        "Un catálogo de eventos reportados, sin casos negativos confirmados",
        "El catálogo reúne 102 tornados y trombas marinas entre 1554 y 2025, tomados de crónicas coloniales, prensa, redes sociales, literatura científica y libros. Cada evento está ahí porque alguien lo observó y alguien lo documentó. Un lugar o una fecha sin registro puede significar que no ocurrió nada, o que nadie estaba mirando.",
    )
    cat = data.catalog()
    if cat.empty:
        # Sin el catálogo descargado queda la figura estática, que sí va en el repositorio.
        st.image(str(FIGS / "fig1_catalog_map.png"), width="stretch")
        st.markdown(CASE_TEXT, unsafe_allow_html=True)
        return
    picture, words = theme.columns([2, 3], "catalog")
    with picture:
        with st.container(horizontal=True, key="catalog_options"):
            by_intensity = st.checkbox("Tamaño según intensidad (EF)", key="catalog_by_intensity")
            by_type = st.checkbox("Color según tipo de evento", key="catalog_by_type")
        fig = charts.catalog_map(cat, data.coast(charts.CATALOG_REGION), by_intensity=by_intensity, by_type=by_type)
        st.plotly_chart(fig, width="stretch", theme=None, key="catalog_map")
    with words:
        st.markdown(CASE_TEXT, unsafe_allow_html=True)
        st.markdown(
            "<p class='note'>Cada triángulo es un evento del catálogo, con solo los casos positivos. Pasa el cursor "
            "para ver su fecha, hora, posición, tipo, intensidad, fenómenos y víctimas. El tamaño y el color se "
            "activan con las casillas de arriba.</p>",
            unsafe_allow_html=True,
        )


def _difficulty() -> None:
    """Presenta las decisiones de cálculo y las referencias que deben validarse."""
    _section(
        "dificultad",
        "Tres aspectos que deben adaptarse al contexto chileno",
        "El régimen atmosférico, el sentido de rotación y la cobertura del catálogo condicionan el cálculo de índices y el entrenamiento de modelos.",
    )
    _cards(
        "difficulty",
        [
            (
                "1",
                "orange",
                "Los umbrales deben evaluarse con datos chilenos",
                "Los casos descritos presentan fuerte cambio del viento con la altura y energía convectiva relativamente baja. Este régimen se denomina HSLC, por sus siglas en inglés (high shear, low CAPE: fuerte cizalladura y bajo CAPE). La energía potencial convectiva disponible (CAPE) mide la energía disponible para el ascenso del aire. Los índices combinan estas y otras variables para resumir el entorno. En este régimen la rotación puede ser poco profunda y breve, lo que dificulta detectarla incluso con radar.",
            ),
            (
                "2",
                "orange",
                "Elegir la rama de movimiento y comprobar los signos",
                "El proyecto trabaja con la rama left-mover: una estimación del movimiento de la tormenta hacia la izquierda del viento medio. Para los casos australes descritos, la helicidad relativa a la tormenta (SRH) de esta rama es negativa. Al calcular los índices, hay que comprobar la rama elegida y la convención de signos; no basta con cambiar el signo de todos los resultados.",
            ),
            (
                "3",
                "orange",
                "La falta de reporte no confirma la ausencia de un evento",
                "La mayor cantidad de registros recientes puede estar influida por cambios en la observación y documentación. Para el aprendizaje automático, contamos con eventos reportados y situaciones sin etiqueta confirmada. El aprendizaje con positivos y datos no etiquetados, conocido como PU learning, es una opción para trabajar con esta limitación.",
            ),
        ],
        n_columns=3,
    )
    st.subheader("Referencias de los índices", anchor=False)
    st.markdown(
        "| Índice | Qué resume | Referencia citada en el documento |\n|---|---|---|\n| VGP₀₋₁ · parámetro de generación de vorticidad | Combina CAPE y cambio del viento por unidad de altura en el primer kilómetro | > 0,1 m/s² en los cinco días tornádicos analizados por Vicencio et al. (2021) |\n| SHERBE · índice de entornos con baja energía convectiva | Combina características del viento y del perfil térmico | ≥ 1; referencia de Marín et al. (2024) |\n| STP · parámetro significativo de tornado | Combina energía convectiva, viento y otras condiciones del entorno | Rama left-mover ≤ −0,3; referencia de Marín et al. (2024) |"
    )
    st.markdown(
        "Estos valores orientan la comparación con los estudios citados. Requiere verificación: confirmar las variantes y el alcance de cada criterio antes de usarlo como umbral operativo. El visor calcula SHERBS3, una variante distinta de SHERBE, y una aproximación del STP; no deben trasladarse los criterios entre variantes sin validación.",
    )
    with st.container(border=True, key="sheet_cape"):
        _image(
            diagrams.cape_shear(),
            "Comparación esquemática de CAPE y cizalladura: los casos chilenos de mayo de 2019 combinan baja energía convectiva con fuerte cambio del viento en el primer kilómetro. No es una frontera de detección.",
        )
        st.markdown(
            "Comparación esquemática de CAPE y cizalladura; no representa una frontera de detección del STP. Los casos chilenos de mayo de 2019 combinan CAPE relativamente bajo con fuerte cizalladura en el primer kilómetro. La referencia de 15–45 J/kg corresponde al CAPE medio a fines de mayo en Biobío descrito en el documento. Requiere verificación: confirmar las fuentes y el ámbito de las referencias del esquema antes de utilizarlas en una decisión."
        )
    st.markdown(
        '<div class="notice">Caballero-Morán y Rondanelli (2025) analizaron índices derivados de ERA5 entre 1959 y 2021. El documento del proyecto les atribuye la identificación de zonas del sur austral con condiciones favorables y sin eventos documentados. Este resultado motiva la búsqueda de posibles situaciones subregistradas. <strong>Requiere verificación:</strong> comprobar que esta formulación refleje el alcance del estudio; unas condiciones favorables no confirman un evento ocurrido.</div>',
        unsafe_allow_html=True,
    )


_BANDS_TABLE = """| Banda | λ central (µm) | Tipo | Apodo | Resolución |
|---|---|---|---|---|
| 1 | 0,47 | Visible | Azul | 1 km |
| 2 | 0,64 | Visible | Rojo | 0,5 km |
| 3 | 0,86 | IR cercano | "Veggie" | 1 km |
| 4 | 1,37 | IR cercano | Cirros | 2 km |
| 5 | 1,6 | IR cercano | Nieve/hielo | 1 km |
| 6 | 2,2 | IR cercano | Tamaño de partícula | 2 km |
| 7 | 3,9 | IR | Ventana de onda corta | 2 km |
| 8 | 6,2 | IR | Vapor de agua, nivel alto | 2 km |
| 9 | 6,9 | IR | Vapor de agua, nivel medio | 2 km |
| 10 | 7,3 | IR | Vapor de agua, nivel bajo | 2 km |
| 11 | 8,4 | IR | Fase del tope nuboso | 2 km |
| 12 | 9,6 | IR | Ozono | 2 km |
| 13 | 10,3 | IR | Ventana larga "limpia" | 2 km |
| 14 | 11,2 | IR | Ventana larga | 2 km |
| 15 | 12,3 | IR | Ventana larga "sucia" | 2 km |
| 16 | 13,3 | IR | CO₂ | 2 km |"""


def _figure(file: str, caption: str) -> None:
    """Figura del caso de 2019 en su ficha, con el pie en nota."""
    with st.container(border=True, key=f"sheet_{file[:4]}"):
        _image(FIGS / file, re.sub(r"<[^>]+>", "", caption))
        st.markdown(f"<p class='note'>{caption}</p>", unsafe_allow_html=True)


def _data_section() -> None:
    """Describe cada fuente de datos (ERA5, GOES, catálogo) y la escala de sus celdas."""
    _section(
        "datos",
        "Tres fuentes de datos para estudiar las tormentas",
        "ERA5 reconstruye el estado de la atmósfera, GOES la observa desde el espacio y el catálogo reúne los eventos reportados con los que se comparan ambas.",
    )
    st.subheader("ERA5: la atmósfera reconstruida", anchor=False)
    st.markdown(
        "**Qué es.** ERA5 es el reanálisis atmosférico global del ECMWF, el Centro Europeo de Predicción Meteorológica a Plazo Medio. "
        "No es una medición directa ni un pronóstico: es una reconstrucción de cómo estaba la atmósfera en cada hora desde 1940.\n\n"
        "**Cómo se calcula.** Un reanálisis combina un modelo meteorológico con observaciones del pasado (radiosondas, satélites, aviones, boyas y estaciones). "
        "Repite el análisis para cada período con el mismo método, así que sus valores son comparables entre años. Se publica en una grilla de 0,25° "
        "(unos 31 km) con valores horarios, y su altura se describe con 37 niveles de presión.\n\n"
        "**Qué aporta al proyecto.** Viento, temperatura, humedad y altura de los niveles atmosféricos, además de CAPE y la inhibición convectiva (CIN), "
        "la barrera energética para iniciar el ascenso. Con ellas se calculan la cizalladura y los índices. ERA5 describe el entorno donde nace la tormenta, no la tormenta misma.\n\n"
        "**Cuidado.** Sobre los Andes el nivel de 1000 hPa está bajo el terreno y sus valores son una extrapolación del modelo, "
        "así que la cizalladura de niveles bajos allí no es viento real."
    )
    _figure(
        "fig4_era5_20190530.png",
        "<b>ERA5, 30 de mayo de 2019, 21:00 UTC.</b> Los paneles muestran temperatura a 500 hPa (A), viento a 850 hPa (B), cizalladura entre la superficie y 1 km (C) y entre la superficie y 6 km (D). Los niveles en hPa son superficies de presión que permiten comparar distintas partes de la atmósfera. En C y D se puede observar la extensión de las zonas con cizalladura elevada.",
    )
    st.subheader("GOES: la tormenta vista desde el espacio", anchor=False)
    st.markdown(
        "**Qué es.** GOES-East es un satélite geoestacionario: se mantiene sobre un punto del ecuador, a 75,2° O, una longitud cercana a la de Chile, "
        "y mira siempre el mismo disco terrestre. Su instrumento, el ABI (*Advanced Baseline Imager*), es un radiómetro: mide cuánta radiación llega desde cada punto. "
        "El visor usa GOES-16 (diciembre de 2017 a abril de 2025, el caso de 2019) y GOES-19 desde abril de 2025.\n\n"
        "**Qué son las bandas.** El ABI no toma una sola imagen: mide 16 «bandas», cada una en una longitud de onda distinta, del visible al infrarrojo térmico. "
        "Cada banda es sensible a algo diferente: las visibles muestran la luz del Sol reflejada y las infrarrojas, la temperatura de lo que emite, nubes incluidas. "
        "Para tormentas importan sobre todo la banda 2 (visible rojo: textura y sombras del tope, solo de día), las 8, 9 y 10 (vapor de agua en niveles alto, medio y bajo), "
        "la 13 (infrarrojo de «ventana limpia»: la temperatura de brillo del tope, que indica qué tan alto llegó la tormenta) y las diferencias entre bandas, como 13−11 y 13−16.\n\n"
        "**Cuándo observa.** Una imagen del disco completo cada 10 minutos, 144 al día. Los recortes del visor se guardan a 2 km.\n\n"
        "**Cuidado.** El satélite ve el tope de la tormenta de lado y lo desplaza hacia el sur (paralaje): unos 10 km en Santiago y 21 km a 53°S para un tope de 12 km. "
        "El visor aún no lo corrige."
    )
    with st.expander("Las 16 bandas del ABI"):
        st.markdown(
            "La longitud de onda central (λ) indica qué parte del espectro observa cada banda, en micrómetros (µm); IR significa infrarrojo. "
            "Las resoluciones son nominales y empeoran hacia los bordes de la imagen.\n\n"
            + _BANDS_TABLE
        )
    _figure(
        "fig3_goes_20190530.png",
        "<b>GOES-16, banda 13.</b> Los paneles muestran la temperatura de brillo y su cambio entre imágenes; los triángulos marcan los tornados reportados ese día. La temperatura de brillo es una medida derivada de la radiación infrarroja recibida. Un descenso puede ser compatible con crecimiento vertical, pero también puede deberse al desplazamiento de nubes sobre el mismo píxel. El flujo óptico estima ese movimiento y puede ayudar a separar ambos efectos.",
    )
    st.subheader("El catálogo de eventos", anchor=False)
    st.markdown(
        f"**Qué es.** La base [«Tornadoes and Waterspouts in Chile»]({CATALOG}), publicada en figshare con licencia CC BY 4.0 por doce autores "
        "encabezados por Cristian Bastías-Curivil, entre ellos Roberto Rondanelli y José Vicencio. Se armó con crónicas coloniales, prensa, redes sociales, "
        "literatura científica y libros, e incluye los casos en que los autores consideran más probable que haya ocurrido un tornado o una tromba que lo contrario.\n\n"
        "**Qué trae.** 102 eventos entre 1554 y 2025, con posición, fecha, hora UTC y local, tipo (tornado, tromba o ambos), intensidad en la escala Fujita mejorada (EF), "
        "fenómenos acompañantes (ruido, granizo, tormenta eléctrica, daños) y víctimas. No trae una etiqueta directa de mesociclón. "
        "El mapa de «El problema» muestra dónde están.\n\n"
        "**Límites.** Solo tiene casos positivos: que no haya un reporte no prueba que no ocurriera un evento. Entra al catálogo lo que alguien vio y contó, "
        "así que hay más registros donde hay más gente. Varias horas vienen como rango o redondeadas, y la posición es la del daño observado, no la del mesociclón."
    )
    st.page_link(state.page("data"), label="Abrir el catálogo de datos de cada variable", icon=":material/dataset:")
    st.subheader("El tamaño de las celdas", anchor=False)
    st.markdown(
        "Una celda de ERA5 mide unos 31 km por lado y guarda un solo valor por variable; un mesociclón mide de 2 a 10 km. "
        "Por eso ERA5 describe el entorno de la tormenta y no su rotación. GOES, con píxeles de unos 2 km, ve la nube pero no el giro."
    )
    with st.container(key="hero_scale"):
        _image(diagrams.scale(), _SCALE_ALT, key="scale")
        st.markdown(
            "<p class='note'>Escala lineal: una celda de ERA5 con una cuadrícula de píxeles de GOES y un mesociclón dibujados al mismo tamaño que tendrían sobre el terreno.</p>",
            unsafe_allow_html=True,
        )


def _participate() -> None:
    """Propone tareas para quien quiera participar."""
    _section(
        "participar",
        "Por dónde empezar",
        "El proyecto está abierto a cualquier persona interesada, con o sin formación en meteorología.",
    )
    _cards(
        "tasks",
        [
            (
                "Accesible",
                "primary",
                "Revisar el catálogo",
                "Revisar y homogeneizar fechas, horas UTC, coordenadas y tipos de evento, conservando la fuente y la información de confianza.",
            ),
            (
                "Accesible",
                "primary",
                "Animaciones GOES",
                "Construir secuencias animadas de imágenes GOES de los eventos conocidos para observar la evolución y el desplazamiento de las nubes.",
            ),
            (
                "Intermedia",
                "primary",
                "Cálculo y validación de índices",
                "Completar los índices pendientes y contrastar los cálculos existentes con los casos documentados, comprobando ramas y signos.",
            ),
            (
                "Avanzada",
                "orange",
                "Explorar la rotación del yunque",
                "Explorar señales de rotación en el yunque, la parte superior de la nube que se extiende horizontalmente. Usar flujo óptico para estimar el movimiento en secuencias GOES y evaluar si esas señales ayudan a identificar tormentas mesociclónicas. Debe definirse cómo validar la relación entre la señal observada y la presencia de un mesociclón.",
            ),
        ],
    )
    st.markdown(
        "El documento completo desarrolla la física, las fuentes de datos, las variables derivadas, el planteamiento del modelo, una arquitectura sugerida en AWS y las líneas de trabajo.",
    )
    _links("participate")
    st.divider()
    st.markdown(
        f"<p class='note'>Catálogo de eventos: Bastías-Curivil et al. (2024–2025), <a href='{CATALOG}'>"
        "<em>Tornadoes and Waterspouts in Chile</em></a>, figshare, CC BY 4.0. Fuentes principales: "
        "Vicencio et al. (2021, <em>BAMS</em>) · Marín et al. (2024, <em>MWR</em>) · Barrett et al. "
        "(2020, <em>Atmos. Res.</em>) · Caballero-Morán &amp; Rondanelli (2025, <em>GRL</em>). La lista "
        "completa está en el documento. Datos: ERA5 (ECMWF / Copernicus) y GOES-R (NOAA / NASA), ambos en "
        "el AWS Open Data Program.</p>",
        unsafe_allow_html=True,
    )


def _toc() -> str:
    """El índice de la página como lista de enlaces a las anclas de ``SECTIONS``."""
    links = "".join(f"<li><a href='#{anchor}'>{text}</a></li>" for anchor, text in SECTIONS)
    return f"<nav class='toc' aria-label='En esta página'><ol>{links}</ol></nav>"


def page() -> None:
    """Dibuja el cuerpo de la página y su índice.

    Con ancho de sobra el índice va en una columna fija a la derecha; en pantallas más angostas
    (tablet, teléfono) se ve un desplegable sobre el cuerpo. El CSS de ``theme.py`` elige cuál mostrar
    según el ancho de ``.st-key-project`` (880 px).
    """
    with st.container(key="project"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key="project_body"):
            with st.expander("En esta página", key="toc_compact", icon=":material/toc:"):
                st.markdown(_toc(), unsafe_allow_html=True)
            _cover()
            _importance()
            _animation()
            _problem()
            _difficulty()
            _data_section()
            _participate()
        with st.container(width=220, key="toc_side"):
            st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(_toc(), unsafe_allow_html=True)
