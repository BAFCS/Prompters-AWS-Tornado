# El modelo predictor multimodal de tornados y trombas

Este documento describe el **predictor multimodal**: un clasificador que estima, para cada
Celda_Hora de la grilla ERA5, la probabilidad de que preceda a un Evento del Catálogo. Es el
complemento técnico de [`docs/mesociclones_chile.md`](mesociclones_chile.md) (el *Documento_Fuente*),
que explica la física, el caso chileno y los datos. Aquí se detallan el planteamiento del modelo,
la evaluación, los riesgos, el flujo de componentes, los comandos y los costos de llevarlo a AWS.

El texto narrativo está en español; los identificadores, módulos, flags, rutas y nombres de
configuración (`baseline_era5`, `physical`, `embeddings`) quedan en inglés, como pide `AGENTS.md`.

## 1. Qué se predice

El modelo estima, para cada **Celda_Hora** (un punto de la grilla ERA5 de 0,25° en una hora UTC), la
**probabilidad, entre 0 y 1, de que esa Celda_Hora corresponda a un Evento del Catálogo en un
horizonte de 0 a 3 horas**. La probabilidad es un número continuo en `[0, 1]`; no es una decisión
binaria. Las Celdas_Hora con probabilidad alta son **candidatas** que una persona debe revisar, no
alertas automáticas.

> **Un mesociclón no es un tornado.** El modelo aprende de los Eventos del Catálogo (tornados y
> trombas confirmados), no de detecciones de mesociclón. Detectar un entorno o una firma compatible
> con un mesociclón **no equivale a predecir un tornado**: la etiqueta positiva proviene siempre de
> un Evento registrado del Catálogo, nunca de una detección de rotación. Un mesociclón puede no
> producir tornado, y el Catálogo solo contiene positivos (ver la sección 6 del Documento_Fuente).

Además, el reanálisis **ERA5 no es un producto operativo**: se publica con días de retraso. El
modelo sirve para **explorar el archivo histórico** y para calibrar índices, no para emitir avisos en
tiempo real.

## 2. Las tres etapas del enfoque

El trabajo se plantea en tres etapas, en este orden:

1. **Referencia física.** Las configuraciones `baseline_era5` (solo los 12 índices ERA5 en la hora
   `t`) y `physical` (ERA5 + Variables_GOES + Variables_Rezago). Son el punto de comparación
   interpretable y barato.
2. **Experimento con embeddings de Bedrock.** La configuración `embeddings` agrega a `physical` los
   vectores de un modelo de embeddings de Amazon Bedrock (Titan Multimodal Embeddings G1 por
   defecto, Cohere Embed v4 como alternativa), reducidos con PCA. **Se conserva solo si su CSI supera
   estrictamente al de `physical`** bajo la misma Validación_LOEO; si no, se descarta.
3. **Codificador autosupervisado propio.** Entrenar un codificador de imágenes GOES específico del
   dominio. Queda **como trabajo futuro**: no se implementa en esta entrega.

## 3. Planteamiento del modelo

### 3.1 Aprendizaje PU (positivo y no etiquetado)

El Catálogo solo tiene **positivos** (~102 Eventos; ver la sección 6.1 del Documento_Fuente). No hay
negativos confirmados: que un día no tenga registro no prueba que no hubo tornado. Por eso el
problema es de **aprendizaje con positivos y datos no etiquetados (PU)**: las Celdas_Hora de los
Eventos son positivas (`label = 1`) y una muestra de las demás Celdas_Hora se usa como **no
etiquetadas** (`label = 0`), que son candidatas a negativas pero no negativas confirmadas.

Fundamento y detalle: [sección 6.1 del Documento_Fuente](mesociclones_chile.md#61-aprendizaje-con-positivos-y-datos-no-etiquetados)
y [sección 6.2](mesociclones_chile.md#62-desbalance-entre-eventos-y-situaciones-sin-etiqueta).

### 3.2 Por qué rezagos y árboles, no LSTM ni Transformer

Con solo **~102 Eventos positivos** (el mismo número que declara el Documento_Fuente), una red
recurrente (LSTM) o un Transformer sobreajusta: tienen demasiados parámetros para tan pocos casos. En
su lugar, la estructura temporal entra como **variables** (Variables_Rezago): cada fila de la hora
`t` lleva el valor de cada índice ERA5 y de cada Variable_GOES en `t`, `t−1 h`, `t−2 h` y `t−3 h`, y
las diferencias `x(t) − x(t−k)`. Los árboles de XGBoost aprenden umbrales sobre la tendencia (por
ejemplo, SRH que se vuelve más negativa o un tope que se enfría) además del nivel. Ese horizonte de
tres horas de historia define la ventana 0–3 h del objetivo. Es un modelo **no secuencial**: toda la
dependencia temporal está en las columnas, no en la arquitectura.

### 3.3 Validación_LOEO (dejar-un-evento-afuera)

La evaluación usa **Validación_LOEO**: en cada partición, **todas las Celdas_Hora de un Evento
quedan juntas en el conjunto de prueba** y el modelo se entrena con el resto. Así se evita que filas
de la misma tormenta aparezcan a la vez en entrenamiento y prueba (fuga de información). El Reductor
PCA de la configuración `embeddings` se ajusta **solo con el conjunto de entrenamiento de cada
partición**, nunca con el Evento retenido.

Fundamento y detalle: [sección 6.3 del Documento_Fuente](mesociclones_chile.md#63-validación-separar-los-casos-de-entrenamiento-y-evaluación).

### 3.4 Métricas

Con umbral de decisión 0,5, cada predicción es acierto (*hit*), omisión (*miss*) o falsa alarma
(*false alarm*). Las **Métricas** son POD, FAR y CSI (ver la sección 6.2 del Documento_Fuente):

- **POD** (probabilidad de detección) = `aciertos / (aciertos + omisiones)`.
- **FAR** (proporción de falsas alarmas) = `falsas_alarmas / (aciertos + falsas_alarmas)`.
- **CSI** (índice crítico de éxito) = `aciertos / (aciertos + omisiones + falsas_alarmas)`.

Cada métrica vale 0 cuando su denominador es 0. **La selección del modelo usa el CSI** sumado sobre
las particiones cuyo Evento retenido no pertenece al caso de desarrollo (30 y 31 de mayo de 2019),
que se reporta aparte. De forma **informativa** (no interviene en la selección) se reportan el área
bajo la curva precisión-exhaustividad (PR-AUC) y el umbral que maximiza el CSI.

Definición de las Métricas: [sección 6.2 del Documento_Fuente](mesociclones_chile.md#62-desbalance-entre-eventos-y-situaciones-sin-etiqueta).

## 4. Riesgos del uso de embeddings de Bedrock

Los embeddings son un experimento, no la referencia, por cinco razones. Cada una lleva al menos una
mitigación o la forma en que la Validación_LOEO la pone a prueba:

1. **Cambio de dominio.** Titan y Cohere se entrenaron con fotografías naturales, no con temperatura
   de brillo calibrada de GOES. *Mitigación*: la configuración `embeddings` solo se conserva si su
   CSI supera al de `physical` bajo la misma Validación_LOEO; si el cambio de dominio hace inútil el
   vector, `physical` gana y los embeddings se descartan.
2. **Pérdida de calibración al pasar a RGB de 8 bits.** El Compositor_RGB recorta cada banda a un
   rango físico y la cuantiza a 256 niveles, con lo que se pierden valores finos de temperatura.
   *Mitigación*: la rama física (`baseline_era5`, `physical`) conserva la temperatura de brillo sin
   cuantizar, así que la señal calibrada nunca depende del RGB.
3. **Desajuste de escala.** La celda ERA5 (~31 km, unos 15 píxeles del infrarrojo de 2 km) es mucho
   menor que la entrada mínima de 224 píxeles del modelo de embeddings. *Mitigación*: el
   Compositor_RGB usa una ventana más ancha que la celda (`--window-km`, 100 km por defecto) para dar
   contexto, y remuestrea con vecino más cercano para no inventar valores; aun así, el beneficio real
   lo decide la comparación de CSI.
4. **Naturaleza temporal de la señal.** El mesociclón es un fenómeno que evoluciona, y un embedding
   de una sola imagen es una instantánea. *Mitigación*: las Variables_Rezago y la tasa de
   enfriamiento aportan la dinámica; los embeddings solo agregan la textura espacial de un instante.
5. **Alta dimensión frente a pocos positivos.** Un vector de 1024 o 1536 valores con ~102 positivos
   invita al sobreajuste. *Mitigación*: el **Reductor** (PCA de 8 a 16 componentes) baja la dimensión
   y se ajusta **dentro de cada partición** de la Validación_LOEO, de modo que la reducción nunca ve
   el Evento retenido.

## 5. Convenciones del hemisferio sur

Chile está en el hemisferio sur, y varios índices cambian de signo respecto del uso norteamericano
(ver la [sección 2.6 del Documento_Fuente](mesociclones_chile.md#26-convenciones-de-signo-en-el-hemisferio-sur)):

- La **helicidad relativa a la tormenta (SRH)** de los casos tornádicos es **negativa**: un valor
  negativo indica un entorno favorable, no desfavorable.
- Las supercélulas tornádicas favorecidas son las ***left-movers*** (se desvían a la izquierda del
  viento medio), al revés que en Estados Unidos.
- El **STP** se interpreta en su rama *left-mover*, con valores **negativos** para los casos
  favorables.

El pipeline conserva estos signos tal como los calcula `process_era5.py`: no se invierten. Las
columnas `srh_01`, `srh_03` y `stp_lm` entran a la tabla con su signo austral intacto.

## 6. Umbrales HSLC chilenos

El régimen chileno es **HSLC** (*High Shear, Low CAPE*). Los umbrales de la
[sección 3.2 del Documento_Fuente](mesociclones_chile.md#32-el-régimen-chileno-fuerte-cizalladura-y-bajo-cape),
con su índice, valor y unidad, son:

- **VGP₀₋₁ = √CAPE × cizalladura₀₋₁ > 0,1 m/s²** (los cinco días tornádicos de 2008–2019 lo superan;
  Los Ángeles supera 0,2).
- **SHERBE ≥ 1** (adimensional).
- **STP de la rama *left-mover* ≤ −0,3** (adimensional; nótese el signo negativo austral, distinto
  del umbral +1 usado en otros contextos).

> Estos umbrales **orientan la comparación** con los estudios chilenos citados; **no son reglas de
> decisión del modelo**. XGBoost aprende sus propios cortes a partir de los datos.

## 7. Sin corrección de paralaje

El pipeline **no aplica corrección de paralaje** a las imágenes GOES. El satélite ve el tope de la
tormenta (a 12–15 km de altura) *de lado*, así que el tope aparece desplazado respecto de su posición
real en superficie, hacia el sur a la latitud de Chile (unos 21 km a 53°S para un tope de 12 km).
**Consecuencia**: la posición aparente del tope nuboso y la Celda_Hora asociada pueden no coincidir
exactamente; una firma puede atribuirse a una celda vecina. Es una fuente de error conocida que queda
documentada y sin corregir en esta entrega.

## 8. Flujo de datos (diagrama)

El pipeline va de S3 (ERA5 y GOES) hasta el Servicio_Inferencia, pasando por cada componente del
glosario. Cada nodo lleva su nombre del glosario:

```text
   ┌─────────────── S3 público ───────────────┐
   │  ERA5 (nsf-ncar-era5)   GOES (noaa-goes16/19)  │
   └───────┬───────────────────────┬───────────┘
           │                       │
           ▼                       ▼
   [process_era5.py]        [process_goes.py]        (scripts/pipeline, existentes)
           │                       │
           │                       ▼
           │               ┌──────────────┐
           │               │ Extractor_GOES│  Variables_GOES por Celda_Hora
           │               └──────┬───────┘
           │                      │
           │                      ▼
           │               ┌──────────────┐
           │               │ Compositor_RGB│  PNG por Celda_Hora (receta versionada)
           │               └──────┬───────┘
           │                      │
           │                      ▼
           │              ┌────────────────┐
           │              │ Codificador_Bedrock │  vector de embedding por imagen
           │              └──────┬─────────┘
           │                     │
           │                     ▼
           │               ┌──────────┐
           │               │ Reductor │  PCA 8–16 componentes (por partición LOEO)
           │               └────┬─────┘
           │                    │
           ▼                    ▼
      ┌───────────────────────────────────┐
      │        Constructor_Tabla          │  tabla PU (X, y, fold_group) por configuración
      └──────────────────┬────────────────┘
                         │
                         ▼
                 ┌───────────────┐
                 │   Entrenador  │  SageMaker ×3 configuraciones + compare_runs
                 └──────┬────────┘
                        │
                        ▼
              ┌────────────────────┐
              │ Servicio_Inferencia │  Batch Transform / endpoint SigV4
              └────────────────────┘
```

## 9. Comandos por componente

Todos los comandos se ejecutan **desde la raíz del repositorio**. Donde el script las admite se
muestran `--start`, `--end`, `--region` y `--force` con valores de ejemplo. Si `uv` no está en el
`PATH`, antepón `python -m` (es decir, `python -m uv run ...`).

| Componente del diagrama | Comando de ejemplo |
|---|---|
| ERA5 (S3) → índices | `uv run python scripts/pipeline/download_era5.py --start 2019-05-30 --end 2019-05-31` y luego `uv run python scripts/pipeline/process_era5.py --start 2019-05-30 --end 2019-05-31 --region south-central-austral` |
| GOES (S3) → latlon | `uv run python scripts/pipeline/download_goes.py --start 2019-05-30 --end 2019-05-31` y luego `uv run python scripts/pipeline/process_goes.py --start 2019-05-30 --end 2019-05-31 --region south-central-austral` |
| Extractor_GOES | `uv run python scripts/model/extract_goes_features.py --start 2019-05-30 --end 2019-05-31 --region south-central-austral --force` |
| Constructor_Tabla (selección) | `uv run python scripts/model/build_table.py --stage select --ratio 200 --seed 0 --start 2019-05-30 --end 2019-05-31 --region south-central-austral` |
| Compositor_RGB | `uv run python scripts/model/compose_rgb.py --cells cells.parquet --recipe ir_wv --recipe-version 1 --size 224 --window-km 100 --start 2019-05-30 --end 2019-05-31 --region south-central-austral --force` |
| Codificador_Bedrock | `uv run python scripts/model/encode_bedrock.py --model titan --cache local --start 2019-05-30 --end 2019-05-31 --region south-central-austral --force` |
| Reductor | se ejecuta dentro del Entrenador (`scripts/model/reducer.py`); no tiene CLI propia |
| Constructor_Tabla (construcción) | `uv run python scripts/model/build_table.py --stage build --config physical --seed 0 --start 2019-05-30 --end 2019-05-31 --region south-central-austral` |
| Entrenador (local) | `uv run python scripts/model/train_xgboost.py --indices data/model/south-central-austral/era5_indices --catalog data/tornados_chile.xlsx --out out --seed 0` |
| Entrenador (SageMaker) | `uv run python scripts/model/launch_sagemaker.py train --ml-region us-west-2 --role-arn <ARN> --bucket <ML_BUCKET> --run-id R1 --seed 0` |
| Comparación y selección | `uv run python scripts/model/compare_runs.py --run-id R1 --bucket <ML_BUCKET>` |
| Servicio_Inferencia | `uv run python scripts/model/launch_sagemaker.py transform --ml-region us-west-2 --role-arn <ARN> --bucket <ML_BUCKET> --run-id R1 --start 2021-06-12 --end 2021-06-12 --region south-central-austral` |

Para una corrida local completa de la rama física, el Makefile ofrece el atajo `make check` (que
corre las pruebas) y los pasos de datos documentados en el README. Cada script detalla sus opciones
con `--help`.

## 10. Configuración de XGBoost

- **Objetivo y algoritmo.** `objective="binary:logistic"` (probabilidades en `[0, 1]`),
  `tree_method="hist"`, determinista con `random_state` fijo.
- **NaN nativos.** No se imputa. XGBoost aprende hacia qué rama envía los faltantes: un rezago sin
  datos o una Variable_GOES anulada por menos del 50 % de píxeles válidos es información, no un hueco
  que rellenar con la media.
- **`scale_pos_weight` por partición.** Se calcula como `n_negativas / n_positivas` del conjunto de
  entrenamiento de cada partición (y del conjunto completo en el modelo final), no como un valor
  fijo. Se registra en `metrics.json`.
- **Parada temprana interna agrupada.** Dentro de cada partición de entrenamiento se separa un
  conjunto de validación interno con `GroupShuffleSplit` sobre `fold_group`, de modo que las filas de
  un mismo Evento no se reparten y el Evento retenido nunca participa. Si no quedan positivas en la
  validación interna, se reintenta hasta 10 veces y, si no se logra, se entrena con 300 árboles sin
  parada temprana. La métrica que decide la parada es `aucpr`.
- **Regularización para pocos positivos.** `max_depth=4`, `min_child_weight=5`, `subsample=0.8`,
  `colsample_bytree=0.8`, `reg_lambda=1`, `learning_rate=0.05`, con `n_estimators=1000` como tope.
- **Restricciones monótonas: trabajo futuro.** En HSLC el signo de la relación entre un índice y la
  probabilidad varía (por ejemplo, CAPE bajo con cizalle alto), y el signo austral de SRH/STP
  complica fijarlo a priori. No se aplican todavía.
- **Mismos hiperparámetros en las tres configuraciones.** Solo cambian las columnas de entrada;
  `random_state=seed` y `scale_pos_weight` se derivan de los datos con la misma regla.

> **Cambio respecto de corridas históricas.** El `train_xgboost.py` actual conserva los NaN, redondea
> la hora del Catálogo a la hora entera, usa `--seed` para fijar también las particiones internas y
> XGBoost, y prueba cada partición con sus Celdas_Hora retenidas (no solo con la fila positiva). Por
> eso sus resultados **difieren** de los de corridas anteriores del script, que fijaban 300 árboles,
> no usaban parada temprana y evaluaban solo la fila positiva. El reporte lo indica.

## 11. Costos de llevar el modelo a AWS

Mover el entrenamiento y la inferencia a SageMaker es un **cambio de infraestructura con costo**. Las
cifras siguientes son **estimaciones en us-west-2**, consultadas el **15 de octubre de 2025**;
confírmalas en la [calculadora de precios de AWS](https://calculator.aws/) antes de desplegar, porque
los precios cambian.

| Recurso | Supuesto | Costo estimado (us-west-2, 2025-10-15) |
|---|---|---|
| Trabajo de entrenamiento | `ml.m5.xlarge` (~0,23 USD/hora), ~0,5 h por configuración × 3 configuraciones | ~0,35 USD por corrida completa de las tres configuraciones |
| Batch Transform | `ml.m5.xlarge` (~0,23 USD/hora), ~0,5 h por día de inferencia | ~0,12 USD por día de inferencia |
| Endpoint en tiempo real | `ml.m5.xlarge` encendido, por hora | ~0,23 USD/hora (~165 USD/mes si queda 24/7) |
| Embeddings (Bedrock, Titan Multimodal) | ~0,00006 USD por imagen de entrada | ~1,20 USD por 20 000 Celdas_Hora de una corrida de entrenamiento; en inferencia `embeddings`, ~6 USD por día (orden de 100 000 Celdas_Hora) |
| S3 (artefactos del modelo) | almacenamiento estándar | centavos al mes para tablas, modelos y resultados |

**Recomendación de costo:** usa la configuración `physical` para la inferencia salvo que
`embeddings` gane de forma clara. La inferencia con `embeddings` obliga a codificar en Bedrock todas
las Celdas_Hora del rango, con un costo proporcional al número de celdas.

## 12. Recursos creados y cómo borrarlos

El despliegue real lo ejecuta el equipo; ninguna tarea de la especificación crea recursos. Lo que se
crea y cómo eliminarlo:

- **Bucket S3 de artefactos del modelo** (`ml_bucket` en la salida de Terraform): vacía el prefijo y
  bórralo con
  `aws s3 rm s3://<ML_BUCKET>/model/inference/<run_id>/ --recursive --region us-west-2` (o el prefijo
  que corresponda). `terraform destroy` elimina el bucket (tiene `force_destroy = true`).
- **Endpoint en tiempo real** (si se despliega): es el recurso más caro por quedar encendido.
  Bórralo con
  `uv run python scripts/model/launch_sagemaker.py endpoint delete --ml-region us-west-2 --endpoint-name <NOMBRE>`,
  que elimina el endpoint, su configuración y el modelo asociado.
- **Trabajos de entrenamiento y Batch Transform**: terminan solos; no hay que borrarlos, pero dejan
  objetos en S3 bajo `model/results/<run_id>/` y `model/inference/<run_id>/` que puedes vaciar con
  `aws s3 rm ... --recursive`.
- **Rol de ejecución de SageMaker y bucket**: `terraform destroy` en `infra/terraform/` los elimina
  junto con el resto de la infraestructura.

> **La cuenta debe permitir us-west-2.** SageMaker y Bedrock de este pipeline viven en **us-west-2**
> (la región de `nsf-ncar-era5`). Antes del `terraform apply`, confirma que la cuenta puede crear
> recursos y tiene acceso a los modelos de Bedrock en esa región. La variable `ml_region` está
> validada a `us-west-2` en `infra/terraform/variables.tf`.

## 13. Nota sobre el contenedor de SageMaker

El entrenamiento usa la imagen de XGBoost de SageMaker en *script mode*: `sm_job/train_entry.py` es
el punto de entrada y `sm_job/requirements.txt` fija la misma versión de `xgboost` que `uv.lock`. El
paquete se llama `sm_job/` y **no** `sagemaker/` para no tapar al SDK de Bedrock/SageMaker cuando
`scripts/model` está en `sys.path`. La inferencia carga `inference.py` desde el directorio de envío
(`SAGEMAKER_SUBMIT_DIRECTORY`). Esta ruta solo se puede comprobar por completo ejecutando un trabajo
real en AWS.
