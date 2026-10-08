# Starter kit para la hackathon AWS Breaking Barriers — propuesta

> **Estado:** borrador para discutir con el equipo. Nada de esto está implementado. Las decisiones
> marcadas como *tomadas* salieron de una primera conversación y se pueden revisar; las *abiertas*
> necesitan una respuesta antes de empezar.

## 1. Objetivo

Que un equipo de la hackathon pueda clonar el repositorio, correr `uv sync` y **en menos de 30
minutos estar mirando datos reales** del problema (catálogo de tornados, ERA5 y GOES sobre Chile) en
un notebook interactivo, sin tener que resolver antes cómo se leen archivos de 1,3 GB, cómo se
reproyecta una imagen geoestacionaria o por qué los índices cambian de signo en el hemisferio sur.

El entregable de cada equipo es un **prototipo de producto funcional que resuelva el problema usando
servicios de AWS**. El starter kit no les entrega ese producto: les quita la fricción de los datos
para que dediquen el tiempo a él.

### Para quién

- Estudiantes universitarios (U. de Chile y otras instituciones), profesionales y personas
  interesadas en la tecnología.
- **Piso común: saben Python.** No se puede suponer conocimiento de meteorología, de ML ni de AWS.
- Equipos heterogéneos: el kit tiene que servir tanto al que nunca abrió un NetCDF como al que
  quiere entrenar un modelo desde la primera hora.

### Restricciones

- La hackathon dura unos **3 días, de los cuales ~1,5 son de programación**. Todo lo que tome más
  de una hora en ponerse a andar es tiempo que no se dedica al producto.
- **No sabemos todavía qué acceso a AWS tendrán los equipos** (cuentas con créditos, cuentas
  temporales del evento, o ninguna). El kit tiene que funcionar en local y poder usarse en AWS sin
  cambios.
- Stack fijo: Python con uv, ruff, pyright, JupyterLab e ipywidgets (lo que deja la PR #1), más
  plotly para las visualizaciones.

## 2. Qué incluye y qué no

**Incluye**

1. Un **paquete Python** (`src/mesociclones/`) con las funciones para leer y recortar cada fuente.
2. **Scripts** para generar el dataset (organización) y para descargarlo por partes (equipos).
3. Un **dataset precalculado y publicado**, sobre Chile centro-sur, listo para abrir.
4. **Notebooks de exploración** con plotly, sus widgets nativos y mapas GeoJSON.
5. Documentación: cómo empezar, qué hay en el dataset y qué servicios de AWS podrían usar.

**No incluye** (decisión tomada): modelo base, métrica o evaluador común, ni plantillas de
despliegue en AWS. El producto y su arquitectura los diseña cada equipo; la documentación solo
sugiere servicios.

## 3. Por qué hace falta un dataset precalculado

Es la pieza central del kit y la más cara de preparar, así que conviene entender por qué no basta
con apuntar a los equipos a los buckets públicos.

- Un archivo de ERA5 de niveles de presión en `s3://nsf-ncar-era5/` pesa **~1,3 GB** y contiene
  una variable, un día y el globo entero; Chile es menos del 1 % de eso.
- Una imagen GOES de disco completo pesa **388 MB en la banda 2** (visible, 0,5 km) y 20–27 MB en
  las bandas infrarrojas.
- Para los días que proponemos (sección 4), bajar los archivos originales serían **~7 TB de ERA5 y
  ~11 TB de GOES**.

`scripts/figures/figs_era5.py` ya demuestra que se puede leer solo el recuadro por rangos de bytes (unos
20–50 s por variable y día), pero hacerlo para más de mil días toma horas incluso en paralelo y
necesita estar cerca de los buckets. No es algo que un equipo pueda hacer al comienzo de la
hackathon. Por eso: **la organización genera el dataset una vez, antes del evento, y lo publica**
(decisión tomada). Los scripts de extracción quedan en el kit para que los equipos que quieran
puedan ampliarlo.

## 4. Contenido del dataset

Recuadro **33°–45°S × 76°–68°W** (donde está el 89 % de los eventos del catálogo).

| Componente | Contenido | Tamaño estimado |
|---|---|---|
| Catálogo | Los 102 eventos normalizados: fecha y hora UTC, lat/lon, tipo (tornado/tromba/ambos), EF, `Register`. GeoJSON + Parquet. | < 1 MB |
| Días | Tabla de qué días hay en el dataset y si son de evento o de control. Parquet. | < 1 MB |
| ERA5 niveles de presión | U, V, T, Z y humedad específica · **27 niveles (1000–100 hPa)** · 0,25° · **24 h** · días de evento + controles | ~9 GB |
| ERA5 superficie | CAPE, viento a 10 m, presión de superficie, T y Td a 2 m · 24 h · mismos días | ~0,5 GB |
| GOES | Bandas 2 (visible, remuestreada a 2 km), 8 y 10 (vapor de agua) y 13 (IR) · **12–24 UTC cada 10 min** · días de evento + controles desde 2018 | ~21 GB |
| **Total** | | **~30 GB** |

**Qué días entran**

- **Días de evento:** el catálogo tiene 70 días únicos con evento desde 1940 (inicio de ERA5) y 38
  desde 2018 (GOES-16 operativo sobre Chile).
- **Días de control:** ~1000 para ERA5 (abril–septiembre, 1940–2025) y ~300 para GOES (2018–2025),
  elegidos al azar con semilla fija, excluyendo ±3 días alrededor de cada evento. No son "negativos
  verdaderos": son días sin registro, y el catálogo tiene un sesgo de reporte fuerte. Esto hay que
  explicarlo en la documentación para los equipos.

**Por qué esas elecciones**

- **Niveles 1000–100 hPa:** los 10 niveles superiores (1–70 hPa) son estratosfera y no aportan a la
  convección; quitarlos ahorra un 27 % sin perder nada relevante.
- **24 h en ERA5:** cada archivo de NCAR ya trae las 24 horas del día, así que no cuesta más
  archivos, solo más bytes leídos.
- **12–24 UTC en GOES:** cubre la tarde local, cuando ocurre la mayoría de los eventos (mediana
  14:00 hora local). Dejar fuera la noche es lo que mantiene GOES en ~21 GB; el día completo lo
  duplicaría.
- **Derivados precalculados:** solo el cizalle 0–1 km y 0–6 km. SRH, VGP y STP quedan como
  funciones del paquete (con el signo del hemisferio sur y tests), no como variables del dataset,
  para que los equipos vean cómo se calculan en vez de usarlos como caja negra.

## 5. Compresión

Decisión tomada: **todo sin pérdida**. Mediciones hechas sobre una hora real de ERA5 y una imagen
real de GOES, con Blosc/zstd y un solo núcleo:

| Dato | Factor sin pérdida | Comprimir | Descomprimir |
|---|---|---|---|
| ERA5 (float32) | 2,2–3,0x según la variable | ~190 MB/s | ~1,9 GB/s |
| GOES (enteros originales del archivo) | 4x respecto de float32 | ~180 MB/s | ~1,7 GB/s |

- **GOES ya viene cuantizado:** el archivo original guarda enteros de 16 bits con escala y offset.
  Guardando esos enteros (en vez de convertir a float, como hace hoy `figs_goes.py`) se obtiene 4x
  sin perder nada.
- **Cuantizar ERA5 casi no cambia el total** (bajaría de ~30 a ~27 GB), porque GOES domina el
  tamaño, y obligaría a decidir y justificar una precisión por variable. No vale la pena.
- **El costo de comprimir es despreciable:** los ~66 GB sin comprimir se comprimen en ~6 minutos en
  un núcleo. Descomprimir es más rápido que cualquier red o disco, así que la compresión hace la
  lectura **más rápida**, no más lenta.

Sin comprimir vs. comprimido, para un equipo que descarga todo:

| | Sin comprimir (~66 GB) | Comprimido (~30 GB) |
|---|---|---|
| Descarga completa a 100 Mbps | ~90 min | ~40 min |
| Salida de S3 a internet (~US$0,09/GB) | ~US$6 | ~US$2,7 |
| Almacenamiento en S3 (~US$0,023/GB-mes) | ~US$1,5/mes | ~US$0,7/mes |

En dinero la diferencia es menor; lo que importa es el tiempo de los equipos. Y en la práctica la
mayoría no va a descargar todo: Zarr permite abrir el dataset directamente en S3 y leer solo el
trozo que se usa.

*Los precios son aproximados y hay que confirmarlos en la calculadora de AWS.*

## 6. Dónde y cómo se genera

**En AWS, en la región de cada fuente** (decisión tomada):

- ERA5 en **us-west-2** (`nsf-ncar-era5`), GOES en **us-east-1** (`noaa-goes16`, `noaa-goes19`).
- Dentro de la misma región la transferencia desde S3 es gratis y la red es de 10+ Gbps; desde un
  notebook en Chile serían días de descarga.
- Propuesta: una instancia EC2 *spot* de ~16 vCPU por región durante unas horas, del orden de
  **US$5–20 en cómputo**. El trabajo es de entrada/salida, así que se paraleliza con ~50 tareas
  concurrentes en la misma máquina.
- `generar_dataset.py` procesa un día por tarea y es **reanudable**: si un día ya está escrito, se
  salta. Si la instancia *spot* se interrumpe, se relanza y continúa.
- El script también corre en cualquier máquina (para probar con pocos días), pero la generación
  completa se documenta como algo que se hace en EC2.

## 7. Estructura del kit

```
src/mesociclones/          paquete reutilizable: tipado, con docstrings y tests
  config.py                recuadro, niveles, bandas, buckets, ubicación del dataset
  catalogo.py              xlsx de figshare → tabla normalizada → GeoJSON / Parquet
  dias.py                  selección de días de evento y de control
  era5.py                  recorte de un día desde nsf-ncar-era5 → xarray.Dataset
  goes.py                  proyección del ABI, elección de satélite por fecha, recorte
  derivados.py             cizalle, SRH y VGP con el signo del hemisferio sur
  dataset.py               abrir() → xarray lazy sobre el Zarr publicado (S3 o local)

scripts/
  generar_dataset.py       organización: genera y escribe el Zarr, un día por tarea
  descargar_dataset.py     equipos: baja subconjuntos por fecha, variable o banda
  figs_*.py                los tres actuales, reescritos sobre el paquete

notebooks/                 exploración (sección 8)
docs/starter_kit/          esta propuesta, guía para participantes, guía de generación en EC2
```

**Formato del dataset publicado**

- `catalogo.geojson`, `catalogo.parquet`, `dias.parquet`
- `era5_pl.zarr` — tiempo × nivel × lat × lon
- `era5_sfc.zarr` — tiempo × lat × lon
- `goes.zarr` — tiempo × banda × y × x, con lat/lon 2D como coordenadas

La ubicación se lee de la variable de entorno `MESOCICLONES_DATOS` (una URL `s3://...` o una ruta
local); si no está definida, se usa `data/`. Así el código no depende de dónde terminemos
publicando.

**Por qué un paquete y no solo notebooks:** la lógica de recorte, proyección e índices se escribe y
se prueba una vez. Los equipos la pueden importar tal cual en su producto (por ejemplo, dentro de
una Lambda) en vez de copiar celdas de un notebook.

**Dependencias nuevas:** xarray, zarr, plotly.

## 8. Notebooks (propuesta preliminar, no discutida)

Esta parte quedó pendiente en la primera conversación. Una propuesta de partida, todos con plotly y
sus widgets nativos:

1. **Catálogo:** mapa GeoJSON de los eventos con filtros por tipo, EF, década y mes; histogramas
   enlazados al filtro.
2. **Un caso en ERA5:** elegir un día de evento y explorar nivel, variable y hora con controles; ver
   el cizalle sobre el mapa con los eventos marcados.
3. **Un caso en GOES:** animación de la banda 13 (y las otras) alrededor de un evento, con control
   de tiempo y banda.
4. **Eventos vs. controles:** comparar distribuciones de cizalle, CAPE y VGP entre días de evento y
   de control, con la advertencia sobre el sesgo de reporte.

## 9. Decisiones abiertas para el equipo

1. **Acceso a AWS durante el evento.** Define si los equipos leen el Zarr desde S3 o lo descargan,
   y qué servicios conviene sugerir en la documentación.
2. **Dónde publicar el dataset.** Un bucket S3 propio (idealmente en us-east-1, la región más
   probable de las cuentas del evento), Hugging Face, o postular al **AWS Open Data Sponsorship**,
   con el que AWS paga el almacenamiento y la transferencia, como con ERA5 y GOES. Con ~30 GB, un
   release de GitHub no alcanza.
3. **Quién paga y lanza la generación en EC2** (US$5–20 estimados más el almacenamiento).
4. **Tamaño:** ¿mantener ~300 días de control con GOES, o bajar a ~100 (≈ 20 GB en total)?
   ¿GOES cada 20 min en los controles?
5. **Notebooks:** validar o cambiar la lista de la sección 8.
6. **Plazos:** cuándo tiene que estar publicado el dataset antes de la hackathon.

## 10. Riesgos e incógnitas

- **Cuántos bytes se leen realmente por archivo al recortar.** Depende de cómo están divididos en
  bloques (*chunks*) los archivos de origen, y hoy no lo sabemos. Determina el tiempo y el costo de
  la generación, así que es lo primero que hay que medir.
- **Cadencia de GOES antes de abril de 2019:** GOES-16 tomaba el disco completo cada 15 min (no cada
  10) hasta el cambio al modo 6. Los días de 2018 e inicios de 2019 tendrán menos imágenes; el
  dataset tiene que manejar tiempos irregulares.
- **Cambio de GOES-16 a GOES-19 en abril de 2025.** Ambos operan como GOES-East en 75,2°W, así que
  la grilla debería ser la misma, pero hay que verificarlo.
- **Remuestrear la banda 2** de 0,5 km a 2 km es la única transformación con pérdida del dataset (de
  resolución, no de precisión); hay que documentar el método.
- **Variables de superficie de ERA5 en NCAR:** verificado que CAPE, viento a 10 m, presión de
  superficie y T/Td a 2 m están en `e5.oper.an.sfc/` (p. ej. `128_059_cape`). A diferencia de los
  niveles de presión, esos archivos son **mensuales** (una variable, un mes, el globo), así que la
  extracción de superficie conviene organizarla por mes y no por día.
- **Validar los índices del hemisferio sur:** SRH y VGP necesitan tests con signos conocidos; el
  caso del 30 de mayo de 2019 sirve como verificación contra la literatura.

## 11. Orden de trabajo propuesto

1. **Medir** los bytes leídos y el tiempo por día en ERA5 y GOES desde EC2, con 2–3 días de prueba.
   Con eso se confirman o ajustan el tamaño, el costo y el tiempo de las secciones 4–6.
2. **Paquete:** `catalogo`, `dias`, `era5`, `goes`, `derivados`, con tests. Reescribir `figs_*.py`
   sobre él y verificar que las figuras salen iguales.
3. **Generación:** `generar_dataset.py` reanudable; probarlo en local con ~5 días.
4. **Publicación:** resolver dónde (decisión abierta 2), generar el dataset completo en EC2 y
   publicarlo; `dataset.py` y `descargar_dataset.py` contra la ubicación real.
5. **Notebooks** (según lo que se decida en la sección 8).
6. **Guías:** para participantes (cómo empezar, qué hay en el dataset, qué es un control y por qué
   no es un negativo) y para la organización (cómo regenerar el dataset en EC2).
