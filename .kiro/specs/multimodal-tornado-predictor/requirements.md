# Requirements Document

## Introduction

Esta funcionalidad define y construye el modelo predictor multimodal del proyecto de tormentas mesociclónicas en Chile. El modelo codifica las imágenes GOES-East en un espacio vectorial, une esos vectores con las variables derivadas de ERA5 y entrena, en Amazon SageMaker, un clasificador con estructura temporal que estima la probabilidad de que una celda-hora preceda a un tornado o tromba registrado.

La entrega tiene dos partes:

1. Un documento nuevo, `docs/modelo_predictor.md`, que describe el modelo, sus supuestos, sus riesgos y cómo se evalúa, en coherencia con `docs/mesociclones_chile.md` (fuente de verdad, en particular la sección 6).
2. El pipeline que ese documento describe: extracción de variables GOES diseñadas a mano, codificación de imágenes con Amazon Bedrock, construcción de la tabla multimodal con rezagos temporales, entrenamiento y evaluación en SageMaker, e inferencia.

El enfoque es incremental y comparativo. Primero se establece una referencia física (índices ERA5 + variables GOES diseñadas a mano, en XGBoost). Después se evalúan los embeddings de Bedrock como experimento, que solo se conserva si mejora el CSI bajo la misma validación dejar-un-evento-afuera. Un codificador autosupervisado propio queda documentado como trabajo futuro. La componente de serie de tiempo se modela con variables de rezago y tendencia (t−1 h, t−2 h, t−3 h) dentro del modelo de árboles, no con LSTM ni Transformer, por el número reducido de positivos (~102 eventos).

Convenciones del repositorio (AGENTS.md): documentación, docstrings y textos en español; identificadores, módulos, flags y rutas en inglés; dependencias con `uv add`; scripts con `argparse` y las opciones `--start`, `--end`, `--region` y `--force` de `common`; salidas en `data/...`; pruebas en `tests/` con `unittest` que no requieren datos descargados; `make check` debe pasar.

## Glossary

- **Documento_Predictor**: el archivo `docs/modelo_predictor.md` que describe el modelo predictor.
- **Documento_Fuente**: el archivo `docs/mesociclones_chile.md`, fuente de verdad del proyecto.
- **Catálogo**: la base «Tornados y Trombas en Chile» (figshare, hoja `Final_Table`), con ~102 eventos solo positivos.
- **Evento**: una fila del Catálogo con fecha, coordenadas y hora UTC conocidas.
- **Celda_Hora**: un punto de la grilla ERA5 de 0,25° en una hora UTC; es la unidad de ejemplo del modelo.
- **Ventana_GOES**: el recorte cuadrado de imagen GOES en grilla lat/lon (`goes_latlon`) centrado en una Celda_Hora.
- **Extractor_GOES**: el componente que calcula variables GOES diseñadas a mano a partir de una Ventana_GOES.
- **Variables_GOES**: temperatura de brillo mínima de la banda 13, tasa de enfriamiento del tope en 15–30 min, área bajo −60 °C y diferencia vapor de agua − ventana infrarroja (BT banda 8 − BT banda 13).
- **Compositor_RGB**: el componente que convierte una Ventana_GOES en una imagen RGB de 8 bits con una receta fija de tres canales o un compuesto (por ejemplo Airmass o Day Cloud Phase).
- **Codificador_Bedrock**: el componente que envía imágenes del Compositor_RGB a un modelo de embeddings de Amazon Bedrock y devuelve un vector.
- **Modelo_Embedding**: el modelo de Bedrock usado por el Codificador_Bedrock (Titan Multimodal Embeddings G1 por defecto; Cohere Embed v4 como alternativa).
- **Reductor**: el componente que proyecta los embeddings a pocas dimensiones (PCA de 8 a 16 componentes).
- **Constructor_Tabla**: el componente que arma la tabla positivo-no etiquetado (PU) multimodal, con una fila por Celda_Hora.
- **Variables_Rezago**: los valores de una variable en t−1 h, t−2 h y t−3 h y sus diferencias respecto de t.
- **Entrenador**: el componente que entrena y evalúa los modelos en SageMaker.
- **Validación_LOEO**: validación dejar-un-evento-afuera, donde todas las Celdas_Hora de un Evento quedan juntas en el conjunto de prueba.
- **Métricas**: POD (probabilidad de detección), FAR (proporción de falsas alarmas) y CSI (índice crítico de éxito), según la sección 6.2 del Documento_Fuente.
- **Configuración_Experimento**: la combinación de variables usada en una corrida: `baseline_era5` (solo índices ERA5), `physical` (ERA5 + Variables_GOES + Variables_Rezago) y `embeddings` (`physical` + embeddings reducidos).
- **Servicio_Inferencia**: el componente de SageMaker que devuelve probabilidades para Celdas_Hora nuevas.
- **Infraestructura**: los recursos de Terraform en `infra/terraform/` necesarios para SageMaker y Bedrock.

## Requirements

### Requisito 1: Documento del modelo predictor

**User Story:** Como integrante del equipo, quiero un documento en `docs/` que describa el modelo predictor, para entender qué se predice, con qué datos, cómo se evalúa y qué riesgos tiene.

#### Acceptance Criteria

1. THE Documento_Predictor SHALL existir en la ruta `docs/modelo_predictor.md` con todo el texto narrativo en español, y SHALL mantener en inglés solo los identificadores, módulos, flags, rutas y nombres de Configuración_Experimento, según las convenciones de AGENTS.md.
2. THE Documento_Predictor SHALL definir el objetivo de predicción como la probabilidad, entre 0 y 1, de que una Celda_Hora corresponda a un Evento registrado en un horizonte de 0 a 3 horas.
3. THE Documento_Predictor SHALL incluir una afirmación explícita de que detectar un mesociclón no equivale a predecir un tornado, y SHALL indicar que la etiqueta positiva proviene de los Eventos del Catálogo y no de detecciones de mesociclón.
4. THE Documento_Predictor SHALL describir las tres etapas del enfoque en este orden: (a) referencia física con las Configuraciones_Experimento `baseline_era5` y `physical`; (b) experimento con embeddings de Bedrock en la Configuración_Experimento `embeddings`, con el criterio de conservarlo solo si su CSI supera al de `physical` bajo la misma Validación_LOEO; y (c) codificador autosupervisado propio, rotulado como trabajo futuro sin implementación en esta entrega.
5. THE Documento_Predictor SHALL describir el planteamiento PU, la Validación_LOEO y las Métricas (POD, FAR y CSI, con la fórmula de cada una en función de aciertos, omisiones y falsas alarmas), y SHALL citar cada tema con el número de sección correspondiente (6.1, 6.2 o 6.3) y un enlace relativo al Documento_Fuente.
6. THE Documento_Predictor SHALL documentar, como cinco entradas separadas, los riesgos del uso de embeddings de Bedrock: cambio de dominio frente a temperatura de brillo calibrada, pérdida de calibración al convertir a RGB de 8 bits, desajuste de escala entre la celda ERA5 (~31 km, ~15 píxeles IR de 2 km) y la entrada mínima de 224 píxeles, naturaleza temporal de la señal del mesociclón y alta dimensión frente a pocos positivos; y SHALL indicar para cada entrada al menos una mitigación o la forma en que la Validación_LOEO la evalúa.
7. THE Documento_Predictor SHALL justificar el uso de Variables_Rezago (t−1 h, t−2 h y t−3 h y sus diferencias respecto de t) en un modelo de árboles en lugar de LSTM o Transformer, citando el número de positivos del Catálogo (~102 Eventos) con el mismo valor que declara el Documento_Fuente.
8. THE Documento_Predictor SHALL documentar las convenciones del hemisferio sur (SRH y STP negativos indican entorno favorable, rama *left-mover* para el movimiento de la tormenta), con referencia a la sección 2.6 del Documento_Fuente.
9. THE Documento_Predictor SHALL listar cada umbral HSLC chileno con su índice, valor numérico y unidad, con los mismos valores que la sección 3.2 del Documento_Fuente, y SHALL indicar que esos umbrales orientan la comparación y no son reglas de decisión del modelo.
10. THE Documento_Predictor SHALL declarar que el pipeline no aplica corrección de paralaje a las imágenes GOES y SHALL describir su consecuencia como un desplazamiento posible entre la posición aparente del tope nuboso y la Celda_Hora asociada.
11. THE Documento_Predictor SHALL incluir un diagrama en texto dentro del propio Markdown que muestre, en orden, el flujo desde S3 (ERA5 y GOES) por el Extractor_GOES, el Compositor_RGB, el Codificador_Bedrock, el Reductor, el Constructor_Tabla y el Entrenador hasta el Servicio_Inferencia, con cada componente como un nodo identificado por su nombre del glosario.
12. THE Documento_Predictor SHALL documentar, para cada componente del diagrama del flujo de datos, al menos un comando ejecutable desde la raíz del repositorio que incluya el script o destino de `make` y, cuando el script las admite, las opciones `--start`, `--end`, `--region` y `--force` con valores de ejemplo.
13. WHEN el Documento_Predictor se publica, THE README.md SHALL incluir un enlace relativo a `docs/modelo_predictor.md` que resuelva al archivo existente.
14. IF un valor numérico del Documento_Predictor (número de Eventos, umbrales HSLC, tamaño de celda ERA5 o resolución GOES) difiere del valor declarado en el Documento_Fuente, THEN THE Documento_Predictor SHALL adoptar el valor del Documento_Fuente como referencia.

### Requisito 2: Variables GOES diseñadas a mano

**User Story:** Como científico de datos, quiero variables GOES con significado físico por Celda_Hora, para tener una referencia interpretable antes de usar embeddings.

#### Acceptance Criteria

1. WHEN el Extractor_GOES recibe una Ventana_GOES, THE Extractor_GOES SHALL calcular la temperatura de brillo mínima de la banda 13 en kelvin sobre los píxeles válidos de esa banda, donde un píxel válido es aquel cuyo valor decodificado es finito y distinto del `_FillValue` del archivo.
2. WHEN el Extractor_GOES recibe una Ventana_GOES, THE Extractor_GOES SHALL calcular la fracción de píxeles válidos de la banda 13 con temperatura de brillo estrictamente menor que 213,15 K (−60 °C), con el número de píxeles válidos de la banda 13 como denominador.
3. WHEN el Extractor_GOES recibe una Ventana_GOES, THE Extractor_GOES SHALL calcular la máxima diferencia BT banda 8 − BT banda 13 en kelvin usando solo los píxeles válidos en ambas bandas a la vez.
4. WHEN el Extractor_GOES recibe dos Ventanas_GOES de la misma Celda_Hora con sellos de inicio de barrido separados por 15 a 30 minutos (ambos inclusive), THE Extractor_GOES SHALL calcular la tasa de enfriamiento como (BT mínima banda 13 anterior − BT mínima banda 13 posterior) × 15 / Δt en minutos, expresada en K/15 min, con valores positivos para un tope que se enfría.
5. THE Extractor_GOES SHALL decodificar los valores `int16` con `scale_factor` y `add_offset` antes de calcular cualquier variable, y SHALL tratar los valores iguales a `_FillValue` como píxeles sin dato antes de la decodificación.
6. IF una Ventana_GOES contiene menos del 50 % de píxeles válidos de la banda 13 respecto del total de píxeles de la ventana, THEN THE Extractor_GOES SHALL asignar NaN a todas las Variables_GOES de esa Celda_Hora y SHALL conservar la fila de esa Celda_Hora en la salida.
7. FOR ALL Ventanas_GOES con al menos un píxel válido, THE Extractor_GOES SHALL producir una temperatura de brillo mínima menor o igual que cada temperatura de brillo válida de la banda 13 de la ventana y una fracción bajo −60 °C en el intervalo cerrado [0, 1] (invariante).
8. FOR ALL Ventanas_GOES, la permutación de los píxeles de la ventana, aplicada por igual a las bandas 8 y 13, SHALL dejar sin cambios la temperatura de brillo mínima, la fracción bajo −60 °C y la máxima diferencia de bandas (invariante ante permutación).
9. THE Extractor_GOES SHALL ofrecer un script CLI en `scripts/model/` con las opciones `--start`, `--end`, `--region` y `--force`, que escribe en `data/` una tabla Parquet por día con una fila por Celda_Hora que contiene latitud, longitud, hora UTC y las cuatro Variables_GOES, y que omite los días cuya tabla ya existe salvo con `--force`.
10. IF no existe una segunda Ventana_GOES de la misma Celda_Hora separada por 15 a 30 minutos, o alguna de las dos ventanas tiene la temperatura de brillo mínima en NaN, THEN THE Extractor_GOES SHALL asignar NaN a la tasa de enfriamiento de esa Celda_Hora y SHALL calcular las demás Variables_GOES con normalidad.
11. IF el archivo de entrada de una Ventana_GOES no contiene la banda 8 o la banda 13, THEN THE Extractor_GOES SHALL omitir ese archivo y SHALL emitir un aviso que nombre el archivo y la banda faltante, sin detener el procesamiento de los demás archivos.
12. IF un día del rango `--start`–`--end` no tiene archivos GOES en lat/lon para la región, THEN THE script CLI del Extractor_GOES SHALL omitir ese día sin escribir tabla, SHALL emitir un aviso con la fecha y SHALL continuar con el día siguiente.

### Requisito 3: Composición RGB para los modelos de embeddings

**User Story:** Como científico de datos, quiero convertir las Ventanas_GOES en imágenes RGB reproducibles, para usarlas como entrada de los modelos de Bedrock.

#### Acceptance Criteria

1. WHEN el Compositor_RGB recibe una Ventana_GOES, THE Compositor_RGB SHALL generar una imagen RGB cuadrada de 3 canales de 8 bits, con un lado configurable entre 224 y 1024 píxeles (224 por defecto), guardada en un formato sin pérdida.
2. THE Compositor_RGB SHALL aplicar una receta de composición fija e identificada por un nombre y un número de versión, que declare para cada uno de los 3 canales la banda GOES (o la diferencia de bandas), el límite inferior y el límite superior de temperatura de brillo en kelvin (con límite inferior estrictamente menor que el superior) y el valor de relleno para píxeles sin dato.
3. WHEN el Compositor_RGB normaliza un canal, THE Compositor_RGB SHALL recortar los valores de temperatura de brillo al rango [límite inferior, límite superior] de la receta, escalarlos linealmente de modo que el límite inferior corresponda a 0 y el superior a 255, y redondearlos al entero más cercano en el rango 0 a 255.
4. FOR ALL Ventanas_GOES, la normalización de un canal antes del remuestreo seguida de la inversión lineal de la receta SHALL reproducir cada temperatura de brillo válida comprendida dentro del rango de la receta con un error absoluto menor o igual que un paso de cuantización, definido como (límite superior − límite inferior) / 255 kelvin, y SHALL devolver el límite correspondiente para los valores fuera del rango (ida y vuelta).
5. FOR ALL Ventanas_GOES, componer dos veces la misma ventana con la misma receta, la misma versión y el mismo tamaño de salida SHALL producir archivos de imagen idénticos byte a byte (determinismo).
6. IF una Ventana_GOES contiene píxeles sin dato (NaN o valor de relleno del archivo GOES) y al menos el 50 % de píxeles válidos, THEN THE Compositor_RGB SHALL asignar a esos píxeles, en cada canal, el valor de relleno entero entre 0 y 255 declarado en la receta, y SHALL registrar en los metadatos la fracción de píxeles sin dato.
7. WHEN el Compositor_RGB genera una imagen, THE Compositor_RGB SHALL registrar en los metadatos de esa imagen el nombre y la versión de la receta, la Celda_Hora de origen, el sello de inicio de barrido del archivo GOES, el tamaño de la ventana en kilómetros, el tamaño de la imagen en píxeles y la escala de remuestreo (píxeles de salida por píxel de entrada).
8. IF una Ventana_GOES contiene menos del 50 % de píxeles válidos en alguna de las bandas de la receta, THEN THE Compositor_RGB SHALL omitir la generación de la imagen de esa Celda_Hora y SHALL registrar la Celda_Hora omitida con el motivo, sin detener el procesamiento de las demás ventanas.
9. IF una Ventana_GOES no contiene alguna de las bandas declaradas en la receta, THEN THE Compositor_RGB SHALL omitir la imagen de esa Celda_Hora y SHALL registrar la Celda_Hora y la banda faltante, sin generar una imagen parcial.
10. IF la receta solicitada no existe, su versión no existe o algún canal declara un límite inferior mayor o igual que el superior, THEN THE Compositor_RGB SHALL terminar antes de procesar ventanas con un mensaje de error que identifique la receta y el campo inválido.

### Requisito 4: Codificación de imágenes con Amazon Bedrock

**User Story:** Como científico de datos, quiero obtener embeddings de las imágenes GOES con Bedrock, para evaluar si un espacio vectorial preentrenado aporta información al modelo.

#### Acceptance Criteria

1. WHEN el Codificador_Bedrock recibe una imagen del Compositor_RGB, THE Codificador_Bedrock SHALL devolver un vector de punto flotante cuya longitud es igual a la dimensión de salida configurada para el Modelo_Embedding (1024 por defecto para Titan Multimodal Embeddings G1) y cuyos componentes son todos valores finitos (sin NaN ni infinitos).
2. THE Codificador_Bedrock SHALL usar Titan Multimodal Embeddings G1 como Modelo_Embedding cuando la CLI se ejecuta sin la opción de selección de modelo.
3. WHERE el usuario selecciona Cohere Embed v4 mediante una opción de la CLI, THE Codificador_Bedrock SHALL usar Cohere Embed v4 como Modelo_Embedding para todas las imágenes de esa corrida y SHALL registrar el identificador del modelo usado en la salida de la corrida.
4. IF el Modelo_Embedding no se ofrece en la región configurada con `--region` o la cuenta no tiene acceso habilitado a ese modelo, THEN THE Codificador_Bedrock SHALL terminar con código de salida distinto de cero antes de enviar la primera imagen, con un mensaje de error que indique el identificador del modelo y la región, sin escribir entradas en la caché.
5. THE Codificador_Bedrock SHALL guardar cada embedding exitoso en caché local o en S3 bajo una clave formada por el hash del contenido en bytes de la imagen, el identificador del Modelo_Embedding, la dimensión de salida y la versión de la receta del Compositor_RGB, de modo que cambiar cualquiera de esos cuatro elementos produce una clave distinta.
6. WHEN el Codificador_Bedrock encuentra en caché un embedding válido con la misma clave y la corrida no usa `--force`, THE Codificador_Bedrock SHALL reutilizar el embedding guardado sin invocar Bedrock, y dos corridas consecutivas sobre las mismas imágenes SHALL producir vectores idénticos y cero invocaciones a Bedrock en la segunda corrida (idempotencia).
7. IF Bedrock devuelve un error de limitación de tasa para una imagen, THEN THE Codificador_Bedrock SHALL reintentar esa imagen hasta 5 veces con espera exponencial que comienza en 1 segundo y se duplica en cada reintento (1, 2, 4, 8 y 16 segundos), y SHALL registrar la imagen como fallida y continuar con la siguiente imagen si los 5 reintentos fallan.
8. WHEN el Codificador_Bedrock termina una corrida, THE Codificador_Bedrock SHALL informar el número de imágenes codificadas, reutilizadas desde caché y fallidas, cuya suma es igual al número de imágenes de entrada, y SHALL terminar con código de salida distinto de cero si el número de imágenes fallidas es mayor que cero.
9. THE Codificador_Bedrock SHALL enviar a Bedrock únicamente los bytes de la imagen del Compositor_RGB y los parámetros del Modelo_Embedding, sin incluir datos del Catálogo (fechas, coordenadas ni etiquetas de Evento) en el contenido de la solicitud.
10. IF Bedrock devuelve un error distinto de limitación de tasa, o una invocación no responde en 30 segundos, THEN THE Codificador_Bedrock SHALL registrar esa imagen como fallida con el tipo de error, no SHALL escribir una entrada en la caché para ella y SHALL continuar con la siguiente imagen.
11. IF Bedrock devuelve un vector cuya longitud difiere de la dimensión configurada o que contiene valores no finitos, THEN THE Codificador_Bedrock SHALL registrar esa imagen como fallida y no SHALL escribir el vector en la caché.
12. WHEN la corrida se ejecuta con `--force`, THE Codificador_Bedrock SHALL invocar Bedrock para todas las imágenes de entrada aunque exista una entrada en caché con la misma clave y SHALL reemplazar las entradas de caché existentes con los nuevos embeddings exitosos.

### Requisito 5: Reducción de dimensión de los embeddings

**User Story:** Como científico de datos, quiero reducir los embeddings a pocas dimensiones, para evitar el sobreajuste con ~102 positivos.

#### Acceptance Criteria

1. THE Reductor SHALL proyectar los embeddings del Modelo_Embedding a un número entero de componentes configurable mediante una opción de la CLI, con valores permitidos entre 8 y 16 inclusive y un valor por defecto de 8.
2. WHILE se ejecuta la Validación_LOEO, THE Reductor SHALL ajustarse en cada partición solo con las Celdas_Hora del conjunto de entrenamiento de esa partición, y SHALL proyectar las Celdas_Hora del conjunto de prueba con el Reductor ajustado en esa misma partición, sin usar ninguna Celda_Hora del Evento dejado afuera en el ajuste.
3. FOR ALL conjuntos de embeddings de N filas (N ≥ 1) con la dimensión usada en el ajuste, THE Reductor SHALL producir una matriz de exactamente N filas, en el mismo orden de entrada, y exactamente el número de columnas configurado (invariante de forma).
4. WHEN el Reductor termina un ajuste, THE Reductor SHALL registrar, para ese ajuste y para cada partición de la Validación_LOEO, la fracción de varianza explicada por cada componente retenida y la fracción acumulada, con cada valor entre 0 y 1 y la fracción acumulada no decreciente y menor o igual que 1.
5. FOR ALL Reductores ajustados, guardar el Reductor y cargarlo de nuevo SHALL producir proyecciones idénticas valor a valor para la misma entrada, y SHALL conservar el número de componentes y el identificador del Modelo_Embedding usados en el ajuste (ida y vuelta).
6. IF el número de componentes configurado no es un entero entre 8 y 16 inclusive, THEN THE Reductor SHALL terminar antes de ajustar con un mensaje de error que indique el valor recibido y el rango permitido, sin escribir ningún Reductor ajustado.
7. IF el conjunto de ajuste contiene menos filas con embedding válido que el número de componentes configurado, o los embeddings a proyectar tienen una dimensión distinta de la usada en el ajuste, THEN THE Reductor SHALL rechazar la operación con un mensaje de error que indique las filas o dimensiones esperadas y recibidas, sin producir proyecciones.
8. IF una Celda_Hora no tiene embedding o su embedding contiene valores NaN, THEN THE Reductor SHALL excluir esa fila del ajuste y SHALL asignar NaN a todas sus componentes proyectadas, conservando la fila en la salida.

### Requisito 6: Tabla multimodal con estructura temporal

**User Story:** Como científico de datos, quiero una tabla que una índices ERA5, Variables_GOES, embeddings reducidos y sus rezagos, para entrenar un modelo que capture la evolución temporal de la tormenta.

#### Acceptance Criteria

1. WHEN el Constructor_Tabla recibe una Configuración_Experimento (`baseline_era5`, `physical` o `embeddings`), THE Constructor_Tabla SHALL producir exactamente una fila por Celda_Hora seleccionada, con las columnas de variables de esa Configuración_Experimento, la etiqueta (1 = positiva, 0 = no etiquetada), el identificador del Evento (vacío en las filas no etiquetadas) y la fecha y hora UTC de la Celda_Hora, y sin columnas de variables de otras Configuraciones_Experimento.
2. WHEN el Constructor_Tabla etiqueta un Evento, THE Constructor_Tabla SHALL marcar como positiva la Celda_Hora cuyo punto de grilla ERA5 está a menor distancia de las coordenadas del Evento y cuya hora UTC es la hora del Evento redondeada a la hora entera más cercana, y SHALL resolver los empates de distancia eligiendo el punto de grilla de menor latitud y luego el de menor longitud.
3. WHEN el Constructor_Tabla selecciona las Celdas_Hora no etiquetadas, THE Constructor_Tabla SHALL tomar una muestra aleatoria sin reemplazo, de tamaño igual a un número configurable de Celdas_Hora no etiquetadas por cada positiva (entero entre 1 y 1000), con una semilla entera configurable por CLI, y SHALL excluir de la muestra toda Celda_Hora marcada como positiva.
4. THE Constructor_Tabla SHALL usar los índices ERA5 con su signo físico austral, de modo que el valor de SRH y de STP de cada fila sea idéntico al valor producido por el procesamiento ERA5, sin invertir ni tomar el valor absoluto de la SRH ni del STP.
5. THE Constructor_Tabla SHALL calcular, para cada índice ERA5 y cada Variable_GOES de la Configuración_Experimento, los valores en t−1 h, t−2 h y t−3 h en la misma Celda_Hora y las diferencias definidas como valor en t menos valor en t−k, para k = 1, 2 y 3 h.
6. FOR ALL filas de la tabla, THE Constructor_Tabla SHALL calcular cada Variable_Rezago y cada Variable_GOES solo con datos cuya hora, o cuyo sello de inicio de barrido GOES, es menor o igual que la hora de la fila (sin información del futuro).
7. IF la hora de rezago t−k no tiene datos disponibles para la Celda_Hora (fuera del rango descargado o con valor NaN), THEN THE Constructor_Tabla SHALL asignar NaN al valor en t−k y a la diferencia correspondiente, y SHALL conservar la fila en la tabla.
8. WHEN el Constructor_Tabla alinea una Ventana_GOES con una Celda_Hora de hora t, THE Constructor_Tabla SHALL usar la Ventana_GOES con el sello de inicio de barrido `s` del archivo GOES más reciente dentro del intervalo (t − 60 min, t].
9. IF no existe ningún archivo GOES con sello de inicio de barrido `s` dentro del intervalo (t − 60 min, t], THEN THE Constructor_Tabla SHALL asignar NaN a todas las Variables_GOES y embeddings reducidos de esa Celda_Hora y SHALL conservar la fila en la tabla.
10. FOR ALL tablas, THE Constructor_Tabla SHALL asignar a cada Celda_Hora positiva exactamente un identificador de Evento y SHALL asignar cada identificador de Evento incluido a exactamente una Celda_Hora positiva (invariante).
11. IF dos o más Eventos corresponden a la misma Celda_Hora positiva, THEN THE Constructor_Tabla SHALL asignar esa Celda_Hora al Evento con el identificador menor, SHALL omitir los demás Eventos como positivos y SHALL informar al terminar los identificadores de los Eventos omitidos.
12. IF un Evento carece de fecha, coordenadas u hora UTC, o sus coordenadas quedan fuera de la región de la grilla ERA5 procesada, THEN THE Constructor_Tabla SHALL omitir ese Evento, continuar con los demás e informar al terminar el número y los identificadores de los Eventos omitidos.
13. WHEN el Constructor_Tabla procesa el mismo conjunto de entradas con la misma Configuración_Experimento y la misma semilla dos veces, THE Constructor_Tabla SHALL producir tablas con las mismas filas, en el mismo orden, con las mismas columnas y valores idénticos, tratando NaN como igual a NaN (determinismo).

### Requisito 7: Entrenamiento y evaluación comparativa en SageMaker

**User Story:** Como integrante del equipo, quiero entrenar y comparar las configuraciones en SageMaker con la misma validación, para decidir con evidencia si los embeddings aportan.

#### Acceptance Criteria

1. THE Entrenador SHALL entrenar las Configuraciones_Experimento `baseline_era5`, `physical` y `embeddings` con XGBoost, cada una como un trabajo de entrenamiento de SageMaker independiente, usando los mismos hiperparámetros de XGBoost en las tres configuraciones.
2. THE Entrenador SHALL evaluar cada Configuración_Experimento con la misma Validación_LOEO, la misma semilla y la misma lista de identificadores de Evento como particiones, de modo que las tres configuraciones tengan el mismo número de particiones evaluadas y el mismo conjunto de Eventos retenidos en cada partición.
3. FOR ALL particiones de la Validación_LOEO, THE Entrenador SHALL mantener todas las Celdas_Hora con el identificador del Evento retenido fuera del conjunto de entrenamiento de esa partición, de modo que la intersección entre los identificadores de Evento de entrenamiento y de prueba sea vacía (sin fuga).
4. THE Entrenador SHALL calcular POD, FAR y CSI a partir de los aciertos, omisiones y falsas alarmas acumulados en todas las particiones, clasificando como positiva cada Celda_Hora con probabilidad predicha mayor o igual que 0,5, y SHALL omitir la exactitud como métrica de decisión.
5. FOR ALL conteos de aciertos, omisiones y falsas alarmas mayores o iguales que 0, THE Entrenador SHALL producir POD, FAR y CSI entre 0 y 1 inclusive y SHALL asignar 0 a una Métrica cuyo denominador sea 0 (invariante).
6. WHEN los trabajos de entrenamiento de las tres Configuraciones_Experimento terminan con éxito, THE Entrenador SHALL escribir un reporte comparativo que incluya, por configuración, POD, FAR, CSI, aciertos, omisiones, falsas alarmas, número de Eventos evaluados y la importancia de cada variable ordenada de mayor a menor; y, como información complementaria que no interviene en la selección del modelo, el área bajo la curva precisión-exhaustividad (PR-AUC) de las predicciones fuera de partición y el umbral que maximiza el CSI sobre esas predicciones.
7. WHEN el Entrenador compara las Configuraciones_Experimento, THE Entrenador SHALL marcar en el reporte como modelo seleccionado a `embeddings` solo si su CSI es estrictamente mayor que el CSI de `physical`, y a `physical` en caso contrario, incluido el empate.
8. THE Entrenador SHALL excluir del cálculo de las Métricas usadas en la selección del modelo todos los Eventos con fecha 30 o 31 de mayo de 2019, y SHALL reportar POD, FAR y CSI de esos Eventos en una sección separada del reporte identificada como caso de desarrollo.
9. WHEN el trabajo de entrenamiento de una Configuración_Experimento termina con éxito, THE Entrenador SHALL escribir `model.json`, `metrics.json`, `importance.json` y `reporte.html` de esa configuración bajo un subprefijo con el nombre de la configuración dentro del prefijo de salida de S3.
10. THE Entrenador SHALL conservar en `scripts/model/train_xgboost.py` las opciones `--indices`, `--catalog`, `--out` y `--seed` y los cuatro archivos de salida actuales, y SHALL hacer que el script y el trabajo de SageMaker ejecuten el mismo código de construcción de tabla y de Validación_LOEO, de modo que, con las mismas entradas y la misma semilla, la configuración `baseline_era5` en SageMaker produzca los mismos aciertos, omisiones y falsas alarmas que el script; los resultados pueden diferir de corridas históricas de la versión anterior del script, y el reporte SHALL indicarlo.
11. IF el trabajo de entrenamiento de SageMaker de una Configuración_Experimento falla o no termina, THEN THE Entrenador SHALL registrar en el reporte el nombre de la configuración y el motivo del fallo, SHALL conservar las salidas de las configuraciones terminadas con éxito y SHALL omitir la selección de modelo si falta `physical` o `embeddings`.
12. IF la tabla de entrada de una Configuración_Experimento no contiene Celdas_Hora positivas o carece de alguna columna requerida por esa configuración, THEN THE Entrenador SHALL terminar antes de lanzar el trabajo de SageMaker con un mensaje que indique la configuración y la causa (sin positivos o columnas faltantes por nombre).
13. IF una partición de la Validación_LOEO tiene un conjunto de entrenamiento con una sola clase, THEN THE Entrenador SHALL omitir esa partición en las tres Configuraciones_Experimento y SHALL informar en el reporte el número de particiones omitidas.

### Requisito 8: Inferencia en SageMaker

**User Story:** Como usuario del visor, quiero obtener probabilidades para días y regiones nuevas, para revisar candidatos del archivo histórico.

#### Acceptance Criteria

1. THE Servicio_Inferencia SHALL ofrecer inferencia por lotes con SageMaker Batch Transform para el rango de fechas y la región indicados con las opciones `--start`, `--end` y `--region`, y SHALL escribir en S3 una fila de salida por cada Celda_Hora de entrada con la probabilidad, la fecha, la hora UTC, la latitud, la longitud y el nombre de la Configuración_Experimento usada.
2. WHEN el Servicio_Inferencia recibe filas que contienen todas las columnas del modelo seleccionado, THE Servicio_Inferencia SHALL devolver una probabilidad en el intervalo cerrado [0, 1] por fila, con el mismo número de filas y en el mismo orden que la entrada.
3. IF una fila de entrada carece de una o más columnas requeridas por el modelo seleccionado, THEN THE Servicio_Inferencia SHALL rechazar la solicitud completa sin devolver ni escribir probabilidades, con un mensaje de error que nombre todas las columnas faltantes.
4. WHERE se habilita un endpoint en tiempo real, THE Servicio_Inferencia SHALL rechazar toda solicitud sin una firma IAM (SigV4) válida y SHALL quedar sin acceso público.
5. THE Documento_Predictor SHALL indicar que las probabilidades identifican candidatos para revisión y no confirman un tornado, y que ERA5 no es una fuente operativa en tiempo real.
6. WHEN se inicia un trabajo de inferencia, THE Servicio_Inferencia SHALL cargar el `model.json` de la Configuración_Experimento marcada como modelo seleccionado en el reporte comparativo del Entrenador (Requisito 7).
7. IF una fila de entrada contiene la columna requerida con valor NaN (por ejemplo una Variable_Rezago sin datos o Variables_GOES anuladas por menos del 50 % de píxeles válidos), THEN THE Servicio_Inferencia SHALL tratar ese valor como faltante, devolver la probabilidad de esa fila y continuar sin rechazar la solicitud.
8. IF un trabajo de Batch Transform falla, THEN THE Servicio_Inferencia SHALL marcar el trabajo como fallido con un mensaje que indique la causa y el archivo de entrada afectado, y SHALL dejar sin cambios las salidas de corridas anteriores en S3.

### Requisito 9: Infraestructura para SageMaker y Bedrock

**User Story:** Como responsable de infraestructura, quiero recursos reproducibles y de mínimo privilegio para SageMaker y Bedrock, para mover el entrenamiento desde EC2 sin abrir accesos innecesarios.

#### Acceptance Criteria

1. THE Infraestructura SHALL definir en Terraform, dentro de `infra/terraform/`, un rol IAM de ejecución de SageMaker cuyas políticas concedan solo: lectura y escritura de objetos bajo los prefijos S3 del proyecto; lectura y listado (sin escritura ni borrado) de `nsf-ncar-era5`, `noaa-goes16` y `noaa-goes19`; `bedrock:InvokeModel` restringido a los identificadores de recurso de los Modelos_Embedding configurados (Titan Multimodal Embeddings G1 y, si está habilitado, Cohere Embed v4); `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` y `logs:DescribeLogStreams` restringidos a `arn:aws:logs:us-west-2:<cuenta>:log-group:/aws/sagemaker/*`; y `cloudwatch:PutMetricData` con la condición `cloudwatch:namespace` limitada a `/aws/sagemaker/*`.
2. THE Infraestructura SHALL definir las políticas del rol de ejecución de SageMaker sin comodines `*` en el campo de acciones y sin comodines `*` en el campo de recursos fuera de los prefijos S3 del proyecto, con una única excepción explícita: la declaración de `cloudwatch:PutMetricData`, que AWS solo admite con recurso `*` y que SHALL llevar la condición `StringLike` sobre `cloudwatch:namespace` = `/aws/sagemaker/*`; y SHALL definirlas sin conceder acciones de IAM, de borrado de buckets ni de modificación de políticas de bucket.
3. THE Infraestructura SHALL crear todos los recursos de SageMaker (trabajos de entrenamiento, modelos, Batch Transform y endpoints) e invocar Bedrock en la región us-east-1, la única que permite la cuenta y la del bucket de datos.
4. IF la variable de región de Terraform toma un valor distinto de us-east-1, THEN THE Infraestructura SHALL fallar en la validación de `terraform plan` con un mensaje que indique la región requerida, sin crear ni modificar recursos.
5. WHEN se ejecuta `terraform plan` inmediatamente después de un `terraform apply` exitoso sin cambios en el código ni en las variables, THE Infraestructura SHALL reportar cero recursos por agregar, cambiar o destruir (reproducibilidad).
6. THE Infraestructura SHALL conservar sin eliminar ni desactivar el flujo de entrenamiento en EC2 de `infra/terraform/training.tf` hasta que el Entrenador en SageMaker, con las mismas particiones de la Validación_LOEO y la misma semilla, produzca para `baseline_era5` valores de POD, FAR y CSI con una diferencia absoluta menor o igual que 0,01 respecto de los obtenidos con el flujo en EC2.
7. THE Documento_Predictor SHALL documentar que el movimiento a SageMaker es un cambio de infraestructura con costo, e incluir una estimación en USD por trabajo de entrenamiento, por corrida de Batch Transform y por hora de endpoint en tiempo real, indicando la fecha de consulta de los precios.
8. THE Documento_Predictor SHALL listar cada recurso de AWS creado por la Infraestructura para SageMaker y Bedrock y SHALL documentar los comandos para eliminarlos, incluyendo la eliminación de endpoints en tiempo real y de los artefactos en los prefijos S3 del proyecto.

### Requisito 10: Calidad y pruebas

**User Story:** Como mantenedor del repositorio, quiero que el pipeline siga las convenciones y tenga pruebas sin datos descargados, para mantener `make check` en verde.

#### Acceptance Criteria

1. THE Extractor_GOES, el Compositor_RGB, el Reductor, el Constructor_Tabla y el cálculo de Métricas SHALL tener, cada uno, al menos un módulo de pruebas `unittest` en `tests/` que construya sus entradas con datos sintéticos generados en la propia prueba (arreglos o tablas en memoria con semilla fija) y que cubra cada propiedad invariante, de ida y vuelta, de determinismo o sin fuga declarada para ese componente en los Requisitos 2, 3, 5, 6 y 7.
2. THE Codificador_Bedrock SHALL tener pruebas `unittest` en `tests/` que sustituyan el cliente de Bedrock por un doble de prueba y que verifiquen al menos: la dimensión del vector devuelto, la reutilización desde caché sin llamar al doble (Requisito 4.6), los reintentos ante limitación de tasa hasta 5 veces (Requisito 4.7) y la terminación ante un Modelo_Embedding no disponible (Requisito 4.4).
3. WHILE se ejecutan las pruebas de `tests/`, THE conjunto de pruebas SHALL completarse sin leer archivos de `data/`, sin conexiones de red y sin credenciales de AWS configuradas.
4. WHEN se ejecuta `make check`, THE repositorio SHALL ejecutar en orden `ruff check`, `ruff format --check`, pyright en modo `basic` y `python -m unittest discover -s tests`, y SHALL terminar con código de salida 0 solo si los cuatro pasos terminan con código 0, sin errores de ruff ni de pyright y sin pruebas fallidas o con error.
5. IF alguno de los pasos de `make check` falla, THEN THE repositorio SHALL hacer que `make check` termine con código de salida distinto de 0 e indique en la salida el paso que falló.
6. THE pipeline SHALL agregar cada dependencia nueva con `uv add`, con una versión exacta fijada en `pyproject.toml` y registrada en `uv.lock`.
7. THE pipeline SHALL escribir docstrings, mensajes de la CLI y textos de reporte en español, y SHALL usar identificadores, nombres de módulos, flags y rutas en inglés.
