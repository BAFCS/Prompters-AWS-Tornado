"""Página «Starter kit»: dónde están los datos, qué scripts trae el repositorio y cómo usarlos en AWS.

Cierra con los próximos pasos: el criterio de éxito, las decisiones abiertas y las tareas, que se
muestran igual que en Problema (``p_project.decisions`` y ``p_project.tasks``).
No usa datos: se muestra aunque no haya recortes.
"""

import streamlit as st

from viewer_app import diagrams, layout, p_project, state
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
)

_LIST = """\
# Listar no descarga nada; --no-sign-request evita pedir credenciales
aws s3 ls --no-sign-request s3://nsf-ncar-era5/e5.oper.an.pl/201905/
aws s3 ls --no-sign-request s3://noaa-goes16/ABI-L2-MCMIPF/2019/150/21/
aws s3 ls --no-sign-request s3://noaa-goes19/ABI-L2-MCMIPF/
"""

_SETUP = f"""\
# Abrir una terminal en la máquina: EC2 → la instancia → Connect → Session Manager
# (o, desde tu computador, aws ssm start-session --target <id-de-la-instancia>)
sudo dnf install -y git tmux
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
uv run python scripts/pipeline/download_era5.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/download_goes.py --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_goes.py  --start 2019-05-30 --end 2019-05-31
uv run python scripts/pipeline/process_era5.py  --start 2019-05-30 --end 2019-05-31

# Copia de los recortes al bucket del equipo, en la misma región
aws s3 sync data/crops/ s3://<bucket-del-equipo>/crops/
"""

_VIEWER = """\
# En la máquina de AWS, dentro de tmux para que el visor siga corriendo al cerrar la sesión
tmux new -s visor
uv run streamlit run scripts/viewer/viewer.py --server.port 8501

# En otra terminal de tu computador (aws configure sso, la primera vez)
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


def _cover() -> None:
    """Título y para qué sirve la página."""
    st.title("Starter kit", anchor="inicio")
    st.markdown(
        "<p class='lede'>Esta página reúne en qué buckets están los datos, qué hace cada script del "
        "repositorio y cómo correrlos dentro de AWS. Por cada día hay que leer unos 12 GB de ERA5 y GOES "
        "para guardar 1,5 GB, así que las descargas se hacen en una máquina de AWS "
        "(ver <a href='#nube' target='_self'>Trabajar en AWS</a>).</p>",
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
        "| Otros productos GOES (mismos buckets) | `GLM-L2-LCFA/`, `ABI-L2-ACHAF/`, `ABI-L2-DMWF/`, `ABI-L2-DSIF/` | Rayos (desde feb 2018); altura del tope, vientos y estabilidad (desde dic 2019, no cubren el caso de 2019). Sus usos están en [Ideas para explorar](#explorar) |\n"
        "| Catálogo de tornados (fuera de AWS) | [figshare](https://doi.org/10.6084/m9.figshare.25119566), hoja `Final_Table` | 102 eventos, un archivo de 160 kB |"
    )
    st.code(_LIST, language="bash")
    st.markdown(
        "Hay dos buckets que conviene evitar: `era5-pds`, descontinuado y sin niveles de presión, y "
        "`noaa-goes18` (GOES-West), que no cubre Chile."
    )


def _scripts() -> None:
    """Qué hace cada script del repositorio y qué deja."""
    layout.section(
        "scripts",
        "Los scripts",
        "Cuatro scripts preparan los datos: dos bajan y recortan, dos calculan.",
    )
    st.markdown(
        "Los de `scripts/pipeline/` se corren en el orden de la tabla: primero se baja, después se calcula. Todos aceptan "
        "`--start` y `--end` (fechas UTC), `--region` y `--force`; `--help` muestra el resto de las "
        "opciones. Saltan lo que ya existe, así que si una descarga se corta basta repetir el comando.\n\n"
        "| Script | Qué hace | Salida |\n"
        "|---|---|---|\n"
        "| `pipeline/download_era5.py` | Baja ERA5 (niveles de presión y superficie) y recorta la región | `data/crops/<región>/era5_pl/`, `era5_sfc/`, un archivo por día |\n"
        "| `pipeline/download_goes.py` | Baja GOES `ABI-L2-MCMIPF`. Lee el índice del archivo y pide a S3 solo los bloques que tocan la región. Elige GOES-16 o GOES-19 según la fecha | `data/crops/<región>/goes/`, un archivo por hora |\n"
        "| `pipeline/process_goes.py` | Reproyecta GOES a una grilla regular de latitud y longitud, con vecino más cercano para no alterar los valores. No corrige paralaje | `data/crops/<región>/goes_latlon/` |\n"
        "| `pipeline/process_era5.py` | Calcula cizalladura, movimiento de Bunkers *left-mover*, SRH, VGP₀₋₁, STP sin CIN, SHERBS3 y LCL con los signos del hemisferio sur | `data/crops/<región>/era5_indices/` |"
    )
    st.caption(
        "Regiones predefinidas: `south-central-austral` (por defecto, 30°S–56°S), `south-central` "
        "(30°S–45°S) y `full`. Para otro recuadro se usa `--bbox` junto con un `--region` nuevo; si no se "
        "cambia `--region`, los datos quedan mezclados con los de la región por defecto. `common.py` "
        "reúne regiones, fechas y acceso a S3, y `scripts/figures/` dibuja las figuras del documento: no "
        "hace falta correrlos para preparar los datos."
    )


def _architecture() -> None:
    """El diagrama de la arquitectura, qué servicio va en cada etapa, permisos y costos."""
    layout.section(
        "arquitectura",
        "Arquitectura",
        "La máquina, el bucket y el entrenamiento van en us-west-2, la región de ERA5, para no pagar "
        "transferencias entre regiones.",
    )
    with st.container(border=True, key="sheet_architecture"):
        layout.image(diagrams.architecture(), _ARCH_ALT, key="architecture")
        st.markdown(
            "<p class='note'>Las cifras son por día de datos de la región por defecto. La máquina y el "
            "bucket, con borde de acento, son lo que crea el equipo, y las flechas de acento muestran por "
            "dónde pasan sus datos; las otras dos son la lectura anónima de los buckets públicos. La caja "
            "punteada es el permiso que limita a la máquina.</p>",
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
        "- **Rol de la máquina.** Un rol IAM que en S3 solo puede leer y escribir el bucket del equipo, más "
        "la política `AmazonSSMManagedInstanceCore` para Session Manager. Los buckets públicos se leen de "
        "forma anónima y no necesitan permisos.\n"
        "- **Sin puertos abiertos.** El grupo de seguridad de la máquina queda sin reglas de entrada: todo "
        "pasa por Session Manager.\n"
        "- **Alerta de gasto.** Crear una alerta en AWS Budgets y detener la máquina cuando nadie la usa."
    )


def _cloud() -> None:
    """Cómo correr todo dentro de AWS: la máquina, la descarga y cómo abrir el visor."""
    layout.section(
        "nube",
        "Trabajar en AWS",
        "Todo corre en una sola máquina EC2; desde tu computador solo se abre el visor.",
    )
    st.subheader("1. Una máquina en us-west-2", anchor=False)
    st.markdown(
        "ERA5 es casi todo lo que se transfiere (≈ 11 GB por día) y está en us-west-2, así que la máquina va "
        "ahí. GOES está en us-east-1, pero el script pide solo los bloques de la región, que pesan mucho "
        "menos. São Paulo (`sa-east-1`) queda más cerca de Chile, pero no aloja ninguno de los dos "
        "conjuntos.\n\n"
        "Basta una instancia EC2 de uso general con unos 4 vCPU, 16 GB de RAM y 50 a 100 GB de disco, "
        "que se fija al crear la instancia (Amazon Linux 2023 trae 8 GB por defecto).\n\n"
        "La máquina se crea a mano desde la consola de EC2. Más adelante se podría automatizar con "
        "Terraform, que dejaría la máquina, el rol y el bucket descritos en un archivo."
    )
    st.code(_SETUP, language="bash")
    st.subheader("2. Bajar, recortar y guardar en S3", anchor=False)
    st.markdown(
        "Lo prudente es partir con el caso de mayo de 2019 y unos pocos días de control, medir cuánto tarda "
        "y cuánto cuesta, y solo después ampliar. Los scripts escriben en el disco de la máquina; al "
        "terminar, los recortes se copian al bucket del equipo para que no se pierdan si se termina (borra) "
        "la máquina."
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
    """Cómo pasar de los recortes a un modelo y qué herramientas pueden servir."""
    layout.section(
        "entrenar",
        "Datos para entrenar",
        "Los recortes en NetCDF sirven para explorar día a día. Para entrenar hay que reorganizarlos según "
        "cómo los va a leer el modelo, por ejemplo en una tabla Parquet por año en el bucket del equipo.",
    )
    st.markdown(
        "Herramientas que pueden servir:\n\n"
        "- **xarray** (ya instalado): leer los recortes NetCDF.\n"
        "- **pandas y pyarrow** (ya instalados): escribir y leer la tabla de ejemplos en Parquet, directo "
        "desde S3.\n"
        "- **Zarr y dask** (`uv add zarr dask`): cubos para modelos de imágenes, como secuencias GOES, "
        "leídos por bloques desde S3.\n"
        "- **Athena**: consultas SQL sobre el Parquet sin levantar un servidor.\n"
        "- **SageMaker**: cuadernos de Studio para prototipos (su disco de 5 GB hay que ampliarlo) y "
        "trabajos de entrenamiento cuando los datos no caben en memoria.\n"
        "- **MLflow en SageMaker**: registrar cada experimento con sus parámetros y métricas."
    )


def _next_steps() -> None:
    """La definición del problema que falta cerrar y las primeras tareas."""
    layout.section(
        "pasos",
        "Próximos pasos",
        "Antes de entrenar hay que decidir qué se predice. Las decisiones son las mismas que en Problema.",
    )
    st.subheader("Definir el problema", anchor=False)
    st.markdown(f"**Criterio de éxito.** {p_project.SUCCESS}")
    p_project.decisions()
    st.subheader("Primeras tareas", anchor=False)
    st.markdown(
        "1. Preparar el caso de 2019 en AWS con los [comandos de arriba](#nube) y revisarlo en el visor.\n"
        "2. Ordenar el catálogo: fechas, horas UTC, coordenadas y confianza de cada registro.\n"
        "3. Elegir los días de control y armar una primera tabla con los índices de ERA5, un ejemplo por fila.\n"
        "4. Entrenar un modelo tabular simple (por ejemplo, *gradient boosting*) y evaluarlo separando "
        "eventos completos, sin mezclar horas de un mismo brote entre entrenamiento y prueba.\n"
        "5. Con esa referencia, sumar GOES y comparar con los mismos casos de evaluación."
    )
    st.page_link(
        state.page("case"), label="Explorar el caso de mayo de 2019", icon=":material/map:"
    )
    st.page_link(
        state.page("data"), label="Ver qué mide cada índice en Datos", icon=":material/dataset:"
    )


def _explore() -> None:
    """Líneas de trabajo abiertas, del documento (sección 8) y de lo que el repositorio no hace todavía."""
    layout.section(
        "explorar",
        "Ideas para explorar",
        "Tareas y líneas abiertas, de menor a mayor dificultad. Son las mismas de «Cómo participar» en Problema.",
    )
    p_project.tasks()


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
    st.page_link(
        state.page("references"),
        label="Ver los trabajos relacionados en Referencias",
        icon=":material/menu_book:",
    )
