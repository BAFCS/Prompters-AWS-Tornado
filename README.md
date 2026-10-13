# Predicción de tormentas mesociclónicas en Chile

Proyecto abierto para la hackathon [**Breaking Barriers**](https://www.taurusmkt.com/breakingbarrierschile): estimar qué tormentas del centro-sur de Chile
desarrollan **rotación organizada de mesoescala** (un mesociclón), potencialmente tornádica,
a partir del reanálisis **ERA5** y las imágenes multiespectrales del satélite **GOES**.

> Chile tiene **102 tornados y trombas catalogados entre 1554 y 2025** — dos tercios de ellos
> en los últimos once años —, ninguna red de radar meteorológico operacional, y la certeza
> fundada de que **la mayoría de los eventos nunca fue vista por nadie**. Este proyecto busca
> tanto anticipar las tormentas que vienen como **encontrar en el archivo histórico las que
> faltan**.

## Contenido

| Ruta | Qué es |
|---|---|
| `docs/mesociclones_chile.md` | **El documento principal.** El problema, la física, el caso chileno, los datos de entrada, las variables a calcular, cómo plantear el modelo, la arquitectura en AWS y las tareas abiertas. |
| `scripts/viewer/viewer.py` y `scripts/viewer/viewer_app/` | **El visor**: una aplicación web local con el problema, las fichas de variables, el starter kit para AWS, el caso de estudio y los mapas. |
| `scripts/pipeline/download_*.py`, `scripts/pipeline/process_*.py` | Descargan ERA5 y GOES recortados a Chile y calculan los índices que usa el visor. |
| `scripts/figures/figs_*.py` | Generan las cuatro figuras de `figs/` desde los datos reales. |
| `tests/` | Pruebas automáticas. |
| `AGENTS.md` | Convenciones del código y trampas del dominio, para personas y agentes de código. |

## Cómo lanzar el visor, paso a paso

Esta guía parte de cero: no hace falta saber Python ni tener nada instalado. Al final tendrás el
visor abierto en tu navegador con el caso del 30 de mayo de 2019, el día con cinco tornados en el
Biobío.

> [!IMPORTANT]
> Esta guía sirve para probar el visor con uno o dos días en tu computador. Para trabajar con más
> días, las descargas se hacen en una máquina de AWS en us-west-2, donde está ERA5: cada día obliga a
> leer unos 12 GB. La página **Starter kit** del visor explica cómo, paso a paso.

Lo que necesitas:

- Un computador con Linux, macOS o Windows.
- Conexión a internet.
- Unos 5 GB libres en disco: el programa y sus librerías ocupan cerca de 2 GB, y cada día de datos
  unos 1,5 GB (casi todo son las imágenes GOES de las 24 horas).

> [!NOTE]
> Los comandos de esta guía se escriben en una **terminal**, una ventana donde se escriben órdenes
> en vez de hacer clic. Para abrirla:
>
> - **macOS**: abre Spotlight (<kbd>Cmd</kbd> + <kbd>Espacio</kbd>), escribe `Terminal` y pulsa <kbd>Enter</kbd>.
> - **Windows**: abre el menú Inicio, escribe `PowerShell` y ábrelo.
> - **Linux**: busca «Terminal» en el menú de aplicaciones o pulsa <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>T</kbd>.
>
> Copia cada comando, pégalo en la terminal y pulsa <kbd>Enter</kbd>. Espera a que termine antes
> de escribir el siguiente: sabrás que terminó cuando vuelva a aparecer el cursor.

### Paso 1. Instalar uv

[uv](https://docs.astral.sh/uv/) es el programa que instala Python y todas las librerías del
proyecto. No necesitas instalar Python por tu cuenta: uv lo descarga solo.

En **macOS o Linux**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

En **Windows** (en PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cuando termine, **cierra la terminal y abre una nueva**. Después comprueba que uv quedó instalado:

```bash
uv --version
```

Debe responder con un número de versión, por ejemplo `uv 0.12.20`. Si dice que no encuentra el comando, revisa la sección
[Problemas frecuentes](#problemas-frecuentes).

### Paso 2. Descargar este repositorio

Si tienes [git](https://git-scm.com/downloads) instalado:

```bash
git clone https://github.com/idia-tt/aws-mesocyclonic.git
cd aws-mesocyclonic
```

Si no tienes git, abre la página del repositorio en GitHub, pulsa el botón verde **Code** y luego
**Download ZIP**. Descomprime el archivo y, en la terminal, entra a la carpeta con `cd` seguido de
su ubicación. Por ejemplo, si quedó en la carpeta de descargas:

- macOS y Windows: `cd Downloads/aws-mesocyclonic-main` (la carpeta se llama así aunque el
  sistema esté en español).
- Linux en español: `cd Descargas/aws-mesocyclonic-main`.

> [!IMPORTANT]
> Todos los comandos que siguen se ejecutan **desde la carpeta del repositorio** (la que contiene
> este `README.md`). Si cierras la terminal, vuelve a entrar con `cd` antes de seguir.

### Paso 3. Instalar las dependencias

```bash
uv sync
```

uv descarga Python 3.13 y las librerías que usa el proyecto (Streamlit, xarray, plotly, entre
otras) y las deja en una carpeta `.venv` dentro del repositorio. No toca el Python de tu sistema.
La primera vez tarda unos minutos.

> [!TIP]
> No hace falta «activar» ningún entorno. Basta con anteponer `uv run` a cada comando, como en los
> pasos siguientes: uv se encarga de usar la carpeta `.venv`.

### Paso 4. Descargar el catálogo de tornados y la línea de costa

Son dos archivos pequeños. El visor funciona sin ellos, pero entonces no muestra los eventos ni
la costa en los mapas.

En **macOS o Linux**:

```bash
mkdir -p data
curl -L -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl -L -o data/coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip
```

En **Windows** (en PowerShell):

```powershell
mkdir data -Force
curl.exe -L -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl.exe -L -o data/coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip
```

### Paso 5. Descargar y preparar un día de datos

El visor no descarga nada por su cuenta: lee los archivos que dejan estos cuatro scripts en
`data/crops/`. Ejecútalos **en este orden**, porque cada uno usa lo que dejó el anterior:

```bash
uv run python scripts/pipeline/download_era5.py --start 2019-05-30
uv run python scripts/pipeline/download_goes.py --start 2019-05-30
uv run python scripts/pipeline/process_goes.py --start 2019-05-30
uv run python scripts/pipeline/process_era5.py --start 2019-05-30
```

Qué hace cada uno:

1. `download_era5.py` baja del reanálisis ERA5 las variables de ese día (viento, temperatura,
   humedad, presión, CAPE y otras), en altura y en superficie, recortadas al centro-sur y sur de Chile.
2. `download_goes.py` baja las imágenes del satélite GOES de ese día, recortadas a la misma región.
3. `process_goes.py` pasa las imágenes del satélite a una grilla de latitud y longitud, la misma
   forma que usa ERA5, para poder superponerlas.
4. `process_era5.py` calcula los índices de tiempo severo (cizalladura, helicidad, VGP, STP) con los
   signos del hemisferio sur.

> [!WARNING]
> El paso más lento es `download_era5.py`. Los archivos de ERA5 en AWS cubren el planeta entero y
> no se pueden pedir recortados, así que por cada hora del día se transfiere el bloque global y se
> recorta en tu computador. Eso suma unos **11 GB de tráfico por día**, aunque en disco solo quedan
> unos 70 MB. El volumen es el mismo desde cualquier lugar. Según tu conexión puede tardar de varios
> minutos a más de una hora, así que en tu computador conviene bajar solo uno o dos días; para más,
> corre los scripts dentro de AWS, en us-west-2, como explica la página **Starter kit**.

> [!TIP]
> Si una descarga se corta, vuelve a ejecutar el mismo comando. Los scripts saltan los archivos que
> ya están completos y siguen con los que faltan.

Para preparar otro día, cambia la fecha (formato año-mes-día). Para varios días seguidos, agrega
`--end`, por ejemplo `--start 2019-05-30 --end 2019-05-31`. Cada script explica todas sus opciones
con `--help`, por ejemplo `uv run python scripts/pipeline/download_goes.py --help`.

### Paso 6. Abrir el visor

```bash
uv run streamlit run scripts/viewer/viewer.py
```

La terminal mostrará una dirección (`Local URL`). Ábrela en tu navegador. Casi siempre es
**<http://localhost:8501>**, pero si ese puerto ya está ocupado Streamlit elige otro, por ejemplo
8502, así que usa la que aparece en la terminal.

El visor queda funcionando mientras la terminal siga abierta. Para cerrarlo, vuelve a la terminal y
pulsa <kbd>Ctrl</kbd> + <kbd>C</kbd>.

Si estás modificando el código del visor, agrega `--server.runOnSave true` para que se actualice solo
al guardar un archivo, sin pulsar *Rerun*:

```bash
uv run streamlit run scripts/viewer/viewer.py --server.runOnSave true
```

> [!NOTE]
> El visor corre en tu computador. La dirección `localhost` significa «este mismo equipo»: desde
> otro computador no se puede abrir.

### Cómo se usa

- Arriba están las páginas. **Problema** explica el problema, **Datos** describe cada variable y
  **Starter kit** reúne los buckets, los scripts y cómo trabajar en AWS, y **Referencias** agrupa la
  bibliografía; las cuatro funcionan aunque no hayas descargado datos. **Caso de estudio** resume el día elegido y **Mapas** muestra hasta seis
  mapas con el zoom sincronizado.
- La barra de la izquierda elige la región, el día, la hora y el evento. Lo que elijas ahí se
  mantiene al cambiar de página.
- Las horas están en tiempo universal coordinado (UTC). En mayo, la hora de Chile continental es
  UTC − 4.
- El botón **Cambiar a modo oscuro** de la barra alterna entre el tema claro y el oscuro.

### Problemas frecuentes

**La terminal dice que no encuentra `uv`.**
Cierra la terminal y abre una nueva: la instalación agrega uv a la ruta de programas, pero solo las
terminales nuevas se enteran. Si sigue sin aparecer, reinicia la sesión de tu computador.

**El visor dice «No hay datos preparados para explorar».**
Falta el paso 5, o se ejecutó desde otra carpeta. Revisa que exista la carpeta
`data/crops/south-central-austral/` dentro del repositorio.

**El mapa no muestra triángulos rojos de eventos ni la costa.**
Falta el paso 4. Descarga los dos archivos, revisa que estén en la carpeta `data/` y recarga la
página del navegador. El visor nota que los archivos son nuevos y los lee.

**El navegador muestra un visor viejo o una aplicación que no es esta.**
Había otro programa de Streamlit abierto en el puerto 8501, y este visor se abrió en otro puerto sin
avisar. Abre la dirección `Local URL` que muestra la terminal, por ejemplo <http://localhost:8502>.
Si no necesitas el programa anterior, ciérralo con <kbd>Ctrl</kbd> + <kbd>C</kbd> en su terminal.

**Una descarga falla con un error de red.**
Vuelve a ejecutar el mismo comando; retoma donde quedó.

### Para quien va a modificar el código

```bash
uv sync                                         # instala también las herramientas de desarrollo
uv run ruff check scripts tests                 # revisa el estilo
uv run ruff format scripts tests                # formatea
uv run pyright                                  # revisa los tipos
uv run python -m unittest discover -s tests -v  # ejecuta las pruebas
uv add <paquete>                                # agrega una dependencia (nunca con pip)
```

`make check` corre las cuatro revisiones de una vez y `make fix` corrige el estilo; `make` a secas
lista los demás atajos. El Makefile es opcional: en Windows no hay `make`, pero los comandos de arriba funcionan tal cual en PowerShell.

`AGENTS.md` describe la estructura del código, las convenciones del proyecto y de dónde sale cada
dato.

## Cómo participar

La sección 8 del documento lista once tareas ordenadas por dificultad. Las más accesibles son
ordenar el catálogo de eventos y construir animaciones GOES de los casos conocidos. Entre las
avanzadas está **buscar rotación en el yunque con flujo óptico**, que no depende del catálogo de
tornados; antes hay que decidir cómo comprobar que esa señal corresponde a un mesociclón.

En el visor, las páginas **Problema** («Cómo participar») y **Starter kit** («Ideas para explorar»)
muestran la misma lista de tareas, y Starter kit agrega las primeras tareas para empezar.

## Dónde seguir

- **El documento** (`docs/mesociclones_chile.md`): la física, el caso chileno, los datos, las
  variables, cómo plantear el modelo y la arquitectura en AWS.
- **El visor**: **Datos** explica cada variable, **Starter kit** reúne los buckets y cómo trabajar en
  AWS, y **Referencias** tiene la bibliografía completa.
- **El catálogo de eventos**: Bastías-Curivil et al., *Tornadoes and Waterspouts in Chile*, figshare,
  [doi:10.6084/m9.figshare.25119566](https://doi.org/10.6084/m9.figshare.25119566), CC BY 4.0. No se
  versiona en el repositorio: se descarga en el paso 4 y se cita como indica su licencia.

## Acerca de y contacto

Proyecto preparado para la hackathon [Breaking Barriers](https://www.taurusmkt.com/breakingbarrierschile) por:

- [Francisco Forster](https://idia.uchile.cl/quienes-somos/francisco-forster/), IDIA, Universidad de Chile.
- [Pablo Badilla](https://idia.uchile.cl/quienes-somos/pablo-badilla/), IDIA, Universidad de Chile.
- [Roberto Rondanelli](https://www.cr2.cl/roberto-rondanelli/), CR2.

Las dudas sobre el proyecto o el código se pueden plantear como un *issue* en este repositorio.
