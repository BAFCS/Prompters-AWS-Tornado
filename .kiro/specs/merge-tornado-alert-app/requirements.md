# Requirements Document

## Introduction

Esta funcionalidad une dos ramas del equipo en una rama nueva `merge/datos-modelo` creada desde `main` y construye una primera versión simple y funcional de una aplicación que muestra la favorabilidad de tornados en Chile en una página web estática y genera alertas en modo demostración.

- Rama `intentos-nico` (Nico): ingesta del lago de datos en S3 (`era5_store/`, `era5_cds_year/`, `goes_store/`).
- Rama `feat/multimodal-tornado-predictor-wip` (Daniel): predictor XGBoost multimodal con contrato de inferencia (`sm_job/inference.py`).

La versión 1 conecta ambas partes mediante un adaptador de datos, ejecuta la inferencia (modelo real si existen artefactos; modelo sustituto heurístico si no), genera un sitio estático con mapa Leaflet publicado por S3 + CloudFront, y evalúa reglas de alerta con destinos intercambiables (demo primero, WhatsApp después). El puntaje del modelo es un puntaje PU (positivo-no etiquetado), no una probabilidad calibrada, y la interfaz lo presenta como tal.

Alcance excluido de la versión 1: envío real por WhatsApp, autenticación del sitio, entrenamiento del modelo, corrección de los errores conocidos de los scripts de ingesta de Nico y despliegue de SageMaker.

## Glossary

- **Rama_Integración**: rama Git `merge/datos-modelo` creada desde `origin/main` que integra las cabezas de `origin/intentos-nico` y `origin/feat/multimodal-tornado-predictor-wip` vigentes en cada Sincronización, con los SHA integrados registrados en la Bitácora_Progreso y en el Documento_Planificación.
- **Sincronización**: nuevo merge de las cabezas actuales de `origin/intentos-nico` y `origin/feat/multimodal-tornado-predictor-wip` en la Rama_Integración.
- **Documento_Planificación**: archivo `docs/planificacion_merge.md` con ideas de diseño, decisiones y preguntas abiertas para el equipo.
- **Bitácora_Progreso**: archivo JSON `docs/logs/progreso.json` de solo agregado que registra el avance entre sesiones.
- **Entrada_Bitácora**: objeto dentro de Bitácora_Progreso con los campos `timestamp` (ISO 8601 UTC), `tarea`, `estado` (`pendiente`, `en_curso`, `hecho`, `bloqueado`), `notas` y `decisiones`.
- **Lago_Datos**: prefijos S3 producidos por la rama de Nico: `era5_store/era5_YYYYMMDD.zarr`, `era5_cds_year/<YYYY>/<MM>/era5_{pl,sfc}_YYYYMMDD.nc` y `goes_store/<YYYY-MM-DD>/goes_YYYYMMDD.nc`.
- **Entradas_Modelo**: archivos que espera el pipeline del modelo: `era5_indices/era5_idx_AAAAMMDD.nc` y `goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` (grilla de 0,02°).
- **Adaptador**: módulo nuevo que lee un día del Lago_Datos (o archivos locales con la misma estructura) y produce las Entradas_Modelo de ese día sin modificar el código de Nico ni el de Daniel.
- **Reporte_Calidad**: archivo JSON por día emitido por el Adaptador con el resultado de cada verificación de completitud y esquema.
- **Día_Utilizable**: día cuyo Reporte_Calidad no contiene verificaciones con severidad `error`.
- **Tabla_Inferencia**: Parquet generado por `build_table.py --stage infer` con las columnas clave `date`, `hour_utc`, `latitude`, `longitude` y las columnas de configuración.
- **Ejecutor_Inferencia**: módulo nuevo que recibe una Tabla_Inferencia y produce el CSV_Predicciones usando el Modelo_Real o el Modelo_Sustituto.
- **Modelo_Real**: artefactos `model.json`, `feature_columns.json`, `config.json` y opcionalmente `reducer.npz` compatibles con `sm_job/inference.py`.
- **Modelo_Sustituto**: modelo heurístico basado en umbrales físicos sobre índices ERA5 (por ejemplo CAPE y cizalladura) con la misma interfaz que el Modelo_Real.
- **CSV_Predicciones**: CSV con las columnas `probability,date,hour_utc,latitude,longitude,config` y un archivo de metadatos acompañante que indica `modelo` (`real` o `sustituto`) y la fecha de generación.
- **Índice_Favorabilidad**: valor de `probability` expresado como porcentaje entre 0 y 100, presentado como índice relativo y no como probabilidad calibrada.
- **Generador_Sitio**: script nuevo que produce el Sitio_Estático a partir de uno o más CSV_Predicciones y del Catálogo.
- **Sitio_Estático**: conjunto de archivos HTML, CSS, JavaScript y JSON con un mapa Leaflet, sin servidor de aplicación.
- **Catálogo**: archivo `data/tornados_chile.xlsx` con 102 eventos históricos.
- **Motor_Alertas**: módulo nuevo que evalúa las Reglas_Alerta sobre un CSV_Predicciones y entrega Alertas a los Destinos_Alerta.
- **Regla_Alerta**: configuración con umbral de Índice_Favorabilidad, Zona_Alerta y ventana de supresión.
- **Zona_Alerta**: polígono o caja geográfica con nombre (por ejemplo una región de Chile) definida en un archivo de configuración.
- **Alerta**: mensaje estructurado con zona, fecha, hora UTC, Índice_Favorabilidad máximo, tipo de modelo y texto de descargo.
- **Destino_Alerta**: implementación intercambiable que entrega una Alerta: `consola`, `archivo` (JSONL), `sns_email` (opcional) y `whatsapp` (stub).
- **Despliegue**: configuración Terraform en `infra/terraform` que publica el Sitio_Estático bajo el prefijo `sitio/` del bucket S3 existente, detrás de la distribución CloudFront existente con OAC.
- **Puerta_Calidad**: comando `make check` (ruff check, ruff format --check, pyright y unittest).
- **Día_Demo**: 2019-05-30, único día con eventos del Catálogo presente en el Lago_Datos.

## Requirements

### Requisito 1: Rama de integración y resolución de conflictos

**Historia de Usuario:** Como integrante del equipo, quiero unir ambas ramas en una rama nueva desde `main`, para revisar la integración mediante un PR sin tocar `main`.

#### Criterios de Aceptación

1. WHEN se inicia la integración, THE Rama_Integración SHALL crearse con el nombre `merge/datos-modelo` a partir del commit al que apunta `origin/main` tras ejecutar `git fetch` (cf59a73 al momento de redactar este documento) y publicarse en `origin` con seguimiento remoto configurado hacia `origin/merge/datos-modelo`.
2. THE Rama_Integración SHALL tener como ancestros los commits cabeza de `origin/intentos-nico` y `origin/feat/multimodal-tornado-predictor-wip` observados en la Sincronización más reciente, de modo que `git merge-base --is-ancestor` devuelva código cero para ambos SHA registrados en esa Sincronización.
3. WHEN un merge produce conflictos en `pyproject.toml`, THE Rama_Integración SHALL conservar cada dependencia declarada en cualquiera de las dos ramas, con versión fijada exacta (`==`), y, si ambas ramas declaran la misma dependencia con versiones distintas, SHALL conservar una única entrada con la versión más alta y registrar la elección en el Documento_Planificación.
4. WHEN `pyproject.toml` cambia durante la integración, THE Rama_Integración SHALL incluir un `uv.lock` regenerado con `uv lock`, verificable porque `uv lock --check` termina con código cero sobre el commit final de la rama.
5. WHEN un merge produce conflictos en `README.md` u otros archivos de documentación (`.md`), THE Rama_Integración SHALL conservar el contenido de ambas ramas en secciones separadas con un encabezado que identifique la rama de origen, sin eliminar ningún párrafo de ninguna de las dos versiones.
6. WHEN la integración termina, THE Rama_Integración SHALL dejar `origin/main` apuntando al mismo commit que tenía antes de iniciar la integración, sin commits ni pushes directos a `main`.
7. WHEN la integración termina, THE Rama_Integración SHALL superar la Puerta_Calidad (`make check` con código de salida cero) sobre su último commit antes de abrir el PR hacia `main`.
8. IF un merge requiere modificar código de Nico o de Daniel más allá de resolver conflictos, THEN THE Rama_Integración SHALL registrar en el Documento_Planificación cada archivo modificado, el cambio realizado y su motivo.
9. WHEN se completa un commit de merge, THE Rama_Integración SHALL no contener marcadores de conflicto (`<<<<<<<`, `=======`, `>>>>>>>`) en ningún archivo versionado.
10. IF la Puerta_Calidad termina con un código de salida distinto de cero, THEN THE Rama_Integración SHALL permanecer sin PR abierto hasta que una corrección posterior haga que la Puerta_Calidad termine con código cero, y la falla SHALL registrarse en la Bitácora_Progreso con `estado` igual a `bloqueado`.
11. WHEN se resuelve un conflicto en `README.md`, THE Rama_Integración SHALL conservar en `README.md` el enlace a `docs/modelo_predictor.md` que exige `tests/test_docs.py`.
12. WHEN se realiza una Sincronización, THE Rama_Integración SHALL incorporar cada rama de origen mediante `git merge --no-ff`, sin rebase, squash ni force-push sobre `intentos-nico`, `feat/multimodal-tornado-predictor-wip`, `main` ni `merge/datos-modelo`.
13. WHEN se completa una Sincronización, THE Rama_Integración SHALL registrar los SHA integrados de `origin/intentos-nico`, `origin/feat/multimodal-tornado-predictor-wip` y `origin/main` en una Entrada_Bitácora de la Bitácora_Progreso y en la tabla de Sincronizaciones del Documento_Planificación.
14. WHEN se va a abrir el PR hacia `main`, THE Rama_Integración SHALL realizar una Sincronización final con las cabezas vigentes de ambas ramas de origen y superar la Puerta_Calidad (`make check` con código de salida cero) sobre el commit resultante de esa Sincronización.

### Requisito 2: Documento de planificación

**Historia de Usuario:** Como integrante del equipo, quiero un documento de planificación con ideas y preguntas abiertas, para decidir en conjunto el rumbo de la aplicación.

#### Criterios de Aceptación

1. THE Documento_Planificación SHALL describir el flujo Lago_Datos → Adaptador → Tabla_Inferencia → Ejecutor_Inferencia → CSV_Predicciones → Generador_Sitio y Motor_Alertas, indicando para cada uno de los 7 componentes su artefacto de entrada y su artefacto de salida, e indicando que Generador_Sitio y Motor_Alertas consumen ambos el mismo CSV_Predicciones de forma independiente.
2. THE Documento_Planificación SHALL listar las 3 decisiones ya tomadas por el usuario (rama nueva desde `main`, Adaptador como módulo separado y Sitio_Estático con alertas en modo demo), cada una con su fecha en formato AAAA-MM-DD y una frase que indique su motivo.
3. THE Documento_Planificación SHALL incluir una sección de preguntas abiertas para el equipo con al menos 7 preguntas que cubran: región de ML (us-west-2 frente a us-east-1), cuenta AWS de producción, calibración del puntaje PU, umbrales de alerta, definición de Zonas_Alerta, requisitos de WhatsApp (cuenta Meta, número verificado, plantillas aprobadas, consentimiento) y autenticación del sitio, donde cada pregunta indica al menos 2 opciones consideradas, el componente afectado y un estado `abierta` o `resuelta`.
4. THE Documento_Planificación SHALL listar los 5 errores conocidos del Lago_Datos (días GOES incompletos marcados como completos, ítems ERA5 con NaN marcados como completos, escrituras Zarr no atómicas, sobrescritura del JSON de progreso y `curate_granularity.py` incompatible con la estructura real), indicando para cada error la mitigación aplicada en el Adaptador y la verificación del Reporte_Calidad que la detecta, o el texto "sin mitigación en v1" cuando el Adaptador no lo mitiga.
5. THE Documento_Planificación SHALL listar los riesgos de la versión 1, incluyendo al menos sitio público sin autenticación, ausencia de eventos etiquetados en la ventana 2025-10-15 → 2026-09-30 y uso del Modelo_Sustituto, indicando para cada riesgo su impacto sobre la aplicación y la medida de mitigación o la indicación explícita de que el riesgo se acepta en la versión 1.
6. THE Documento_Planificación SHALL estar escrito en español en formato Markdown en `docs/planificacion_merge.md` con un encabezado de sección para cada uno de los siguientes apartados: flujo, decisiones, preguntas abiertas, errores conocidos, riesgos, cambios al código de origen y sincronización con ramas en movimiento.
7. THE Documento_Planificación SHALL incluir en el apartado de cambios al código de origen cada cambio registrado según el Requisito 1, criterio 8, con el archivo afectado, la rama de origen y el motivo, o el texto "ninguno" cuando no existan cambios.
8. WHEN una pregunta abierta se resuelve, THE Documento_Planificación SHALL marcar la pregunta con estado `resuelta`, conservar su texto original y agregar la decisión resultante al apartado de decisiones con su fecha en formato AAAA-MM-DD.
9. THE Documento_Planificación SHALL incluir una sección con el encabezado "Sincronización con ramas en movimiento" que liste los archivos compartidos `infra/terraform/s3.tf`, `infra/terraform/cloudfront.tf`, `infra/terraform/outputs.tf`, `infra/terraform/versions.tf`, `README.md`, `pyproject.toml` y `uv.lock`, indicando para cada archivo el integrante responsable, y que describa el acuerdo de coordinación de avisar al equipo antes de modificar cualquiera de esos archivos.
10. THE Documento_Planificación SHALL incluir en la sección "Sincronización con ramas en movimiento" una tabla de Sincronizaciones con una fila por cada Sincronización realizada y las columnas fecha (AAAA-MM-DD), SHA de `intentos-nico`, SHA de `feat/multimodal-tornado-predictor-wip`, SHA de `origin/main`, conflictos resueltos y resultado de la Puerta_Calidad.
11. THE Documento_Planificación SHALL incluir en la sección de preguntas abiertas, además de las preguntas del criterio 3, una pregunta sobre la interacción entre la propiedad de subconjunto del Requisito 7, criterio 12, y la ventana de supresión del Requisito 7, criterio 2, y una pregunta sobre la política de fijación exacta de versiones (`==`) del Requisito 1, criterio 3, cada una con al menos 2 opciones consideradas, el componente afectado y un estado `abierta` o `resuelta`.

### Requisito 3: Bitácora de progreso en JSON

**Historia de Usuario:** Como integrante del equipo (o agente), quiero una bitácora JSON de solo agregado, para retomar el contexto entre sesiones.

#### Criterios de Aceptación

1. THE Bitácora_Progreso SHALL ser un documento JSON válido codificado en UTF-8 cuyo elemento raíz es un arreglo en el que cada elemento es una Entrada_Bitácora con los cinco campos `timestamp`, `tarea`, `estado`, `notas` y `decisiones`.
2. WHEN se agrega una Entrada_Bitácora válida, THE Bitácora_Progreso SHALL ubicar la nueva entrada al final del arreglo, aumentar la cantidad de entradas en exactamente 1 y conservar sin cambios el contenido y el orden de todas las Entradas_Bitácora previas.
3. WHEN se agrega una Entrada_Bitácora válida, THE Bitácora_Progreso SHALL escribirse de forma atómica mediante un archivo temporal en el mismo directorio seguido de un renombrado sobre `docs/logs/progreso.json`, de modo que cualquier lectura concurrente obtenga el documento anterior completo o el documento nuevo completo.
4. IF una Entrada_Bitácora carece de alguno de los cinco campos obligatorios, tiene un `timestamp` que no es una fecha y hora ISO 8601 con zona UTC, tiene una `tarea` vacía o de más de 200 caracteres, o tiene un `estado` distinto de `pendiente`, `en_curso`, `hecho` o `bloqueado`, THEN THE Bitácora_Progreso SHALL rechazar la entrada con un código de salida distinto de cero y un mensaje que nombre cada campo inválido, dejando el archivo existente sin modificaciones.
5. FOR ALL secuencias de 0 a 100 Entradas_Bitácora válidas, agregar las entradas una por una sobre una Bitácora_Progreso inexistente y luego leer la Bitácora_Progreso SHALL producir la misma secuencia en el mismo orden con valores de campo idénticos (propiedad de ida y vuelta).
6. WHEN se agrega una Entrada_Bitácora válida y el archivo `docs/logs/progreso.json` no existe, THE Bitácora_Progreso SHALL crear el archivo y los directorios faltantes con un arreglo que contenga únicamente esa entrada.
7. IF el archivo existente no es JSON válido o su elemento raíz no es un arreglo, THEN THE Bitácora_Progreso SHALL rechazar el agregado con un código de salida distinto de cero y un mensaje que indique que el archivo está corrupto, sin sobrescribir ni modificar el archivo.
8. IF la escritura del archivo temporal o el renombrado fallan, THEN THE Bitácora_Progreso SHALL terminar con un código de salida distinto de cero, conservar el archivo original sin cambios y eliminar el archivo temporal.

### Requisito 4: Adaptador del lago de datos a las entradas del modelo

**Historia de Usuario:** Como integrante del equipo, quiero un adaptador que transforme el lago de datos de Nico en las entradas que espera el modelo de Daniel, para conectar ambas ramas sin reescribir su código.

#### Criterios de Aceptación

1. WHEN se solicita un día presente en `era5_store`, THE Adaptador SHALL producir un único archivo `era5_indices/era5_idx_AAAAMMDD.nc` que contenga todas las variables y coordenadas que lee `build_table.py`, calculadas solo a partir de los 6 niveles de presión disponibles en `era5_store` (1000, 925, 850, 700, 500 y 300 hPa) y de las variables de superficie.
2. WHEN se solicita un día que no está en `era5_store` y sí está en `era5_cds_year` (archivos `era5_pl_AAAAMMDD.nc` y `era5_sfc_AAAAMMDD.nc` presentes), THE Adaptador SHALL renombrar las coordenadas y variables de `era5_cds_year` (`valid_time`, `pressure_level`, `u10`, `t2m` y las demás que difieran) a los nombres usados en `era5_store`, y seleccionar los mismos 6 niveles de presión, antes de calcular los índices.
3. WHEN se solicita un día presente en `goes_store`, THE Adaptador SHALL leer el archivo diario `goes_AAAAMMDD.nc` (banda C13, grilla nativa de 882 × 466 píxeles con latitud y longitud 2D), convertir los enteros int16 a valores físicos como `entero × scale_factor + add_offset`, y producir un archivo `goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` por cada hora UTC (00 a 23) con al menos una escena, remuestreado a una grilla regular de 0,02° en latitud y longitud.
4. WHEN el Adaptador convierte un píxel GOES cuyo valor entero es igual a `_FillValue` (-1), THE Adaptador SHALL asignar NaN a ese píxel en lugar de aplicar `scale_factor` y `add_offset`.
5. THE Adaptador SHALL aceptar como origen una URI S3 o un directorio local con la misma estructura de prefijos que el Lago_Datos, y SHALL producir salidas idénticas para el mismo día con ambos tipos de origen.
6. WHEN el Adaptador termina de procesar un día, THE Adaptador SHALL emitir un Reporte_Calidad que contenga: el número de escenas GOES en cada una de las 24 horas UTC, la fracción de NaN (entre 0 y 1) por variable ERA5, la presencia de cada variable y de cada uno de los 6 niveles de presión esperados, y las dimensiones de la grilla GOES nativa (esperada 882 × 466) y de la grilla de salida, con una severidad (`ok`, `advertencia` o `error`) por verificación.
7. IF una o más de las 24 horas UTC de un día GOES no tienen escenas, THEN THE Adaptador SHALL listar cada hora faltante en el Reporte_Calidad con severidad `advertencia` y producir archivos solo para las horas con al menos una escena.
8. IF una variable ERA5 tiene una fracción de NaN estrictamente mayor que el umbral configurado (por defecto 0,05; rango válido de 0 a 1), THEN THE Adaptador SHALL registrar esa variable con severidad `error` en el Reporte_Calidad y no escribir `era5_idx_AAAAMMDD.nc` para ese día.
9. IF falta una variable esperada, alguno de los 6 niveles de presión esperados o una dimensión esperada, o la grilla GOES nativa no mide 882 × 466, THEN THE Adaptador SHALL registrar la verificación con severidad `error` en el Reporte_Calidad, no escribir la salida afectada de ese día y continuar con el siguiente día solicitado.
10. IF un día solicitado no está en `era5_store`, ni en `era5_cds_year`, ni en `goes_store`, THEN THE Adaptador SHALL emitir un Reporte_Calidad de ese día con una verificación de severidad `error` que indique la ausencia de datos de origen, no producir Entradas_Modelo y continuar con el siguiente día solicitado.
11. IF las credenciales AWS no son válidas o han expirado, THEN THE Adaptador SHALL terminar antes de escribir cualquier archivo de salida, con un código de salida distinto de cero y un mensaje que indique el nombre del perfil AWS usado.
12. WHEN el Adaptador escribe un archivo de salida o un Reporte_Calidad, THE Adaptador SHALL escribirlo primero en un archivo temporal y luego renombrarlo al nombre final, de modo que una interrupción no deje un archivo final parcial.
13. WHEN se solicita un día cuyas Entradas_Modelo ya existen y cuyo Reporte_Calidad no contiene verificaciones con severidad `error`, THE Adaptador SHALL omitir el reprocesamiento y dejar los archivos sin cambios, salvo que se indique la opción de forzar, en cuyo caso SHALL reprocesar y sobrescribir el día.
14. FOR ALL arreglos GOES int16 con `scale_factor` y `add_offset`, decodificar y luego codificar con los mismos parámetros (redondeando al entero más cercano) SHALL reproducir exactamente los enteros originales distintos de `_FillValue`, y los píxeles con `_FillValue` (-1) SHALL volver a codificarse como -1 (propiedad de ida y vuelta).
15. FOR ALL campos ERA5 sintéticos con los 6 niveles de presión, los índices calculados por el Adaptador desde la estructura de `era5_cds_year` SHALL coincidir con los calculados desde la estructura equivalente de `era5_store` con una diferencia absoluta máxima de 1e-6 por celda (propiedad de confluencia).

### Requisito 5: Ejecutor de inferencia

**Historia de Usuario:** Como integrante del equipo, quiero ejecutar la inferencia con el modelo real cuando exista y con un modelo sustituto cuando no, para tener predicciones en la aplicación desde la versión 1.

#### Criterios de Aceptación

1. WHEN se ejecuta el Ejecutor_Inferencia y la ruta configurada contiene `model.json`, `feature_columns.json` y `config.json` del Modelo_Real, THE Ejecutor_Inferencia SHALL producir el CSV_Predicciones con el Modelo_Real, usando `reducer.npz` solo si está presente, con valores de `probability` que difieran en no más de 1e-6 de los que produce `sm_job/inference.py` sobre la misma Tabla_Inferencia y los mismos artefactos.
2. WHEN se ejecuta el Ejecutor_Inferencia y la ruta configurada no existe o no contiene ninguno de los archivos `model.json`, `feature_columns.json` y `config.json`, THE Ejecutor_Inferencia SHALL producir el CSV_Predicciones con el Modelo_Sustituto.
3. WHEN el Ejecutor_Inferencia termina con éxito, THE Ejecutor_Inferencia SHALL escribir en los metadatos del CSV_Predicciones el campo `modelo` con valor `real` o `sustituto`, la fecha de generación en formato ISO 8601 UTC, el número total de filas procesadas y el número de filas con al menos un valor NaN en columnas de entrada.
4. THE Ejecutor_Inferencia SHALL producir en cada fila del CSV_Predicciones un valor numérico de `probability` dentro del intervalo cerrado [0, 1], sin valores NaN ni vacíos.
5. WHEN el Ejecutor_Inferencia procesa una Tabla_Inferencia con N filas (N ≥ 0), THE Ejecutor_Inferencia SHALL producir un CSV_Predicciones con exactamente N filas de datos más la fila de encabezado `probability,date,hour_utc,latitude,longitude,config`, en el mismo orden de la Tabla_Inferencia y con los mismos valores de `date`, `hour_utc`, `latitude`, `longitude` y `config`.
6. IF la Tabla_Inferencia carece de alguna de las columnas clave (`date`, `hour_utc`, `latitude`, `longitude`) o de alguna columna de entrada requerida por el modelo seleccionado (las listadas en `feature_columns.json` para el Modelo_Real, o las columnas de CAPE y cizalladura para el Modelo_Sustituto), THEN THE Ejecutor_Inferencia SHALL terminar con un código de salida distinto de cero, mostrar un mensaje que liste todas las columnas faltantes y no escribir el CSV_Predicciones ni sus metadatos.
7. IF la Tabla_Inferencia contiene valores NaN en columnas de entrada, THEN THE Ejecutor_Inferencia SHALL procesar todas las filas, pasando los NaN sin imputar al Modelo_Real cuando se usa el Modelo_Real, y asignando `probability` igual a 0 a las filas con NaN en CAPE o cizalladura cuando se usa el Modelo_Sustituto.
8. FOR ALL pares de filas sintéticas de una Tabla_Inferencia que solo difieren en que la segunda tiene CAPE mayor o igual y cizalladura mayor o igual que la primera, el Modelo_Sustituto SHALL asignar a la segunda fila un valor de `probability` mayor o igual que el de la primera (propiedad metamórfica de monotonía).
9. FOR ALL Tablas_Inferencia válidas, ejecutar el Ejecutor_Inferencia dos veces sobre la misma entrada y los mismos artefactos SHALL producir CSV_Predicciones idénticos byte a byte y metadatos idénticos salvo el campo de fecha de generación (propiedad de determinismo).
10. IF la ruta configurada contiene al menos uno pero no todos los archivos `model.json`, `feature_columns.json` y `config.json`, THEN THE Ejecutor_Inferencia SHALL terminar con un código de salida distinto de cero, mostrar un mensaje que liste los artefactos faltantes y no usar el Modelo_Sustituto como reemplazo.
11. IF la Tabla_Inferencia o algún artefacto del Modelo_Real no puede leerse o no puede interpretarse, THEN THE Ejecutor_Inferencia SHALL terminar con un código de salida distinto de cero, mostrar un mensaje que nombre el archivo afectado y no escribir el CSV_Predicciones ni sus metadatos.
12. WHEN el Ejecutor_Inferencia escribe el CSV_Predicciones y sus metadatos, THE Ejecutor_Inferencia SHALL escribir cada archivo de forma atómica mediante archivo temporal y renombrado, de modo que un CSV_Predicciones previo en la misma ruta permanezca sin cambios si la ejecución falla.

### Requisito 6: Generador del sitio estático

**Historia de Usuario:** Como usuario del sitio, quiero ver un mapa con el índice de favorabilidad por hora y los eventos del catálogo, para entender dónde las condiciones son favorables a tornados.

#### Criterios de Aceptación

1. WHEN se ejecuta con entre 1 y 366 CSV_Predicciones válidos, THE Generador_Sitio SHALL producir un Sitio_Estático en el directorio de salida indicado por argumento con un `index.html`, los recursos estáticos y exactamente un archivo JSON de datos por cada día distinto presente en los CSV_Predicciones, que contenga hasta 24 horas UTC × las celdas de la grilla ERA5 de 0,25° (hasta 105 × 41 celdas por hora) con su Índice_Favorabilidad y el tipo de modelo leído de los metadatos.
2. WHEN se selecciona un día y una hora UTC, THE Sitio_Estático SHALL mostrar un mapa Leaflet centrado en Chile continental con una capa que pinte cada celda de 0,25° con datos para ese día y hora con el color de la leyenda correspondiente a su Índice_Favorabilidad.
3. THE Sitio_Estático SHALL ofrecer un selector de día que liste solo los días con archivo JSON de datos en orden cronológico y un selector de hora UTC con los valores enteros de 0 a 23, ambos con foco alcanzable mediante la tecla Tab y valor modificable con las teclas de flecha.
4. WHEN se selecciona un día, THE Sitio_Estático SHALL mostrar como marcadores los eventos del Catálogo cuya fecha coincide con ese día, y WHEN se activa un marcador mediante clic o tecla Enter, THE Sitio_Estático SHALL mostrar la fecha, la localidad y la fuente del evento.
5. THE Sitio_Estático SHALL mostrar una leyenda del Índice_Favorabilidad de 0 a 100 % dividida en 5 intervalos de 20 puntos porcentuales con etiquetas numéricas en cada límite y colores tomados de una paleta secuencial apta para daltonismo (viridis o cividis).
6. THE Sitio_Estático SHALL mostrar en todo momento, sin necesidad de desplazamiento ni interacción, el texto "Índice de favorabilidad relativo; no es una probabilidad calibrada ni un pronóstico oficial".
7. WHEN se muestra un día cuyos metadatos indican `modelo` igual a `sustituto`, THE Sitio_Estático SHALL mostrar una etiqueta visible con el texto "Modelo sustituto heurístico (demo)", y WHEN se muestra un día cuyos metadatos indican `modelo` igual a `real`, THE Sitio_Estático SHALL ocultar esa etiqueta.
8. THE Sitio_Estático SHALL usar texto con una relación de contraste de al menos 4,5:1 respecto de su fondo y una etiqueta accesible (nombre accesible no vacío) en cada selector, botón y control del mapa.
9. WHEN existe un CSV_Predicciones válido para el Día_Demo, THE Generador_Sitio SHALL incluir el Día_Demo en el Sitio_Estático y THE Sitio_Estático SHALL mostrarlo como día seleccionado al cargar; IF no existe, THEN THE Sitio_Estático SHALL seleccionar al cargar el día más reciente disponible.
10. IF un CSV_Predicciones no cumple el esquema `probability,date,hour_utc,latitude,longitude,config`, contiene valores de `probability` fuera de [0, 1] o de `hour_utc` fuera de 0 a 23, o carece de su archivo de metadatos, THEN THE Generador_Sitio SHALL omitir ese archivo completo, escribir en la salida de error el nombre del archivo y el motivo, y continuar con los demás archivos.
11. IF no hay predicciones para el día y la hora UTC seleccionados, THEN THE Sitio_Estático SHALL ocultar la capa del Índice_Favorabilidad y mostrar el mensaje "Sin datos para esta hora" conservando visibles los marcadores del Catálogo.
12. FOR ALL CSV_Predicciones válidos, convertir las filas al JSON de datos del sitio y volver a leerlas SHALL reproducir los mismos valores de `date`, `hour_utc`, `latitude`, `longitude` y `probability` con redondeo a 4 decimales (propiedad de ida y vuelta).
13. IF ninguno de los CSV_Predicciones recibidos es válido, THEN THE Generador_Sitio SHALL terminar con un código de salida distinto de cero sin escribir ni modificar archivos en el directorio de salida.
14. IF el Catálogo no existe o no se puede leer, THEN THE Generador_Sitio SHALL generar el Sitio_Estático sin marcadores de eventos y escribir en la salida de error una advertencia que indique la ruta del Catálogo.
15. WHEN se cambia el día o la hora UTC seleccionados, THE Sitio_Estático SHALL actualizar la capa del Índice_Favorabilidad, los marcadores y la etiqueta de modelo en un máximo de 2 segundos sin recargar la página.

### Requisito 7: Motor de alertas con destinos intercambiables

**Historia de Usuario:** Como responsable de monitoreo, quiero recibir alertas cuando el índice supere un umbral en una zona, para reaccionar a tiempo, empezando con un modo demo y luego WhatsApp.

#### Criterios de Aceptación

1. WHEN el Motor_Alertas evalúa un CSV_Predicciones y el Índice_Favorabilidad máximo (valor de `probability` multiplicado por 100) entre los puntos cuya `latitude` y `longitude` caen dentro de una Zona_Alerta o sobre su borde, para una combinación de `date` y `hour_utc`, es estrictamente mayor que el umbral de la Regla_Alerta, THE Motor_Alertas SHALL generar exactamente una Alerta para esa Zona_Alerta, fecha y hora UTC.
2. IF una nueva Alerta para una Zona_Alerta corresponde a una fecha y hora UTC posterior a la última Alerta emitida para esa zona en menos horas que la ventana de supresión de la Regla_Alerta (entero entre 0 y 168 horas, por defecto 6), THEN THE Motor_Alertas SHALL omitir esa Alerta sin entregarla a ningún Destino_Alerta y registrar la omisión con la Zona_Alerta, la fecha, la hora UTC y la hora de la última Alerta emitida.
3. THE Motor_Alertas SHALL leer las Reglas_Alerta, las Zonas_Alerta y los Destinos_Alerta desde un único archivo de configuración versionado en el repositorio, cuya ruta puede indicarse por argumento de línea de comandos.
4. IF la configuración no especifica ningún Destino_Alerta, THEN THE Motor_Alertas SHALL entregar cada Alerta únicamente al Destino_Alerta `consola`, escribiéndola en la salida estándar.
5. WHERE el Destino_Alerta `archivo` está configurado, THE Motor_Alertas SHALL agregar cada Alerta como una línea JSON independiente al final del archivo en la ruta configurada, conservando sin cambios las líneas existentes y creando el archivo si no existe.
6. WHERE el Destino_Alerta `sns_email` está configurado, THE Motor_Alertas SHALL publicar cada Alerta como un mensaje en el tópico SNS configurado.
7. WHERE el Destino_Alerta `whatsapp` está configurado, THE Motor_Alertas SHALL registrar cada Alerta junto con el mensaje "WhatsApp no habilitado en v1" sin realizar ninguna conexión de red ni enviar mensajes externos.
8. THE Alerta SHALL incluir el nombre de la Zona_Alerta, la fecha, la hora UTC, el Índice_Favorabilidad máximo redondeado a 1 decimal, el umbral de la Regla_Alerta, el tipo de modelo (`real` o `sustituto`) leído de los metadatos del CSV_Predicciones y el texto de descargo "Índice relativo; no es un pronóstico oficial".
9. IF un Destino_Alerta falla al entregar una Alerta, THEN THE Motor_Alertas SHALL registrar en la salida de error el Destino_Alerta, la Zona_Alerta, la fecha, la hora UTC y el motivo del fallo, continuar entregando esa Alerta y las siguientes a los demás Destinos_Alerta sin reintentos, y terminar con un código de salida distinto de cero al finalizar la evaluación.
10. IF el archivo de configuración no existe, no puede interpretarse, contiene un umbral fuera del intervalo cerrado [0, 100], una ventana de supresión fuera de [0, 168] horas, un Destino_Alerta no reconocido o una Zona_Alerta con geometría inválida (polígono con menos de 3 vértices, polígono que se autointersecta, caja con latitud o longitud mínima mayor o igual que la máxima, o coordenadas fuera de [-90, 90] de latitud y [-180, 180] de longitud), THEN THE Motor_Alertas SHALL terminar con un código de salida distinto de cero y un mensaje que nombre el elemento inválido, antes de evaluar predicciones y sin entregar Alertas.
11. FOR ALL CSV_Predicciones, evaluar el Motor_Alertas dos veces con el mismo estado de supresión inicial y la misma configuración SHALL producir el mismo conjunto de Alertas con los mismos valores en todos sus campos (propiedad de idempotencia).
12. FOR ALL CSV_Predicciones, subir el umbral de una Regla_Alerta manteniendo fijo el resto de la configuración SHALL producir un conjunto de Alertas candidatas (generadas según el criterio 1, antes de aplicar la supresión del criterio 2) que es subconjunto del conjunto de Alertas candidatas obtenido con el umbral original, y, cuando la ventana de supresión es 0, el conjunto de Alertas entregadas tras la evaluación completa SHALL ser también subconjunto del obtenido con el umbral original con el mismo estado de supresión inicial (propiedad metamórfica).
13. IF el CSV_Predicciones no cumple el esquema `probability,date,hour_utc,latitude,longitude,config` o su archivo de metadatos falta o no indica `modelo`, THEN THE Motor_Alertas SHALL terminar con un código de salida distinto de cero y un mensaje que indique el problema, sin entregar Alertas.
14. IF el CSV_Predicciones no tiene filas o ningún punto cae dentro de una Zona_Alerta, THEN THE Motor_Alertas SHALL no generar Alertas para esa Zona_Alerta, registrar que la zona no tiene datos y terminar con código de salida cero si no hubo otros errores.
15. WHEN el Motor_Alertas termina una evaluación, THE Motor_Alertas SHALL conservar la fecha y hora UTC de la última Alerta emitida por cada Zona_Alerta como estado de supresión disponible para la evaluación siguiente.

### Requisito 8: Despliegue del sitio estático

**Historia de Usuario:** Como integrante del equipo, quiero publicar el sitio en S3 + CloudFront con el patrón Terraform existente, para compartir la demo con una URL.

#### Criterios de Aceptación

1. THE Despliegue SHALL reutilizar el bucket S3 y la distribución CloudFront con OAC ya definidos en `infra/terraform`, sin crear un bucket ni una distribución adicionales, y servir el Sitio_Estático bajo el prefijo dedicado `sitio/`, de modo que la ruta CloudFront `/sitio/<archivo>` corresponda a la clave S3 `sitio/<archivo>`.
2. THE Despliegue SHALL agregar un comportamiento de caché ordenado para `/sitio/*` con origen en el bucket S3, solo métodos GET, HEAD y OPTIONS y redirección a HTTPS, y SHALL conservar sin cambios el comportamiento por defecto hacia la EC2 y los comportamientos existentes `/resultados/estado.html` y `/resultados/*`.
3. THE Despliegue SHALL mantener el bucket S3 con los cuatro bloqueos de acceso público activados, la denegación de transporte sin TLS y una política que permita `s3:GetObject` a CloudFront mediante OAC únicamente sobre los prefijos `resultados/*` y `sitio/*`, condicionada al ARN de la distribución existente.
4. IF se solicita por CloudFront una clave S3 fuera de los prefijos `resultados/` y `sitio/`, o se solicita cualquier objeto del bucket directamente por su URL S3 sin pasar por CloudFront, THEN THE Despliegue SHALL dejar que la solicitud sea rechazada con acceso denegado y sin devolver el contenido del objeto.
5. WHEN se publica el Sitio_Estático, THE Despliegue SHALL subir cada archivo con el `Content-Type` correspondiente a su extensión: `.html` como `text/html; charset=utf-8`, `.css` como `text/css; charset=utf-8`, `.js` como `text/javascript; charset=utf-8`, `.json` como `application/json`, `.png` como `image/png` y `.svg` como `image/svg+xml`.
6. IF el Sitio_Estático contiene un archivo con una extensión fuera de la lista del criterio 5, THEN THE Despliegue SHALL terminar con un código de salida distinto de cero antes de subir archivos y con un mensaje que nombre el archivo y su extensión.
7. WHEN la subida de todos los archivos de una versión nueva del Sitio_Estático termina sin errores, THE Despliegue SHALL crear en CloudFront una invalidación de la ruta `/sitio/*` y mostrar el identificador de la invalidación.
8. IF la subida de algún archivo del Sitio_Estático falla, THEN THE Despliegue SHALL terminar con un código de salida distinto de cero, con un mensaje que nombre el archivo fallido, y sin crear la invalidación de CloudFront.
9. WHEN el Despliegue termina sin errores, THE Despliegue SHALL mostrar la URL completa `https://<dominio de la distribución>/sitio/index.html`, y una solicitud GET a esa URL SHALL devolver el `index.html` publicado con `Content-Type` `text/html; charset=utf-8`.
10. THE Despliegue SHALL documentar en `infra/terraform/README.md` que el Sitio_Estático es accesible públicamente por cualquier persona con la URL, sin autenticación, y que no debe contener credenciales, datos personales ni datos no destinados a publicación.
11. WHEN se ejecuta el Despliegue, THE Despliegue SHALL mostrar la salida de `terraform plan` y aplicar cambios en la cuenta AWS solo después de una confirmación explícita del operador; IF el operador no confirma, THEN THE Despliegue SHALL terminar sin aplicar cambios ni subir archivos.
12. IF las credenciales del perfil AWS configurado no son válidas o han expirado, THEN THE Despliegue SHALL terminar con un código de salida distinto de cero y un mensaje que nombre el perfil antes de ejecutar `terraform apply` o de subir cualquier archivo, sin dejar cambios parciales en el bucket ni en la distribución.
13. THE Despliegue SHALL ubicar los recursos y outputs Terraform nuevos del Sitio_Estático en el archivo nuevo `infra/terraform/site.tf`, limitando los cambios en archivos compartidos a la lista de recursos de la política del bucket en `infra/terraform/s3.tf` y a un único comportamiento de caché ordenado en `infra/terraform/cloudfront.tf`.
14. THE Despliegue SHALL coexistir con `infra/terraform/sagemaker.tf` dejando ese archivo sin modificaciones, de modo que `terraform validate` termine con código de salida cero con ambos archivos presentes.

### Requisito 9: Pruebas y puerta de calidad

**Historia de Usuario:** Como integrante del equipo, quiero pruebas automáticas que no descarguen datos y una puerta de calidad, para detectar fallas antes del PR.

#### Criterios de Aceptación

1. WHEN se ejecuta `make check` en la Rama_Integración, THE Puerta_Calidad SHALL ejecutar ruff check, ruff format --check, pyright y unittest sobre `scripts` y `tests`, en ese orden, y terminar con código de salida cero cuando las cuatro herramientas terminan sin errores.
2. THE Puerta_Calidad SHALL ejecutar las pruebas del Adaptador, el Ejecutor_Inferencia, el Generador_Sitio, el Motor_Alertas y la Bitácora_Progreso usando únicamente datos sintéticos generados en memoria o en directorios temporales que se eliminan al terminar cada prueba, sin leer ni modificar `data/`, `docs/logs/progreso.json` ni otros archivos versionados del repositorio.
3. THE Puerta_Calidad SHALL incluir al menos una prueba de error por cada una de estas entradas incompletas, verificando el comportamiento definido en el requisito correspondiente: día GOES con al menos una hora UTC sin escenas (severidad `advertencia` y solo horas disponibles, Requisito 4.7), variable ERA5 con fracción de NaN mayor que 0,05 (severidad `error` y sin índices ERA5, Requisito 4.8), Tabla_Inferencia sin al menos una columna clave (código de salida distinto de cero y lista de columnas faltantes, Requisito 5.6) y configuración de alertas con umbral fuera de [0, 100] o geometría inválida (código de salida distinto de cero sin evaluar predicciones, Requisito 7.10).
4. THE Puerta_Calidad SHALL incluir una prueba de extremo a extremo sintética que recorra Adaptador → Ejecutor_Inferencia → Generador_Sitio → Motor_Alertas con el Modelo_Sustituto y el Destino_Alerta `archivo`, y que verifique la existencia de `index.html` en el Sitio_Estático y al menos una línea JSON de Alerta en el archivo de destino cuando los datos sintéticos superan el umbral configurado.
5. THE Puerta_Calidad SHALL incluir pruebas basadas en propiedades para los criterios 3.5, 4.14, 4.15, 5.8, 5.9, 6.12, 7.11 y 7.12, cada una evaluada sobre al menos 100 casos generados aleatoriamente con una semilla fija registrada en la prueba, de modo que una falla se reproduzca con la misma semilla.
6. THE Puerta_Calidad SHALL verificar, para cada script bajo `scripts/<área>/`, que el script expone una función `main()` que usa `argparse` y que la invocación con `--help` termina con código de salida cero.
7. WHEN se completa una tarea de implementación, THE Bitácora_Progreso SHALL recibir una Entrada_Bitácora con `estado` `hecho` si la Puerta_Calidad terminó con código cero o `bloqueado` en caso contrario, y con `notas` que indiquen el resultado de la Puerta_Calidad y los modos de falla revisados.
8. IF alguna de las herramientas de la Puerta_Calidad reporta al menos un error o una prueba falla, THEN THE Puerta_Calidad SHALL terminar con código de salida distinto de cero e indicar en la salida el nombre de la herramienta o de la prueba que falló.
9. WHILE se ejecuta la Puerta_Calidad sin conexión de red y sin credenciales AWS configuradas, THE Puerta_Calidad SHALL completar todas las pruebas con el mismo resultado que con conexión, sin realizar solicitudes a S3, SNS ni otros servicios externos.
10. THE Puerta_Calidad SHALL completar la ejecución de todas las pruebas de unittest en un máximo de 300 segundos en un equipo de desarrollo del equipo.
11. THE Puerta_Calidad SHALL incluir pruebas de contrato sin acceso a red que verifiquen que `scripts/model/sm_job/inference.py` expone `model_fn`, `predict_fn`, `output_fn`, `OUTPUT_COLUMNS` y `MissingColumnsError`, y IF falta alguno de esos nombres, THEN THE Puerta_Calidad SHALL fallar con un mensaje que nombre cada símbolo faltante.
12. IF `OUTPUT_COLUMNS` de `scripts/model/sm_job/inference.py` difiere de la secuencia `probability,date,hour_utc,latitude,longitude,config`, THEN THE Puerta_Calidad SHALL fallar con un mensaje que muestre la secuencia esperada y la secuencia encontrada.
13. IF `table.ERA5_FEATURES` no contiene `cape` o no contiene `shear_06`, THEN THE Puerta_Calidad SHALL fallar con un mensaje que nombre cada variable faltante.
14. IF `build_table.py` no acepta la opción `--stage infer`, THEN THE Puerta_Calidad SHALL fallar con un mensaje que indique que la opción `--stage infer` no está disponible.
15. THE Adaptador SHALL declarar en un único módulo de constantes los prefijos de ruta del Lago_Datos, los patrones de nombre de archivo, los nombres de variables y coordenadas y los 6 niveles de presión que usa, y IF alguna de esas constantes diverge de las expectativas derivadas de `docs/DATOS_AWS.md` de la rama `intentos-nico` codificadas en la prueba de contrato, THEN THE Puerta_Calidad SHALL fallar con un mensaje que nombre cada constante divergente, su valor esperado y su valor encontrado.
16. THE Puerta_Calidad SHALL ejecutar `tests/test_docs.py` y terminar con código de salida cero solo cuando `tests/test_docs.py` pasa, incluida la verificación de que `README.md` enlaza a `docs/modelo_predictor.md`.
