"""Página «El proyecto»: la presentación del proyecto con elementos de Streamlit.

Los dos diagramas viven en ``diagramas.py``. Esta página no usa datos: se muestra aunque no haya recortes.
"""

from typing import Literal

import streamlit as st

import comun
from visor_app import diagramas

DOCUMENTO = "https://github.com/fforster/aws-mesocyclonic/blob/main/docs/mesociclones_chile.md"
REPOSITORIO = "https://github.com/fforster/aws-mesocyclonic"
CATALOGO = "https://doi.org/10.6084/m9.figshare.25119566"
FIGS = comun.ROOT / "figs"
Color = Literal["orange", "primary"]
# Secciones del índice: (ancla del encabezado, texto del enlace).
SECCIONES = (
    ("inicio", "Inicio"),
    ("mesociclones", "Mesociclones"),
    ("problema", "El problema"),
    ("dificultad", "Por qué es difícil"),
    ("datos", "Los datos"),
    ("participar", "Participar"),
)


def _antetitulo(texto: str) -> None:
    """Rótulo corto en mayúsculas sobre el título de una sección."""
    st.markdown(f"<p class='antetitulo'>{texto}</p>", unsafe_allow_html=True)


def _seccion(ancla: str, antetitulo: str, titulo: str, bajada: str) -> None:
    """Encabezado de sección: rótulo, título con ``ancla`` para el índice y una frase de contexto."""
    st.divider()
    _antetitulo(antetitulo)
    st.header(titulo, anchor=ancla)
    st.markdown(f"<p class='lede'>{bajada}</p>", unsafe_allow_html=True)


def _enlaces(clave: str) -> None:
    """Botones al documento completo y al repositorio."""
    with st.container(horizontal=True, gap="small"):  # cada botón a su ancho; se parten si no caben
        st.link_button("Leer el documento completo", DOCUMENTO, key=f"{clave}_doc", type="primary",
                       icon=":material/description:")  # fmt: skip
        st.link_button("Repositorio", REPOSITORIO, key=f"{clave}_repo", icon=":material/code:")


def _tarjetas(clave: str, tarjetas: list[tuple[str, Color, str, str]], n_columnas: int = 2) -> None:
    """Tarjetas en una grilla: (insignia, color de la insignia, título, texto).

    La grilla la arma el CSS de ``tema.py`` (clave ``tarjetas<n>_``): ``n_columnas`` con ancho de sobra
    y menos columnas cuando la página es angosta, en vez de columnas que solo se apilan en teléfono.
    """
    with st.container(horizontal=True, key=f"tarjetas{n_columnas}_{clave}"):
        for i, (insignia, color, titulo, texto) in enumerate(tarjetas):
            _tarjeta(f"hoja_{clave}_{i}", insignia, color, titulo, texto)


def _tarjeta(clave: str, insignia: str, color: Color, titulo: str, texto: str) -> None:
    """Una tarjeta con borde: insignia, título en negrita y texto."""
    with st.container(border=True, key=clave):
        st.badge(insignia, color=color)
        st.markdown(f"**{titulo}**")
        st.markdown(texto)


def _portada() -> None:
    """Presenta el objetivo, las referencias del caso y los enlaces."""
    _antetitulo("Proyecto abierto · AWS Hackathon")
    st.title("Predicción de tormentas mesociclónicas en el centro-sur de Chile", anchor="inicio")
    st.markdown(
        '<p class="lede">Un desafío de análisis de datos meteorológicos para estudiar qué tormentas pueden desarrollar rotación organizada.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p>El catálogo utilizado por el proyecto reúne 102 eventos de tornados y trombas marinas entre 1554 y 2025. Los registros dependen de las observaciones y los reportes disponibles, por lo que pueden faltar eventos.</p>\n<p>El objetivo del proyecto es estimar qué tormentas del centro-sur de Chile pueden desarrollar un mesociclón mediante datos de ERA5 y GOES. También se propone explorar el archivo histórico para identificar situaciones que merezcan una revisión por posible subregistro.</p>",
        unsafe_allow_html=True,
    )
    cifras = (("102", "eventos catalogados, 1554–2025", ""), ("7", "tornados en 24 h, mayo 2019", " sev"),
              ("10 min", "frecuencia nominal de GOES", ""), ("0", "registros al sur de 42,4°S", ""))  # fmt: skip
    celdas = "".join(
        f"<div class='cifra{c}'><b>{v}</b><span>{r}</span></div>" for v, r, c in cifras
    )
    st.markdown(f"<div class='cifras'>{celdas}</div>", unsafe_allow_html=True)
    _enlaces("portada")


def _animacion() -> None:
    """Mesociclogénesis en cuatro etapas: el usuario elige la etapa; los rodillos giran solos."""
    st.subheader("Mesociclones, supercélulas y tornados", anchor="mesociclones")
    st.markdown(
        "Un mesociclón es una región de aire en rotación organizada dentro de una tormenta, de unos 2 a 10 km de diámetro. Una tormenta con un mesociclón persistente se denomina supercélula. Un tornado es un fenómeno de menor escala cuya circulación alcanza la superficie. Una supercélula puede desarrollar un tornado, pero esa evolución no es inevitable.",
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="hoja_animacion"):
        st.subheader("Cómo se organiza la rotación dentro de una tormenta", anchor=False)
        st.caption("Formación de un mesociclón: esquema simplificado en cuatro etapas")
        etapa = st.segmented_control(
            "Etapa", [1, 2, 3, 4], default=1, key="proyecto_etapa", label_visibility="collapsed",
            format_func=lambda k: ("Cizalladura", "Inclinación", "Estiramiento", "Mesociclón")[k - 1],
        )  # fmt: skip
        etapa = etapa or 1
        st.image(diagramas.mesociclon(etapa), width="stretch")
        titulo, texto = diagramas.ETAPAS[etapa - 1]
        st.markdown(f"**:primary[{titulo}]**")
        st.markdown(texto)
        st.markdown(
            '<p class="nota">El esquema muestra cómo la rotación horizontal del entorno puede contribuir a la rotación dentro de una tormenta. La formación de un tornado requiere procesos adicionales cerca de la superficie; un mesociclón puede persistir sin producirlo.</p>',
            unsafe_allow_html=True,
        )


def _problema() -> None:
    """Explica el caso de referencia y las limitaciones del catálogo."""
    _seccion(
        "problema",
        "El problema",
        "Un catálogo de eventos reportados, sin casos negativos confirmados",
        "Disponemos de registros de tornados y trombas marinas. La ausencia de un reporte no permite asegurar que no ocurrió un evento.",
    )
    st.markdown(
        '<p>El <strong>30 y 31 de mayo de 2019</strong>, siete tornados golpearon en menos de 24 horas la zona entre Ñuble y La Araucanía. Dos entraron en ciudades: <strong>Los Ángeles</strong> (EF2) y <strong>Talcahuano–Concepción</strong> (EF1–EF2, 17 km de trayecto, una persona fallecida, 50.000 clientes sin electricidad). La escala Fujita mejorada (EF) clasifica la intensidad según los daños observados. Este episodio es el caso de referencia del proyecto para estudiar las condiciones atmosféricas asociadas a los tornados del centro-sur de Chile.</p>\n<p>Existe un catálogo formal y publicado: la base <a href="https://doi.org/10.6084/m9.figshare.25119566">Tornadoes and Waterspouts in Chile</a> (Bastías-Curivil, Rondanelli, Vicencio et al., CC BY 4.0), con <strong>102 eventos entre 1554 y 2025</strong>. Incluye tornados, trombas marinas y eventos clasificados en ambas categorías. Según el resumen disponible, todos tienen coordenadas y el 89 % tiene hora UTC, un dato necesario para compararlos con imágenes satelitales. UTC significa tiempo universal coordinado y puede diferir de la hora local de Chile.</p>\n<p>En la copia del catálogo usada aquí, 70 registros están marcados como tornado, 45 como tromba marina y 19 en ambas categorías. Otros 6 no están marcados en ninguna de las dos; su clasificación debe revisarse. Los conteos de tornados y trombas se solapan y no deben sumarse para obtener el total.</p>\n<p>La cobertura del catálogo depende de que los eventos hayan sido observados, documentados e incorporados a la base. Esto puede favorecer los registros de zonas pobladas y dejar menos información sobre zonas rurales, el mar o eventos nocturnos. Es un sesgo de reporte que debe considerarse al analizar los datos. El catálogo no contiene registros al sur de los 42,4°S; esa ausencia no confirma que allí no hayan ocurrido eventos.</p>\n<p>Una línea de trabajo consiste en identificar días y lugares con condiciones similares a las de eventos documentados. Esos resultados serían candidatos para una revisión posterior; la similitud del entorno no confirma que haya ocurrido un tornado ni que se haya formado un mesociclón.</p>',
        unsafe_allow_html=True,
    )


def _dificultad() -> None:
    """Presenta las decisiones de cálculo y las referencias que deben validarse."""
    _seccion(
        "dificultad",
        "Por qué es difícil",
        "Tres aspectos que deben adaptarse al contexto chileno",
        "El régimen atmosférico, el sentido de rotación y la cobertura del catálogo condicionan el cálculo de índices y el entrenamiento de modelos.",
    )
    _tarjetas(
        "dificultad",
        [
            (
                "1",
                "orange",
                "Los umbrales deben evaluarse con datos chilenos",
                "Los casos descritos presentan fuerte cambio del viento con la altura y energía convectiva relativamente baja. Este régimen se denomina HSLC, por sus siglas en inglés (high shear, low CAPE: fuerte cizalle y bajo CAPE). La energía potencial convectiva disponible (CAPE) mide la energía disponible para el ascenso del aire. Los índices combinan estas y otras variables para resumir el entorno.",
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
        n_columnas=3,
    )
    st.subheader("Referencias de los índices", anchor=False)
    st.markdown(
        "| Índice | Qué resume | Referencia citada en el documento |\n|---|---|---|\n| VGP₀₋₁ · parámetro de generación de vorticidad | Combina CAPE y cambio del viento por unidad de altura en el primer kilómetro | > 0,1 m/s² en los cinco días tornádicos analizados por Vicencio et al. (2021) |\n| SHERBE · índice de entornos con baja energía convectiva | Combina características del viento y del perfil térmico | ≥ 1; referencia de Marín et al. (2024) |\n| STP · parámetro significativo de tornado | Combina energía convectiva, viento y otras condiciones del entorno | Rama left-mover ≤ −0,3; referencia de Marín et al. (2024) |"
    )
    st.markdown(
        "Estos valores orientan la comparación con los estudios citados. Requiere verificación: confirmar las variantes y el alcance de cada criterio antes de usarlo como umbral operativo. El visor calcula SHERBS3, una variante distinta de SHERBE, y una aproximación del STP; no deben trasladarse los criterios entre variantes sin validación.",
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="hoja_cape"):
        st.image(diagramas.cape_cizalle(), width="stretch")
        st.markdown(
            "Comparación esquemática de CAPE y cizalle; no representa una frontera de detección del STP. Los casos chilenos de mayo de 2019 combinan CAPE relativamente bajo con fuerte cizalle en el primer kilómetro. La referencia de 15–45 J/kg corresponde al CAPE medio a fines de mayo en Biobío descrito en el documento. Requiere verificación: confirmar las fuentes y el ámbito de las referencias del esquema antes de utilizarlas en una decisión."
        )
    st.markdown(
        '<div class="aviso">Caballero-Morán y Rondanelli (2025) analizaron índices derivados de ERA5 entre 1959 y 2021. El documento del proyecto les atribuye la identificación de zonas del sur austral con condiciones favorables y sin eventos documentados. Este resultado motiva la búsqueda de posibles situaciones subregistradas. <strong>Requiere verificación:</strong> comprobar que esta formulación refleje el alcance del estudio; unas condiciones favorables no confirman un evento ocurrido.</div>',
        unsafe_allow_html=True,
    )


def _datos() -> None:
    """Describe los datos del visor y separa sus límites del acceso técnico."""
    _seccion(
        "datos",
        "Los datos",
        "Tres fuentes de datos para estudiar las tormentas",
        "ERA5 es una reconstrucción histórica del estado de la atmósfera que combina observaciones y un modelo. GOES aporta imágenes satelitales para observar las nubes y su evolución. El catálogo aporta los eventos reportados con los que se comparan esos datos.",
    )
    st.subheader("Datos usados por el visor", anchor=False)
    st.markdown(
        "| Fuente | Qué aporta | Resolución o cobertura |\n|---|---|---|\n| ERA5 | Viento, temperatura, humedad y altura de los niveles atmosféricos, además de CAPE y la inhibición convectiva (CIN), la barrera energética para iniciar el ascenso | 0,25° · registros horarios |\n| GOES-16 · caso de 2019 | Imágenes de 16 bandas del visible al infrarrojo. Los recortes utilizados por el visor se guardan a 2 km | 2 km · frecuencia nominal de 10 min |\n| Catálogo · figshare, CC BY 4.0 | 102 eventos con coordenadas, hora UTC cuando está disponible, tipo y clasificación EF basada en daños cuando está disponible. No proporciona una etiqueta directa de mesociclón | 1554–2025 · 102 eventos |"
    )
    st.markdown(
        "ERA5 describe el entorno a una escala de unos 31 km, por lo que no representa directamente un mesociclón. Las imágenes GOES pueden mostrar las nubes desplazadas respecto de su posición real por el ángulo de observación; este efecto se llama paralaje. El visor todavía no aplica una corrección de paralaje.",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Los 102 registros históricos no equivalen a 102 casos comparables con GOES. El conjunto analizable depende de que coincidan la cobertura temporal de las fuentes, las coordenadas y una hora suficientemente precisa del evento."
    )
    with st.expander("Acceso y procesamiento de los archivos"):
        st.markdown(
            "- Los scripts del proyecto acceden a ERA5 en `s3://nsf-ncar-era5/`; no utilizan el archivo antiguo `era5-pds`. Los campos incluyen los códigos `u, v, w, t, q, z`.\n- Un archivo global de nivel de presión ocupa aproximadamente 1,4 GB por variable y día. Los scripts leen rangos de bytes y recortan los datos después de la lectura; no hay recorte en el servidor.\n- El caso de 2019 usa `s3://noaa-goes16/`. Para otros períodos hay que comprobar qué satélite y archivo corresponden.\n- Requiere verificación: confirmar la cobertura temporal de cada archivo antes de planificar una descarga. La cobertura general de ERA5 no debe confundirse con la del archivo S3 usado por el proyecto.\n- El producto de altura de tope nuboso ACHAF se menciona como una opción para estudiar la corrección de paralaje; hay que verificar su compatibilidad antes de incorporarlo."
        )
    with st.expander("Otros productos que podrían incorporarse"):
        st.markdown(
            "Los productos de altura y fase del tope nuboso, vientos derivados y rayos se describen como posibles fuentes adicionales. No forman parte de las imágenes multibanda que lee este visor. Requiere verificación: confirmar su disponibilidad, resolución y compatibilidad con el período seleccionado antes de incorporarlos."
        )
    st.subheader("Datos del caso de mayo de 2019", anchor=False)
    st.markdown(
        "Las figuras siguientes se generaron con datos de los archivos públicos para el 30 de mayo de 2019. Las páginas Mapas, Sondeo y Series exploran el mismo caso."
    )
    figuras = [
        (
            "fig4_era5_20190530.png",
            "<b>ERA5, 30 de mayo de 2019, 21:00 UTC.</b> Los paneles muestran temperatura a 500 hPa (A), viento a 850 hPa (B), cizalle entre la superficie y 1 km (C) y entre la superficie y 6 km (D). Los niveles en hPa son superficies de presión que permiten comparar distintas partes de la atmósfera. En C y D se puede observar la extensión de las zonas con cizalle elevado.",
        ),
        (
            "fig3_goes_20190530.png",
            "<b>GOES-16, banda 13.</b> Los paneles muestran la temperatura de brillo y su cambio entre imágenes; los triángulos marcan los tornados reportados ese día. La temperatura de brillo es una medida derivada de la radiación infrarroja recibida. Un descenso puede ser compatible con crecimiento vertical, pero también puede deberse al desplazamiento de nubes sobre el mismo píxel. El flujo óptico estima ese movimiento y puede ayudar a separar ambos efectos.",
        ),
    ]
    for archivo, pie in figuras:
        with st.container(border=True, key=f"hoja_{archivo[:4]}"):
            st.image(str(FIGS / archivo), width="stretch")
            st.markdown(f"<p class='nota'>{pie}</p>", unsafe_allow_html=True)


def _participar() -> None:
    """Propone tareas y hace explícitas las decisiones pendientes de la hackathon."""
    _seccion(
        "participar",
        "Participar",
        "Por dónde empezar",
        "El proyecto está abierto a cualquier persona interesada, con o sin formación en meteorología.",
    )
    _tarjetas(
        "tareas",
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
        unsafe_allow_html=True,
    )
    st.subheader("Por definir para la hackathon", anchor=False)
    st.markdown(
        "La organización debe precisar qué parte del objetivo general corresponde a la hackathon y qué resultado se espera de los equipos. Los siguientes puntos están pendientes de definición; no constituyen requisitos confirmados.",
        unsafe_allow_html=True,
    )
    st.markdown(
        "- Unidad de predicción: qué representa cada caso que debe analizar el modelo.\n- Horizonte temporal: con cuánta anticipación se busca estimar el desarrollo del mesociclón.\n- Forma de validar mesociclones con las evidencias disponibles; el catálogo etiqueta tornados y trombas, no mesociclones.\n- Resultado que debe presentar cada equipo, criterios de evaluación y requisitos de uso de AWS."
    )
    _enlaces("participar")
    st.divider()
    st.markdown(
        f"<p class='nota'>Catálogo de eventos: Bastías-Curivil et al. (2024–2025), <a href='{CATALOGO}'>"
        "<em>Tornadoes and Waterspouts in Chile</em></a>, figshare, CC BY 4.0. Fuentes principales: "
        "Vicencio et al. (2021, <em>BAMS</em>) · Marín et al. (2024, <em>MWR</em>) · Barrett et al. "
        "(2020, <em>Atmos. Res.</em>) · Caballero-Morán &amp; Rondanelli (2025, <em>GRL</em>). La lista "
        "completa está en el documento. Datos: ERA5 (ECMWF / Copernicus) y GOES-R (NOAA / NASA), ambos en "
        "el AWS Open Data Program.</p>",
        unsafe_allow_html=True,
    )


def _indice() -> str:
    """El índice de la página como lista de enlaces a las anclas de ``SECCIONES``."""
    enlaces = "".join(f"<li><a href='#{ancla}'>{texto}</a></li>" for ancla, texto in SECCIONES)
    return f"<nav class='indice' aria-label='En esta página'><ol>{enlaces}</ol></nav>"


def pagina() -> None:
    """Dibuja el índice y el cuerpo de la página.

    Con ancho de sobra el índice va en una columna fija a la izquierda; en pantallas más angostas
    (tablet, teléfono) se ve un desplegable sobre el cuerpo. El CSS de ``tema.py`` elige cuál mostrar
    según el ancho de ``.st-key-proyecto``.
    """
    with st.container(key="proyecto"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(width=220, key="indice_lateral"):
            _antetitulo("En esta página")
            st.markdown(_indice(), unsafe_allow_html=True)
        with st.container(key="proyecto_cuerpo"):
            with st.expander("En esta página", key="indice_compacto", icon=":material/toc:"):
                st.markdown(_indice(), unsafe_allow_html=True)
            _portada()
            _animacion()
            _problema()
            _dificultad()
            _datos()
            _participar()
