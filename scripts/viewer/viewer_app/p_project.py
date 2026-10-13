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
ERA5 = "https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5"
GOES = "https://www.goes-r.gov/"
OPEN_DATA = "https://registry.opendata.aws/"
FIGS = common.ROOT / "figs"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
Color = Literal["orange", "primary"]
# Secciones del índice: (ancla del encabezado, texto del enlace).
SECTIONS = (
    ("inicio", "Inicio"),
    ("objetivo", "Objetivo"),
    ("importancia", "Por qué importa"),
    ("mesociclones", "Mesociclones"),
    ("chile", "Por qué Chile es distinto"),
    ("catalogo", "El catálogo"),
    ("datos", "Los datos"),
    ("volumen", "El volumen de los datos"),
    ("decisiones", "Decisiones abiertas"),
    ("participar", "Participar"),
    ("glosario", "Anexo: glosario"),
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
        '<p class="lede">El 30 y 31 de mayo de 2019, en pleno otoño, el centro-sur de Chile vivió un brote histórico de tornados: al menos siete en 24 horas, con cientos de viviendas dañadas y miles de personas afectadas (<a href="https://www.biobiochile.cl/noticias/ciencia-y-tecnologia/ciencia/2026/07/11/se-cumplen-7-anos-del-historico-brote-de-tornados-en-chile-y-advierten-que-puede-volver-a-ocurrir.shtml">BioBioChile, 2026</a>). Dos de ellos entraron en Los Ángeles y Talcahuano, y en Talcahuano murió una persona. Los especialistas advierten que puede repetirse. Los tornados más fuertes suelen nacer en tormentas con un mesociclón, una rotación organizada dentro de la nube, aunque no todo mesociclón produce un tornado. Lo que no sabemos es cómo reconocer esas tormentas a tiempo con los datos que ya existen para Chile.</p>'
        "<p>Este es un proyecto abierto para la hackathon AWS Breaking Barriers. Tenemos 102 eventos documentados, "
        f"el reanálisis <a href='{ERA5}'>ERA5</a> y las imágenes del satélite <a href='{GOES}'>GOES</a>, ambos públicos en el "
        f"<a href='{OPEN_DATA}'>AWS Open Data Program</a> y descritos en <a href='#datos'>Los datos</a>. Falta entender qué distingue "
        "a las tormentas que rotan de las que no.</p>",
        unsafe_allow_html=True,
    )
    st.page_link(
        state.page("case"), label="Explorar el caso de mayo de 2019", icon=":material/map:"
    )
    stats = (("102", "eventos catalogados, 1554–2025", ""), ("7", "tornados en 24 h, mayo 2019", " sev"),
              ("10 min", "frecuencia nominal de GOES", ""), ("0", "registros al sur de 42,4°S", ""))  # fmt: skip
    cells = "".join(f"<div class='stat{c}'><b>{v}</b><span>{r}</span></div>" for v, r, c in stats)
    st.markdown(f"<div class='stats'>{cells}</div>", unsafe_allow_html=True)
    _links("cover")


def _decision(title: str, question: str, options: list[tuple[str, str]], hint: str) -> None:
    """Una decisión abierta: la pregunta, cada opción con sus implicancias y una sugerencia."""
    with st.container(border=True, key=f"decision_{re.sub(r'\W+', '_', title.lower())}"):
        st.badge("Decisión abierta", color="primary")
        st.markdown(f"**{title}**")
        st.markdown(question)
        st.markdown("\n".join(f"- **{name}.** {text}" for name, text in options))
        st.markdown(f"**Sugerencia.** {hint}")


def _objective() -> None:
    """Objetivo y criterio de éxito; las decisiones abiertas van en ``_decisions``."""
    _section(
        "objetivo",
        "Objetivo",
        "El objetivo del proyecto es estimar qué tormentas del centro-sur de Chile pueden desarrollar un mesociclón mediante datos de ERA5 y GOES.",
    )
    st.subheader("Criterio de éxito", anchor=False)
    st.markdown(
        "Predicción de candidatos a mesociclones en el período 2026. Los candidatos serán evaluados por expertos en el área "
        "y contrastados contra una base de datos actualizada de tornados.\n\n"
        "Esa base de 2026 no es pública: la mantiene internamente el CR2 (Centro de Ciencia del Clima y la Resiliencia). "
        "No está en el visor ni en el catálogo de 102 eventos, que llega a 2025. Por eso conviene **no usarla para entrenar** y reservarla "
        "para evaluar el algoritmo a futuro: un modelo ajustado con los eventos hasta 2025 y probado con 2026 se evalúa sobre datos que no vio."
    )
    st.markdown(
        "«Estimar qué tormentas pueden desarrollar un mesociclón» se puede leer de varias formas. "
        "Las opciones están en <a href='#decisiones'>Decisiones abiertas</a>, después de presentar los datos.",
        unsafe_allow_html=True,
    )


def _decisions() -> None:
    """Las decisiones que el proyecto deja a quienes lo desarrollen, con opciones y una sugerencia."""
    _section(
        "decisiones",
        "Decisiones abiertas",
        "Con los datos y su costo a la vista, quedan las decisiones de diseño: seis que cambian qué datos se preparan, qué modelo se entrena y cómo se evalúa.",
    )
    st.markdown(
        "El proyecto **no fija estas decisiones: les corresponde a quienes lo desarrollen**, que además pueden proponer otras. "
        "Para cada una van las opciones, lo que implica elegirlas y una sugerencia de partida, que se puede rechazar con argumentos."
    )
    _decision(
        "¿Qué se predice? La unidad de análisis",
        "Hay que decidir sobre qué objeto se hace cada predicción.",
        [
            (
                "Una tormenta seguida en GOES",
                "Se identifica una nube convectiva en las imágenes y se sigue en el tiempo. Es lo más cercano a «qué tormentas», pero exige un algoritmo de seguimiento "
                "y la nube se ve desplazada por el paralaje. ERA5 se asocia a la tormenta por su posición.",
            ),
            (
                "Una celda de ERA5 por hora",
                "Cada celda de unos 31 km y cada hora es una muestra. Es simple y ya está calculado, pero describe el entorno y no la tormenta: una celda puede tener varias tormentas o ninguna.",
            ),
            (
                "Una región por día",
                "Se predice si ese día hubo condiciones para un mesociclón en la zona. Hay menos muestras (38 días con algún tornado o tromba desde 2018) y no se sabe cuál tormenta fue.",
            ),
        ],
        "Partir con la celda de ERA5 por hora, que se puede hacer ya, y avanzar a la tormenta seguida en GOES si el tiempo lo permite.",
    )
    _decision(
        "¿Qué cuenta como positivo?",
        "El catálogo trae tornados y trombas, no mesociclones: ningún evento tiene una etiqueta directa de rotación.",
        [
            (
                "Un tornado reportado",
                "Hay etiquetas, aunque pocas (102 eventos, 50 desde 2018, cuando GOES-16 ya operaba). Un tornado no siempre viene de un mesociclón, y hay mesociclones sin tornado.",
            ),
            (
                "Un mesociclón inferido",
                "Se define con un indicador de rotación, como la rotación estimada en el yunque con flujo óptico o un índice como VGP₀₋₁ sobre su umbral. "
                "Hay más muestras, pero el modelo aprendería a repetir ese indicador y no habría un hecho observado con qué verificarlo.",
            ),
            (
                "Ambos, por niveles",
                "Un tornado reportado es la etiqueta fuerte y un indicador de rotación, la débil. Pide más trabajo y permite comprobar si coinciden.",
            ),
        ],
        "Usar el tornado reportado como etiqueta de evaluación y el mesociclón inferido solo como variable de apoyo, dejando clara la diferencia en cada resultado.",
    )
    _decision(
        "¿Cómo se eligen los días de comparación?",
        "El catálogo no tiene días sin tornado, y un modelo necesita ejemplos de los dos lados. Estas son dos formas de tomarlos, que se pueden combinar.",
        [
            (
                "Días al azar, en la época de los tornados",
                "Sortear días de otoño e invierno, cuando se concentran los eventos del catálogo, que no estén en él, sin repetir fechas. "
                "Así el modelo ve días típicos de esa estación. Pero un día sorteado casi nunca tiene una tormenta, así que el modelo puede aprender a decir «hay nubes y viento», que es más fácil que reconocer una supercélula.",
            ),
            (
                "Días elegidos a mano para contrastar",
                "Un puñado de días con características distintas: lluvia frontal sin convección, un día soleado y estable, "
                "tormentas sin tornado conocido y un día de alta cizalladura sin evento. Sirven para probar qué distingue cada situación y para depurar el modelo. "
                "Son pocos: no alcanzan para entrenar ni para estimar tasas de error.",
            ),
        ],
        "Usar ambos: unas decenas de días al azar para entrenar y evaluar, más tres o cuatro días elegidos como casos de prueba. "
        "Tener presente que un día sin reporte no prueba que no hubiera tornado (el catálogo tiene subregistro), así que los «negativos» son en parte ruido.",
    )
    _decision(
        "¿Diagnóstico o pronóstico?",
        "Hay que decidir con cuánta anticipación se estima.",
        [
            (
                "Diagnóstico",
                "Con los datos de la hora del evento se dice si la tormenta tiene condiciones de rotar. Es el problema más fácil y permite estudiar qué importa, pero no avisa a nadie.",
            ),
            (
                "Anticipación de unas horas",
                "Se usan datos previos a la tormenta, de una a seis horas antes. Es lo que serviría para alertar. Es más difícil. Además, ERA5 se publica con días de retraso y no es un pronóstico, y esta opción solo se puede evaluar con eventos de hora conocida.",
            ),
        ],
        "Resolver primero el diagnóstico, como paso para el segundo.",
    )
    _decision(
        "¿Se mira también hacia atrás?",
        "Además de 2026, se puede recorrer el archivo histórico en busca de situaciones que merezcan una revisión por posible subregistro. "
        "Sería un objetivo secundario: puede ser parte del proyecto o quedar fuera de él.",
        [
            (
                "Con ERA5 desde 1940",
                "Alcanza para los entornos favorables de los 86 años, pero no ve la tormenta, solo su entorno, y el catálogo está sesgado hacia donde hay gente.",
            ),
            (
                "Con GOES desde 2017",
                "Ve la nube, pero solo cubre desde fines de 2017.",
            ),
            ("No hacerlo", "Concentra el trabajo en un solo objetivo."),
        ],
        "Dejarlo como segundo objetivo, solo si el primero funciona. Los candidatos que salgan se tratan como hipótesis a revisar por expertos, no como eventos.",
    )
    _decision(
        "¿Qué entrega el modelo y cómo se mide?",
        "La salida y la métrica determinan qué se considera un buen resultado.",
        [
            (
                "Un puntaje por tormenta o celda",
                "Permite ordenar los candidatos y elegir un umbral. Hay que decidir ese umbral, que cambia cuántos aciertos y cuántas falsas alarmas se aceptan.",
            ),
            (
                "Una lista corta de candidatos",
                "Es lo que los expertos pueden revisar. Se pierde la información fina y hay que fijar cuántos candidatos se entregan.",
            ),
        ],
        "Medir con la tasa de acierto y la de falsas alarmas, siempre separando los años de entrenamiento de los de evaluación, y reportar cuántos candidatos tuvo que revisar un experto por cada tornado encontrado.",
    )


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
        "(lo explicamos más abajo, en «Por qué Chile es distinto»).</p>"
        "<p>Además, los tornados "
        "<a href='https://www.cr2.cl/tornados-no-estarian-catalogados-como-una-amenaza-climatica-en-chile-el-mostrador/'>no figuran como una amenaza climática en el país</a>, "
        "así que no hay un marco que obligue a medirlos (Rondanelli, 2025).</p>"
        "<p>Un modelo que "
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
    st.session_state["project_stage"] = min(
        4, max(1, (st.session_state.get("project_stage") or 1) + delta)
    )


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
        '<p class="note">El esquema muestra cómo la rotación horizontal del entorno puede contribuir a la rotación dentro de una tormenta. La formación de un tornado requiere procesos adicionales cerca de la superficie; un mesociclón puede persistir sin producirlo. Las líneas rojas del esquema son la rotación: los rodillos horizontales y el giro del mesociclón.</p>',
        unsafe_allow_html=True,
    )


_PLAN_ALT = (
    "Vista desde arriba: en Chile la tormenta left-mover se desvía a la izquierda del viento medio y gira en sentido "
    "horario; en las Grandes Llanuras la right-mover se desvía a la derecha y gira en sentido antihorario."
)


def _animation() -> None:
    """Mesociclogénesis en cuatro etapas: el usuario elige la etapa; los rodillos giran solos."""
    _section(
        "mesociclones",
        "Mesociclones, supercélulas y tornados",
        "Los tornados más intensos suelen formarse dentro de tormentas que giran, llamadas supercélulas.",
    )
    st.markdown(
        "Un mesociclón es una región de aire en rotación organizada dentro de una tormenta, de unos 2 a 10 km de diámetro. Una tormenta con un mesociclón persistente se denomina supercélula. Un tornado es un fenómeno de menor escala cuya circulación alcanza la superficie. Una supercélula puede desarrollar un tornado, pero esa evolución no es inevitable.",
    )
    with st.container(border=True, key="sheet_animation"):
        st.subheader("Cómo se organiza la rotación dentro de una tormenta", anchor=False)
        st.caption("Formación de un mesociclón: esquema simplificado en cuatro etapas")
        st.toggle("Reproducir en bucle", key="project_play", on_change=_restart_play)
        # El fragmento se repite solo mientras se reproduce; cambiar de etapa no recarga la página.
        st.fragment(run_every=_PLAY_SECONDS if st.session_state.get("project_play") else None)(
            _stages
        )()


CATALOG_TEXT = (
    f'<p>La base <a href="{CATALOG}">Tornadoes and Waterspouts in Chile</a> está publicada en figshare con licencia CC BY 4.0 por doce autores '
    "encabezados por Cristian Bastías-Curivil, entre ellos Roberto Rondanelli y José Vicencio. Incluye los casos en que los autores consideran más probable "
    "que haya ocurrido un tornado o una tromba que lo contrario. Reúne <strong>102 eventos entre 1554 y 2025</strong>: 70 marcados como tornado, 45 como tromba marina "
    "y 19 en ambas categorías, así que esos números no se suman; otros 6 no tienen tipo y su clasificación debe revisarse.</p>"
    "<p>Cada evento trae posición, fecha, hora local y UTC, tipo, intensidad en la escala Fujita mejorada (EF), fenómenos acompañantes (ruido, granizo, "
    "tormenta eléctrica, daños) y víctimas. Todos tienen coordenadas y el 89 % tiene hora UTC, que es lo que permite buscarlos en las imágenes satelitales; "
    "UTC es el tiempo universal coordinado y no coincide con la hora local de Chile. Varias horas vienen como rango o redondeadas, y la posición es la del daño "
    "observado, no la del mesociclón.</p>"
    "<p>Hay más registros en zonas pobladas y menos en el campo, en el mar o de noche. "
    "La fecha también pesa: 68 de los 102 eventos son de 2015 en adelante, y parte de ese aumento puede deberse a que hoy se observa y documenta más. "
    "No hay ningún registro al sur de los 42,4°S, y esa ausencia no prueba que allí no ocurran.</p>"
    "<p>El catálogo no trae una etiqueta de mesociclón ni casos negativos: un modelo cuenta con eventos reportados y con un resto sin etiqueta. "
    "El aprendizaje con positivos y datos no etiquetados (<em>PU learning</em>) está pensado para ese caso.</p>"
)


def _catalog() -> None:
    """Muestra el catálogo en un mapa y explica sus limitaciones."""
    _section(
        "catalogo",
        "Un catálogo de eventos reportados, sin casos negativos confirmados",
        "El catálogo reúne 102 tornados y trombas marinas entre 1554 y 2025, tomados de crónicas coloniales, prensa, redes sociales, literatura científica y libros. Cada evento está ahí porque alguien lo observó y alguien lo documentó. Un lugar o una fecha sin registro puede significar que no ocurrió nada, o que nadie estaba mirando.",
    )
    cat = data.catalog()
    if cat.empty:
        # Sin el catálogo descargado queda la figura estática, que sí va en el repositorio.
        st.image(str(FIGS / "fig1_catalog_map.png"), width="stretch")
        st.markdown(CATALOG_TEXT, unsafe_allow_html=True)
        return
    picture, words = theme.columns([2, 3], "catalog")
    with picture:
        with st.container(horizontal=True, key="catalog_options"):
            by_intensity = st.checkbox("Tamaño según intensidad (EF)", key="catalog_by_intensity")
            by_type = st.checkbox("Color según tipo de evento", key="catalog_by_type")
        fig = charts.catalog_map(
            cat, data.coast(charts.CATALOG_REGION), by_intensity=by_intensity, by_type=by_type
        )
        st.plotly_chart(fig, width="stretch", theme=None, key="catalog_map")
    with words:
        st.markdown(CATALOG_TEXT, unsafe_allow_html=True)
        st.markdown(
            "<p class='note'>Cada triángulo es un evento del catálogo, con solo los casos positivos. Pasa el cursor "
            "para ver su fecha, hora, posición, tipo, intensidad, fenómenos y víctimas. El tamaño y el color se "
            "activan con las casillas de arriba.</p>",
            unsafe_allow_html=True,
        )


def _chile() -> None:
    """Explica el régimen HSLC, el signo austral y los criterios propuestos para Chile."""
    _section(
        "chile",
        "Por qué Chile es distinto",
        "Según Vicencio et al. (2021), con el umbral clásico del STP, el índice de referencia en Estados Unidos, el brote de 2019 habría pasado inadvertido.",
    )
    _cards(
        "chile",
        [
            (
                "HSLC",
                "primary",
                "Poca energía, mucho viento",
                "En las Grandes Llanuras de Estados Unidos los tornados suelen formarse con varios miles de J/kg de CAPE, la energía disponible para que el aire suba. "
                "En mayo de 2019 el CAPE en Biobío estuvo entre 200 y 500 J/kg, pero el viento cambiaba mucho con la altura: entre 12 y 20 m/s de diferencia en el primer kilómetro. "
                "A esta combinación se le llama HSLC (*high shear, low CAPE*), y los índices de Estados Unidos no están calibrados para ella. "
                "En este régimen la rotación puede ser poco profunda y breve, lo que la hace difícil de detectar incluso con radar.",
            ),
            (
                "Hemisferio sur",
                "primary",
                "La rotación va al revés",
                "Aquí las supercélulas tornádicas suelen desviarse a la izquierda del viento medio (rama *left-mover*), y su helicidad relativa a la tormenta (SRH) es negativa. "
                "Las herramientas pensadas para el hemisferio norte, usadas tal cual, entregan índices con el signo cambiado. "
                "Multiplicar todo por −1 tampoco sirve: hay que elegir la rama y revisar la convención de cada índice.",
            ),
        ],
    )
    with st.container(border=True, key="sheet_cape"):
        _image(
            diagrams.cape_shear(),
            "Esquema de CAPE frente a cizalladura: los casos chilenos de mayo de 2019 combinan poca energía convectiva con mucho cambio del viento en el primer kilómetro.",
        )
        st.markdown(
            "<p class='note'>Esquema de CAPE frente a cizalladura de 0–1 km. Los casos de mayo de 2019 quedan en la zona de poca energía y mucho viento. "
            "A fines de mayo el CAPE medio en Biobío es de 15–45 J/kg, así que 500 J/kg es mucho para la zona aunque sea poco al lado de Estados Unidos. "
            "El esquema es ilustrativo y no marca un umbral de detección.</p>",
            unsafe_allow_html=True,
        )
    st.subheader("Criterios propuestos para Chile", anchor=False)
    st.markdown(
        "| Índice | Qué resume | Criterio |\n|---|---|---|\n"
        "| VGP₀₋₁ · parámetro de generación de vorticidad | CAPE y cambio del viento por unidad de altura en el primer kilómetro | > 0,1 m/s² en los cinco días tornádicos que analizaron Vicencio et al. (2021) |\n"
        "| SHERBE · índice para entornos de baja energía convectiva | Viento y perfil térmico | ≥ 1 (Marín et al. 2024) |\n"
        "| STP · parámetro significativo de tornado | Energía convectiva, viento y otras condiciones del entorno | ≤ −0,3 en la rama *left-mover* (Marín et al. 2024) |"
    )
    st.markdown(
        "Salen de estudios con pocos casos y sirven para comparar, no como umbrales operativos. El visor calcula SHERBS3, una variante de SHERBE con la cizalladura de 0–3 km, "
        "y una aproximación del STP, así que estos criterios no se aplican directamente a sus mapas."
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
        "Es una reconstrucción de cómo estaba la atmósfera cada hora desde 1940.\n\n"
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
        "<b>ERA5, 30 de mayo de 2019, 21:00 UTC.</b> Los paneles muestran temperatura a 500 hPa (A), viento a 850 hPa (B), cizalladura entre la superficie y 1 km (C) y entre la superficie y 6 km (D). Los niveles en hPa son superficies de presión que permiten comparar distintas partes de la atmósfera. En C y D se puede observar la extensión de las zonas con cizalladura elevada. La línea roja del panel C marca 12 m/s, la menor cizalladura de 0–1 km observada en el brote de 2019; la verde del panel D, 18 m/s. Los triángulos rojos son los tornados reportados.",
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
        "<b>GOES-16, banda 13, 30 de mayo de 2019, entre las 21:30 y las 21:50 UTC.</b> Los paneles muestran la temperatura de brillo y su cambio entre imágenes; los triángulos marcan los tornados reportados ese día. La temperatura de brillo es una medida derivada de la radiación infrarroja recibida. Un descenso puede ser compatible con crecimiento vertical, pero también puede deberse al desplazamiento de nubes sobre el mismo píxel. El flujo óptico estima ese movimiento y puede ayudar a separar ambos efectos.",
    )
    st.subheader("El catálogo de eventos", anchor=False)
    st.markdown(
        "Los 102 tornados y trombas del catálogo son los casos con que se comparan ERA5 y GOES. "
        "Qué trae cada registro y cuáles son sus límites está en la sección [El catálogo](#catalogo)."
    )
    st.page_link(
        state.page("data"),
        label="Abrir el catálogo de datos de cada variable",
        icon=":material/dataset:",
    )
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


def _volume() -> None:
    """Cuánto pesan los datos por día y por subconjunto, y por qué hay que trabajarlos dentro de AWS."""
    _section(
        "volumen",
        "El volumen de los datos",
        "Un día de ERA5 y GOES pesa decenas de gigabytes en origen y deja poco más de uno en disco. "
        "Por eso conviene recortar dentro de AWS.",
    )
    st.subheader("Un día de datos", anchor=False)
    st.markdown(
        "ERA5 guarda cada variable de niveles de presión en un archivo global, y el servidor no permite pedir "
        "solo Chile: cada hora es un bloque del planeta entero (50–65 MB) que hay que traer completo para "
        "recortarlo después. GOES publica el disco completo en cada imagen, 144 al día. Lo que queda "
        "guardado es una fracción de lo que se lee.\n\n"
        "| Conjunto | Tamaño en origen | A transferir | Queda guardado |\n"
        "|---|---|---|---|\n"
        "| ERA5, niveles de presión (8 variables) | ≈ 11 GB (8 archivos de ≈ 1,4 GB) | ≈ 11 GB | ≈ 64 MB |\n"
        "| ERA5, superficie (12 variables) | archivos mensuales | pocos MB | ≈ 3 MB |\n"
        "| GOES, 16 bandas a 2 km | ≈ 52 GB (144 imágenes de ≈ 360 MB) | ≈ 0,7 GB | ≈ 0,7 GB, más ≈ 0,75 GB reproyectado |\n"
        "| Índices de ERA5 | se calculan | — | ≈ 5 MB |\n"
        "| Catálogo de tornados | un archivo | 160 kB | 160 kB |\n"
        "| **Total por día** | **≈ 63 GB** | **≈ 12 GB** | **≈ 1,5 GB** |"
    )
    st.caption(
        "Medido: lo que queda guardado, con los recortes del 30 y 31 de mayo de 2019 y el catálogo, y el "
        "tamaño por archivo que documenta el proyecto. Estimado: lo que transfiere GOES (solo los bloques "
        "que tocan la región, del orden de lo que se guarda) y la superficie de ERA5."
    )
    st.subheader("Los subconjuntos que importan", anchor=False)
    st.markdown(
        "Cuánto hay que leer depende de qué días se necesiten. El catálogo tiene 70 días distintos con "
        "algún tornado o tromba desde 1940, el inicio de ERA5, y 38 desde 2018, cuando GOES-16 ya operaba. Un modelo "
        "también necesita días sin tornado, que el catálogo no trae; la fila de controles supone, como "
        "ejemplo, diez días de control por cada día con evento. Cómo elegirlos es una decisión abierta "
        "(véase «Decisiones abiertas»): días al azar en la época de los tornados, y unos pocos elegidos a mano "
        "(lluvia, cielo despejado, tormenta sin tornado) como puntos de comparación.\n\n"
        "| Subconjunto | Días | ERA5 a transferir | GOES a transferir | Queda guardado |\n"
        "|---|---|---|---|---|\n"
        "| Un día | 1 | 11 GB | 0,7 GB | 1,5 GB |\n"
        "| Caso de estudio (30 y 31 de mayo de 2019) | 2 | 22 GB | 1,4 GB | 3 GB |\n"
        "| Días con evento, era GOES (desde 2018) | 38 | 418 GB | 27 GB | 57 GB |\n"
        "| Días con evento, era ERA5 (desde 1940) | 70 | 770 GB | 27 GB (solo los 38 con GOES) | 59 GB |\n"
        "| Casos y controles, era GOES (supuesto: 10 controles por caso) | 418 | 4,6 TB | 293 GB | 627 GB |\n"
        "| Un año completo | 365 | 4,0 TB | 256 GB | 548 GB |\n"
        "| Diez años (GOES existe en unos 8) | 3 650 | 40 TB | 2,1 TB | 4,4 TB |"
    )
    st.subheader("Cuánto tarda traerlo", anchor=False)
    st.markdown(
        "ERA5 domina el tiempo: es casi todo lo que se transfiere. La tabla cuenta solo su transferencia, "
        "con el enlace lleno todo el rato, así que son tiempos mínimos. Para AWS se supone 1 Gbps "
        "sostenido, lo que alcanza una instancia pequeña en la misma región que los datos; instancias más "
        "grandes y varias en paralelo lo reducen.\n\n"
        "| Subconjunto | Desde un computador con 100 Mbps | Dentro de AWS (1 Gbps) |\n"
        "|---|---|---|\n"
        "| Un día | 15 min | 1,5 min |\n"
        "| Caso de estudio | 29 min | 3 min |\n"
        "| 38 días con evento | 9 h | 56 min |\n"
        "| Casos y controles | 4,3 días | 10 h |\n"
        "| Un año completo | 3,7 días | 9 h |\n"
        "| Diez años | 37 días | 3,7 días |"
    )
    st.subheader("Qué se hace dónde", anchor=False)
    st.markdown(
        "Traer a un computador personal lo que hay que leer no tiene sentido: el tiempo se va en la red y "
        "no en el análisis. Leer ERA5 y GOES y recortarlos es el trabajo que tiene que ocurrir dentro de AWS, "
        "porque no hay forma de pedirle menos al servidor. Una vez hechos los recortes, el volumen cae "
        "unas 40 veces y ya es manejable.\n\n"
        "| Etapa | Dónde | Por qué |\n"
        "|---|---|---|\n"
        "| Leer ERA5 y GOES y recortar la región | AWS, en la región de cada bucket | ≈ 12 GB por día que no se pueden reducir antes de leerlos |\n"
        "| Calcular índices y armar los ejemplos | AWS, junto a los recortes | Los recortes de un año pesan ≈ 0,5 TB |\n"
        "| Entrenar y evaluar el modelo | AWS | Lee los recortes completos varias veces |\n"
        "| Explorar un caso en el visor | En cualquier computador | Un caso son unos 3 GB de recortes |\n\n"
        "Starter kit dice en qué región conviene trabajar y cómo correr los scripts ahí."
    )
    st.page_link(
        state.page("starter"),
        label="Ver los buckets y los scripts en Starter kit",
        icon=":material/rocket_launch:",
    )


def _participate() -> None:
    """Propone tareas para quien quiera participar."""
    _section(
        "participar",
        "Por dónde empezar",
        "El proyecto está abierto a cualquier persona interesada. Para aportar no hace falta formación en meteorología.",
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


_GLOSSARY = (
    ("Banda (ABI)", "Cada una de las 16 longitudes de onda en que mide el satélite GOES; unas ven la luz reflejada y otras, el calor que emiten las nubes."),
    ("CAPE", "Energía disponible para que una burbuja de aire suba por flotación. Más CAPE permite corrientes ascendentes más fuertes."),
    ("CIN", "Barrera de energía que impide que el aire empiece a subir. Hay que vencerla para que se forme una tormenta."),
    ("Cizalladura", "Cambio del viento con la altura, en velocidad o dirección. Organiza la rotación dentro de una tormenta."),
    ("Control", "Día o situación sin tornado conocido que se usa para comparar con los casos."),
    ("ERA5", "Reanálisis atmosférico del ECMWF: reconstruye cómo estaba la atmósfera cada hora desde 1940."),
    ("Flujo óptico", "Técnica que estima el movimiento entre dos imágenes consecutivas."),
    ("GOES", "Satélites geoestacionarios de la NOAA; GOES-East observa Chile cada 10 minutos."),
    ("HSLC", "Régimen de poca energía (CAPE baja) y mucha cizalladura, frecuente en los tornados de Chile. Los umbrales norteamericanos no sirven aquí."),
    ("hPa y nivel de presión", "La atmósfera se describe por niveles de presión: 850 hPa está a unos 1,5 km de altura y 500 hPa, a unos 5,5 km."),
    ("Left-mover", "Tormenta que se desvía a la izquierda del viento medio. En el hemisferio sur es la rama favorecida y gira en sentido horario."),
    ("Mesociclón", "Rotación organizada dentro de una tormenta, de 2 a 10 km de diámetro."),
    ("Paralaje", "Desplazamiento aparente de un tope nuboso por verlo de lado desde el satélite: unos 21 km a 53°S para un tope de 12 km."),
    ("Reanálisis", "Reconstrucción del estado de la atmósfera que combina un modelo con observaciones, repetida con el mismo método para todo el período."),
    ("SRH, VGP, SHERBE y STP", "Índices que combinan viento y energía para señalar entornos favorables a tormentas con rotación. Cada uno tiene su ficha en Datos."),
    ("Subregistro", "Eventos que ocurrieron y no quedaron en el catálogo porque nadie los vio o los reportó."),
    ("Supercélula", "Tormenta con un mesociclón persistente."),
    ("Temperatura de brillo", "Temperatura equivalente a la radiación infrarroja que recibe el satélite. Cuanto más fría, más alto el tope de la nube."),
    ("Tope penetrante", "Cúpula que sobresale del yunque cuando la corriente ascendente pasa la tropopausa."),
    ("Tornado y tromba marina", "Columna de aire en rotación en contacto con el suelo (tornado) o con el agua (tromba). La escala EF mide su intensidad."),
    ("Tropopausa", "Límite entre la troposfera, donde ocurre el tiempo, y la estratosfera."),
    ("Yunque", "Parte alta de la nube de tormenta, que se extiende horizontalmente al llegar a una capa estable cerca de la tropopausa y suele tener cristales de hielo."),
)  # fmt: skip


def _glossary() -> None:
    """Anexo con los términos que el texto usa sin definir en cada mención."""
    _section(
        "glosario",
        "Anexo: glosario",
        "Los términos técnicos de esta página, en orden alfabético. Cada variable tiene además su ficha en Datos.",
    )
    st.markdown("\n".join(f"- **{term}.** {text}" for term, text in _GLOSSARY))


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
            _objective()
            _importance()
            _animation()
            _chile()
            _catalog()
            _data_section()
            _volume()
            _decisions()
            _participate()
            _glossary()
        with st.container(width=220, key="toc_side"):
            st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(_toc(), unsafe_allow_html=True)
