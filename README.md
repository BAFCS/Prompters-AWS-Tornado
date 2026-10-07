# Predicción de tormentas mesociclónicas en Chile

Proyecto abierto para el **AWS Hackathon**: estimar qué tormentas del centro-sur de Chile
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
| `docs/mesociclones_chile.pdf` | El mismo documento en A4 (33 páginas), con las figuras. |
| `scripts/viewer.py` y `scripts/viewer_app/` | **El visor**: una aplicación web local para explorar un día de datos (mapas, sondeos y series). |
| `scripts/download_*.py`, `scripts/process_*.py` | Descargan ERA5 y GOES recortados a Chile y calculan los índices que usa el visor. |
| `scripts/figs_*.py` | Generan las cuatro figuras de `figs/` desde los datos reales. |
| `tests/` | Pruebas automáticas del visor. |

## Cómo lanzar el visor, paso a paso

Esta guía parte de cero: no hace falta saber Python ni tener nada instalado. Al final tendrás el
visor abierto en tu navegador con el caso del 30 de mayo de 2019, el día con cinco tornados en el
Biobío.

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
git clone https://github.com/fforster/aws-mesocyclonic.git
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
uv run python scripts/download_era5.py --start 2019-05-30
uv run python scripts/download_goes.py --start 2019-05-30
uv run python scripts/process_goes.py --start 2019-05-30
uv run python scripts/process_era5.py --start 2019-05-30
```

Qué hace cada uno:

1. `download_era5.py` baja del reanálisis ERA5 las variables de ese día (viento, temperatura,
   humedad, presión, CAPE y otras), en altura y en superficie, recortadas al centro-sur y sur de Chile.
2. `download_goes.py` baja las imágenes del satélite GOES de ese día, recortadas a la misma región.
3. `process_goes.py` pasa las imágenes del satélite a una grilla de latitud y longitud, la misma
   forma que usa ERA5, para poder superponerlas.
4. `process_era5.py` calcula los índices de tiempo severo (cizalle, helicidad, VGP, STP) con los
   signos del hemisferio sur.

> [!WARNING]
> El paso más lento es `download_era5.py`. Los archivos de ERA5 en AWS cubren el planeta entero y
> no se pueden pedir recortados, así que por cada hora del día se transfiere el bloque global y se
> recorta en tu computador. Eso suma unos **11 GB de tráfico por día**, aunque en disco solo quedan
> unos 70 MB. El volumen es el mismo desde cualquier lugar; solo se evita corriendo el script dentro
> de AWS, en la región us-west-2, donde están los datos. Según tu conexión puede tardar de varios minutos a más de una hora.

> [!TIP]
> Si una descarga se corta, vuelve a ejecutar el mismo comando. Los scripts saltan los archivos que
> ya están completos y siguen con los que faltan.

Para preparar otro día, cambia la fecha (formato año-mes-día). Para varios días seguidos, agrega
`--end`, por ejemplo `--start 2019-05-30 --end 2019-05-31`. Cada script explica todas sus opciones
con `--help`, por ejemplo `uv run python scripts/download_goes.py --help`.

### Paso 6. Abrir el visor

```bash
uv run streamlit run scripts/viewer.py
```

La terminal mostrará una dirección (`Local URL`). Ábrela en tu navegador. Casi siempre es
**<http://localhost:8501>**, pero si ese puerto ya está ocupado Streamlit elige otro, por ejemplo
8502, así que usa la que aparece en la terminal.

El visor queda funcionando mientras la terminal siga abierta. Para cerrarlo, vuelve a la terminal y
pulsa <kbd>Ctrl</kbd> + <kbd>C</kbd>.

> [!NOTE]
> El visor corre en tu computador. La dirección `localhost` significa «este mismo equipo»: desde
> otro computador no se puede abrir.

### Cómo se usa

- Arriba están las páginas. **El proyecto** explica el problema y funciona aunque no hayas
  descargado datos. **El caso** resume el día elegido, **Mapas** muestra hasta seis mapas con el zoom
  sincronizado, **Sondeo** muestra el perfil vertical de la atmósfera en un punto y **Series** su
  evolución durante el día.
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

`AGENTS.md` describe la estructura del código, las convenciones del proyecto y de dónde sale cada
dato.

## Las figuras son datos reales, no esquemas

`figs_era5.py` extrae una hora, 37 niveles de presión y el recuadro chileno desde archivos
globales de 1,1–1,8 GB en `s3://nsf-ncar-era5/` **en unos 20 segundos por variable**, sin
descargarlos completos — es la demostración práctica de la estrategia de lectura por rangos
de bytes que recomienda el documento. `figs_goes.py` baja tres imágenes consecutivas de
`ABI-L2-CMIPF` del 30 de mayo de 2019, implementa la proyección geoestacionaria del ABI y
calcula la tendencia de temperatura de brillo en diez minutos.

Cada figura se regenera con su script, por ejemplo `uv run python scripts/figs_era5.py`.
`AGENTS.md` indica qué archivos de entrada necesita cada uno.

## Las etiquetas

La base de datos de eventos es pública y tiene DOI:

> **Bastías-Curivil, C., Rondanelli, R., Vicencio, J., Matus, F., Caballero, V., Muñoz, F.,
> Barraza, J., Campos, D., Valenzuela, R., de la Maza, A., Campos, J. & Trobok, I.**
> *Tornadoes and Waterspouts in Chile / Tornados y Trombas en Chile.* figshare, Dataset, v5.
> [doi:10.6084/m9.figshare.25119566](https://doi.org/10.6084/m9.figshare.25119566) — **CC BY 4.0**

Un `.xlsx` de **102 filas y 32 columnas**, 1554–2025. Lo esencial:

| | |
|---|---|
| Tornados / trombas / ambos | 70 / 45 / 19 |
| Con coordenadas | **102 (100 %)** |
| Con hora UTC | **91 (89 %)** |
| Con clasificación EF | 94 (92 %) |
| Con registro visual (`Register`) | 50 |
| Intensidades | ~53 EF0 · 28 EF1 · 9 EF2 · 4 EF3 · ningún EF4–EF5 |
| Estacionalidad | invierno 54,9 % · otoño 31,4 % — **junio es el mes máximo (36)**, luego mayo (24) |
| Reparto temporal | 22,5 % antes de 2000 · 10,8 % en 2000–2014 · **66,7 % en 2015–2025** |
| Latitud | 89 % entre 34° y 42°S · **ningún registro al sur de 42,4°S** |

Tres columnas merecen atención en el diseño del modelo: **`Register`** funciona como variable
de confianza de la etiqueta; **`Tornado`/`Waterspout`** separan las dos vías físicas de
formación; y **`Hour (UTC)`** es la que permite cruzar con las imágenes GOES.

La base no se versiona en este repositorio: descárguela desde figshare y cítela como indica
su licencia.

## Los tres hallazgos que definen el proyecto

**1 · Los índices norteamericanos no funcionan aquí.**
Los tornados chilenos ocurren en un régimen **HSLC** (*High Shear, Low CAPE*). El brote del
30–31 de mayo de 2019 tuvo apenas **200–1.000 J/kg** de CAPE — la media climatológica de
fines de mayo en el Biobío es de **15–45 J/kg** — con cizalle 0–1 km de **12–20 m/s**.
Vicencio et al. (2021) señalan explícitamente que **el STP clásico no habría dado la alarma**.
Los umbrales calibrados para Chile son otros:

- `VGP₀₋₁ = √CAPE × cizalle₀₋₁ > 0,1 m/s²`
- `SHERBE ≥ 1`
- `STP` (rama *left-mover*) **≤ −0,3**, no `+1`

**2 · Estamos en el hemisferio sur.** La SRH de los casos tornádicos es **negativa** y las
supercélulas favorecidas son las ***left-movers***. Usar MetPy o SHARPpy tal cual produce
índices con el signo cambiado; es el error silencioso más costoso de este proyecto.

**3 · Los eventos faltantes ya están señalados en la literatura.**
Caballero-Morán & Rondanelli (2025, *GRL*) encontraron, con ERA5 1959–2021, amplias zonas
del sur austral con VGP, cizalle y helicidad suficientes y **ningún registro documentado**,
atribuible a subregistro por baja densidad poblacional. La propia base de datos lo confirma:
**no contiene ni un solo evento al sur de los 42,4°S**, pese a que más de mil kilómetros de
territorio chileno se extienden más allá.

## Datos

```bash
# ERA5 — NSF NCAR, us-west-2  ✅ el bucket a usar
aws s3 ls --no-sign-request s3://nsf-ncar-era5/

# ERA5 — DEPRECADO: solo 18 variables de superficie, sin niveles de presión ni CAPE
aws s3 ls --no-sign-request s3://era5-pds/

# GOES-East, us-east-1 — el satélite que mira a Chile (75,2°W)
aws s3 ls --no-sign-request s3://noaa-goes19/   # abr 2025 – presente
aws s3 ls --no-sign-request s3://noaa-goes16/   # dic 2017 – abr 2025
```

Dos trampas documentadas en `docs/`: los archivos de nivel de presión de ERA5 pesan **≈1,36 GB
cada uno** (una variable, un día, el globo entero) y no admiten recorte del lado del servidor;
y el **paralaje** de GOES desplaza los topes nubosos unos **20 km a 53°S**, varias celdas de grilla.

## Por dónde empezar

La sección 8 del documento lista diez tareas ordenadas por dificultad. Las de mayor impacto
por unidad de esfuerzo son curar el catálogo de eventos y construir *loops* GOES de los casos
conocidos; la de mayor potencial es **detectar la rotación del yunque por flujo óptico**, un
detector de mesociclones que no depende del catálogo de tornados.

## Referencias principales

- Vicencio, J. *et al.* (2021). *The Chilean Tornado Outbreak of May 2019.* **BAMS** 102(3), E611–E634. [doi](https://doi.org/10.1175/BAMS-D-19-0218.1) · [PDF](https://dgf.uchile.cl/rene/PUBS/Tornado_chile_2019.pdf)
- Marín, J. C. *et al.* (2024). *Climatological Aspects of Notable Tornado Events in Chile.* **MWR** 152(8), 1803–1819. [doi](https://doi.org/10.1175/MWR-D-23-0249.1)
- Barrett, B. S. *et al.* (2020). *A multiscale analysis of the tornadoes of 30–31 May 2019.* **Atmos. Res.** 236, 104811. [doi](https://doi.org/10.1016/j.atmosres.2019.104811)
- Caballero-Morán, V. & Rondanelli, R. (2025). *Tornado Seasonality in Central-Southern Chile.* **GRL** 52. [doi](https://doi.org/10.1029/2024GL110900)

La lista completa está en `docs/mesociclones_chile.md`.

---

*Los diagramas de la página El proyecto del visor son esquemas dibujados a mano en SVG; las cuatro figuras de `figs/` sí
se generan desde los datos reales con los scripts de `scripts/`.*
