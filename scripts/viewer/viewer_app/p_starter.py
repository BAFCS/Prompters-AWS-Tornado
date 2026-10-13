"""Página «Starter kit»: dónde están los datos, qué scripts trae el repositorio y cómo usarlos en AWS.

Cierra con los próximos pasos (definir el problema, ideas para explorar) y los trabajos relacionados.
No usa datos: se muestra aunque no haya recortes.
"""

import streamlit as st

from viewer_app import diagrams, state, variables
from viewer_app.p_project import REPOSITORY, _cards, _image, _section

# Secciones del índice: (ancla del encabezado, texto del enlace).
SECTIONS = (
    ("inicio", "Inicio"),
    ("buckets", "Dónde están los datos"),
    ("scripts", "Los scripts"),
    ("arquitectura", "Arquitectura"),
    ("nube", "Cómo usarlo en AWS"),
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
# En la máquina de AWS (us-west-2), no en tu computador
git clone {REPOSITORY}.git
cd aws-mesocyclonic
curl -LsSf https://astral.sh/uv/install.sh | sh   # instala uv
uv sync
curl -L -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
"""

_PIPELINE = """\
# Primero se baja y recorta, después se calcula
uv run python scripts/pipeline/download_era5.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/download_goes.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_goes.py  --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_era5.py  --start 2019-05-30 --end 2019-05-31

# Los recortes quedan en data/crops/: se guardan en el bucket del equipo, en la misma región
aws s3 sync data/crops/ s3://<bucket-del-equipo>/crops/
"""

_VIEWER = """\
# En la máquina de AWS
uv run streamlit run scripts/viewer/viewer.py --server.port 8501

# En tu computador: un túnel hacia esa máquina (EC2 con Session Manager)
aws ssm start-session --target <id-de-la-instancia> \\
  --document-name AWS-StartPortForwardingSession \\
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}'
# y abrir http://localhost:8501
"""


def _cover() -> None:
    """Título y para qué sirve la página."""
    st.title("Starter kit", anchor="inicio")
    st.markdown(
        "<p class='lede'>Lo necesario para empezar: en qué buckets están los datos, qué hace cada "
        "script del repositorio y cómo correrlos dentro de AWS. Un día de ERA5 y GOES obliga a leer "
        "unos 12 GB para quedarse con 1,5 GB, así que todo se lee, se recorta y se calcula en la nube, "
        "y a tu computador no baja ningún dato.</p>",
        unsafe_allow_html=True,
    )


def _buckets() -> None:
    """Los buckets públicos de ERA5 y GOES, con su región, y las fuentes que no están en AWS."""
    _section(
        "buckets",
        "Dónde están los datos",
        "ERA5 y GOES están en buckets públicos de Amazon S3 y se leen sin credenciales. ERA5 está en la región us-west-2 y GOES, en us-east-1.",
    )
    st.markdown(
        "| Conjunto | Bucket y prefijo | Qué contiene |\n"
        "|---|---|---|\n"
        "| ERA5, niveles de presión | `s3://nsf-ncar-era5/e5.oper.an.pl/` | Un archivo por variable y día, con el globo entero y 37 niveles (≈ 1,4 GB) |\n"
        "| ERA5, superficie | `s3://nsf-ncar-era5/e5.oper.an.sfc/` | Archivos mensuales: viento a 10 m, temperatura y punto de rocío a 2 m, presión, CAPE |\n"
        "| ERA5, campos fijos | `s3://nsf-ncar-era5/e5.oper.invariant/` | Orografía y máscara de tierra |\n"
        "| GOES-16 (dic 2017 – abr 2025) | `s3://noaa-goes16/ABI-L2-MCMIPF/` | Disco completo, 16 bandas a 2 km, cada 10 minutos (≈ 360 MB por imagen) |\n"
        "| GOES-19 (desde abr 2025) | `s3://noaa-goes19/ABI-L2-MCMIPF/` | Lo mismo, con el satélite que reemplazó a GOES-16 |\n"
        "| Catálogo de tornados | [figshare](https://doi.org/10.6084/m9.figshare.25119566), hoja `Final_Table`, fuera de AWS | 102 eventos, un archivo de 160 kB |"
    )
    st.code(_LIST, language="bash")
    st.markdown(
        "GOES tiene otros productos útiles en los mismos buckets: `ABI-L2-ACHAF` (altura del tope, para "
        "corregir el paralaje), `ABI-L2-DMWF` (vientos derivados del movimiento de las nubes), "
        "`ABI-L2-DSIF` (índices de estabilidad estimados desde el satélite) y `GLM-L2-LCFA` (rayos).\n\n"
        "El bucket `era5-pds` está deprecado y solo tiene variables de superficie: no sirve aquí. "
        "`noaa-goes18` es GOES-West y no ve Chile."
    )


def _scripts() -> None:
    """Qué hace cada script del repositorio y qué deja."""
    _section(
        "scripts",
        "Los scripts",
        "El repositorio trae la cadena completa, desde el bucket hasta el visor.",
    )
    st.markdown(
        "Los de `scripts/pipeline/` se corren en orden: primero se baja, después se calcula. Todos aceptan "
        "`--start` y `--end` (fechas UTC), `--region` o `--bbox`, y `--force`, y `--help` muestra el resto "
        "de las opciones. Saltan lo que ya existe, así que si una descarga se corta basta repetir el "
        "comando.\n\n"
        "| Script | Qué hace | Deja en `data/crops/<región>/` |\n"
        "|---|---|---|\n"
        "| `download_era5.py` | Baja ERA5 (niveles de presión y superficie) y recorta la región. Cada hora de un nivel de presión es un bloque global de 50–65 MB que se transfiere entero y se recorta en memoria | `era5_pl/`, `era5_sfc/`, un archivo por día |\n"
        "| `download_goes.py` | Baja GOES `ABI-L2-MCMIPF`. Lee el índice del archivo y pide a S3 solo los bloques que tocan la región. Elige GOES-16 o GOES-19 según la fecha | `goes/`, un archivo por hora |\n"
        "| `process_goes.py` | Reproyecta GOES a una grilla regular de latitud y longitud, con vecino más cercano para no alterar los valores. No corrige paralaje | `goes_latlon/` |\n"
        "| `process_era5.py` | Calcula cizalladura, movimiento de Bunkers *left-mover*, SRH, VGP₀₋₁, STP sin CIN, SHERBS3 y LCL con los signos del hemisferio sur | `era5_indices/` |\n"
        "| `viewer/viewer.py` | Este visor | — |\n"
        "| `figures/figs_*.py` | Las figuras del documento: catálogo, entorno ERA5 y una imagen de la banda 13 | `figs/` |"
    )
    st.caption(
        "Regiones predefinidas: `south-central-austral` (por defecto, 30°S–56°S), `south-central` "
        "(30°S–45°S) y `full`; `--bbox` define otra a medida. Lo compartido entre scripts vive en "
        "`scripts/common.py`."
    )


_ARCH_ALT = (
    "Diagrama de la arquitectura. Los buckets públicos de GOES (us-east-1) y ERA5 (us-west-2) alimentan una "
    "máquina en us-west-2, que corre los scripts y el visor y guarda los recortes en el bucket del equipo. "
    "Desde ese bucket se consultan las tablas con Athena y se entrena con SageMaker. Un rol IAM limita los "
    "permisos al bucket del equipo. El computador personal se conecta a la máquina por Session Manager y "
    "solo recibe la página."
)

_BUCKET_LAYOUT = """\
s3://<bucket-del-equipo>/          # us-west-2, acceso público bloqueado
  crops/<región>/...               # lo que dejan los scripts (NetCDF), igual que data/crops/
  features/year=2019/part-0.parquet   # tabla de ejemplos, una carpeta por año
  cubes/goes_20190530.zarr         # cubos para modelos de imágenes
  models/                          # modelos entrenados y sus métricas
"""

_FORMATS = """\
import xarray as xr

# Tabla de ejemplos (pandas): una fila por celda y hora, índices de ERA5 y la etiqueta.
# pyarrow y s3fs ya están instalados, así que se escribe directo en S3.
table.to_parquet("s3://<bucket-del-equipo>/features/", partition_cols=["year"])

# Un recorte de GOES como cubo Zarr, en bloques de una hora (requiere: uv add zarr)
goes = xr.open_mfdataset("data/crops/south-central-austral/goes_latlon/20190530/*.nc")
goes.chunk({"time": 6}).to_zarr("s3://<bucket-del-equipo>/cubes/goes_20190530.zarr")
"""

_ATHENA = """\
-- Tras registrar features/ como tabla (un crawler de AWS Glue o CREATE EXTERNAL TABLE)
SELECT year, count(*) AS ejemplos, sum(label) AS positivos
FROM features
GROUP BY year
ORDER BY year;
"""


def _architecture() -> None:
    """El diagrama de la arquitectura y la receta del entorno: máquina, disco, permisos y costos."""
    _section(
        "arquitectura",
        "Arquitectura",
        "Todo lo del equipo vive en us-west-2, junto a ERA5. Los datos entran desde los buckets públicos y "
        "no salen de AWS.",
    )
    with st.container(border=True, key="sheet_architecture"):
        _image(diagrams.architecture(), _ARCH_ALT, key="architecture")
        st.markdown(
            "<p class='note'>Las cifras son por día de datos de la región por defecto. Las cajas y flechas resaltadas "
            "son lo que maneja el equipo; las flechas grises, la lectura de los buckets públicos.</p>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "| Etapa | Servicio | Para qué |\n"
        "|---|---|---|\n"
        "| Leer y recortar | EC2 o SageMaker Studio | Corre los scripts de `scripts/pipeline/` cerca de ERA5 |\n"
        "| Guardar | S3, bucket del equipo | Recortes, tablas de ejemplos, cubos y modelos |\n"
        "| Consultar | Athena | SQL sobre las tablas Parquet sin levantar un servidor |\n"
        "| Entrenar | SageMaker | Cuadernos para prototipos y trabajos de entrenamiento que leen de S3 |\n"
        "| Mirar | El visor en la misma máquina | Se abre por Session Manager; solo viaja la página |"
    )
    st.subheader("El entorno", anchor=False)
    st.markdown(
        "- **Máquina.** Una instancia de uso general mediana, con unos 4 vCPU y 16 GB de RAM, alcanza. "
        "`download_era5.py` usa unos 400 MB por proceso y corre cuatro a la vez; lo que limita es la red, y "
        "las instancias más grandes tienen más ancho de banda. Un espacio JupyterLab de SageMaker Studio "
        "sirve igual y trae los cuadernos listos.\n"
        "- **Disco.** Es de paso: lo que importa queda en S3. Los bloques globales de ERA5 se recortan en "
        "memoria y no tocan el disco, así que 50 a 100 GB alcanzan para decenas de días de recortes "
        "(≈ 1,5 GB por día) antes de copiarlos al bucket.\n"
        "- **Bucket del equipo.** En us-west-2, con el acceso público bloqueado, que es lo que S3 trae por "
        "defecto. Un orden posible está más abajo.\n"
        "- **Permisos.** La máquina usa un rol IAM que puede leer y escribir solo en el bucket del equipo, "
        "más la política `AmazonSSMManagedInstanceCore` para Session Manager. Los buckets públicos no "
        "necesitan permisos: los scripts los leen de forma anónima. Así nadie guarda claves de acceso en "
        "su computador, y la máquina no abre puertos: el grupo de seguridad puede quedar sin reglas de "
        "entrada.\n"
        "- **Costos.** Se cobran las horas de instancia, el disco (también con la instancia detenida), lo "
        "guardado en S3, las transferencias entre regiones y lo que sale de AWS a internet. Conviene una "
        "alerta en AWS Budgets, una etiqueta por equipo (por ejemplo, `team=<nombre>`) en cada recurso y "
        "detener la máquina cuando nadie la usa."
    )
    st.code(_BUCKET_LAYOUT, language="text")


def _training_data() -> None:
    """Formatos para pasar de los recortes a un modelo: Parquet para tablas, Zarr para cubos."""
    _section(
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
        "S3; conviene que cada bloque coincida con lo que pide el modelo, por ejemplo una hora de la región |"
    )
    st.code(_FORMATS, language="python")
    st.markdown(
        "Con la tabla en Parquet, Athena responde preguntas rápidas sin escribir código, por ejemplo "
        "cuántos ejemplos y positivos hay por año antes de separar entrenamiento y prueba:"
    )
    st.code(_ATHENA, language="sql")
    st.markdown(
        "Para entrenar, un cuaderno de SageMaker Studio basta mientras el conjunto quepa en memoria. "
        "Cuando no, un trabajo de entrenamiento de SageMaker lee de `features/` o `cubes/` y deja el "
        "modelo en `models/`. SageMaker también ofrece MLflow administrado para registrar cada "
        "experimento con sus parámetros y métricas. Todo en us-west-2, igual que el bucket."
    )


def _cloud() -> None:
    """Cómo correr todo dentro de AWS: dónde, en qué orden y cómo mirar el visor sin bajar datos."""
    _section(
        "nube",
        "Cómo usarlo en AWS",
        "Se trabaja en una máquina de AWS en us-west-2. Tu computador solo abre una terminal y un navegador.",
    )
    st.subheader("1. Una máquina en us-west-2", anchor=False)
    st.markdown(
        "ERA5 está en us-west-2 y es casi todo lo que se transfiere (≈ 11 GB por día), así que la máquina "
        "va ahí. GOES está en us-east-1, pero el script pide solo los bloques de la región y se puede leer "
        "desde us-west-2. Sirve una instancia EC2 o un espacio de SageMaker Studio; cada proceso de "
        "`download_era5.py` usa unos 400 MB de RAM y por defecto corren cuatro. São Paulo (`sa-east-1`) "
        "queda más cerca de Chile pero no aloja ninguno de los dos conjuntos, así que no ayuda."
    )
    st.code(_SETUP, language="bash")
    st.subheader("2. Bajar, recortar y guardar en S3", anchor=False)
    st.markdown(
        "Conviene partir con el caso de mayo de 2019 y unos pocos días de control, medir cuánto tarda y "
        "cuánto cuesta, y recién después ampliar. Los scripts escriben en el disco de la máquina; al "
        "terminar, los recortes se copian a un bucket del equipo en la misma región para que no se pierdan "
        "al apagarla."
    )
    st.code(_PIPELINE, language="bash")
    st.subheader("3. Mirar el visor", anchor=False)
    st.markdown(
        "El visor también corre en la máquina de AWS. Por el túnel viaja solo la página que ves, no los "
        "archivos. Desde SageMaker Studio se puede abrir por su proxy de puertos en vez del túnel."
    )
    st.code(_VIEWER, language="bash")
    st.markdown(
        "<div class='notice'><strong>Lo que no conviene hacer.</strong> Correr los scripts de descarga en "
        "tu computador o copiar los recortes de S3 a tu disco. Desde Chile, bajar un solo día de ERA5 toma "
        "unos 15 minutos con 100 Mbps, y un año completo, casi cuatro días. Cada gigabyte que sale de AWS a "
        "internet, como los recortes copiados desde el bucket del equipo, además se cobra.</div>",
        unsafe_allow_html=True,
    )


def _next_steps() -> None:
    """La definición del problema que falta cerrar y las primeras tareas."""
    _section(
        "pasos",
        "Próximos pasos",
        "Antes de entrenar hay que decidir qué se predice. Problema detalla cada decisión con sus opciones.",
    )
    st.subheader("Definir el problema", anchor=False)
    st.markdown(
        "El criterio de éxito es entregar candidatos a mesociclón para 2026, que revisarán expertos y se "
        "contrastarán con una base de tornados que mantiene el CR2 y que no es pública. Lo demás queda en "
        "manos de cada equipo:\n\n"
        "- **Unidad de análisis**: una tormenta seguida en GOES, una celda de ERA5 por hora o una región por día.\n"
        "- **Qué es un positivo**: un tornado reportado, un mesociclón inferido o ambos, por niveles.\n"
        "- **Días de comparación**: días al azar en la época de tornados, días elegidos a mano o una mezcla. "
        "Un día sin reporte no prueba que no hubo tornado.\n"
        "- **Diagnóstico o pronóstico**: estimar con los datos de la hora del evento o con datos de horas antes.\n"
        "- **Mirar hacia atrás**: buscar en el archivo histórico situaciones que pudieron no quedar registradas.\n"
        "- **Salida y métrica**: un puntaje o una lista corta de candidatos; tasa de acierto, falsas alarmas "
        "y cuántos candidatos revisa un experto por cada tornado encontrado."
    )
    st.page_link(
        state.page("project"),
        label="Ver las decisiones abiertas en Problema",
        icon=":material/info:",
    )
    st.subheader("Por dónde empezar", anchor=False)
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
    _section(
        "explorar",
        "Ideas para explorar",
        "Líneas abiertas que el repositorio todavía no cubre, ordenadas de menor a mayor dificultad.",
    )
    _cards(
        "explore",
        [
            ("Intermedia", "primary", "Corregir el paralaje",
             "GOES ve los topes de lado: a 40°S un tope de 12 km aparece unos 13 km corrido hacia el sur. Con la altura de `ABI-L2-ACHAF` se puede corregir y comparar la posición antes y después."),
            ("Intermedia", "primary", "Rayos y saltos de actividad",
             "El GLM registra rayos cada 20 segundos. Un aumento brusco de la tasa de rayos se ha usado como señal de tormenta severa (Schultz et al. 2009). Ojo: cerca de 52°S el detector pierde cobertura."),
            ("Intermedia", "primary", "Firmas del tope nuboso",
             "Topes penetrantes y penachos de cirros sobre el yunque son indicadores de tormentas severas en el visible y el infrarrojo (Bedka et al. 2018). Falta ver si aparecen en tormentas HSLC con poca energía."),
            ("Intermedia", "primary", "Vientos y estabilidad desde el satélite",
             "`ABI-L2-DMWF` y `ABI-L2-DSIF` dan viento en altura e índices de estabilidad observados, que sirven para contrastar con ERA5."),
            ("Avanzada", "orange", "Rotación con flujo óptico",
             "Estimar el movimiento del yunque en secuencias GOES y buscar patrones de rotación. Antes hay que decidir cómo comprobar que esa señal corresponde a un mesociclón."),
            ("Avanzada", "orange", "PU learning con sesgo de reporte",
             "Tratar los días sin registro como no etiquetados en vez de negativos (Elkan y Noto 2008), modelando la probabilidad de que un evento quede registrado según población, hora y año."),
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


def _related() -> None:
    """Referencias agrupadas por tema, desde la bibliografía compartida de ``variables``."""
    _section(
        "relacionados",
        "Trabajos relacionados",
        "Dónde buscar cómo se ha abordado el mismo problema, en Chile y en otros lugares.",
    )
    for title, keys in RELATED:
        st.subheader(title, anchor=False)
        refs = [variables.REFERENCES[k] for k in keys]
        st.markdown(
            "\n".join(f"- {r.full} [Enlace]({r.url})" if r.url else f"- {r.full}" for r in refs)
        )
    st.markdown(
        "La sección 10 del documento tiene la lista completa, con los análogos de costa occidental "
        "(Australia, California, Inglaterra) y los textos de física de referencia."
    )


def _toc() -> str:
    """El índice de la página como lista de enlaces a las anclas de ``SECTIONS``."""
    links = "".join(f"<li><a href='#{anchor}'>{text}</a></li>" for anchor, text in SECTIONS)
    return f"<nav class='toc' aria-label='En esta página'><ol>{links}</ol></nav>"


def page() -> None:
    """Dibuja la página con el índice al costado (o desplegable arriba en pantallas angostas)."""
    with st.container(key="starter"), st.container(horizontal=True, wrap=False, gap="large"):
        with st.container(key="starter_body"):
            with st.expander("En esta página", key="toc_compact", icon=":material/toc:"):
                st.markdown(_toc(), unsafe_allow_html=True)
            _cover()
            _buckets()
            _scripts()
            _architecture()
            _cloud()
            _training_data()
            _next_steps()
            _explore()
            _related()
        with st.container(width=220, key="toc_side"):
            st.markdown("<p class='toc-title'>En esta página</p>", unsafe_allow_html=True)
            st.markdown(_toc(), unsafe_allow_html=True)
