"""Catálogo de datos: una ficha por variable de las tres fuentes (ERA5, GOES, catálogo) y sus derivados.

Es la fuente única de los textos por variable: la página Datos dibuja todas las fichas y la página
Mapas toma de aquí su ayuda en contexto. Todo sale de las secciones 4 y 5 de
``docs/mesociclones_chile.md`` y de las fórmulas de ``process_era5.py`` y ``layers.py``; si cambia el
documento o un cálculo, hay que corregirlo aquí. Las fórmulas van en LaTeX (KaTeX de Streamlit).
"""

import unicodedata
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Source:
    """Una de las fuentes de datos: abre su parte de la página con lo que es y sus límites."""

    key: str  # ancla de la sección
    title: str
    lede: str  # una frase: qué aporta al proyecto
    facts: tuple[tuple[str, str], ...]  # (rasgo, valor): resolución, cobertura, acceso
    limits: str  # markdown: lo que esta fuente no puede hacer
    refs: tuple[str, ...] = ()  # claves de ``REFERENCES``


@dataclass(frozen=True)
class Group:
    """Un grupo de fichas dentro de una fuente (crudos de presión, derivados cinemáticos, …)."""

    key: str  # ancla del grupo
    source: str  # clave de ``SOURCES``
    title: str
    lede: str
    compact: bool = False  # fichas breves en dos columnas (campos crudos, bandas, columnas)
    refs: tuple[str, ...] = ()  # fuentes comunes a las fichas del grupo


@dataclass(frozen=True)
class Variable:
    """La ficha de una variable: qué es, por qué importa, cómo se calcula y qué cuidar."""

    key: str  # ancla de la ficha y valor de ``?v=`` en la URL
    symbol: str  # cómo se escribe en el visor: «VGP₀₋₁», «C13», «Register»
    name: str
    unit: str  # «» si no tiene
    group: str  # clave de ``GROUPS``
    what: str  # markdown; la primera oración debe bastar como definición
    why: str = ""  # por qué sirve para estudiar mesociclones
    formula: str = ""  # LaTeX, sin delimitadores
    # markdown que acompaña a la fórmula: términos, constantes, cómo lo hace el visor
    method: str = ""
    # criterio calibrado para Chile que cita el documento (lleva el triángulo rojo)
    threshold: str = ""
    caveat: str = ""  # trampa austral o límite de la variable
    inputs: tuple[str, ...] = ()  # claves de otras fichas de las que se calcula
    products: tuple[str, ...] = ()  # claves de ``products.catalog`` que la muestran en Mapas
    level: float | None = None  # hPa con que abrir el panel si el producto es de presión
    synonyms: str = ""  # palabras extra para el buscador
    # claves de ``REFERENCES`` propias de la ficha (se suman a las del grupo)
    refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reference:
    """Una fuente citada: la cita corta de las fichas y la completa de la bibliografía."""

    short: str  # «Vicencio et al. (2021)»
    full: str  # markdown
    url: str = ""


# Todas salen de la sección 10 de docs/, salvo Bunkers (2000), citado en ``process_era5.py``, Thompson
# et al. (2012), de quien es el STP de capa fija que calcula el visor, y la formulación del BRN, que el
# documento nombra sin citar. Los DOI se verificaron contra doi.org (octubre de 2026).
REFERENCES = {
    "era5-ncar": Reference(
        "NSF NCAR (ERA5 en AWS)",
        "ERA5 en AWS, NSF NCAR. `s3://nsf-ncar-era5/` (us-west-2). DOI 10.5065/BH6N-5N20.",
        "https://doi.org/10.5065/BH6N-5N20",
    ),
    "era5-doc": Reference(
        "Documentación de ERA5 (ECMWF)",
        "ECMWF. *ERA5: data documentation*.",
        "https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation",
    ),
    "hersbach2020": Reference(
        "Hersbach et al. (2020)",
        "Hersbach, H. et al. (2020). The ERA5 global reanalysis. *QJRMS*, 146, 1999–2049.",
        "https://doi.org/10.1002/qj.3803",
    ),
    "goes-aws": Reference(
        "NOAA GOES en AWS",
        "NOAA. GOES en el AWS Open Data Program: `s3://noaa-goes16/`, `s3://noaa-goes19/` (us-east-1).",
        "https://registry.opendata.aws/noaa-goes/",
    ),
    "goes-abi": Reference(
        "Especificaciones del ABI (goes-r.gov)",
        "NOAA/NASA. *Advanced Baseline Imager* y *Geostationary Lightning Mapper*, goes-r.gov.",
        "https://www.goes-r.gov/spacesegment/abi.html",
    ),
    "bastias": Reference(
        "Bastías-Curivil et al. (2024–2025)",
        "Bastías-Curivil, C., Rondanelli, R., Vicencio, J. et al. (2024–2025). *Tornadoes and "
        "Waterspouts in Chile / Tornados y Trombas en Chile*. figshare, v5. CC BY 4.0.",
        "https://doi.org/10.6084/m9.figshare.25119566",
    ),
    "vicencio2021": Reference(
        "Vicencio et al. (2021)",
        "Vicencio, J., Rondanelli, R., Campos, D. et al. (2021). The Chilean Tornado Outbreak of May "
        "2019: Synoptic, Mesoscale, and Historical Contexts. *BAMS*, 102(3), E611–E634.",
        "https://doi.org/10.1175/BAMS-D-19-0218.1",
    ),
    "barrett2020": Reference(
        "Barrett et al. (2020)",
        "Barrett, B. S., Marín, J. C. & Jacques-Coper, M. (2020). A multiscale analysis of the tornadoes "
        "of 30–31 May 2019 in south-central Chile. *Atmospheric Research*, 236, 104811.",
        "https://doi.org/10.1016/j.atmosres.2019.104811",
    ),
    "marin2024": Reference(
        "Marín et al. (2024)",
        "Marín, J. C., Gutiérrez, F., Gensini, V. A. et al. (2024). Climatological Aspects of Notable "
        "Tornado Events in Chile. *Monthly Weather Review*, 152(8), 1803–1819.",
        "https://doi.org/10.1175/MWR-D-23-0249.1",
    ),
    "caballero2025": Reference(
        "Caballero-Morán y Rondanelli (2025)",
        "Caballero-Morán, V. & Rondanelli, R. (2025). Tornado Seasonality in Central-Southern Chile. "
        "*Geophysical Research Letters*, 52, e2024GL110900.",
        "https://doi.org/10.1029/2024GL110900",
    ),
    "sherburn2014": Reference(
        "Sherburn y Parker (2014)",
        "Sherburn, K. D. & Parker, M. D. (2014). Climatology and ingredients of significant severe "
        "convection in high-shear, low-CAPE environments. *Weather and Forecasting*, 29, 854–877.",
        "https://doi.org/10.1175/WAF-D-13-00041.1",
    ),
    "thompson2003": Reference(
        "Thompson et al. (2003)",
        "Thompson, R. L. et al. (2003). Close proximity soundings within supercell environments "
        "obtained from the Rapid Update Cycle. *Weather and Forecasting*, 18, 1243–1261. Formulación "
        "original del STP y del SCP.",
        "https://doi.org/10.1175/1520-0434(2003)018<1243:CPSWSE>2.0.CO;2",
    ),
    "thompson2012": Reference(
        "Thompson et al. (2012)",
        "Thompson, R. L., Smith, B. T., Grams, J. S., Dean, A. R. & Broyles, C. (2012). Convective modes "
        "for significant severe thunderstorms in the contiguous United States. Part II: Supercell and "
        "QLCS tornado environments. *Weather and Forecasting*, 27, 1136–1154. STP de capa fija y SCP "
        "de capa efectiva.",
        "https://doi.org/10.1175/WAF-D-11-00116.1",
    ),
    "rasmussen1998": Reference(
        "Rasmussen y Blanchard (1998)",
        "Rasmussen, E. N. & Blanchard, D. O. (1998). A baseline climatology of sounding-derived "
        "supercell and tornado forecast parameters. *Weather and Forecasting*, 13, 1148–1164. "
        "Formulación original del VGP.",
        "https://doi.org/10.1175/1520-0434(1998)013<1148:ABCOSD>2.0.CO;2",
    ),
    "bunkers2000": Reference(
        "Bunkers et al. (2000)",
        "Bunkers, M. J. et al. (2000). Predicting supercell motion using a new hodograph technique. "
        "*Weather and Forecasting*, 15, 61–79.",
        "https://doi.org/10.1175/1520-0434(2000)015<0061:PSMUAN>2.0.CO;2",
    ),
    "weisman1982": Reference(
        "Weisman y Klemp (1982)",
        "Weisman, M. L. & Klemp, J. B. (1982). The dependence of numerically simulated convective storms "
        "on vertical wind shear and buoyancy. *Monthly Weather Review*, 110, 504–520. Formulación del BRN.",
        "https://doi.org/10.1175/1520-0493(1982)110<0504:TDONSC>2.0.CO;2",
    ),
    "markowski2010": Reference(
        "Markowski y Richardson (2010)",
        "Markowski, P. & Richardson, Y. (2010). *Mesoscale Meteorology in Midlatitudes*. Wiley.",
    ),
    "metpy": Reference("MetPy", "Unidata. *MetPy*: cálculo de índices termodinámicos y cinemáticos.",
                        "https://unidata.github.io/MetPy/"),
    "documento": Reference(
        "Documento del proyecto",
        "*Predicción de tormentas mesociclónicas en Chile*, `docs/mesociclones_chile.md`, secciones 4 y 5.",
        "https://github.com/fforster/aws-mesocyclonic/blob/main/docs/mesociclones_chile.md",
    ),
}  # fmt: skip

SOURCES = (
    Source(
        "era5",
        "ERA5 · el entorno",
        "Un reanálisis: el estado completo de la atmósfera, hora por hora desde 1940, reconstruido con "
        "un modelo que combina las observaciones históricas disponibles. Describe el escenario en el que una "
        "tormenta puede organizarse o no.",
        (
            ("Resolución", "0,25° × 0,25° distribuida (~31 km nativa) · horaria"),
            ("Vertical", "37 niveles de presión, de 1000 a 1 hPa"),
            (
                "Cobertura",
                "enero 1940 – presente; versión preliminar ERA5T con ~5 días de latencia",
            ),
            ("Acceso", "`s3://nsf-ncar-era5/` (us-west-2, anónimo); `era5-pds` está deprecado"),
            (
                "En el visor",
                "recortes diarios en `era5_pl/`, `era5_sfc/` y los índices en `era5_indices/`",
            ),
        ),
        "Con 31 km de resolución **ERA5 no resuelve un mesociclón**: uno de 5 km cabe en una sola celda. "
        "ERA5 describe el entorno; GOES aporta información sobre la nube y su evolución. "
        "Sobre los Andes los niveles bajos (1000 hPa y a veces 925 hPa) quedan **bajo tierra** y sus "
        "valores son una extrapolación del modelo; los índices del visor parten del viento a 10 m para "
        "evitarlo. Cada archivo de nivel de presión pesa ~1,4 GB (una variable, un día, el globo) y no "
        "admite recorte en el servidor: los scripts leen rangos de bytes y recortan en memoria.",
        refs=("era5-ncar", "era5-doc", "hersbach2020"),
    ),
    Source(
        "goes",
        "GOES-16 · la tormenta",
        "Un satélite geoestacionario sobre el ecuador a 75,2°W, casi sobre el meridiano de Chile. Su "
        "radiómetro ABI mide 16 bandas, del visible al infrarrojo térmico, y barre el disco completo "
        "cada 10 minutos: 144 imágenes por día, de día y de noche.",
        (
            ("Resolución", "0,5–2 km según la banda; el visor guarda las 16 bandas a 2 km"),
            ("Cadencia", "disco completo cada 10 min (modo 6, desde 2019)"),
            (
                "Cobertura",
                "`noaa-goes16` dic 2017 – abr 2025 · `noaa-goes19` desde abr 2025 (us-east-1)",
            ),
            ("Producto", "`ABI-L2-MCMIPF`: las 16 bandas calibradas en un archivo"),
            (
                "En el visor",
                "recortes por hora en `goes/` y reproyectados a lat/lon en `goes_latlon/`",
            ),
        ),
        "Chile queda lejos del punto que el satélite ve de frente (el ecuador, 75,2°W), cerca del borde de "
        "la imagen. A 53°S un píxel de 2 km se comporta como uno de ~2 × 4 km, y el **paralaje** hace que "
        "el tope de una nube de 12 km de altura aparezca unos 10 km más al sur en Santiago y 21 km a 53°S, "
        "con una pequeña componente hacia el este: varias celdas de GOES. **El visor todavía no corrige el paralaje.** El detector de "
        "rayos GLM declara cobertura hasta ~52°S: que no haya rayos en el extremo sur no significa que no "
        "los hubo. Filtra los archivos por la hora de inicio del barrido (`s`), nunca por la de creación.",
        refs=("goes-aws", "goes-abi"),
    ),
    Source(
        "catalogo",
        "Catálogo de tornados · las etiquetas",
        "La base «Tornadoes and Waterspouts in Chile» (Bastías-Curivil et al., figshare, CC BY 4.0): "
        "casos en los que sus autores consideran más probable que haya ocurrido un tornado o una tromba "
        "que lo contrario, "
        "reconstruidos desde crónicas coloniales, prensa, redes sociales y literatura científica.",
        (
            ("Tamaño", "102 filas y 32 columnas, una hoja (`Final_Table`)"),
            ("Cobertura", "1554–2025; ningún registro al sur de 42,4°S"),
            ("Hora", "89 % con hora UTC, 93 % con hora local; todos con coordenadas"),
            ("Acceso", "`data/tornados_chile.xlsx`, descargado a mano desde figshare"),
        ),
        "**Solo hay positivos**: «no hubo tornado ese día en ese lugar» no está observado, se infiere "
        "porque nadie lo reportó. La probabilidad de entrar al catálogo depende de la población, la hora "
        "y el año (**sesgo de reporte**), y la posición es la del daño, no la del mesociclón. **No existe "
        "una etiqueta de mesociclón.** Además, 102 registros no son 102 casos comparables con GOES: hace "
        "falta que coincidan la cobertura del satélite, las coordenadas y una hora precisa.",
        refs=("bastias",),
    ),
    Source(
        "contexto",
        "Geográficos y temporales · el contexto",
        "Variables que no salen de ninguna de las tres fuentes, sino del terreno, la geometría de la "
        "observación y el calendario. Ayudan al modelo a separar lo que es física de lo que es dónde y "
        "cuándo se mira.",
        (
            (
                "Terreno",
                "un modelo digital de elevación (ERA5 trae orografía en `e5.oper.invariant/`)",
            ),
            ("Geometría", "se calcula con la posición del satélite y del Sol"),
            ("Población", "un censo o grilla de población, como control del sesgo de reporte"),
        ),
        "Son variables de control: no explican por qué se forma un mesociclón, pero sin ellas un modelo "
        "puede aprender que los tornados «ocurren» donde vive gente o donde el satélite mira mejor.",
        refs=("documento",),
    ),
)

GROUPS = (
    Group("era5-presion", "era5", "Campos en niveles de presión",
          "Variables crudas en los 37 niveles de presión. El visor descarga las que necesitan los índices "
          "y los mapas.", compact=True, refs=("era5-doc",)),
    Group("era5-superficie", "era5", "Superficie y nivel único",
          "Variables crudas a 2, 10 o 100 m, en la superficie o integradas en la columna; incluye los "
          "índices de estabilidad que el ECMWF entrega ya calculados.", compact=True, refs=("era5-doc",)),
    Group("era5-cinematicos", "era5", "Derivados cinemáticos",
          "Describen cómo cambia el viento con la altura y la rotación del aire en el entorno. Ayudan a "
          "estudiar la organización de las tormentas.", refs=("markowski2010",)),
    Group("era5-termodinamicos", "era5", "Derivados termodinámicos",
          "Cuánta energía tiene el aire para subir, dónde se forma la base de la nube y qué tan rápido se "
          "enfría con la altura.", refs=("markowski2010",)),
    Group("era5-compuestos", "era5", "Índices compuestos",
          "Combinan variables meteorológicas en un número. Su ámbito de aplicación depende de la "
          "formulación; los umbrales deben evaluarse con casos chilenos."),
    Group("goes-bandas", "goes", "Las 16 bandas del ABI",
          "Las bandas 1–6 miden luz solar reflejada (solo de día); las 7–16, radiación infrarroja emitida, "
          "que se expresa como temperatura de brillo.", compact=True, refs=("goes-abi",)),
    Group("goes-imagen", "goes", "Derivados por imagen",
          "Lo que se calcula con una sola imagen: qué tan alto llegó el tope, su textura y las firmas de "
          "una corriente ascendente muy potente.", refs=("documento",)),
    Group("goes-tendencias", "goes", "Tendencias cada 10 minutos",
          "Los cambios entre imágenes aportan información sobre el desarrollo de la nube. Hay que "
          "distinguirlos de su desplazamiento y comprobar el intervalo de tiempo.", refs=("documento",)),
    Group("goes-productos", "goes", "Otros productos GOES",
          "Productos de nivel 2 y del detector de rayos que no forman parte del archivo multibanda que lee "
          "el visor.", compact=True, refs=("goes-aws",)),
    Group("catalogo-columnas", "catalogo", "Columnas del catálogo",
          "Las columnas que importan para el proyecto, con su cobertura en las 102 filas.", compact=True, refs=("bastias",)),
    Group("contexto-variables", "contexto", "Variables de contexto",
          "Terreno, geometría de la observación, calendario y población.", refs=("documento",)),
)  # fmt: skip

_SOUTH = "En el hemisferio sur"

VARIABLES = (
    # --- ERA5 · niveles de presión ---------------------------------------------------------------
    Variable(
        "viento", "u, v", "Viento horizontal", "m/s", "era5-presion",
        "Las componentes zonal (u, positiva hacia el este) y meridional (v, positiva hacia el norte) del "
        "viento en cada nivel de presión.",
        why="Es la materia prima de todos los índices cinemáticos: cizalladura, helicidad, movimiento de "
        "Bunkers y forma del hodógrafo.",
        formula=r"|\vec V| = \sqrt{u^2 + v^2}",
        products=("pl:u", "pl:v"), level=850.0, synonyms="viento zonal meridional rapidez",
    ),
    Variable(
        "w", "w", "Velocidad vertical (omega)", "Pa/s", "era5-presion",
        "Pese al nombre, ERA5 la entrega en coordenadas de presión: cuánto cambia la presión de una "
        "parcela por segundo. **Negativa significa ascenso.**",
        why="Marca dónde el entorno de gran escala fuerza el ascenso; a 31 km no muestra la corriente "
        "ascendente de una tormenta, que mide pocos kilómetros.",
        formula=r"\omega = \frac{Dp}{Dt} \approx -\rho\, g\, w",
        method="Con ρ la densidad del aire y g = 9,81 m/s², la aproximación hidrostática pasa de omega "
        "a metros por segundo.",
        products=("pl:w",), level=500.0, synonyms="omega ascenso",
    ),
    Variable(
        "t", "t", "Temperatura", "K", "era5-presion",
        "Temperatura del aire en cada nivel de presión, en kelvin (0 °C = 273,15 K).",
        why="Con ella se calculan los gradientes térmicos, la temperatura en 500 hPa y la flotabilidad "
        "de las parcelas.",
        products=("pl:t",), level=500.0, synonyms="temperatura aire",
    ),
    Variable(
        "q", "q", "Humedad específica", "kg/kg", "era5-presion",
        "Masa de vapor de agua por masa de aire húmedo.",
        why="Junto con la temperatura define la humedad relativa, el punto de rocío y el agua "
        "precipitable.",
        products=("pl:q",), level=850.0, synonyms="humedad vapor",
    ),
    Variable(
        "z", "z", "Geopotencial", "m²/s²", "era5-presion",
        "La energía potencial por unidad de masa de un nivel de presión respecto del nivel del mar. "
        "Dividida por la gravedad estándar da la **altura geopotencial**, en metros.",
        why="Convierte niveles de presión en alturas: es lo que permite calcular cizalladura «entre 10 m y "
        "1 km». En 500 hPa dibuja vaguadas y bajas segregadas.",
        formula=r"Z = \frac{\Phi}{g_0}, \qquad g_0 = 9{,}80665\ \mathrm{m\,s^{-2}}",
        products=("pl:z",), level=500.0, synonyms="altura geopotencial",
    ),
    Variable(
        "r", "r", "Humedad relativa", "%", "era5-presion",
        "Cuánto vapor tiene el aire respecto del máximo que admite a esa temperatura.",
        why="El aire seco en niveles medios alimenta las corrientes descendentes; el aire húmedo cerca "
        "del suelo baja la base de la nube.",
        formula=r"\mathrm{HR} = 100\,\frac{e}{e_s(T)}",
        method="e es la presión de vapor y e_s la de saturación a la temperatura T.",
        products=("pl:r",), level=700.0, synonyms="humedad",
    ),
    Variable(
        "vo", "ζ", "Vorticidad relativa", "1/s", "era5-presion",
        "La rotación del aire en el plano horizontal, sin contar la rotación de la Tierra.",
        why="Se mira en 850, 700 y 500 hPa para seguir los sistemas que disparan la convección.",
        formula=r"\zeta = \frac{\partial v}{\partial x} - \frac{\partial u}{\partial y}",
        caveat=f"{_SOUTH} la rotación ciclónica es horaria y tiene **ζ negativa**.",
        products=("pl:vo",), level=500.0, synonyms="rotación vorticity",
    ),
    Variable(
        "pv", "PV", "Vorticidad potencial", "PVU", "era5-presion",
        "Combina la rotación absoluta del aire con su estabilidad. Se conserva en un flujo sin fricción ni "
        "calentamiento, así que funciona como trazador del aire estratosférico.",
        why="En 300–500 hPa identifica intrusiones estratosféricas y bajas segregadas (*cutoff lows*), "
        "un disparador sinóptico habitual en Chile.",
        formula=r"\mathrm{PV} = -g\,(\zeta + f)\,\frac{\partial \theta}{\partial p}",
        method="f es el parámetro de Coriolis y θ la temperatura potencial; 1 PVU = 10⁻⁶ K m² kg⁻¹ s⁻¹.",
        caveat=f"{_SOUTH} f es negativo y la PV del aire estratosférico también.",
        synonyms="potential vorticity intrusión estratosférica baja segregada cutoff",
    ),
    # --- ERA5 · superficie -----------------------------------------------------------------------
    Variable(
        "viento10", "10u, 10v", "Viento a 10 m", "m/s", "era5-superficie",
        "Componentes del viento a 10 m sobre el terreno.",
        why="Es el punto de partida de los perfiles del visor: reemplaza al nivel de 1000 hPa, que "
        "sobre los Andes queda bajo tierra.",
        products=("sfc:10u", "sfc:10v"), synonyms="viento superficie",
    ),
    Variable(
        "viento100", "100u, 100v", "Viento a 100 m", "m/s", "era5-superficie",
        "Componentes del viento a 100 m sobre el terreno.",
        why="Ayuda a ver la cizalladura en los primeros cientos de metros, donde importa para la "
        "tornadogénesis.",
        products=("sfc:100u", "sfc:100v"),
    ),
    Variable(
        "t2m", "2t", "Temperatura a 2 m", "K", "era5-superficie",
        "Temperatura del aire a 2 m sobre el terreno.",
        why="Con el punto de rocío da la altura de la base de la nube (LCL).",
        products=("sfc:2t",), synonyms="temperatura superficie",
    ),
    Variable(
        "td2m", "2d", "Punto de rocío a 2 m", "K", "era5-superficie",
        "La temperatura a la que habría que enfriar el aire, sin cambiar su humedad, para que se sature.",
        why="Cuanto más cerca de la temperatura, más húmedo el aire y más baja la base de la nube.",
        products=("sfc:2d",), synonyms="rocío dewpoint",
    ),
    Variable(
        "sp", "sp", "Presión de superficie", "Pa", "era5-superficie",
        "La presión del aire en el terreno, sin reducir al nivel del mar.",
        why="Dice qué niveles de presión están bajo tierra: sobre los Andes es mucho menor que "
        "1000 hPa. El visor la usa para medir alturas sobre el terreno.",
        products=("sfc:sp",), synonyms="presión terreno",
    ),
    Variable(
        "msl", "msl", "Presión a nivel del mar", "Pa", "era5-superficie",
        "La presión de superficie reducida al nivel del mar, para comparar lugares de distinta altura.",
        why="Dibuja las bajas y los frentes. El 30 de mayo de 2019 había una baja ocluida de ~995 hPa "
        "frente a la costa.",
        products=("sfc:msl",), synonyms="presión isobaras baja",
    ),
    Variable(
        "cape", "CAPE", "Energía potencial convectiva disponible", "J/kg", "era5-superficie",
        "La energía que gana una parcela de aire al subir desde su nivel de convección libre hasta su "
        "nivel de equilibrio, por ser más cálida que el entorno. ERA5 la entrega ya calculada.",
        why="Mide la inestabilidad: cuánta energía hay para la corriente ascendente. En Chile suele "
        "ser baja (régimen HSLC), por eso no basta sola.",
        formula=r"\mathrm{CAPE} = g \int_{\mathrm{LFC}}^{\mathrm{EL}} \frac{T_{v,p} - T_{v,e}}{T_{v,e}}\,dz",
        method="T_v,p y T_v,e son las temperaturas virtuales de la parcela y del entorno. ERA5 usa su "
        "propia parcela: no es directamente comparable con SBCAPE, MLCAPE ni MUCAPE.",
        caveat="El documento cita rangos distintos de CAPE para 2019 (200–1.000 y 200–500 J/kg); falta "
        "aclarar su fuente y cálculo antes de compararlos.",
        inputs=("t", "q"), products=("sfc:cape",), synonyms="inestabilidad energía flotabilidad",
    ),
    Variable(
        "cin", "CIN", "Inhibición convectiva", "J/kg", "era5-superficie",
        "La energía que hay que gastar para llevar una parcela desde la superficie hasta su nivel de "
        "convección libre, a través de las capas donde es más fría que el entorno. ERA5 la entrega ya "
        "calculada, en `e5.oper.fc.sfc.instan/`.",
        why="Es la «tapa» que puede impedir que la convección empiece aunque haya CAPE.",
        formula=r"\mathrm{CIN} = g \int_{\mathrm{sfc}}^{\mathrm{LFC}} \frac{T_{v,p} - T_{v,e}}{T_{v,e}}\,dz",
        caveat="El visor todavía no la descarga: por eso su STP es una aproximación sin CIN.",
        inputs=("t", "q"), synonyms="inhibición cap tapa",
    ),
    Variable(
        "tcwv", "tcwv", "Agua precipitable", "kg/m²", "era5-superficie",
        "Todo el vapor de agua de la columna, como si se condensara: 1 kg/m² equivale a 1 mm de agua.",
        why="Mide la humedad disponible que transporta el flujo del noroeste desde el Pacífico.",
        formula=r"\mathrm{PW} = \frac{1}{g} \int_{p_{\mathrm{tope}}}^{p_s} q\,dp",
        inputs=("q",), products=("sfc:tcwv",), synonyms="vapor columna humedad",
    ),
    Variable(
        "blh", "blh", "Altura de la capa límite", "m", "era5-superficie",
        "El espesor de la capa de aire en contacto con el suelo que se mezcla por turbulencia.",
        why="Describe cuánta mezcla hay cerca del suelo; ayuda a interpretar la humedad y el viento de "
        "niveles bajos.",
        products=("sfc:blh",), synonyms="capa límite pbl",
    ),
    Variable(
        "tcc", "tcc", "Nubosidad total", "0–1", "era5-superficie",
        "Fracción del cielo cubierta por nubes según el modelo.",
        why="Es la nubosidad de ERA5, no la observada: comparar con GOES muestra dónde el modelo acierta.",
        products=("sfc:tcc",), synonyms="nubes cobertura",
    ),
    Variable(
        "sst", "SST", "Temperatura superficial del mar", "K", "era5-superficie",
        "La temperatura del agua en la superficie del océano.",
        why="El Pacífico es la fuente de calor y humedad de la convección que llega a la costa; su "
        "diferencia con el aire se describe en los derivados termodinámicos.",
        synonyms="mar océano",
    ),
    # --- ERA5 · derivados cinemáticos ------------------------------------------------------------
    Variable(
        "shear_01", "Cizalladura 0–1 km", "Cizalladura de capa baja", "m/s", "era5-cinematicos",
        "La magnitud de la diferencia vectorial del viento entre 10 m y 1 km sobre el terreno.",
        why="Es la cizalladura que importa para la tornadogénesis. Es una diferencia de vectores, no de "
        "rapideces: un viento que gira 90° sin acelerar tiene cizalladura grande.",
        formula=r"\mathrm{BWD}_{0\text{–}1} = \left|\vec V(1\ \mathrm{km}) - \vec V(10\ \mathrm{m})\right|",
        method="El visor interpola el perfil cada 100 m sobre el terreno, partiendo del viento a 10 m.",
        threshold="12 m/s es el valor de comparación citado para los días tornádicos estudiados en Chile. "
        "Cumplirlo describe el entorno; no confirma un tornado.",
        inputs=("viento", "viento10", "z", "sp"), products=("idx:shear_01",),
        synonyms="shear cizalle bulk wind difference bwd",
    ),
    Variable(
        "shear_03", "Cizalladura 0–3 km", "Cizalladura de 0 a 3 km", "m/s", "era5-cinematicos",
        "La magnitud de la diferencia vectorial del viento entre 10 m y 3 km.",
        why="Entra en SHERBS3, el índice para entornos de mucha cizalladura y poco CAPE.",
        formula=r"\mathrm{BWD}_{0\text{–}3} = \left|\vec V(3\ \mathrm{km}) - \vec V(10\ \mathrm{m})\right|",
        inputs=("viento", "viento10", "z", "sp"), products=("idx:shear_03",), synonyms="shear cizalle",
    ),
    Variable(
        "shear_06", "Cizalladura 0–6 km", "Cizalladura de capa profunda", "m/s", "era5-cinematicos",
        "La magnitud de la diferencia vectorial del viento entre 10 m y 6 km.",
        why="Es el discriminante clásico entre tormentas ordinarias y organizadas.",
        formula=r"\mathrm{BWD}_{0\text{–}6} = \left|\vec V(6\ \mathrm{km}) - \vec V(10\ \mathrm{m})\right|",
        caveat="En el caso de 2019 supera 18 m/s en casi toda la región, así que distingue poco entre "
        "lugares de esa situación. No tiene un criterio local de decisión.",
        inputs=("viento", "viento10", "z", "sp"), products=("idx:shear_06",), synonyms="shear cizalle",
    ),
    Variable(
        "bunkers", "Bunkers LM", "Movimiento de la tormenta (Bunkers)", "m/s", "era5-cinematicos",
        "Una estimación de hacia dónde se mueve una supercélula: el viento medio de 0–6 km desplazado "
        "7,5 m/s perpendicular a la cizalladura. Da dos soluciones: *right-mover* (se desvía a la derecha del "
        "viento medio) y *left-mover* (a la izquierda, la favorecida en el hemisferio sur).",
        why="La helicidad relativa a la tormenta necesita este vector.",
        formula=r"\vec C_{\mathrm{LM}} = \bar{\vec V}_{0\text{–}6} + D\,\frac{\hat k \times \vec S}{|\vec S|}, \qquad \vec S = \bar{\vec V}_{5{,}5\text{–}6} - \bar{\vec V}_{0\text{–}0{,}5}",
        method="D = 7,5 m/s; las barras son vientos medios sin ponderar en esas capas (km sobre el "
        "terreno). La rama *right-mover* cambia el signo del segundo término.",
        caveat=f"{_SOUTH} la supercélula favorecida es la **left-mover**: usar la otra rama da índices con "
        "el signo cambiado.",
        inputs=("viento", "viento10"), synonyms="storm motion left-mover right-mover",
    ),
    Variable(
        "srh_01", "SRH₀₋₁", "Helicidad relativa a la tormenta 0–1 km", "m²/s²", "era5-cinematicos",
        "Cuánta vorticidad horizontal *streamwise* (alineada con el flujo que entra a la tormenta) hay en "
        "el primer kilómetro: la rotación lista para ser inclinada hacia la vertical.",
        why="Resume la vorticidad horizontal alineada con el aire que entra a la tormenta. Aporta "
        "información sobre la relación entre el perfil de viento y la rotación del ascenso.",
        formula=r"\mathrm{SRH}_{0\text{–}h} = \sum_n \left[(u_{n+1}-c_x)(v_n-c_y) - (u_n-c_x)(v_{n+1}-c_y)\right]",
        method="Suma sobre el perfil interpolado cada 100 m hasta h = 1 km, con (c_x, c_y) el movimiento "
        "*left-mover* de Bunkers. Es la fórmula de MetPy.",
        caveat=f"{_SOUTH}, con la rama *left-mover*, la **SRH tornádica es negativa**. En 2019 se citan "
        "valores de −100 a −250 m²/s². El signo por sí solo no confirma un entorno tornádico.",
        inputs=("viento", "bunkers"), products=("idx:srh_01",),
        synonyms="helicity helicidad storm relative",
    ),
    Variable(
        "srh_03", "SRH₀₋₃", "Helicidad relativa a la tormenta 0–3 km", "m²/s²", "era5-cinematicos",
        "La misma helicidad, integrada en los primeros 3 km.",
        why="Describe la rotación disponible para el mesociclón en niveles medios-bajos.",
        formula=r"\mathrm{SRH}_{0\text{–}3} = \sum_{z_n < 3\ \mathrm{km}} \left[(u_{n+1}-c_x)(v_n-c_y) - (u_n-c_x)(v_{n+1}-c_y)\right]",
        caveat="Negativa en el hemisferio sur con la rama *left-mover*; los casos de 2019 citados van de "
        "−253 a −688 m²/s².",
        inputs=("viento", "bunkers"), products=("idx:srh_03",), synonyms="helicity helicidad",
    ),
    Variable(
        "adv_vort", "−V·∇ζ", "Advección de vorticidad", "1/s²", "era5-cinematicos",
        "Cuánta vorticidad trae el viento a un lugar. Se calcula en 850, 700 y 500 hPa.",
        why="La advección de vorticidad ciclónica en niveles medios fuerza ascenso de gran escala "
        "delante de las vaguadas.",
        formula=r"A_\zeta = -\vec V \cdot \nabla(\zeta + f)",
        caveat=f"{_SOUTH} la vorticidad ciclónica es negativa: la advección que favorece el ascenso tiene "
        "el signo contrario al del hemisferio norte.",
        inputs=("vo", "viento"), synonyms="advección vorticidad vaguada",
    ),
    Variable(
        "hodografo", "Hodógrafo", "Forma del hodógrafo", "", "era5-cinematicos",
        "La curva que traza la punta del vector viento al subir. Un perfil que solo acelera da una recta; "
        "uno que además gira da una curva.",
        why="La curvatura distingue el perfil poco favorable del muy favorable para supercélulas. Se "
        "resume en unos pocos números: curvatura integrada, longitud de arco y área en los primeros 3 km.",
        formula=r"L_{0\text{–}3} = \int_0^{3\ \mathrm{km}} \left|\frac{\partial \vec V}{\partial z}\right| dz",
        method="La página Sondeo dibuja el hodógrafo del punto elegido.",
        inputs=("viento",), synonyms="hodograph curvatura",
    ),
    Variable(
        "llj", "LLJ", "Jet de niveles bajos", "m/s", "era5-cinematicos",
        "La magnitud y la altura del máximo de viento bajo 1,5 km.",
        why="Transporta humedad y concentra cizalladura cerca del suelo. El 30 de mayo de 2019 el jet del "
        "noroeste en 850 hPa llegaba a 20–30 m/s y se frenaba contra la cordillera.",
        formula=r"V_{\mathrm{LLJ}} = \max_{z < 1{,}5\ \mathrm{km}} |\vec V(z)|",
        inputs=("viento",), synonyms="low level jet chorro",
    ),
    Variable(
        "divergencia", "δ", "Convergencia y divergencia", "1/s", "era5-cinematicos",
        "Cuánto se separa (δ > 0) o se junta (δ < 0) el aire en un nivel.",
        why="Convergencia en 925/850 hPa dispara el ascenso; divergencia en 200–300 hPa lo sostiene, "
        "como una aspiradora en altura.",
        formula=r"\delta = \frac{\partial u}{\partial x} + \frac{\partial v}{\partial y}",
        inputs=("viento",), synonyms="convergencia divergence",
    ),
    # --- ERA5 · derivados termodinámicos ---------------------------------------------------------
    Variable(
        "cape_variantes", "SB/ML/MUCAPE", "Variantes de CAPE", "J/kg", "era5-termodinamicos",
        "La misma integral que la CAPE, con parcelas distintas: **SBCAPE** sube desde la superficie, "
        "**MLCAPE** con el promedio de los primeros ~100 hPa y **MUCAPE** desde el nivel más inestable, "
        "para convección elevada.",
        why="El STP original usa MLCAPE; elegir la parcela cambia el valor y la comparación con la "
        "literatura.",
        formula=r"\mathrm{CAPE}_{\text{parcela}} = g \int_{\mathrm{LFC}}^{\mathrm{EL}} \frac{T_{v,p} - T_{v,e}}{T_{v,e}}\,dz",
        inputs=("t", "q", "t2m", "td2m", "sp"), synonyms="sbcape mlcape mucape parcela",
    ),
    Variable(
        "cape_03", "CAPE₀₋₃", "CAPE de niveles bajos", "J/kg", "era5-termodinamicos",
        "La CAPE acumulada solo en los primeros 3 km.",
        why="Controla el estiramiento de la vorticidad cerca del suelo. Con CAPE total bajo, como en "
        "Chile, puede discriminar mucho mejor que la CAPE integrada.",
        formula=r"\mathrm{CAPE}_{0\text{–}3} = g \int_{\mathrm{LFC}}^{3\ \mathrm{km}} \frac{T_{v,p} - T_{v,e}}{T_{v,e}}\,dz",
        inputs=("t", "q"), synonyms="cape baja 3cape",
    ),
    Variable(
        "lcl", "LCL", "Nivel de condensación por ascenso", "m", "era5-termodinamicos",
        "La altura a la que una parcela que sube desde la superficie se satura: la base de la nube.",
        why="Un LCL bajo, con aire húmedo cerca del suelo, es uno de los discriminantes tornádicos más "
        "robustos de la literatura.",
        formula=r"z_{\mathrm{LCL}} \approx 125\ \mathrm{m\,K^{-1}}\,(T_{2m} - T_{d,2m})",
        method="Aproximación de Espy: 125 m por cada grado de diferencia entre temperatura y punto de "
        "rocío a 2 m.",
        caveat="Los valores menores de 650–713 m citados corresponden al caso de 2019.",
        inputs=("t2m", "td2m"), products=("idx:lcl",), synonyms="base nube condensación",
    ),
    Variable(
        "lfc_el", "LFC, EL", "Nivel de convección libre y de equilibrio", "m", "era5-termodinamicos",
        "El LFC es donde una parcela empieza a ser más cálida que el entorno y sube sola; el EL, donde "
        "deja de serlo.",
        why="Entre los dos se acumula la CAPE, y el EL fija qué tan profunda puede ser la convección.",
        inputs=("t", "q"), synonyms="lfc el equilibrio convección libre",
    ),
    Variable(
        "gamma_03", "Γ₀₋₃", "Gradiente térmico 0–3 km", "K/km", "era5-termodinamicos",
        "Cuánto se enfría el aire por kilómetro de ascenso en los primeros 3 km.",
        why="Un gradiente fuerte en niveles bajos favorece el ascenso aun con poca CAPE; entra en "
        "SHERBS3.",
        formula=r"\Gamma_{0\text{–}3} = -\frac{T(3\ \mathrm{km}) - T(10\ \mathrm{m})}{3\ \mathrm{km}}",
        method="El visor usa la temperatura a 2 m como dato a 10 m.",
        inputs=("t", "t2m", "z"), products=("idx:gamma_03",), synonyms="lapse rate gradiente",
    ),
    Variable(
        "gamma_75", "Γ₇₀₀₋₅₀₀", "Gradiente térmico 700–500 hPa", "K/km", "era5-termodinamicos",
        "Cuánto se enfría el aire por kilómetro entre los niveles de 700 y 500 hPa.",
        why="Describe la inestabilidad de niveles medios; entra en SHERBS3.",
        formula=r"\Gamma_{700\text{–}500} = \frac{T_{700} - T_{500}}{Z_{500} - Z_{700}}",
        inputs=("t", "z"), products=("idx:gamma_75",), synonyms="lapse rate gradiente",
    ),
    Variable(
        "t500", "T₅₀₀", "Temperatura en 500 hPa", "K", "era5-termodinamicos",
        "La temperatura en el nivel de 500 hPa, a unos 5,5 km.",
        why="Un indicador simple del aire frío en altura, el mecanismo dominante de inestabilización en "
        "Chile. El 30 de mayo de 2019 había un núcleo de −24 a −26 °C sobre la zona de los tornados.",
        inputs=("t",), products=("pl:t",), level=500.0, synonyms="aire frío altura núcleo frío",
    ),
    Variable(
        "humedad_capas", "T − Td", "Humedad por capas y depresión del punto de rocío", "K",
        "era5-termodinamicos",
        "La humedad relativa en varias capas y la diferencia entre temperatura y punto de rocío en "
        "700 hPa.",
        why="Una depresión grande en 700 hPa marca aire seco en niveles medios, que alimenta las "
        "corrientes descendentes.",
        formula=r"\Delta T_{d,700} = T_{700} - T_{d,700}",
        inputs=("t", "q", "r"), synonyms="depresión rocío aire seco",
    ),
    Variable(
        "dcape", "DCAPE", "CAPE de corrientes descendentes", "J/kg", "era5-termodinamicos",
        "La energía disponible para una parcela que baja enfriada por evaporación.",
        why="Está ligada a la intensidad de la corriente descendente trasera (RFD) y de las ráfagas.",
        formula=r"\mathrm{DCAPE} = g \int_{\mathrm{sfc}}^{z_0} \frac{T_{v,e} - T_{v,p}}{T_{v,e}}\,dz",
        method="z₀ es el nivel desde donde parte la parcela descendente, típicamente en niveles medios.",
        inputs=("t", "q"), synonyms="descendente downdraft rfd",
    ),
    Variable(
        "sst_aire", "SST − T₂ₘ", "Contraste mar–aire", "K", "era5-termodinamicos",
        "La diferencia entre la temperatura del mar y la del aire a 2 m.",
        why="Mide el calor y la humedad que el Pacífico entrega al aire que llega a la costa.",
        formula=r"\Delta T = \mathrm{SST} - T_{2m}",
        inputs=("sst", "t2m"), synonyms="mar aire contraste",
    ),
    # --- ERA5 · índices compuestos ---------------------------------------------------------------
    Variable(
        "vgp_01", "VGP₀₋₁", "Parámetro de generación de vorticidad", "m/s²", "era5-compuestos",
        "Combina la energía para el ascenso (CAPE) con el cambio del viento por unidad de altura en el "
        "primer kilómetro.",
        why="Vicencio et al. (2021) lo utilizan para distinguir los cinco días tornádicos analizados. "
        "Su capacidad de separación debe evaluarse con otros casos.",
        formula=r"\mathrm{VGP}_{0\text{–}1} = \sqrt{\mathrm{CAPE}}\;\frac{\mathrm{BWD}_{0\text{–}1}}{1000\ \mathrm{m}}",
        method="El VGP original (Rasmussen y Blanchard, 1998) multiplica la raíz de la CAPE por la cizalladura "
        "de una capa de varios kilómetros; Vicencio et al. (2021) lo evalúan con la capa de 0–1 km.",
        threshold="Mayor que 0,1 m/s² en los cinco días tornádicos analizados entre 2008 y 2019 (Vicencio et "
        "al. 2021). Su alcance fuera de esos casos requiere evaluación.",
        inputs=("cape", "shear_01"), products=("idx:vgp_01",),
        synonyms="vorticity generation parameter",
    ),
    Variable(
        "stp_lm", "STP", "Parámetro significativo de tornado, rama left-mover", "", "era5-compuestos",
        "Combina energía, base de nube, helicidad y cizalladura profunda en un número (Thompson et al. 2003, "
        "2012).",
        why="Es el índice compuesto estándar para tornados significativos. El STP clásico no habría "
        "detectado el brote de 2019: recalibrarlo con datos chilenos sería un resultado publicable.",
        formula=r"\mathrm{STP} = \frac{\mathrm{CAPE}}{1500}\cdot\frac{2000 - \mathrm{LCL}}{1000}\cdot\frac{\mathrm{SRH}_{0\text{–}1}}{150}\cdot\frac{\mathrm{BWD}_{0\text{–}6}}{20}",
        method="Es la versión de capa fija de Thompson et al. (2012). El término del LCL vale 1 bajo "
        "1000 m y 0 sobre 2000 m; el de la cizalladura vale 0 bajo 12,5 m/s y se satura en 30 m/s. "
        "**Aproximación del visor**: usa la CAPE de ERA5 y omite el término de CIN, (200 + CIN)/150.",
        threshold="≤ −0,3 con la rama *left-mover* (Marín et al. 2024), no el +1 norteamericano. Aplicarlo a "
        "esta aproximación sin CIN requiere validación.",
        caveat="Con la SRH *left-mover* el STP austral es negativo.",
        inputs=("cape", "lcl", "srh_01", "shear_06"), products=("idx:stp_lm",),
        synonyms="significant tornado parameter",
    ),
    Variable(
        "sherbs3", "SHERBS3", "Índice para entornos HSLC", "", "era5-compuestos",
        "Severe Hazards in Environments with Reduced Buoyancy (Sherburn y Parker 2014): combina cizalladura "
        "con gradientes térmicos, sin usar CAPE. Diseñado para entornos de mucha cizalladura y poca "
        "energía (HSLC), como el chileno.",
        why="Donde la CAPE es tan baja que los índices clásicos fallan, los gradientes térmicos "
        "capturan la inestabilidad.",
        formula=r"\mathrm{SHERBS3} = \frac{\mathrm{BWD}_{0\text{–}3}}{26\ \mathrm{m\,s^{-1}}}\cdot\frac{\Gamma_{0\text{–}3}}{5{,}2\ \mathrm{K\,km^{-1}}}\cdot\frac{\Gamma_{700\text{–}500}}{5{,}6\ \mathrm{K\,km^{-1}}}",
        method="La variante **SHERBE** usa la cizalladura de la capa efectiva y lo normaliza por 27 m/s; "
        "los gradientes térmicos son los mismos.",
        caveat="SHERBE ≥ 1 es el umbral propuesto para Chile, pero corresponde a la variante efectiva: "
        "SHERBS3 no tiene un umbral validado.",
        inputs=("shear_03", "gamma_03", "gamma_75"), products=("idx:sherbs3",),
        synonyms="sherbe hslc",
    ),
    Variable(
        "ehi", "EHI", "Índice energía–helicidad", "", "era5-compuestos",
        "El producto de la CAPE y la helicidad, normalizado.",
        why="Junta en un número los dos ingredientes de una supercélula: ascenso y rotación.",
        formula=r"\mathrm{EHI} = \frac{\mathrm{CAPE} \cdot \mathrm{SRH}}{160\,000}",
        caveat="Con la SRH *left-mover* del hemisferio sur, el EHI favorable es negativo.",
        inputs=("cape", "srh_01"), synonyms="energy helicity index",
    ),
    Variable(
        "scp", "SCP", "Parámetro compuesto de supercélula", "", "era5-compuestos",
        "Combina la CAPE de la parcela más inestable, la helicidad y la cizalladura de la capa efectiva "
        "(versión de capa efectiva de Thompson et al. 2012).",
        why="Discrimina entornos de supercélula de los de tormentas ordinarias.",
        formula=r"\mathrm{SCP} = \frac{\mathrm{MUCAPE}}{1000}\cdot\frac{\mathrm{SRH}_{\mathrm{ef}}}{50}\cdot\frac{\mathrm{BWD}_{\mathrm{ef}}}{20}",
        caveat="Calibrado para el hemisferio norte; en el sur hay que usar la helicidad *left-mover* y "
        "recalibrar.",
        inputs=("cape_variantes", "srh_03", "shear_06"), synonyms="supercell composite parameter",
    ),
    Variable(
        "brn", "BRN", "Número de Richardson global", "", "era5-compuestos",
        "La razón entre la flotabilidad y la cizalladura: cuánto domina la energía del ascenso sobre la "
        "organización que da el viento.",
        why="Discrimina el modo convectivo: valores bajos favorecen tormentas organizadas por la cizalladura.",
        formula=r"\mathrm{BRN} = \frac{\mathrm{CAPE}}{\tfrac12 \left|\bar{\vec V}_{0\text{–}6} - \bar{\vec V}_{0\text{–}0{,}5}\right|^2}",
        method="Los vientos medios se ponderan por densidad.",
        inputs=("cape", "viento"), synonyms="bulk richardson number",
    ),
    # --- GOES · bandas ---------------------------------------------------------------------------
    Variable("C01", "C01", "Banda 1 · azul", "", "goes-bandas",
             "Visible de 0,47 µm, 1 km nativo. Ve aerosoles, humo y polvo además de las nubes.",
             products=("goes:C01",), synonyms="visible azul"),
    Variable("C02", "C02", "Banda 2 · rojo", "", "goes-bandas",
             "Visible de 0,64 µm, la de mayor resolución: 0,5 km nativo (2 km en el visor).",
             why="Muestra la textura y las sombras del tope nuboso, como los topes penetrantes. Solo "
             "de día.",
             products=("goes:C02",), synonyms="visible rojo textura"),
    Variable("C03", "C03", "Banda 3 · «veggie»", "", "goes-bandas",
             "Infrarrojo cercano de 0,86 µm, 1 km. La vegetación la refleja con fuerza.",
             products=("goes:C03",)),
    Variable("C04", "C04", "Banda 4 · cirros", "", "goes-bandas",
             "Infrarrojo cercano de 1,37 µm, 2 km. El vapor de niveles bajos la absorbe, así que destaca "
             "los cirros delgados y altos.",
             products=("goes:C04",), synonyms="cirros"),
    Variable("C05", "C05", "Banda 5 · nieve y hielo", "", "goes-bandas",
             "Infrarrojo cercano de 1,6 µm, 1 km. Separa nubes de hielo, oscuras, de nubes de agua.",
             products=("goes:C05",), synonyms="nieve hielo"),
    Variable("C06", "C06", "Banda 6 · tamaño de partícula", "", "goes-bandas",
             "Infrarrojo cercano de 2,2 µm, 2 km. Responde al tamaño de las partículas del tope.",
             products=("goes:C06",), synonyms="partícula"),
    Variable("C07", "C07", "Banda 7 · ventana de onda corta", "K", "goes-bandas",
             "Infrarrojo de 3,9 µm, 2 km. De día suma luz solar reflejada a la emisión térmica.",
             products=("goes:C07",), synonyms="onda corta"),
    Variable("C08", "C08", "Banda 8 · vapor de agua alto", "K", "goes-bandas",
             "Infrarrojo de 6,2 µm, 2 km. Mide el vapor de los niveles altos.",
             why="Revela la circulación de niveles medios-altos aunque no haya nubes. Entra en el RGB "
             "Airmass y en C08 − C13.",
             products=("goes:C08",), synonyms="vapor agua"),
    Variable("C09", "C09", "Banda 9 · vapor de agua medio", "K", "goes-bandas",
             "Infrarrojo de 6,9 µm, 2 km. Mide el vapor de los niveles medios.",
             products=("goes:C09",), synonyms="vapor agua"),
    Variable("C10", "C10", "Banda 10 · vapor de agua bajo", "K", "goes-bandas",
             "Infrarrojo de 7,3 µm, 2 km. Mide el vapor de los niveles medios-bajos.",
             products=("goes:C10",), synonyms="vapor agua"),
    Variable("C11", "C11", "Banda 11 · fase del tope", "K", "goes-bandas",
             "Infrarrojo de 8,4 µm, 2 km. Ayuda a distinguir topes de hielo y de agua.",
             products=("goes:C11",), synonyms="fase"),
    Variable("C12", "C12", "Banda 12 · ozono", "K", "goes-bandas",
             "Infrarrojo de 9,6 µm, 2 km. El ozono la absorbe: sigue el aire estratosférico.",
             products=("goes:C12",), synonyms="ozono"),
    Variable(
        "C13", "C13", "Banda 13 · ventana larga «limpia»", "K", "goes-bandas",
        "Infrarrojo de 10,3 µm, 2 km. Casi no la absorbe la atmósfera: mide la temperatura de brillo del "
        "tope o del suelo.",
        why="Es el termómetro de qué tan alto llegó una tormenta: más frío suele ser más alto. No mide "
        "la altura ni la intensidad del ascenso directamente.",
        products=("goes:C13",), synonyms="infrarrojo ir temperatura brillo",
    ),
    Variable("C14", "C14", "Banda 14 · ventana larga", "K", "goes-bandas",
             "Infrarrojo de 11,2 µm, 2 km. La ventana infrarroja clásica.",
             products=("goes:C14",)),
    Variable("C15", "C15", "Banda 15 · ventana larga «sucia»", "K", "goes-bandas",
             "Infrarrojo de 12,3 µm, 2 km. El vapor la absorbe algo más que la 13.",
             products=("goes:C15",)),
    Variable("C16", "C16", "Banda 16 · CO₂", "K", "goes-bandas",
             "Infrarrojo de 13,3 µm, 2 km. El CO₂ la absorbe: ve niveles más altos que las ventanas.",
             products=("goes:C16",), synonyms="co2"),
    # --- GOES · derivados por imagen -------------------------------------------------------------
    Variable(
        "airmass", "RGB Airmass", "Composición RGB de masas de aire", "", "goes-imagen",
        "Una imagen en color que combina bandas infrarrojas para distinguir masas de aire y estructuras "
        "nubosas. Funciona de día y de noche.",
        why="Muestra la nube coma, las intrusiones secas (aire relativamente seco que baja desde "
        "niveles altos) y las bajas segregadas que acompañan a los brotes chilenos.",
        formula=r"R = T_{08} - T_{10},\quad G = T_{12} - T_{13},\quad B = T_{08}",
        method="Cada canal se escala a 0–1: rojo entre −26,2 y 0,6 K, verde entre −43,2 y 6,7 K, y azul "
        "entre 243,9 y 208,5 K (C08 invertido: los topes y el aire frío salen azules).",
        caveat="Los colores orientan, no miden: se leen junto con otros datos.",
        inputs=("C08", "C10", "C12", "C13"), products=("rgb:airmass",),
        synonyms="rgb masa aire nube coma intrusión seca",
    ),
    Variable(
        "C08-C13", "C08 − C13", "Diferencia vapor de agua – ventana", "K", "goes-imagen",
        "La diferencia de temperatura de brillo entre la banda de vapor alto (6,2 µm) y la ventana limpia "
        "(10,3 µm).",
        why="Normalmente es muy negativa. Cerca de cero o positiva sugiere un tope que alcanza o supera "
        "la tropopausa; hay que interpretarla junto con las condiciones del píxel.",
        formula=r"\Delta T_b = T_{b,6{,}2} - T_{b,10{,}3}",
        caveat="Un valor cercano a cero no confirma por sí solo un tope sobre la tropopausa.",
        inputs=("C08", "C13"), products=("goes:C08-C13",), synonyms="diferencia bandas tropopausa",
    ),
    Variable(
        "bt_min", "BT_min", "Temperatura de brillo mínima", "K", "goes-imagen",
        "El valor más frío de la banda 13 dentro de la celda de tormenta.",
        why="Ayuda a localizar topes fríos. Su relación con la altura depende del perfil térmico y "
        "de las propiedades de la nube; no mide directamente la intensidad del ascenso.",
        formula=r"T_{b,\min} = \min_{\text{celda}} T_{b,13}",
        inputs=("C13",), synonyms="mínimo tope frío",
    ),
    Variable(
        "tropo_tope", "T_tropo − T_tope", "Sobrepaso de la tropopausa", "K", "goes-imagen",
        "La diferencia entre la temperatura de la tropopausa de ERA5 y la del tope nuboso.",
        why="Cuánto sobrepasó la tormenta su nivel de equilibrio: cruza las dos fuentes.",
        formula=r"\Delta T = T_{\mathrm{tropopausa}} - T_{b,13}",
        inputs=("C13", "t"), synonyms="tropopausa overshoot",
    ),
    Variable(
        "overshooting", "OT", "Topes penetrantes", "", "goes-imagen",
        "Mínimos locales de temperatura de brillo rodeados de un yunque más cálido, con una textura "
        "característica en la banda 2.",
        why="Marcan una corriente ascendente tan fuerte que perfora la tropopausa.",
        inputs=("C13", "C02"), synonyms="overshooting top tope penetrante",
    ),
    Variable(
        "diferencias", "ΔBT", "Diferencias entre bandas", "K", "goes-imagen",
        "Restas de temperatura de brillo entre bandas infrarrojas. El documento cita los pares C13 − C11 "
        "y C13 − C16 para estudiar las propiedades del tope (§4.2), y además C14 − C13 (11,2 − 10,3 µm) "
        "y C16 − C13 (13,3 − 10,3 µm) como variables por imagen (§5.4). C08 − C13 tiene ficha propia.",
        why="Cada banda ve una altura o una fase distinta; la resta aísla esa diferencia.",
        formula=r"T_{b,13} - T_{b,11},\quad T_{b,13} - T_{b,16},\quad T_{b,14} - T_{b,13}",
        method="C13 − C16 y C16 − C13 son el mismo par con el signo cambiado: al compararlas con la "
        "literatura, revisa el orden de la resta.",
        inputs=("C11", "C13", "C14", "C16"), synonyms="diferencia bandas",
    ),
    Variable(
        "v_fria", "Firma V", "Firma en «V» o «U» fría", "", "goes-imagen",
        "El patrón en forma de V o U de temperaturas frías que deja el flujo divergente en altura alrededor "
        "de un ascenso muy potente.",
        why="Es un precursor clásico de tiempo severo visible en el infrarrojo.",
        inputs=("C13",), synonyms="enhanced v cold u",
    ),
    Variable(
        "aacp", "AACP", "Pluma de cirros sobre el yunque", "", "goes-imagen",
        "Una pluma de cirros que se eleva sobre el yunque, aguas abajo de un tope penetrante.",
        why="En la literatura reciente es uno de los mejores precursores satelitales de tormenta severa.",
        inputs=("C02", "C13"), synonyms="above anvil cirrus plume",
    ),
    Variable(
        "textura", "Textura", "Textura del yunque", "", "goes-imagen",
        "Estadísticas del gradiente y de la varianza local de la banda 2.",
        why="Separa el yunque «burbujeante» de una tormenta vigorosa de la superficie lisa de una en "
        "decaimiento.",
        formula=r"\sigma^2_{\mathrm{local}} = \frac{1}{N}\sum_{\text{ventana}} (R_{02} - \bar R_{02})^2",
        inputs=("C02",), synonyms="varianza gradiente",
    ),
    Variable(
        "area_umbral", "A(T_b < T₀)", "Área del tope bajo umbrales", "km²", "goes-imagen",
        "El área de la celda con temperatura de brillo bajo −50, −60 y −70 °C.",
        why="Mide el tamaño del yunque frío; su tendencia es una de las variables dinámicas.",
        formula=r"A_{T_0} = \sum_{\text{píxeles}} \mathbb{1}[T_{b,13} < T_0]\;\Delta A",
        inputs=("C13",), synonyms="área yunque",
    ),
    Variable(
        "fase", "Fase", "Fase y tamaño de partícula del tope", "", "goes-imagen",
        "Si el tope es de hielo o de agua y qué tan grandes son sus partículas, con las bandas 11 y 6 o con "
        "los productos ACTPF y CPSF.",
        why="Las corrientes ascendentes fuertes llevan partículas pequeñas de hielo al tope.",
        inputs=("C06", "C11"), synonyms="hielo agua partícula",
    ),
    # --- GOES · tendencias -----------------------------------------------------------------------
    Variable(
        "dT", "ΔC13", "Tasa de enfriamiento del tope", "K", "goes-tendencias",
        "El cambio de temperatura de brillo de la banda 13 entre una imagen y la anterior, píxel a píxel.",
        why="Aporta información sobre la evolución de la nube, junto con su movimiento. Enfriamientos "
        "más rápidos que −4 K en "
        "15 min son un indicador establecido de convección en rápido desarrollo.",
        formula=r"\Delta T_b = T_{b,13}(t) - T_{b,13}(t - \Delta t)",
        method="El visor resta la imagen anterior disponible; Δt suele ser 10 min, pero no siempre: "
        "revisa el intervalo del título. También conviene en ventanas de 30 y 60 min.",
        caveat="Los dipolos de enfriamiento y calentamiento suelen ser nubes que se desplazan, no que "
        "crecen. El flujo óptico ayuda a separarlos.",
        inputs=("C13",), products=("goes:dT",), synonyms="tendencia enfriamiento dbt/dt",
    ),
    Variable(
        "expansion", "dA/dt", "Expansión del yunque", "km²/min", "goes-tendencias",
        "La tasa de crecimiento del área fría del tope.",
        why="Un yunque que se expande rápido indica una corriente ascendente vigorosa.",
        formula=r"\frac{dA_{T_0}}{dt} \approx \frac{A_{T_0}(t) - A_{T_0}(t-\Delta t)}{\Delta t}",
        inputs=("area_umbral",), synonyms="área crecimiento",
    ),
    Variable(
        "ot_crecimiento", "OT(t)", "Crecimiento del tope penetrante", "", "goes-tendencias",
        "Cómo cambian en el tiempo el tamaño y la temperatura de un tope penetrante.",
        why="Sigue el pulso de la corriente ascendente más intensa de la tormenta.",
        inputs=("overshooting",), synonyms="overshooting",
    ),
    Variable(
        "flujo_optico", "∇ × F", "Flujo óptico y su rotación", "1/s", "goes-tendencias",
        "Un campo de movimiento aparente estimado entre imágenes consecutivas. Su rotacional describe "
        "el giro de ese campo.",
        why="Permite buscar patrones compatibles con rotación y puede ayudar a distinguir el "
        "desplazamiento de los cambios de la nube en ΔC13.",
        formula=r"\zeta_F = \frac{\partial F_y}{\partial x} - \frac{\partial F_x}{\partial y}",
        caveat="El movimiento del yunque no confirma por sí solo un mesociclón ni mide directamente "
        f"su circulación interna. {_SOUTH} la rotación ciclónica es horaria.",
        inputs=("C13",), synonyms="optical flow rotación yunque",
    ),
    Variable(
        "lightning_jump", "Lightning jump", "Salto en la tasa de rayos", "rayos/min", "goes-tendencias",
        "Un aumento súbito de la frecuencia de descargas que detecta el GLM.",
        why="Precede típicamente en varios minutos al tiempo severo en superficie: uno de los "
        "indicadores de *nowcasting* mejor validados.",
        caveat="La eficiencia del GLM cae hacia el sur y Magallanes queda en el borde de su campo de visión.",
        inputs=("glm",), synonyms="rayos glm",
    ),
    Variable(
        "propagacion", "Desvío", "Propagación y desvío respecto del viento medio", "m/s",
        "goes-tendencias",
        "La velocidad y dirección con que se mueve la tormenta, y cuánto se aparta del viento medio de la "
        "capa.",
        why="Una desviación persistente a la izquierda es una señal de interés para las supercélulas "
        "ciclónicas australes. Debe combinarse con otras observaciones antes de clasificar la tormenta.",
        formula=r"\vec D = \vec C_{\mathrm{obs}} - \bar{\vec V}_{0\text{–}6}",
        inputs=("C13", "bunkers"), synonyms="movimiento tormenta left-mover desvío",
    ),
    # --- GOES · otros productos ------------------------------------------------------------------
    Variable("acha", "ACHAF", "Altura del tope nuboso", "m", "goes-productos",
             "Producto `ABI-L2-ACHAF`: la altura estimada del tope de la nube.",
             why="Es lo que hace falta para corregir el paralaje.",
             synonyms="altura tope paralaje"),
    Variable("actp", "ACTPF", "Fase del tope nuboso", "", "goes-productos",
             "Producto `ABI-L2-ACTPF`: si el tope es de hielo, agua o mixto.", synonyms="fase"),
    Variable("dsi", "DSIF", "Índices de estabilidad derivados", "", "goes-productos",
             "Producto `ABI-L2-DSIF`: CAPE, índice de levantamiento y agua precipitable estimados desde el "
             "satélite.",
             why="Un contraste independiente de ERA5.", synonyms="estabilidad cape satélite"),
    Variable("dmw", "DMWF", "Vientos derivados del movimiento", "m/s", "goes-productos",
             "Producto `ABI-L2-DMWF`: viento en altura medido siguiendo nubes y vapor.",
             why="Es una observación real de viento, con mucha más resolución que ERA5.",
             synonyms="vientos atmospheric motion vectors"),
    Variable("glm", "GLM", "Rayos", "", "goes-productos",
             "Producto `GLM-L2-LCFA` del detector de rayos: archivos cada 20 segundos.",
             caveat="Cobertura hasta ~52°S, con eficiencia de 70–90 % que cae hacia el sur.",
             synonyms="rayos lightning"),
    Variable("l1b", "L1b RadF", "Radiancias crudas", "", "goes-productos",
             "Producto `ABI-L1b-RadF`: radiancias sin convertir. Existe un reprocesamiento de GOES-16 "
             "(2018 – fines de 2024) con mejor calibración y navegación.",
             why="Conviene para una climatología multianual o si se quiere controlar la calibración.",
             synonyms="radiancia calibración"),
    # --- Catálogo · columnas ---------------------------------------------------------------------
    Variable("cat_posicion", "Latitude, Longitude", "Posición del evento", "°", "catalogo-columnas",
             "Las coordenadas del evento. Cobertura: 102 de 102.",
             caveat="Es la posición del daño observado, no la del mesociclón.",
             synonyms="coordenadas lugar"),
    Variable("cat_fecha", "Date", "Fecha", "", "catalogo-columnas",
             "La fecha en calendario gregoriano. Cobertura: 102 de 102.", synonyms="día"),
    Variable("cat_hora_utc", "Hour (UTC)", "Hora UTC", "UTC", "catalogo-columnas",
             "La hora del evento en tiempo universal, a veces como rango (`22-23:25`) o redondeada. "
             "Cobertura: 91 (89 %).",
             why="Es la columna que permite cruzar con GOES.",
             caveat="Con imágenes cada 10 min, un error de ±1 h son ±6 imágenes.", synonyms="hora"),
    Variable("cat_hora_local", "Hour (local)", "Hora local", "", "catalogo-columnas",
             "La hora local del evento. Cobertura: 95 (93 %). La mediana es las 14:00, en la ventana "
             "de calentamiento diurno.",
             synonyms="hora"),
    Variable("cat_tipo", "Tornado, Waterspout", "Tipo de evento", "binaria", "catalogo-columnas",
             "Indicadores de tornado (70) y tromba marina (45); 19 están marcados como ambos, trombas que "
             "tocaron tierra.",
             why="Distinguen registros sobre tierra y sobre agua y permiten estudiar la transición mar–tierra. "
             "Determinar el mecanismo de formación requiere evidencia adicional.",
             caveat="Los conteos se solapan: no se suman para obtener el total.",
             synonyms="tromba tornado"),
    Variable("cat_ef", "Max. EF Rating", "Intensidad EF", "EF0–EF3", "catalogo-columnas",
             "La intensidad en la escala Fujita mejorada, estimada por los daños. Cobertura: 94 (92 %). "
             "Unos 53 EF0, 28 EF1, 9 EF2 y 4 EF3; ningún EF4 ni EF5.",
             synonyms="fujita intensidad daño"),
    Variable("cat_register", "Register", "Registro visual", "sí/no", "catalogo-columnas",
             "Si existe testimonio o material visual de la columna rotatoria: 50 sí, 49 no.",
             why="Ayuda a seleccionar casos para revisar su evidencia y estudiar la confianza de las etiquetas. "
             "No confirma por sí solo el mecanismo de formación.",
             synonyms="confianza testimonio"),
    Variable("cat_fenomenos", "Hail, Electric Storm, …", "Fenómenos acompañantes", "binaria",
             "catalogo-columnas",
             "Granizo, tormenta eléctrica, sonido y daño, como indicadores binarios.",
             synonyms="granizo rayos daño"),
    Variable("cat_victimas", "Fatalities, Injured", "Víctimas", "", "catalogo-columnas",
             "Fallecidos y heridos: 38 fallecidos en 6 eventos y unos 1.020 heridos en 17.",
             synonyms="muertos heridos"),
    Variable("cat_fuentes", "Sources, Comments", "Procedencia y notas", "", "catalogo-columnas",
             "Las fuentes, los enlaces a documentos y los comentarios de cada registro.",
             synonyms="fuentes referencias"),
    # --- Contexto --------------------------------------------------------------------------------
    Variable(
        "distancias", "d_costa, d_Andes", "Distancia a la costa y a los Andes", "km",
        "contexto-variables",
        "La distancia de cada punto a la línea de costa y al pie de la cordillera.",
        why="Los Andes pueden modificar el viento de niveles bajos y la costa es la entrada de tormentas "
        "que vienen del mar.",
        synonyms="costa cordillera geografía",
    ),
    Variable(
        "terreno", "h, ∇h", "Altura del terreno y pendiente", "m", "contexto-variables",
        "La elevación del terreno y su pendiente.",
        why="Separa los valores reales de los extrapolados bajo tierra y describe el forzamiento "
        "orográfico.",
        method="Los índices del visor estiman la altura del terreno desde la presión de superficie.",
        inputs=("sp", "z"), synonyms="orografía elevación",
    ),
    Variable(
        "cenital_sat", "θ_sat", "Ángulo cenital del satélite", "°", "contexto-variables",
        "El ángulo entre la vertical del lugar y la dirección al satélite: ~40° en Santiago, ~60° en "
        "Punta Arenas.",
        why="Permite que el modelo compense la degradación geométrica: el píxel estirado y el paralaje.",
        formula=r"d_{\mathrm{paralaje}} \approx h_{\mathrm{tope}}\,\tan\theta_{\mathrm{sat}}",
        synonyms="paralaje geometría",
    ),
    Variable(
        "cenital_sol", "θ_sol", "Ángulo cenital solar", "°", "contexto-variables",
        "El ángulo entre la vertical del lugar y el Sol.",
        why="Las bandas visibles requieren luz solar; el modelo necesita considerar la iluminación.",
        synonyms="sol día noche",
    ),
    Variable(
        "calendario", "sin, cos", "Hora del día y día del año", "", "contexto-variables",
        "La hora y el día del año codificados en un círculo, para que las 23:00 queden cerca de las 00:00.",
        why="Captura el ciclo diurno (mediana a las 14:00 local) y la estacionalidad (máximo en junio).",
        formula=r"\left(\sin\frac{2\pi h}{24},\ \cos\frac{2\pi h}{24}\right), \qquad \left(\sin\frac{2\pi d}{365{,}25},\ \cos\frac{2\pi d}{365{,}25}\right)",
        synonyms="hora estación ciclo diurno",
    ),
    Variable(
        "poblacion", "Población", "Densidad de población", "hab/km²", "contexto-variables",
        "Cuántas personas viven por kilómetro cuadrado.",
        why="Ayuda a estudiar el sesgo de reporte. Incluirla no garantiza separar ocurrencia y "
        "observación: hace falta un modelo y supuestos sobre cómo se documentan los eventos.",
        synonyms="sesgo reporte censo",
    ),
)  # fmt: skip

# Fuentes propias de cada ficha; se suman a las de su grupo (``references_of``).
_REFS = {
    "msl": ("vicencio2021",), "cape": ("barrett2020",),
    "shear_01": ("vicencio2021",), "shear_06": ("vicencio2021",), "bunkers": ("bunkers2000",),
    "srh_01": ("metpy", "vicencio2021"), "srh_03": ("metpy", "vicencio2021"), "llj": ("vicencio2021",),
    "lcl": ("vicencio2021",), "t500": ("vicencio2021",),
    "vgp_01": ("rasmussen1998", "vicencio2021"), "stp_lm": ("thompson2003", "thompson2012", "marin2024"),
    "sherbs3": ("sherburn2014", "marin2024"), "scp": ("thompson2003", "thompson2012"), "brn": ("weisman1982",),
    "calendario": ("caballero2025",), "poblacion": ("bastias",), "ehi": ("documento",),
}  # fmt: skip
VARIABLES = tuple(replace(v, refs=(*v.refs, *_REFS.get(v.key, ()))) for v in VARIABLES)

BY_KEY = {v.key: v for v in VARIABLES}
# producto → la primera ficha que lo nombra (pl:t → «t», no «T₅₀₀»)
BY_PRODUCT: dict[str, Variable] = {}
for _v in VARIABLES:
    for _p in _v.products:
        BY_PRODUCT.setdefault(_p, _v)


def _normalize(text: str) -> str:
    """``text`` en minúsculas y sin tildes, para buscar «helicidad» y encontrar «Helicidad»."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def search(query: str) -> list[Variable]:
    """Las variables cuyas palabras contienen todas las de ``query`` (vacía: todas)."""
    words = _normalize(query).split()
    return [
        v for v in VARIABLES
        if all(p in _normalize(" ".join((v.key, v.symbol, v.name, v.synonyms, v.what)))
               for p in words)
    ]  # fmt: skip


def references_of(v: Variable) -> list[str]:
    """Claves de ``REFERENCES`` de la ficha ``v``: las de su grupo y las propias, sin repetir."""
    group = next(g for g in GROUPS if g.key == v.group)
    return list(dict.fromkeys((*group.refs, *v.refs)))


def summary(v: Variable) -> str:
    """La ayuda en contexto de Mapas: definición, criterio chileno y cuidado, en un párrafo."""
    threshold = f"**Criterio en Chile:** {v.threshold}" if v.threshold else ""
    parts = [f"**{v.symbol} · {v.name}.** {v.what}", threshold, v.caveat]
    return " ".join(p for p in parts if p)
