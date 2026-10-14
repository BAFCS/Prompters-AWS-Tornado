# Requirements Document

## Introduction

El proyecto *aws-mesocyclonic* busca anticipar qué tormentas del centro-sur de Chile desarrollan un mesociclón. Chile no tiene una red de radares Doppler, así que sin radar un tornado solo existe si alguien lo ve y lo reporta. Además, los modelos de Estados Unidos fallan aquí: las tormentas chilenas tienen poca energía (CAPE baja), cizalladura fuerte en altura y rotan en sentido contrario (hemisferio sur). Por eso el proyecto combina el catálogo de tornados y trombas (`data/tornados_chile.xlsx`, 102 eventos), la línea de costa (`data/coast.zip`), los recortes ERA5 y GOES en NetCDF (`data/crops/<región>/`) y las figuras de `figs/`.

Hoy el visor es una aplicación Streamlit (`scripts/viewer/viewer.py`) que se ejecuta en un servidor Python, lee los archivos desde el disco local (`viewer_app/data.py`, con caché por fecha de modificación) y solo se abre en `localhost` o por un túnel de Session Manager en una EC2. Esta funcionalidad publica los datos y el visor en AWS para que cualquier persona los consulte desde internet, con toda la infraestructura definida como código en AWS CDK.

**Decisión abierta que debe resolver el diseño.** La arquitectura sugerida (S3 para el frontend, una capa intermedia con API Gateway y funciones Lambda que sirven datos desde S3) choca con el visor actual: Streamlit renderiza en el servidor y no se puede alojar como sitio estático en S3. El diseño debe elegir y justificar una de estas opciones, o una combinación:

- **Opción A, frontend estático**: un sitio nuevo (HTML/JS) en S3 detrás de CloudFront, que pide los datos a una API (API Gateway + Lambda) que lee desde S3. Requiere reescribir la interfaz del visor.
- **Opción B, Streamlit en contenedor**: la imagen del `Dockerfile` existente desplegada en un servicio de contenedores (por ejemplo ECS Fargate o App Runner) detrás de CloudFront, leyendo los datos desde S3. Conserva el visor, pero mantiene un servidor siempre encendido.

Los requisitos se escriben de forma que valgan para ambas opciones; los que solo aplican a una se marcan con la cláusula WHERE correspondiente.

## Glossary

- **Plataforma_Nube**: el conjunto de recursos de AWS que publica los datos y el visor de este repositorio.
- **App_CDK**: la aplicación AWS CDK versionada en el repositorio que define todos los recursos de la Plataforma_Nube.
- **Bucket_Datos**: el bucket S3 privado que guarda el catálogo, la costa, los recortes NetCDF y los productos derivados que consume el visor.
- **Bucket_Frontend**: el bucket S3 privado que guarda los archivos estáticos del frontend (solo en la Opción A).
- **CDN**: la distribución de Amazon CloudFront que es el único punto de entrada público de la Plataforma_Nube.
- **API_Datos**: la capa intermedia (API Gateway y funciones Lambda) que responde consultas de datos leyendo el Bucket_Datos.
- **Servicio_Visor**: el servicio de contenedores que ejecuta el visor Streamlit existente (solo en la Opción B).
- **Frontend_Publico**: la interfaz web que ve el usuario final, sea el sitio estático (Opción A) o el Servicio_Visor (Opción B).
- **Script_Carga**: el script de línea de comandos del repositorio que sube el contenido de `data/` y `figs/` al Bucket_Datos.
- **Catálogo**: la hoja `Final_Table` de `data/tornados_chile.xlsx` (Bastías-Curivil et al., CC BY 4.0).
- **Día_Disponible**: una fecha de una región para la que existe al menos un archivo ERA5 (`era5_pl`, `era5_sfc`, `era5_indices`) o GOES (`goes_latlon`) en el Bucket_Datos.
- **Visitante**: cualquier persona en internet que abre el Frontend_Publico sin identificarse.
- **Mantenedor**: la persona del proyecto con credenciales de AWS que despliega la App_CDK y ejecuta el Script_Carga.
- **Opción_A**: la variante de arquitectura con frontend estático en S3 y API_Datos.
- **Opción_B**: la variante de arquitectura con el visor Streamlit en el Servicio_Visor.

## Requirements

### Requisito 1: Infraestructura reproducible con AWS CDK

**User Story:** Como Mantenedor, quiero desplegar toda la infraestructura con un solo comando de CDK, para poder recrearla, actualizarla o eliminarla sin pasos manuales en la consola.

#### Acceptance Criteria

1. THE App_CDK SHALL definir en código todos los recursos de AWS de la Plataforma_Nube, incluidos el Bucket_Datos, el Bucket_Frontend (en la Opción_A), la CDN, la API_Datos (en la Opción_A) o el Servicio_Visor (en la Opción_B), los roles IAM, los grupos de logs, las alarmas y el presupuesto, de modo que ningún recurso de la Plataforma_Nube exista fuera de las pilas de la App_CDK.
2. WHEN el Mantenedor ejecuta `cdk deploy` con credenciales válidas sobre una cuenta y región con bootstrap de CDK, THE App_CDK SHALL crear o actualizar la Plataforma_Nube completa, terminar con código de salida cero y entregar como salida de la pila la URL HTTPS de la CDN, sin pasos manuales adicionales en la consola de AWS.
3. WHEN el Mantenedor ejecuta `cdk synth` con todos los parámetros de contexto requeridos, THE App_CDK SHALL producir las plantillas de CloudFormation, terminar con código de salida cero y no referenciar recursos que no estén definidos en la App_CDK, salvo los recursos de bootstrap de CDK.
4. THE App_CDK SHALL recibir la cuenta, la región de despliegue, el nombre del entorno y la marca de entorno productivo como parámetros de contexto o variables de entorno, sin identificadores de cuenta escritos en el código.
5. THE App_CDK SHALL etiquetar cada recurso que admita etiquetas con una etiqueta de proyecto cuyo valor es `aws-mesocyclonic` y una etiqueta de entorno cuyo valor es el nombre del entorno recibido como parámetro.
6. WHEN el Mantenedor ejecuta `cdk destroy` sobre un entorno sin la marca de entorno productivo, THE App_CDK SHALL eliminar todos los recursos de ese entorno, incluidos el Bucket_Datos y el Bucket_Frontend con todos sus objetos y versiones de objetos, y terminar con código de salida cero sin pasos manuales previos de vaciado.
7. WHERE el entorno tiene la marca de entorno productivo, THE App_CDK SHALL conservar el Bucket_Datos y todos sus objetos y versiones al eliminar la pila.
8. THE App_CDK SHALL incluir pruebas automáticas de las plantillas sintetizadas, ejecutadas por `make check`, que fallen si algún bucket no tiene activadas las cuatro opciones de S3 Block Public Access, si algún bucket no tiene cifrado en reposo, o si el rol de la API_Datos o del Servicio_Visor tiene sobre el Bucket_Datos alguna acción distinta de `s3:GetObject` y `s3:ListBucket`.
9. IF falta un parámetro requerido (región de despliegue o nombre del entorno) o tiene un valor vacío, THEN THE App_CDK SHALL detener `cdk synth` y `cdk deploy` sin generar plantillas ni crear recursos, terminar con código de salida distinto de cero y mostrar un mensaje en español que nombre el parámetro faltante.
10. IF `cdk deploy` falla durante la creación o actualización de un recurso, THEN THE App_CDK SHALL dejar que CloudFormation revierta la pila al último estado desplegado con éxito, terminar con código de salida distinto de cero y conservar los objetos existentes en el Bucket_Datos.

### Requisito 2: Almacenamiento de datos en S3

**User Story:** Como Mantenedor, quiero que los datos del repositorio vivan en S3, para que la Plataforma_Nube los sirva sin depender del disco de una máquina.

#### Acceptance Criteria

1. THE Bucket_Datos SHALL guardar cada archivo bajo una clave igual a su ruta relativa a la raíz del repositorio, con los prefijos `data/` y `figs/` y los mismos nombres de archivo, de modo que existan las claves `data/tornados_chile.xlsx`, `data/coast.zip`, `data/crops/<región>/era5_pl/era5_pl_AAAAMMDD.nc`, `data/crops/<región>/era5_sfc/era5_sfc_AAAAMMDD.nc`, `data/crops/<región>/era5_indices/era5_idx_AAAAMMDD.nc`, `data/crops/<región>/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` y `figs/<nombre>.png`.
2. THE Bucket_Datos SHALL tener activadas las cuatro opciones de S3 Block Public Access (bloquear ACL públicas nuevas, ignorar ACL públicas existentes, bloquear políticas de bucket públicas nuevas y restringir el acceso público por políticas existentes).
3. IF una solicitud anónima (sin credenciales de AWS ni firma de Origin Access Control de la CDN) pide leer, listar o escribir un objeto del Bucket_Datos, THEN THE Bucket_Datos SHALL rechazar la solicitud con una respuesta de acceso denegado, sin devolver el contenido ni la lista de objetos.
4. THE Bucket_Datos SHALL tener activado el cifrado del lado del servidor por defecto, de modo que el 100 % de los objetos guardados queden cifrados en reposo, incluidos los que se suben sin indicar cifrado.
5. IF una solicitud al Bucket_Datos no usa TLS (HTTP sin cifrar), THEN THE Bucket_Datos SHALL rechazarla con una respuesta de acceso denegado mediante una política de bucket que exija conexiones seguras, sin leer ni modificar ningún objeto.
6. THE Bucket_Datos SHALL tener el versionado de objetos activado y SHALL eliminar las versiones no actuales tras un número configurable de días, por defecto 30 días.
7. THE App_CDK SHALL crear un Bucket_Datos distinto por cada nombre de entorno y SHALL publicar el nombre de ese Bucket_Datos como salida de la pila, para que el Script_Carga lo identifique a partir del nombre de entorno.

### Requisito 3: Carga de datos al Bucket_Datos

**User Story:** Como Mantenedor, quiero subir los datos locales con un comando, para publicar días nuevos sin tocar la infraestructura.

#### Acceptance Criteria

1. WHEN el Mantenedor ejecuta el Script_Carga con un nombre de entorno y sin las opciones `--start`, `--end` ni `--region`, THE Script_Carga SHALL subir al Bucket_Datos de ese entorno el Catálogo (`tornados_chile.xlsx`), `coast.zip`, todos los archivos NetCDF de `data/crops/` de todas las regiones y todas las figuras de `figs/`, cada uno con una clave igual a su ruta relativa dentro de `data/` o `figs/` según la estructura del Requisito 2.1.
2. WHEN un archivo local tiene el mismo tamaño en bytes y la misma suma de verificación de contenido que el objeto con la misma clave en el Bucket_Datos, y el Mantenedor no pasó la opción `--force`, THE Script_Carga SHALL omitir la subida de ese archivo y contarlo como omitido.
3. WHEN el Mantenedor ejecuta el Script_Carga con las opciones `--start`, `--end` y `--region` de `common` (fechas UTC en formato AAAA-MM-DD, ambas inclusive, con `--end` igual a `--start` si se omite), THE Script_Carga SHALL subir de `data/crops/` solo los archivos de esa región cuya fecha, tomada del nombre del archivo (`AAAAMMDD`) o de la carpeta `goes_latlon/<AAAAMMDD>/`, está dentro del intervalo, y SHALL tratar el Catálogo, `coast.zip` y las figuras de `figs/` con la regla del criterio 2.
4. WHEN el Script_Carga se ejecuta dos veces seguidas sin `--force` sobre los mismos archivos locales, THE Script_Carga SHALL subir 0 archivos en la segunda ejecución, y THE Bucket_Datos SHALL quedar con el mismo conjunto de claves y contenidos que tras la primera ejecución, sin que el Script_Carga elimine objetos del Bucket_Datos que no existen en el disco local (idempotencia).
5. IF la subida de un archivo falla por un error de red o de permisos después de 5 intentos con esperas de 2, 4, 8 y 16 segundos entre intentos, THEN THE Script_Carga SHALL informar la ruta del archivo afectado y el motivo del fallo, continuar con los archivos restantes, conservar en el Bucket_Datos los objetos ya subidos sin dejar objetos con contenido parcial, y terminar con código de salida distinto de cero.
6. IF el directorio `data/` no contiene archivos que calcen con las opciones dadas, THEN THE Script_Carga SHALL informar que no hay nada que subir, no hacer ninguna escritura en el Bucket_Datos y terminar con código de salida cero.
7. THE Script_Carga SHALL seguir las convenciones de `scripts/pipeline/` descritas en `AGENTS.md`: `main()` con `argparse`, docstrings y mensajes en español y opción `--force` para volver a subir todos los archivos seleccionados aunque cumplan la regla del criterio 2.
8. IF el nombre de entorno no corresponde a un Bucket_Datos desplegado, o las credenciales de AWS del Mantenedor faltan o no tienen permiso de escritura sobre ese bucket, THEN THE Script_Carga SHALL informar en español la causa, no subir ningún archivo y terminar con código de salida distinto de cero.
9. IF `--start` o `--end` no tienen el formato AAAA-MM-DD, `--end` es anterior a `--start`, o `--region` no es una región de `common.REGIONS` ni viene acompañada de `--bbox`, THEN THE Script_Carga SHALL informar en español el parámetro inválido, no subir ningún archivo y terminar con código de salida distinto de cero.
10. WHEN el Script_Carga termina, THE Script_Carga SHALL mostrar un resumen con la cantidad de archivos subidos, omitidos y fallidos, cuya suma es igual a la cantidad de archivos seleccionados.

### Requisito 4: Acceso público de solo lectura

**User Story:** Como Visitante, quiero abrir el visor desde cualquier navegador sin crear una cuenta, para explorar los tornados y las tormentas de Chile.

#### Acceptance Criteria

1. THE CDN SHALL publicar el Frontend_Publico en la URL HTTPS que entrega `cdk deploy` como salida de la pila, y SHALL responder a una solicitud GET a esa URL sin credenciales, cookies ni cabeceras de autenticación con la página de inicio del Frontend_Publico.
2. WHEN un Visitante solicita una URL de la CDN por HTTP, THE CDN SHALL responder con una redirección a la misma URL por HTTPS, conservando la ruta y los parámetros de consulta originales.
3. IF un Visitante envía una solicitud directa al Bucket_Datos o al Bucket_Frontend sin pasar por la CDN, THEN THE Plataforma_Nube SHALL rechazar la solicitud con un error de acceso denegado y sin entregar el contenido de ningún objeto.
4. THE Plataforma_Nube SHALL ofrecer a los Visitantes solo operaciones de lectura: los métodos GET, HEAD y OPTIONS en la API_Datos y, en el Servicio_Visor, solo interacciones que consultan datos sin crear, modificar ni eliminar objetos del Bucket_Datos o del Bucket_Frontend.
5. IF un Visitante envía una solicitud de escritura (PUT, POST, DELETE o PATCH) a la API_Datos o a un bucket a través de la CDN, THEN THE Plataforma_Nube SHALL rechazar la solicitud con un código HTTP 403 o 405 y dejar sin cambios todos los objetos del Bucket_Datos y del Bucket_Frontend.
6. THE documentación del despliegue SHALL declarar que la ausencia de autenticación para lectura es intencional, porque los datos son públicos (catálogo CC BY 4.0, ERA5 y GOES abiertos).
7. THE Frontend_Publico SHALL mostrar en todas sus páginas la atribución del Catálogo con los autores (Bastías-Curivil et al.), el DOI 10.6084/m9.figshare.25119566 como enlace y la licencia CC BY 4.0.
8. IF un Visitante envía una solicitud directa a la API_Datos o al Servicio_Visor sin pasar por la CDN, THEN THE Plataforma_Nube SHALL rechazar la solicitud con un error de acceso denegado y sin entregar datos.
9. IF el origen de la CDN (Bucket_Frontend, API_Datos o Servicio_Visor) no responde o responde con un error 5xx, THEN THE CDN SHALL entregar al Visitante una página de error en español que indique que el servicio no está disponible temporalmente.

### Requisito 5: API de datos (Opción A)

**User Story:** Como desarrollador del frontend estático, quiero una API que entregue los datos ya listos para dibujar, para no descargar archivos NetCDF completos en el navegador.

#### Acceptance Criteria

1. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita la lista de regiones, THE API_Datos SHALL responder con un código HTTP 200 y una lista JSON con el nombre de cada región que tiene al menos un objeto bajo `crops/<región>/` en el Bucket_Datos, sin duplicados y ordenada alfabéticamente; si no hay regiones, la lista SHALL estar vacía.
2. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita los días de una región existente, THE API_Datos SHALL responder con un código HTTP 200 y una lista JSON con cada Día_Disponible de esa región, en orden cronológico ascendente y sin fechas repetidas, en la que cada día indica con un valor verdadero o falso la presencia de cada uno de los productos `era5_pl`, `era5_sfc`, `era5_indices` y `goes_latlon`.
3. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita el Catálogo, THE API_Datos SHALL responder con un código HTTP 200 y un JSON con todos los eventos de la hoja `Final_Table` (102 en la versión actual del Catálogo), cada uno con fecha (`AAAA-MM-DD`), latitud y longitud en grados decimales, hora UTC (`HH:MM` o valor nulo si no se puede leer), tipo (tornado, tromba, ambos o sin clasificación), EF (o valor nulo) y confianza del registro (o valor nulo).
4. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita los eventos de una fecha válida, THE API_Datos SHALL responder con un código HTTP 200 y solo los eventos del Catálogo de esa fecha, ordenados por hora UTC ascendente con los eventos sin hora al final; si la fecha no tiene eventos, la respuesta SHALL ser una lista vacía con código HTTP 200.
5. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita un producto (con la misma clave que usa `viewer_app/products.py`, por ejemplo `idx:srh_01`, `goes:C13` o `rgb:airmass`) de un Día_Disponible, una hora y una región, THE API_Datos SHALL responder con un código HTTP 200 y la grilla del producto recortada a la región, sus vectores de latitud y longitud, sus unidades y la hora efectiva del dato, que es la hora ERA5 pedida o la imagen GOES más cercana a la hora pedida (la misma que elige `viewer_app/data.py`), en una respuesta de 6 MB como máximo.
6. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante solicita la costa de una región, THE API_Datos SHALL responder con un código HTTP 200 y las líneas de costa de `coast.zip` recortadas a los límites de la región y simplificadas con una tolerancia de 0,005°, de modo que ningún vértice quede fuera de los límites de la región.
7. WHERE la Plataforma_Nube usa la Opción_A, IF un Visitante solicita una región, fecha, hora o producto con formato válido que no existe en el Bucket_Datos, THEN THE API_Datos SHALL responder con un código HTTP 404 y un mensaje en español que nombre el parámetro no encontrado y su valor.
8. WHERE la Plataforma_Nube usa la Opción_A, IF un Visitante envía un parámetro con formato inválido (fecha distinta de `AAAAMMDD` o que no es una fecha de calendario, hora fuera de `00:00` a `23:59`, región con caracteres distintos de minúsculas, dígitos y guiones o de más de 64 caracteres, o clave de producto sin la forma `<prefijo>:<variable>`), THEN THE API_Datos SHALL responder con un código HTTP 400 y un mensaje en español que nombre el parámetro y describa el formato esperado, sin leer el Bucket_Datos.
9. WHERE la Plataforma_Nube usa la Opción_A, THE API_Datos SHALL calcular los valores del Catálogo (coordenadas, hora UTC, tipo, EF y confianza) con las mismas reglas que `viewer_app/data.py` (`coordinate`, `utc_hour` y `kind_of`), de modo que para cada fila del Catálogo ambos produzcan el mismo resultado, con coordenadas iguales hasta 6 decimales.
10. WHERE la Plataforma_Nube usa la Opción_A, FOR ALL respuestas JSON de la API_Datos, serializar la respuesta y volver a leerla SHALL producir datos equivalentes a los originales, con los valores faltantes (NaN de las grillas y celdas vacías del Catálogo) representados como nulo JSON y recuperados como faltantes (propiedad de ida y vuelta).
11. WHERE la Plataforma_Nube usa la Opción_A, THE API_Datos SHALL incluir en cada respuesta con código HTTP 200 cabeceras de caché que permitan a la CDN guardarla entre 1 hora y 24 horas, e incluir en cada respuesta con código HTTP 4xx o 5xx cabeceras que limiten su caché en la CDN a 60 segundos como máximo.
12. WHERE la Plataforma_Nube usa la Opción_A, WHEN la CDN recibe una solicitud idéntica (misma ruta y mismos parámetros) a una respuesta exitosa vigente en su caché, THE CDN SHALL responder con esa respuesta guardada sin invocar la función Lambda.
13. WHERE la Plataforma_Nube usa la Opción_A, IF la API_Datos no puede leer el Bucket_Datos o falla al procesar un archivo NetCDF, THEN THE API_Datos SHALL responder con un código HTTP 5xx y un mensaje en español que indique que el dato no está disponible por un error interno, sin exponer rutas internas ni detalles de credenciales.
14. WHERE la Plataforma_Nube usa la Opción_A, WHEN la API_Datos procesa una solicitud que no está en la caché de la CDN, THE API_Datos SHALL completar la respuesta en un máximo de 10 segundos; IF el procesamiento supera 10 segundos, THEN THE API_Datos SHALL responder con un código HTTP 504.

### Requisito 6: Frontend estático (Opción A)

**User Story:** Como Visitante, quiero un sitio web que muestre el catálogo, el caso de estudio y los mapas, para entender el problema sin instalar nada.

#### Acceptance Criteria

1. WHERE la Plataforma_Nube usa la Opción_A, THE Bucket_Frontend SHALL guardar los archivos estáticos del Frontend_Publico y bloquear todo acceso público directo, de modo que una solicitud directa a un objeto del Bucket_Frontend sin pasar por la CDN sea rechazada.
2. WHERE la Plataforma_Nube usa la Opción_A, THE Frontend_Publico SHALL mostrar el contenido de las páginas Problema, Datos, Starter kit y Referencias cuando la API_Datos no tenga ningún Día_Disponible y cuando la API_Datos no responda, porque ese contenido no depende de respuestas de la API_Datos.
3. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante abre la página de mapas, THE Frontend_Publico SHALL mostrar un mapa con un marcador por cada evento del Catálogo que tenga latitud y longitud numéricas, junto con la línea de costa entregada por la API_Datos, y SHALL omitir del mapa los eventos sin coordenadas numéricas.
4. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante abre la página de mapas, THE Frontend_Publico SHALL ofrecer como opciones de selección solo las regiones entregadas por la API_Datos y, para la región elegida, solo sus Días_Disponibles en el orden por fecha que entrega la API_Datos.
5. WHERE la Plataforma_Nube usa la Opción_A, WHEN un Visitante elige región, Día_Disponible y hora, THE Frontend_Publico SHALL pedir a la API_Datos los productos ERA5 y GOES disponibles para esa selección y mostrar cada producto con sus unidades y la hora UTC de la grilla.
6. WHERE la Plataforma_Nube usa la Opción_A, IF la API_Datos responde con un código de error (4xx o 5xx), no responde en 30 segundos o la solicitud falla por un error de red, THEN THE Frontend_Publico SHALL mostrar un mensaje en español que identifique el dato que no se pudo cargar (Catálogo, costa, regiones, días o producto), conservar la selección actual de región, día y hora, y seguir mostrando los demás datos ya cargados.
7. WHERE la Plataforma_Nube usa la Opción_A, IF la región elegida no tiene ningún Día_Disponible o el Día_Disponible elegido no tiene un producto para la hora elegida, THEN THE Frontend_Publico SHALL mostrar un mensaje en español que indique que no hay datos para esa selección, en lugar de un mapa vacío sin aviso.
8. WHERE la Plataforma_Nube usa la Opción_A, WHILE una solicitud a la API_Datos está en curso, THE Frontend_Publico SHALL mostrar un indicador de carga en la zona donde aparecerá el dato pedido.
9. WHERE la Plataforma_Nube usa la Opción_A, WHEN el Mantenedor ejecuta `cdk deploy` con archivos del frontend modificados, THE App_CDK SHALL subir los archivos al Bucket_Frontend e invalidar en la CDN todas las rutas del Frontend_Publico, de modo que una solicitud hecha después de terminar el despliegue reciba la versión nueva.

### Requisito 7: Visor Streamlit en contenedor (Opción B)

**User Story:** Como Mantenedor, quiero publicar el visor Streamlit existente sin reescribirlo, para conservar todas sus páginas y gráficos.

#### Acceptance Criteria

1. WHERE la Plataforma_Nube usa la Opción_B, THE Servicio_Visor SHALL ejecutar la imagen construida desde el `Dockerfile` del repositorio, con el visor escuchando en el puerto 8501 y sin incluir el contenido de `data/` dentro de la imagen.
2. WHERE la Plataforma_Nube usa la Opción_B, WHILE el Servicio_Visor tiene configurado un Bucket_Datos, THE Servicio_Visor SHALL leer el Catálogo, `coast.zip` y los recortes NetCDF desde el Bucket_Datos, sin leer archivos de `data/` del disco local del contenedor.
3. WHERE la Plataforma_Nube usa la Opción_B, WHEN el Script_Carga termina de subir al Bucket_Datos un Día_Disponible nuevo o una versión nueva de un objeto existente, THE Servicio_Visor SHALL mostrar ese día o ese contenido nuevo a un Visitante que recarga la página a más tardar 10 minutos después del fin de la carga, sin volver a desplegar ni reiniciar el contenedor.
4. WHERE la Plataforma_Nube usa la Opción_B, THE CDN SHALL reenviar al Servicio_Visor las conexiones WebSocket que usa Streamlit sin guardarlas en caché, de modo que una sesión de Visitante con interacción al menos cada 60 segundos permanezca conectada durante al menos 30 minutos.
5. WHERE la Plataforma_Nube usa la Opción_B, WHEN la ruta `/_stcore/health` del Servicio_Visor no responde con éxito en 5 segundos en 3 comprobaciones seguidas, realizadas cada 30 segundos, THE Servicio_Visor SHALL reemplazar la instancia del contenedor por una instancia nueva que responda con éxito en `/_stcore/health` en un plazo máximo de 5 minutos.
6. WHERE la Plataforma_Nube usa la Opción_B, IF el visor se ejecuta sin un Bucket_Datos configurado, THEN THE Servicio_Visor SHALL leer los datos desde `data/` en el disco local igual que antes de esta funcionalidad, de modo que `make viewer` y `docker compose up` sigan mostrando las mismas páginas y Días_Disponibles que con los mismos archivos locales.
7. WHERE la Plataforma_Nube usa la Opción_B, IF el Bucket_Datos no responde o un objeto pedido no existe en él, THEN THE Servicio_Visor SHALL mostrar un mensaje en español que identifique el dato que no se pudo cargar y SHALL seguir mostrando las páginas Problema, Datos, Starter kit y Referencias sin terminar el proceso del contenedor.
8. WHERE la Plataforma_Nube usa la Opción_B, WHILE la pila de la Plataforma_Nube está desplegada, THE Servicio_Visor SHALL mantener al menos 1 instancia del contenedor en ejecución y respondiendo con éxito en `/_stcore/health`.

### Requisito 8: Seguridad y mínimo privilegio

**User Story:** Como Mantenedor, quiero que cada componente tenga solo los permisos que necesita, para que un fallo en una pieza no exponga ni modifique los datos.

#### Acceptance Criteria

1. THE App_CDK SHALL otorgar a las funciones de la API_Datos y al Servicio_Visor sobre el Bucket_Datos solo los permisos `s3:GetObject` y `s3:ListBucket`, sin ninguna acción de escritura, eliminación ni cambio de políticas (por ejemplo `s3:PutObject`, `s3:DeleteObject` o `s3:PutBucketPolicy`).
2. THE App_CDK SHALL otorgar permisos de escritura sobre el Bucket_Datos (`s3:PutObject` y las acciones que el Script_Carga necesita) solo al rol que usa el Mantenedor para el Script_Carga, y a ningún otro rol, función, servicio ni a la CDN.
3. THE CDN SHALL acceder al Bucket_Datos y al Bucket_Frontend mediante Origin Access Control, y la política de cada bucket SHALL permitir lectura a CloudFront solo cuando la solicitud venga de la distribución de la CDN del mismo entorno.
4. THE App_CDK SHALL limitar las solicitudes por IP a la API_Datos o al Servicio_Visor mediante AWS WAF o throttling de API Gateway, con un máximo configurable por parámetro de contexto entre 100 y 20.000 solicitudes por ventana de 5 minutos, y un valor por defecto de 1000 solicitudes cada 5 minutos.
5. IF una IP supera el límite de solicitudes configurado dentro de una ventana de 5 minutos, THEN THE Plataforma_Nube SHALL responder con un código HTTP 429 a cada solicitud nueva de esa IP mientras su conteo de los últimos 5 minutos siga sobre el límite, y SHALL seguir atendiendo con normalidad a las demás IP.
6. THE App_CDK SHALL dar credenciales a la API_Datos y al Servicio_Visor solo mediante roles IAM, y ni el código del repositorio ni las plantillas sintetizadas SHALL contener claves de acceso de AWS, contraseñas ni tokens.
7. THE CDN SHALL añadir a todas las respuestas, incluidas las de error, las cabeceras `Strict-Transport-Security` con `max-age` de al menos 31.536.000 segundos, `X-Content-Type-Options: nosniff` y `X-Frame-Options` con valor `DENY` o `SAMEORIGIN`.
8. IF una función de la API_Datos o el Servicio_Visor intenta escribir, sobrescribir o eliminar un objeto del Bucket_Datos, THEN THE Bucket_Datos SHALL rechazar la operación con un error de acceso denegado y dejar el objeto sin cambios.
9. IF el límite de solicitudes por IP configurado queda fuera del rango de 100 a 20.000 o no es un número entero, THEN THE App_CDK SHALL fallar en `cdk synth` con un mensaje en español que indique el rango válido, sin generar plantillas.

### Requisito 9: Costos acotados

**User Story:** Como Mantenedor de un proyecto abierto, quiero que la Plataforma_Nube tenga un costo previsible, para que el acceso público no genere facturas inesperadas.

#### Acceptance Criteria

1. THE App_CDK SHALL crear un presupuesto de AWS Budgets de costo real mensual, en dólares estadounidenses, con un monto configurable entre 1 y 1000 USD (por defecto 20 USD), que avise al correo del Mantenedor recibido como parámetro de contexto o variable de entorno al llegar al 80 % y al 100 % del monto. El presupuesto SHALL cubrir todos los recursos que llevan la etiqueta del proyecto y del entorno.
2. THE App_CDK SHALL fijar la retención de cada grupo de logs de CloudWatch que crea la Plataforma_Nube en un valor configurable de días, que debe ser uno de los valores de retención que acepta CloudWatch Logs entre 1 y 365 días (por defecto 14 días), sin que ningún grupo de logs quede con retención indefinida.
3. WHERE la Plataforma_Nube usa la Opción_A, THE App_CDK SHALL fijar en cada función Lambda de la API_Datos un límite de concurrencia reservada configurable entre 1 y 100 ejecuciones simultáneas (por defecto 10).
4. WHERE la Plataforma_Nube usa la Opción_B, THE App_CDK SHALL fijar un número mínimo de 1 instancia y un número máximo configurable de instancias del Servicio_Visor entre 1 y 10 (por defecto 2).
5. THE CDN SHALL usar la clase de precio de CloudFront que incluye ubicaciones de borde en Sudamérica y Norteamérica. La plantilla sintetizada debe declarar esa clase de precio de forma explícita.
6. THE documentación del despliegue SHALL incluir una estimación del costo mensual en USD para cada opción desplegada (Opción_A u Opción_B). La estimación SHALL indicar de forma explícita estos supuestos: número de Visitantes al mes, solicitudes al mes, GB transferidos por la CDN al mes, GB guardados en el Bucket_Datos y la región de despliegue, y SHALL desglosar el costo por servicio de AWS.
7. IF el monto del presupuesto, la retención de logs, el límite de concurrencia o el número máximo de instancias está fuera de su rango permitido, o si falta el correo del Mantenedor, THEN THE App_CDK SHALL fallar en `cdk synth` y en `cdk deploy`, sin crear ni modificar recursos, con un mensaje en español que nombre el parámetro inválido y su rango permitido.
8. WHERE la Plataforma_Nube usa la Opción_A, IF las solicitudes simultáneas superan el límite de concurrencia reservada de una función de la API_Datos, THEN THE API_Datos SHALL rechazar las solicitudes que excedan el límite con un código HTTP 429 o 503, sin aumentar la concurrencia por encima del límite configurado.
9. WHERE la Plataforma_Nube usa la Opción_B, WHILE el Servicio_Visor tiene en ejecución el número máximo configurado de instancias, THE Servicio_Visor SHALL dejar de crear instancias nuevas aunque la demanda siga subiendo.

### Requisito 10: Observabilidad

**User Story:** Como Mantenedor, quiero saber si la Plataforma_Nube está caída o con errores, para corregirla antes de que los Visitantes lo noten.

#### Acceptance Criteria

1. THE API_Datos y THE Servicio_Visor SHALL escribir en CloudWatch Logs un registro por cada solicitud atendida y por cada error, con la marca de tiempo en UTC y, en el caso de los errores, un mensaje que identifique la operación que falló, con la retención definida en el Requisito 9.
2. IF la tasa de respuestas 5xx de la CDN supera el 5 % del total de solicitudes en un periodo de 5 minutos con al menos 1 solicitud, THEN THE Plataforma_Nube SHALL enviar un correo de alerta a la dirección del Mantenedor en un plazo máximo de 10 minutos desde el cierre de ese periodo.
3. WHERE la Plataforma_Nube usa la Opción_A, IF una función Lambda de la API_Datos registra al menos 1 error en cada uno de 3 periodos consecutivos de 5 minutos, THEN THE Plataforma_Nube SHALL enviar un correo de alerta a la dirección del Mantenedor que identifique la función afectada, en un plazo máximo de 10 minutos desde el cierre del tercer periodo.
4. WHERE la Plataforma_Nube usa la Opción_B, IF el Servicio_Visor no tiene ninguna instancia de contenedor en estado saludable durante 2 periodos consecutivos de 5 minutos, THEN THE Plataforma_Nube SHALL enviar un correo de alerta a la dirección del Mantenedor en un plazo máximo de 10 minutos desde el cierre del segundo periodo.
5. WHEN una alarma de los criterios 2, 3 o 4 vuelve a su estado normal tras haber notificado una alerta, THE Plataforma_Nube SHALL enviar un correo de recuperación a la dirección del Mantenedor que identifique la alarma resuelta.
6. THE App_CDK SHALL recibir la dirección de correo del Mantenedor para las alertas como parámetro de contexto o variable de entorno, sin valores fijos en el código, y SHALL fallar en `cdk synth` con un mensaje en español que indique el parámetro faltante si no se entrega.

### Requisito 11: Documentación y convenciones del repositorio

**User Story:** Como colaborador de la hackathon, quiero instrucciones claras para desplegar y actualizar la nube, para contribuir sin conocer CDK de antemano.

#### Acceptance Criteria

1. THE documentación del despliegue SHALL describir en español, en este orden y con el comando exacto de cada paso listo para copiar, los pasos para: (a) instalar CDK y sus requisitos indicando la versión mínima de cada herramienta, (b) configurar las credenciales de AWS del Mantenedor, (c) hacer bootstrap de la cuenta y la región, (d) desplegar con `cdk deploy`, (e) cargar datos con el Script_Carga, y (f) eliminar la Plataforma_Nube con `cdk destroy`, y SHALL estar enlazada desde `README.md`.
2. THE documentación del despliegue SHALL indicar el nombre de la salida de la pila que contiene la URL HTTPS pública del Frontend_Publico que entrega `cdk deploy`, y el comando para consultarla de nuevo después del despliegue.
3. THE comando `make check` SHALL ejecutar sobre el código de la App_CDK y del Script_Carga las mismas revisiones que sobre el código existente (`ruff check`, `ruff format --check`, `pyright` y las pruebas de `unittest`), en la misma ejecución que las revisiones y pruebas existentes.
4. THE App_CDK y THE Script_Carga SHALL seguir las convenciones de `AGENTS.md`: identificadores, módulos y flags de la CLI en inglés; documentación, docstrings, comentarios y mensajes al usuario en español; parámetros y retornos de toda función anotados; un docstring en cada módulo y función; y dependencias Python agregadas con `uv add` o `uv add --dev`, sin uso de `pip`.
5. THE repositorio SHALL mantener fuera del control de versiones, mediante `.gitignore`, el directorio `data/`, los formatos de datos ya ignorados (`*.nc`, `*.xlsx`, `*.parquet`, `*.zarr`), las salidas de `cdk synth` (`cdk.out/`) y las credenciales (`.env`, `.aws/`), de modo que tras ejecutar `cdk synth` y el Script_Carga el comando `git status` no muestre ninguno de esos archivos como nuevo ni modificado.
6. IF alguna revisión de estilo, de tipos o alguna prueba de la App_CDK o del Script_Carga falla, THEN THE comando `make check` SHALL terminar con código de salida distinto de cero e identificar en su salida la revisión o prueba que falló.
7. THE pruebas de la App_CDK y del Script_Carga que ejecuta `make check` SHALL completarse sin credenciales de AWS, sin acceso a red y sin archivos descargados en `data/`.
8. THE documentación del despliegue SHALL listar cada parámetro de contexto o variable de entorno que recibe la App_CDK (al menos cuenta, región, nombre del entorno, marca de entorno productivo, monto del presupuesto, correo de notificación, retención de logs, límite de solicitudes por IP y límite de concurrencia o de instancias), con su descripción en español, si es obligatorio y su valor por defecto cuando lo tenga.
