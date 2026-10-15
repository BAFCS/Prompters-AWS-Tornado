# Enfoques de ingesta de datos para el proyecto de mesociclones

Este documento compara, de forma honesta, los tres caminos que tenemos para traer datos de entrada
(ERA5 y GOES) hasta nuestro bucket de pruebas, para que el equipo decida con qué quedarse. No hay un
ganador único: cada enfoque gana en una dimensión y pierde en otra. La recomendación final (sección
final) combina lo mejor de cada uno.

## Contexto operativo (restricciones que mandan)

Todo lo que sigue se decide dentro de estas restricciones, que no son negociables en el laboratorio:

- **Cuenta AWS** `822870558093`, rol `WSParticipantRole`.
- **Solo `us-east-1`.** `us-west-2` está **denegado** por IAM. Esto es la restricción que más pesa,
  porque el bucket de ERA5 (`nsf-ncar-era5`) vive en `us-west-2` y el de GOES (`noaa-goes16/19`) en
  `us-east-1`.
- **Sin GPU** y **sin instancias `>= 6xlarge`.** La ingesta tiene que ser liviana en CPU y memoria;
  nada de recortes que materialicen el globo entero en RAM.
- **Bucket destino:** `s3://mesocyclonic-test-data-20261015013924290100000003/` (regional,
  `us-east-1`).
- **Región Chile** `south-central-austral`: Norte −30, Sur −56, Oeste −76, Este −66.
- Estado actual: la **opción CDS está bloqueada** por el registro SSM de la EC2 (no por el código).
  Mientras tanto, los enfoques alternativos avanzan en paralelo. No se ejecuta nada en AWS todavía;
  solo se preparan scripts y planes en el repositorio.

Los nombres de archivo, variables y niveles mencionados abajo son los que ya usan los scripts del
repo (`scripts/pipeline/download_era5.py`, `scripts/pipeline/download_goes.py`,
`scripts/ingest/ingest_ncar_zarr.py` y `scripts/ingest/ingest_cds.py`), de modo que las tres vías
entregan el **mismo producto de datos** y se pueden comparar de forma justa.

---

## Enfoque A — ERA5 por rango de bytes desde `nsf-ncar-era5` (actual / inicial)

Es lo que hoy hace `scripts/pipeline/download_era5.py` y su variante a Zarr
`scripts/ingest/ingest_ncar_zarr.py`. Se lee el Pool de Datos Abiertos de AWS
(`s3://nsf-ncar-era5/`) de forma **anónima**, pidiendo con rangos de bytes exactamente los bloques
horarios de niveles de presión, y se recorta el recuadro de Chile en memoria antes de escribir.

**Qué datos entrega.** ERA5 completo para el modelo: niveles de presión `u, v, t, z` en
1000/925/850/700/500/300 hPa y superficie `10u, 10v, 2t, 2d, sp, cape`, las 24 horas del día,
recortado a `south-central-austral`. Idéntico al producto del enfoque B.

**Volumen aproximado.** Aquí está el problema central. Los archivos de niveles de presión traen
*una variable, un día y el globo entero*, divididos en bloques horarios de ~50–65 MB **que no se
pueden recortar en el servidor**: por cada hora se transfiere el bloque global y se recorta en el
cliente. En disco quedan solo decenas de MB por día, pero **se transfieren del orden de GB/día**
(el propio `download_era5.py` documenta ~350 MB por hora de datos con 6 variables; el README del
proyecto habla de ~11 GB/día para el conjunto completo). Superficie sí lee casi solo el recuadro
(archivos mensuales con bloques pequeños).

**Latencia.** Síncrona y predecible: no hay cola de un servicio externo, la descarga empieza al
instante. Pero es **lenta** por el volumen transferido, y **peor aún cross-region**: leer
`us-west-2` desde `us-east-1` suma latencia de red y, potencialmente, costo de transferencia entre
regiones. El tiempo de pared crece con los GB, no con los MB que guardamos.

**Credenciales.** **Ninguna para leer** la fuente (acceso anónimo, `anon=True`). Solo se necesitan
credenciales para *escribir* en el bucket destino (el rol de la instancia).

**Encaje con los permisos (solo `us-east-1`, sin GPU).** Funciona, pero **mal alineado**: la fuente
está en `us-west-2`, que tenemos denegado para *nuestros* recursos. Leer un bucket público de otra
región sí es posible (el bucket es de acceso abierto), pero cruzamos regiones en cada byte, que es
justo lo que la restricción nos empuja a evitar. Sin GPU no es problema: es puro I/O y recorte
NumPy. El recorte en memoria es manejable si se hace hora a hora (como ya se hace), no todo el día
de una vez.

**En qué caso conviene.** Como **respaldo robusto y sin dependencias externas**: no necesita API
key, no hay cola, y ya está probado y funcionando. Ideal cuando CDS está caído o encolado, cuando se
necesita un día puntual *ya*, o para reproducir resultados sin depender de un tercero. También es la
única vía si por algún motivo no se puede registrar una cuenta en Copernicus.

---

## Enfoque B — ERA5 desde la API del Copernicus CDS con recorte en servidor (opción ideal)

Es lo que implementa `scripts/ingest/ingest_cds.py` con el paquete `cdsapi`. Se pide a Copernicus el
recuadro de Chile **ya recortado en el servidor** vía `area=[Norte, Oeste, Sur, Este] = [-30, -76,
-56, -66]`, y Copernicus devuelve un NetCDF pequeño que después subimos al bucket destino.

**Qué datos entrega.** Exactamente las mismas variables y niveles que el enfoque A
(`reanalysis-era5-pressure-levels` para `u, v, t, z` y `reanalysis-era5-single-levels` para `10u,
10v, 2t, 2d, sp, cape`, 24 horas). Mismo producto de datos; la diferencia es *cómo llega*.

**Volumen aproximado.** **Solo los MB del recuadro de Chile.** El recorte ocurre en el servidor del
CDS, así que no transferimos el globo: bajamos del orden de **MB/día**, no GB/día. Es la gran
ventaja: el tráfico se reduce uno a dos órdenes de magnitud frente al enfoque A.

**Latencia.** **Asíncrona e impredecible.** `cdsapi.retrieve()` encola la solicitud en el CDS, que
puede responder en segundos o quedar **en cola minutos u horas** según la carga del servicio. La
transferencia en sí es rápida (son MB), pero el tiempo de pared lo domina la cola, no la red. No
sirve para «lo necesito ahora mismo» cuando el servicio está saturado.

**Credenciales.** Requiere **API key de Copernicus** en `~/.cdsapirc` y haber **aceptado la licencia**
del producto en el portal del CDS. Un 403 típico significa credenciales inválidas o licencia sin
aceptar (el script ya traduce ese error). Para *subir* al bucket, además, las credenciales de AWS del
rol.

**Encaje con los permisos (solo `us-east-1`, sin GPU).** **Excelente.** La fuente es una API HTTP
externa, así que **no hay problema de región de AWS**: descargamos desde donde sea y subimos a
`us-east-1`. Sin GPU no aplica. El único punto que lo tiene bloqueado hoy es operativo, no de
diseño: el **registro SSM de la EC2** impide por ahora correrlo en la instancia (y configurar
`~/.cdsapirc` allí).

**En qué caso conviene.** Como **vía principal para ERA5 en producción**: minimiza transferencia,
elimina el cruce de regiones y entrega el producto limpio. Es la opción ideal *cuando* la API key
está configurada y la cola del CDS es tolerable (p. ej. ingesta planificada por lotes, no
interactiva).

---

## Enfoque C — GOES desde `noaa-goes16` / `noaa-goes19` (fruta madura)

Es lo que hace `scripts/pipeline/download_goes.py`: lee el producto `ABI-L2-MCMIPF` (16 bandas,
disco completo, 2 km) de `s3://noaa-goes16/` (hasta 2025-04-04 15 UTC) o `s3://noaa-goes19/` (desde
entonces), pide por rango de bytes solo los bloques (226×226 px) que tocan la región y los ensambla.

**Qué datos entrega.** Imágenes GOES-East por hora recortadas a la región, con los valores tal como
vienen (enteros con `scale_factor`/`add_offset`), más lat/lon por píxel. Hasta 6 imágenes por hora.
No corrige paralaje (desplaza los topes ~21 km a 53°S). Es la otra mitad de la entrada del modelo
(la señal satelital), complementaria a ERA5.

**Volumen aproximado.** Cada archivo de disco completo pesa ~360 MB, **pero** el formato permite
recorte por bloques: solo se bajan los bloques que intersectan Chile. El tráfico real por hora es
una fracción del archivo (los pocos bloques del recuadro), no los 360 MB completos. Aun así es el
dato más pesado por volumen de píxeles; el ahorro viene del recorte por bloque, no de recorte en
servidor.

**Latencia.** Síncrona y rápida: lectura directa de S3 con un `ls` del folder horario y lecturas de
bloque concurrentes. Sin cola externa.

**Credenciales.** **Ninguna para leer** (buckets públicos NOAA, acceso anónimo). Credenciales solo
para escribir en el bucket destino.

**Encaje con los permisos (solo `us-east-1`, sin GPU).** **Perfecto, y es la clave.** `noaa-goes16`
y `noaa-goes19` **ya están en `us-east-1`**, la única región que tenemos permitida. **No hay cruce
de regiones**: leemos y escribimos en la misma región. Sin GPU no aplica (es I/O + ensamblado
NumPy). Esto convierte a GOES en la ingesta de menor fricción de las tres: nada que registrar, nada
que cruzar, nada que esperar en cola.

**En qué caso conviene.** **Siempre, y primero.** Es la ingesta que podemos poner a correr hoy sin
esperar a SSM ni a Copernicus. Avanzar GOES en paralelo desbloquea el trabajo de modelado sobre la
señal satelital mientras ERA5 se resuelve por otra vía.

---

## Tabla resumen

| Dimensión | A — NCAR byte-range (ERA5) | B — CDS API (ERA5) | C — NOAA GOES |
|---|---|---|---|
| **Fuente** | `s3://nsf-ncar-era5/` (`us-west-2`) | API Copernicus CDS (HTTP) | `s3://noaa-goes16/`·`noaa-goes19/` (`us-east-1`) |
| **Dato entregado** | ERA5 PL+SFC, 24 h, recorte Chile | ERA5 PL+SFC, 24 h, recorte Chile (idéntico a A) | GOES-East MCMIPF 16 bandas, hasta 6/h, recorte Chile |
| **Recorte** | En cliente (en memoria) | **En servidor** (`area=`) | En cliente, **por bloques** (barato) |
| **Volumen transferido** | **~GB/día** (globo por hora) | **~MB/día** (solo recuadro) | Fracción de 360 MB/img (solo bloques) |
| **Volumen guardado** | Decenas de MB/día | Decenas de MB/día | Según bandas/horas |
| **Latencia** | Síncrona, lenta (volumen) + cross-region | Asíncrona, cola variable (s a horas) | Síncrona, rápida |
| **Credenciales lectura** | Ninguna (anónimo) | **API key CDS + licencia** | Ninguna (anónimo) |
| **Cruce de regiones** | **Sí** (`us-west-2`→`us-east-1`) | No (API externa) | **No** (intra-`us-east-1`) |
| **Encaje con permisos** | Pobre (fuente en región denegada) | Excelente (bloqueo solo operativo: SSM) | **Perfecto** (intra-región, sin credenciales) |
| **GPU** | No requiere | No requiere | No requiere |
| **Estado hoy** | Funciona, probado | Bloqueado por registro SSM de la EC2 | Listo para correr |
| **Rol recomendado** | Respaldo de ERA5 | Vía principal de ERA5 | Primera ingesta, en paralelo |

---

## Recomendación de arquitectura final

Combinar los tres, asignando a cada fuente el camino que mejor encaja con la restricción de
`us-east-1`:

1. **GOES → directo intra-región (Enfoque C), ya.**
   `noaa-goes16/19` está en `us-east-1`: se lee y se escribe en la misma región, sin credenciales de
   lectura, sin cola, sin cruce. Es la fruta madura. Ponerlo a correr ahora desbloquea el modelado
   de la señal satelital **sin esperar a SSM ni a Copernicus**. Prioridad inmediata.

2. **ERA5 → CDS como vía principal (Enfoque B), en cuanto SSM lo permita.**
   Es la única vía que elimina el cruce de regiones *y* la transferencia de GB para ERA5, porque el
   recorte ocurre en el servidor del CDS y bajamos solo MB. El bloqueo actual es operativo (registro
   SSM de la EC2 + configurar `~/.cdsapirc`), no de diseño: `ingest_cds.py` ya está escrito y maneja
   los errores de licencia y de cola. Desbloquear SSM es la tarea que convierte B en la vía por
   defecto de ERA5.

3. **ERA5 → NCAR byte-range como respaldo (Enfoque A), siempre disponible.**
   Mantener `download_era5.py` / `ingest_ncar_zarr.py` como plan B: cuando el CDS está encolado,
   caído, o se necesita un día puntual de inmediato, el camino anónimo sin dependencias externas
   responde. Acepta el costo de transferir GB cross-region a cambio de no depender de nadie. No es la
   vía de régimen, pero es el seguro que hace que el pipeline nunca quede completamente bloqueado.

En una frase: **GOES directo intra-región + ERA5 vía CDS, con NCAR byte-range como respaldo.** Así la
ingesta vive dentro de `us-east-1` siempre que se puede, minimiza transferencia, no necesita GPU, y
degrada con elegancia cuando una fuente falla.

### Secuencia de desbloqueo sugerida

| Paso | Acción | Depende de |
|---|---|---|
| 1 | Correr ingesta GOES (C) a `us-east-1` | Nada (listo hoy) |
| 2 | Resolver registro SSM de la EC2 | Operaciones / IAM |
| 3 | Configurar `~/.cdsapirc` + aceptar licencia CDS | API key Copernicus |
| 4 | Promover CDS (B) a vía principal de ERA5 | Pasos 2 y 3 |
| 5 | Dejar NCAR byte-range (A) como respaldo documentado | Nada (ya funciona) |

> Nota: todo lo anterior es preparación en el repositorio. No se ejecuta nada en AWS hasta que el
> equipo lo decida; estos scripts solo se lanzan contra S3 de forma deliberada.
