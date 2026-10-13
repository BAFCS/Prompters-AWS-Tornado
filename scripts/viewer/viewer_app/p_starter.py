"""Página «Starter kit»: dónde están los datos, qué scripts trae el repositorio y cómo usarlos en AWS.

Cierra con los próximos pasos (definir el problema, ideas para explorar) y los trabajos relacionados.
No usa datos: se muestra aunque no haya recortes.
"""

import streamlit as st

from viewer_app import diagrams, layout, state, variables
from viewer_app.p_project import REPOSITORY

# Secciones del índice: (ancla del encabezado, texto del enlace).
SECTIONS = (
    ("inicio", "Inicio"),
    ("buckets", "Dónde están los datos"),
    ("scripts", "Los scripts"),
    ("arquitectura", "Arquitectura"),
    ("nube", "Trabajar en AWS"),
    ("entrenar", "Datos para entrenar"),
    ("pasos", "Próximos pasos"),
    ("explorar", "Ideas para explorar"),
    ("relacionados", "Trabajos relacionados"),
)

_LIST = """\
# Listar no descarga nada; --no-sign-request evita pedir credenciales
aws s3 ls --no-sign-request s3://nsf-ncar-era5/e5.oper.an.pl/201905/
aws s3 ls --no-sign-request s3://noaa-goes16/ABI-L2-MCMIPF/2019/150/21/
aws s3 ls --no-sign-request s3://noaa-goes19/ABI-L2-MCMIPF/
"""

_SETUP = f"""\
# En la máquina de AWS (us-west-2, Amazon Linux 2023)
sudo dnf install -y git
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # deja uv en el PATH de esta terminal
git clone {REPOSITORY}.git
cd aws-mesocyclonic
uv sync
mkdir -p data
curl -L -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl -L -o data/coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip
"""

_PIPELINE = """\
# Primero se baja y recorta, después se calcula
uv run python scripts/pipeline/download_era5.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/download_goes.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_goes.py  --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_era5.py  --start 2019-05-30 --end 2019-05-31

# Copia de los recortes al bucket del equipo, en la misma región
aws s3 sync data/crops/ s3://<bucket-del-equipo>/crops/
"""

_VIEWER = """\
# En la máquina de AWS
uv run streamlit run scripts/viewer/viewer.py --server.port 8501

# En tu computador: AWS CLI, el plugin de Session Manager y credenciales temporales
aws sso login
aws ssm start-session --target <id-de-la-instancia> \\
  --document-name AWS-StartPortForwardingSession \\
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}'
# y abrir http://localhost:8501
"""

_ARCH_ALT = (
    "Diagrama de la arquitectura. Los buckets públicos de GOES (us-east-1) y ERA5 (us-west-2) alimentan una "
    "máquina EC2 en us-west-2, que corre los scripts y el visor y guarda los recortes en el bucket del "
    "equipo. Desde ese bucket se consultan las tablas con Athena y se entrena con SageMaker. El rol IAM de "
    "la máquina limita su acceso a S3 al bucket del equipo. El computador personal se conecta a la máquina "
    "por un túnel de Session Manager."
)

_BUCKET_LAYOUT = """\
s3://<bucket-del-equipo>/          # us-west-2, acceso público bloqueado
  crops/<región>/...               # lo que dejan los scripts (NetCDF), igual que data/crops/
  features/year=2019/*.parquet     # tabla de ejemplos, una carpeta por año
  cubes/                           # cubos para modelos de imágenes, si se usan
  models/                          # modelos entrenados y sus métricas
"""

_FORMATS = """\
# Tabla de ejemplos (pandas): una fila por celda y hora, con los índices de ERA5 y la etiqueta.
# pyarrow y s3fs ya están instalados, así que se escribe directo en S3, una carpeta por año.
table.to_parquet("s3://<bucket-del-equipo>/features/", partition_cols=["year"])

# Leer solo un año
import pandas as pd
year_2019 = pd.read_parquet("s3://<bucket-del-equipo>/features/", filters=[("year", "=", 2019)])
"""

_ATHENA = """\
-- Tras registrar features/ como tabla (un crawler de AWS Glue o CREATE EXTERNAL TABLE).
-- Con CREATE EXTERNAL TABLE, cargar las carpetas year=... antes de consultar:
MSCK REPAIR TABLE features;

SELECT year, count(*) AS ejemplos, sum(label) AS positivos
FROM features
GROUP BY year
ORDER BY year;
"""


def _cover() -> None:
    """Título y para qué sirve la página."""
    st.title("Starter kit", anchor="inicio")
    st.markdown(
        "<p class='lede'>Lo necesario para empezar: en qué buckets están los datos, qué hace cada "
        "script del repositorio y cómo correrlos dentro de AWS. Por cada día hay que leer unos 12 GB de "
        "ERA5 y GOES para guardar 1,5 GB, así que las descargas se hacen en una máquina de AWS. En tu "
        "computador alcanza para bajar uno o dos días y probar el visor.</p>",
        unsafe_allow_html=True,
    )


def _buckets() -> None:
    """Los buckets públicos de ERA5 y GOES, con su región, y las fuentes que no están en AWS."""
    layout.section(
        "buckets",
        "Dónde están los datos",
        "ERA5 y GOES están en buckets públicos de Amazon S3 y se leen sin credenciales. ERA5 está en la "
        "región us-west-2 y GOES, en us-east-1.",
    )
    st.markdown(
        "| Conjunto | Bucket y prefijo | Qué contiene |\n"
        "|---|---|---|\n"
        "| ERA5, niveles de presión | `s3://nsf-ncar-era5/e5.oper.an.pl/` | Un archivo por variable y día, con el globo entero y 37 niveles (≈ 1,4 GB) |\n"
        "| ERA5, superficie | `s3://nsf-ncar-era5/e5.oper.an.sfc/` | Archivos mensuales: viento a 10 m, temperatura y punto de rocío a 2 m, presión, CAPE |\n"
        "| ERA5, campos fijos | `s3://nsf-ncar-era5/e5.oper.invariant/` | Orografía y máscara de tierra |\n"
        "| GOES-16 (dic 2017 – abr 2025) | `s3://noaa-goes16/ABI-L2-MCMIPF/` | Disco completo, 16 bandas a 2 km, cada 10 minutos (cada 15 antes de abril de 2019); ≈ 360 MB por imagen |\n"
        "| GOES-19 (desde abr 2025) | `s3://noaa-goes19/ABI-L2-MCMIPF/` | Lo mismo, con el satélite que reemplazó a GOES-16 |\n"
        "| Catálogo de tornados | [figshare](https://doi.org/10.6084/m9.figshare.25119566), hoja `Final_Table`, fuera de AWS | 102 eventos, un archivo de 160 kB |"
    )
    st.code(_LIST, language="bash")
    st.markdown(
        "En los mismos buckets hay otros productos de GOES: `GLM-L2-LCFA` (rayos, desde febrero de 2018) "
        "y, desde diciembre de 2019, `ABI-L2-ACHAF` (altura del tope, para corregir el paralaje), "
        "`ABI-L2-DMWF` (vientos derivados del movimiento de las nubes) y `ABI-L2-DSIF` (índices de "
        "estabilidad estimados desde el satélite). Estos tres últimos no cubren el brote de mayo de 2019.\n\n"
        "El bucket `era5-pds` está deprecado y solo tiene variables de superficie, así que no sirve. "
        "`noaa-goes18` es GOES-West y no sirve para Chile."
    )


def _scripts() -> None:
    """Qué hace cada script del repositorio y qué deja."""
    layout.section(
        "scripts",
        "Los scripts",
        "Estos scripts bajan, recortan y procesan los datos que usa el visor.",
    )
    st.markdown(
        "Los de `scripts/pipeline/` se corren en orden: primero se baja, después se calcula. Todos aceptan "
        "`--start` y `--end` (fechas UTC), `--region` y `--force`; `--help` muestra el resto de las "
        "opciones. Saltan lo que ya existe, así que si una descarga se corta basta repetir el comando.\n\n"
        "| Script | Qué hace | Salida |\n"
        "|---|---|---|\n"
        "| `download_era5.py` | Baja ERA5 (niveles de presión y superficie) y recorta la región. Cada hora de un nivel de presión es un bloque global de 50–65 MB que se transfiere entero y se recorta en memoria | `data/crops/<región>/era5_pl/`, `era5_sfc/`, un archivo por día |\n"
        "| `download_goes.py` | Baja GOES `ABI-L2-MCMIPF`. Lee el índice del archivo y pide a S3 solo los bloques que tocan la región. Elige GOES-16 o GOES-19 según la fecha | `data/crops/<región>/goes/`, un archivo por hora |\n"
        "| `process_goes.py` | Reproyecta GOES a una grilla regular de latitud y longitud, con vecino más cercano para no alterar los valores. No corrige paralaje | `data/crops/<región>/goes_latlon/` |\n"
        "| `process_era5.py` | Calcula cizalladura, movimiento de Bunkers *left-mover*, SRH, VGP₀₋₁, STP sin CIN, SHERBS3 y LCL con los signos del hemisferio sur | `data/crops/<región>/era5_indices/` |\n"
        "| `viewer/viewer.py` | Este visor | — |\n"
        "| `figures/figs_*.py` | Las figuras del documento: catálogo, entorno ERA5 y una imagen de la banda 13 | `figs/` |"
    )
    st.caption(
        "Regiones predefinidas: `south-central-austral` (por defecto, 30°S–56°S), `south-central` "
        "(30°S–45°S) y `full`. Para otro recuadro se usa `--bbox` junto con un `--region` nuevo; sin él, "
        "los datos quedan mezclados con los de la región por defecto. Lo compartido entre scripts vive en "
        "`scripts/common.py`."
    )


def _architecture() -> None:
    """El diagrama de la arquitectura, qué servicio va en cada etapa, permisos y costos."""
    layout.section(
        "arquitectura",
        "Arquitectura",
        "Lo del equipo vive en us-west-2, junto a ERA5.",
    )
    with st.container(border=True, key="sheet_architecture"):
        layout.image(diagrams.architecture(), _ARCH_ALT, key="architecture")
        st.markdown(
            "<p class='note'>Las cifras son por día de datos de la región por defecto. Las cajas y flechas "
            "resaltadas son lo que maneja el equipo; las flechas grises, la lectura de los buckets "
            "públicos.</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "| Etapa | Servicio | Para qué |\n"
        "|---|---|---|\n"
        "| Leer y recortar | EC2 | Corre los scripts de `scripts/pipeline/` cerca de ERA5 |\n"
        "| Guardar | S3, bucket del equipo | Recortes, tablas de ejemplos y modelos |\n"
        "| Consultar | Athena | SQL sobre las tablas Parquet sin levantar un servidor |\n"
        "| Entrenar | SageMaker | Cuadernos para prototipos y trabajos de entrenamiento que leen de S3 |\n"
        "| Mirar | El visor, en la misma máquina EC2 | Se abre desde tu navegador por un túnel |"
    )
    st.subheader("Permisos y costos", anchor=False)
    st.markdown(
        "- **Bucket del equipo.** En us-west-2, con el acceso público bloqueado, que es lo que S3 trae por "
        "defecto. Abajo hay una estructura de carpetas posible.\n"
        "- **Rol de la máquina.** Un rol IAM que en S3 solo puede leer y escribir el bucket del equipo, más "
        "la política `AmazonSSMManagedInstanceCore` para Session Manager. Los buckets públicos no necesitan "
        "permisos, porque los scripts los leen de forma anónima. La máquina no abre puertos y su grupo de "
        "seguridad puede quedar sin reglas de entrada.\n"
        "- **Personas.** Cada una entra con credenciales temporales de la cuenta (por ejemplo, con "
        "`aws sso login`), sin claves permanentes. Athena y SageMaker se usan con esos permisos o con el "
        "rol de SageMaker Studio, no con el de la máquina.\n"
        "- **Costos.** Se cobran las horas de instancia, el disco (también con la instancia detenida), lo "
        "guardado en S3, las transferencias entre regiones y lo que sale de AWS a internet. Conviene una "
        "alerta en AWS Budgets, una etiqueta por equipo (por ejemplo, `team=<nombre>`) en cada recurso y "
        "detener la máquina cuando nadie la usa."
    )
    st.code(_BUCKET_LAYOUT, language="text")


def _cloud() -> None:
    """Cómo correr todo dentro de AWS: la máquina, la descarga y cómo abrir el visor."""
    layout.section(
        "nube",
        "Trabajar en AWS",
        "Tres pasos: preparar una máquina EC2, bajar los datos y abrir el visor desde tu navegador.",
    )
    st.subheader("1. Una máquina en us-west-2", anchor=False)
    st.markdown(
        "ERA5 es casi todo lo que se transfiere (≈ 11 GB por día) y está en us-west-2, así que la máquina va "
        "ahí. GOES está en us-east-1, pero el script pide solo los bloques de la región, que pesan mucho "
        "menos; no medimos cuánto agrega la distancia entre regiones. São Paulo (`sa-east-1`) queda más "
        "cerca de Chile, pero no aloja ninguno de los dos conjuntos.\n\n"
        "Alcanza una instancia EC2 de uso general con unos 4 vCPU y 16 GB de RAM. `download_era5.py` usa "
        "unos 400 MB por proceso y corre cuatro a la vez; lo que limita es la red, y las instancias más "
        "grandes tienen más ancho de banda. Los bloques globales de ERA5 se recortan en memoria y no pasan "
        "por el disco, así que 50 a 100 GB de disco alcanzan para decenas de días (≈ 1,5 GB por día) antes "
        "de copiarlos al bucket."
    )
    st.code(_SETUP, language="bash")
    st.subheader("2. Bajar, recortar y guardar en S3", anchor=False)
    st.markdown(
        "Conviene partir con el caso de mayo de 2019 y unos pocos días de control, medir cuánto tarda y "
        "cuánto cuesta, y recién después ampliar. Los scripts escriben en el disco de la máquina; al "
        "terminar, los recortes se copian al bucket del equipo para que no se pierdan al apagarla."
    )
    st.code(_PIPELINE, language="bash")
    st.subheader("3. Abrir el visor", anchor=False)
    st.markdown(
        "El visor corre en la misma máquina y se abre desde tu navegador por un túnel de Session Manager. "
        "Tu computador necesita la AWS CLI, el plugin de Session Manager y credenciales temporales."
    )
    st.code(_VIEWER, language="bash")
    st.markdown(
        "<div class='notice'><strong>En tu computador, solo uno o dos días.</strong> Desde Chile, bajar un "
        "día de ERA5 toma unos 15 minutos con 100 Mbps, y un año completo, casi cuatro días. Además, AWS "
        "cobra cada gigabyte que sale a internet, por ejemplo al copiar los recortes del bucket a tu "
        "disco.</div>",
        unsafe_allow_html=True,
    )


def _training_data() -> None:
    """Formatos para pasar de los recortes a un modelo, y dónde entrenar."""
    layout.section(
        "entrenar",
        "Datos para entrenar",
        "Los recortes en NetCDF sirven para explorar día a día. Para entrenar conviene reorganizarlos según "
        "cómo los va a leer el modelo.",
    )
    st.markdown(
        "| Qué | Formato | Por qué |\n"
        "|---|---|---|\n"
        "| Recortes por día y por hora | NetCDF, como los dejan los scripts | Los lee el visor y cualquier "
        "herramienta con `xarray` |\n"
        "| Tabla de ejemplos (una fila por celda y hora, o por tormenta) | Parquet, una carpeta por año | Se "
        "lee por columnas y por año sin abrir todo, desde `pandas` o con SQL en Athena |\n"
        "| Cubos para modelos de imágenes (secuencias GOES, ERA5 en 3D) | Zarr | Se lee por bloques desde "
        "S3; conviene que cada bloque coincida con lo que pide el modelo, por ejemplo una hora de la región. "
        "Requiere `uv add zarr dask` |"
    )
    st.code(_FORMATS, language="python")
    st.markdown(
        "Con la tabla en Parquet, Athena responde preguntas rápidas sin escribir código, por ejemplo "
        "cuántos ejemplos y positivos hay por año antes de separar entrenamiento y prueba:"
    )
    st.code(_ATHENA, language="sql")
    st.markdown(
        "Para entrenar, un cuaderno de SageMaker Studio basta mientras el conjunto quepa en memoria. Su "
        "espacio trae 5 GB de disco por defecto, que hay que ampliar antes de instalar el entorno o copiar "
        "datos. Cuando el conjunto no cabe, un trabajo de entrenamiento de SageMaker lee de `features/` y "
        "deja el modelo en `models/`. SageMaker también ofrece MLflow administrado para registrar cada "
        "experimento con sus parámetros y métricas."
    )


def _next_steps() -> None:
    """La definición del problema que falta cerrar y las primeras tareas."""
    layout.section(
        "pasos",
        "Próximos pasos",
        "Antes de entrenar hay que decidir qué se predice. Problema detalla cada decisión con sus opciones.",
    )
    st.subheader("Definir el problema", anchor=False)
    st.markdown(
        "El criterio de éxito es entregar candidatos a mesociclón para 2026, que revisarán expertos y se "
        "contrastarán con una base de tornados que mantiene el CR2 y que no es pública. Lo demás queda en "
        "manos de cada equipo:\n\n"
        "- **Unidad de análisis.** Una tormenta seguida en GOES, una celda de ERA5 por hora o una región por día.\n"
        "- **Qué es un positivo.** Un tornado reportado, un mesociclón inferido o ambos, por niveles.\n"
        "- **Días de comparación.** Días al azar en la época de tornados, días elegidos a mano o una mezcla. "
        "Un día sin reporte no prueba que no hubo tornado.\n"
        "- **Diagnóstico o pronóstico.** Estimar con los datos de la hora del evento o con datos de horas antes.\n"
        "- **Mirar hacia atrás.** Buscar en el archivo histórico situaciones que pudieron no quedar registradas.\n"
        "- **Salida y métrica.** Un puntaje o una lista corta de candidatos, medidos con la tasa de acierto, "
        "las falsas alarmas y cuántos candidatos revisa un experto por cada tornado encontrado."
    )
    st.page_link(
        state.page("project"),
        label="Ver las decisiones abiertas en Problema",
        icon=":material/info:",
    )
    st.subheader("Primeras tareas", anchor=False)
    st.markdown(
        "1. Preparar el caso de 2019 en AWS con los comandos de arriba y revisarlo en el visor.\n"
        "2. Ordenar el catálogo: fechas, horas UTC, coordenadas y confianza de cada registro.\n"
        "3. Elegir los días de control y armar una primera tabla con los índices de ERA5, un ejemplo por fila.\n"
        "4. Entrenar un modelo tabular simple (por ejemplo, *gradient boosting*) y evaluarlo separando "
        "eventos completos, sin mezclar horas de un mismo brote entre entrenamiento y prueba.\n"
        "5. Recién con esa referencia, sumar GOES y comparar con los mismos casos de evaluación."
    )


def _explore() -> None:
    """Líneas de trabajo abiertas, del documento (sección 8) y de lo que el repositorio no hace todavía."""
    layout.section(
        "explorar",
        "Ideas para explorar",
        "Líneas abiertas que el repositorio todavía no cubre, ordenadas de menor a mayor dificultad.",
    )
    layout.cards(
        "explore",
        [
            ("Intermedia", "primary", "Corregir el paralaje",
             "GOES ve los topes de lado: a 40°S un tope de 12 km aparece unos 13 km corrido hacia el sur. Desde diciembre de 2019, `ABI-L2-ACHAF` da la altura del tope para corregirlo. Para fechas anteriores, como el caso de 2019, la altura se puede estimar comparando la temperatura de brillo de la banda 13 con el perfil de temperatura de ERA5."),
            ("Intermedia", "primary", "Rayos y saltos de actividad",
             "El GLM detecta rayos de forma continua y publica un archivo cada 20 segundos. Un aumento brusco de la tasa de rayos se ha usado como señal de tormenta severa (Schultz et al. 2009). Cerca de 52°S el detector pierde cobertura."),
            ("Intermedia", "primary", "Firmas del tope nuboso",
             "Topes penetrantes y penachos de cirros sobre el yunque son indicadores de tormentas severas en el visible y el infrarrojo (Bedka et al. 2018). Falta ver si aparecen en tormentas HSLC con poca energía."),
            ("Intermedia", "primary", "Vientos y estabilidad desde el satélite",
             "Desde diciembre de 2019, `ABI-L2-DMWF` da viento en altura y `ABI-L2-DSIF`, índices de estabilidad estimados, estos solo con cielo despejado. Sirven para contrastar con ERA5 el entorno de las tormentas."),
            ("Avanzada", "orange", "Rotación con flujo óptico",
             "Estimar el movimiento del yunque en secuencias GOES y buscar patrones de rotación. Antes hay que decidir cómo comprobar que esa señal corresponde a un mesociclón."),
            ("Avanzada", "orange", "PU learning con sesgo de reporte",
             "Tratar los días sin registro como no etiquetados en vez de negativos (Elkan y Noto 2008). Su método supone que la probabilidad de registrar un evento es la misma en todas partes; modelarla según población, hora y año queda como extensión."),
            ("Avanzada", "orange", "Preentrenar con otros datos",
             "Aprendizaje autosupervisado con imágenes GOES sin etiquetas, o un modelo entrenado con tornados de Estados Unidos y ajustado con casos chilenos, revisando las convenciones de giro."),
            ("Avanzada", "orange", "Recalibrar los índices",
             "Ajustar STP o SCP a los casos chilenos, separando un ajuste exploratorio de un criterio validado en casos independientes."),
        ],
    )  # fmt: skip


# Trabajos relacionados por tema: (título, claves de ``variables.REFERENCES``).
RELATED = (
    ("El catálogo y los tornados en Chile", ("bastias", "vicencio2021", "barrett2020", "marin2024",
                                             "caballero2025", "marin2026")),
    ("Entornos de convección severa e índices", ("brooks2003", "sherburn2014", "thompson2003",
                                                 "thompson2012", "rasmussen1998", "bunkers2000")),
    ("Satélite y rayos", ("cintineo2014", "bedka2018", "schultz2009")),
    ("Aprendizaje automático", ("lagerquist2020", "elkan2008")),
    ("Datos y herramientas", ("hersbach2020", "era5-ncar", "goes-aws", "metpy")),
)  # fmt: skip


def _link(url: str) -> str:
    """El enlace de una referencia, con la dirección como texto (el DOI cuando lo hay)."""
    text = url.removeprefix("https://").removeprefix("doi.org/")
    return f" [{text}]({url})" if url else ""


def _related() -> None:
    """Referencias agrupadas por tema, desde la bibliografía compartida de ``variables``."""
    layout.section(
        "relacionados",
        "Trabajos relacionados",
        "Dónde buscar cómo se ha abordado el mismo problema, en Chile y en otros lugares.",
    )
    for title, keys in RELATED:
        st.subheader(title, anchor=False)
        refs = [variables.REFERENCES[k] for k in keys]
        st.markdown("\n".join(f"- {r.full}{_link(r.url)}" for r in refs))
    st.markdown(
        "La sección 10 del documento suma los análogos de costa occidental (Australia, California, "
        "Inglaterra) y los textos de física de referencia."
    )


def page() -> None:
    """Dibuja la página con su índice."""
    layout.page("starter", layout.toc(SECTIONS), _body)


def _body() -> None:
    """Todas las secciones, en orden."""
    _cover()
    _buckets()
    _scripts()
    _architecture()
    _cloud()
    _training_data()
    _next_steps()
    _explore()
    _related()
