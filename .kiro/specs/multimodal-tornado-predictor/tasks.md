# Implementation Plan: Predictor multimodal de tornados y trombas

## Overview

El plan construye el pipeline de abajo hacia arriba: primero los módulos puros (sin E/S) de cada componente con sus pruebas de propiedades, luego las CLI que los usan, después el Entrenador y el Servicio_Inferencia de SageMaker, la Infraestructura en Terraform y, al final, `docs/modelo_predictor.md` y el enlace del README. El lenguaje es Python (el del repositorio y del diseño). Las pruebas usan `unittest` con Hypothesis, sin red, sin `data/` y sin credenciales de AWS. Ninguna tarea ejecuta `terraform apply` ni crea recursos reales en AWS.

Comando de verificación: `make check`. En Windows sin `make`, el equivalente es:

```powershell
uv run ruff check scripts tests; uv run ruff format --check scripts tests; uv run pyright; uv run python -m unittest discover -s tests -v
```

## Tasks

- [x] 1. Dependencias y estructura base
  - [x] 1.1 Agregar dependencias y crear la estructura de `scripts/model/sm_job/`
    - `uv add boto3==<versión> sagemaker==<versión>` y `uv add --dev hypothesis==<versión>` con versiones exactas registradas en `uv.lock`
    - Crear `scripts/model/sm_job/__init__.py` y `scripts/model/sm_job/requirements.txt` con `xgboost`, `pyarrow` y `scikit-learn` fijados a las mismas versiones de `uv.lock`
    - Verificar que pyright y ruff cubren los módulos nuevos de `scripts/model/`
    - _Requirements: 10.6, 10.7_

- [x] 2. Extractor_GOES
  - [x] 2.1 Implementar `scripts/model/goes_features.py` (lógica pura)
    - `decode` (NaN para `_FillValue` antes de escalar), `valid_mask`, `window_features` (BT mínima C13, fracción < 213,15 K, máx. C08 − C13 con píxeles válidos en ambas bandas, NaN si < 50 % válidos), `cooling_rate`, `select_scan` (barrido más reciente en `(t − 60 min, t]`), `select_pair` (Δt ∈ [15, 30] min)
    - Constantes `FILL_VALUE`, `COLD_THRESHOLD_K`, `MIN_VALID_FRACTION` y `GOES_FEATURES`; docstrings en español
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.10, 6.6, 6.8, 6.9_

  - [x]* 2.2 Prueba de propiedad: Variables_GOES frente a un modelo de referencia
    - **Property 1: Variables_GOES coinciden con el modelo de referencia**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.7**
    - En `tests/test_goes_features.py`, Hypothesis dentro de `unittest.TestCase`, `max_examples=100`

  - [x]* 2.3 Prueba de propiedad: invariancia ante permutación
    - **Property 2: Invariancia ante permutación de píxeles**
    - **Validates: Requirements 2.8**

  - [x]* 2.4 Prueba de propiedad: ventanas con pocos píxeles válidos
    - **Property 3: Ventanas con pocos píxeles válidos dan NaN**
    - **Validates: Requirements 2.6**
    - Incluir los casos límite 0 %, 49 % y 50 % de válidos

  - [x]* 2.5 Prueba de propiedad: tasa de enfriamiento
    - **Property 4: Tasa de enfriamiento**
    - **Validates: Requirements 2.4, 2.10**

  - [x]* 2.6 Prueba de propiedad: selección del barrido GOES
    - **Property 21: Selección del barrido GOES**
    - **Validates: Requirements 6.8, 6.9**

  - [x] 2.7 Implementar la CLI `scripts/model/extract_goes_features.py`
    - `main()` con `common.parser` (`--start`, `--end`, `--region`, `--force`) y `--window-deg` (0,25 por defecto)
    - Abrir `goes_latlon` con `mask_and_scale=False` y decodificar con los atributos de `C08` y `C13`; leer el archivo de la hora `t` y el de `t − 1`, nunca barridos con `s > t`
    - Aviso y omisión de archivos sin `C08`/`C13` y de días sin archivos; salida `data/model/<region>/goes_features/goes_feat_AAAAMMDD.parquet`, salta lo existente salvo `--force`
    - _Requirements: 2.9, 2.11, 2.12, 6.6, 10.7_

  - [x]* 2.8 Pruebas unitarias de la CLI del Extractor_GOES
    - En `tests/test_extract_goes_features.py`, con NetCDF sintéticos escritos en `tempfile.TemporaryDirectory`
    - Casos: banda faltante con aviso, día sin archivos, salto de días existentes y `--force`, columnas de salida
    - _Requirements: 2.9, 2.11, 2.12, 10.3_

- [x] 3. Compositor_RGB
  - [x] 3.1 Implementar `scripts/model/rgb.py` (lógica pura)
    - `Channel`, `Recipe`, `RECIPES` con `ir_wv` v1 y `airmass` v1, `validate_recipe` (error que nombra receta y campo), `normalize` (recorte, escala lineal, `np.rint`), `denormalize`, `compose` (relleno de píxeles sin dato, fracción sin dato, remuestreo vecino más cercano a 224–1024 px), `to_png_bytes` determinista (sin metadatos, `compress_level=6`, `optimize=False`)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10_

  - [x]* 3.2 Prueba de propiedad: forma de la imagen y relleno
    - **Property 5: Forma de la imagen RGB y relleno de píxeles sin dato**
    - **Validates: Requirements 3.1, 3.6**
    - En `tests/test_rgb.py`

  - [x]* 3.3 Prueba de propiedad: ida y vuelta de la normalización
    - **Property 6: Ida y vuelta de la normalización**
    - **Validates: Requirements 3.3, 3.4**

  - [x]* 3.4 Prueba de propiedad: composición determinista
    - **Property 7: Composición determinista**
    - **Validates: Requirements 3.5**

  - [x] 3.5 Implementar la CLI `scripts/model/compose_rgb.py`
    - Opciones de `common` más `--cells`, `--recipe`, `--recipe-version`, `--size`, `--window-km`
    - Validar la receta antes de procesar ventanas; omitir Celdas_Hora con < 50 % válidos o bandas faltantes y registrarlas en `skipped.parquet` con el motivo, sin detener la corrida
    - Escribir `data/model/<region>/rgb/<recipe>_v<version>/AAAAMMDD/<cell_id>.png` y `manifest.parquet` con los campos del diseño
    - _Requirements: 3.7, 3.8, 3.9, 3.10, 10.7_

  - [x]* 3.6 Pruebas unitarias de la CLI del Compositor_RGB
    - En `tests/test_compose_rgb.py`: receta o versión inexistente, límite inferior ≥ superior, banda faltante, ventana con < 50 % válidos, contenido del manifiesto
    - _Requirements: 3.7, 3.8, 3.9, 3.10, 10.3_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ejecutar `make check` (o el equivalente con `uv run` en Windows). Ensure all tests pass, ask the user if questions arise.

- [x] 5. Codificador_Bedrock
  - [x] 5.1 Implementar `scripts/model/bedrock_encoder.py`
    - `ModelSpec` y `MODELS` (Titan Multimodal Embeddings G1 por defecto, Cohere Embed v4), `cache_key`, protocolo `EmbeddingCache` con `LocalCache` y `S3Cache` (escritura atómica `.tmp` + rename), `BedrockEncoder` con cliente, plano de control y `sleep` inyectables
    - `preflight` con `get_foundation_model`; cuerpo de solicitud solo con la imagen en base64 y los parámetros del modelo
    - Reintentos ante `ThrottlingException` con esperas 1, 2, 4, 8 y 16 s; otros errores y tiempo agotado de 30 s (`Config(read_timeout=30, retries={"max_attempts": 0})`) como fallidos sin caché; validación de longitud y valores finitos; `RunSummary` con `encoded`, `cached`, `failed`
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_

  - [x]* 5.2 Prueba de propiedad: clave de caché
    - **Property 8: La clave de caché distingue sus cuatro componentes**
    - **Validates: Requirements 4.5**
    - En `tests/test_bedrock_encoder.py`, con `FakeBedrockRuntime`, `FakeBedrockControl` y `MemoryCache`

  - [x]* 5.3 Prueba de propiedad: idempotencia de la caché
    - **Property 9: Idempotencia de la caché**
    - **Validates: Requirements 4.6**

  - [x]* 5.4 Prueba de propiedad: contabilidad de la corrida
    - **Property 10: Contabilidad de la corrida de codificación**
    - **Validates: Requirements 4.1, 4.8, 4.9, 4.10, 4.11**

  - [x] 5.5 Pruebas unitarias obligatorias del Codificador_Bedrock con dobles de prueba
    - En `tests/test_bedrock_encoder.py`: dimensión del vector devuelto, reutilización desde caché sin llamar al doble, esperas registradas `[1, 2, 4, 8, 16]` con `sleep` falso, terminación de `preflight` ante modelo no disponible sin escribir caché, `--force` reemplaza la caché
    - Sin red ni credenciales de AWS
    - _Requirements: 4.4, 4.6, 4.7, 4.12, 10.2, 10.3_

  - [x] 5.6 Implementar la CLI `scripts/model/encode_bedrock.py`
    - Opciones de `common` más `--model {titan,cohere-v4}` (Titan por defecto), `--dim`, `--manifest`, `--cache {local,s3}`
    - Escribir `data/model/<region>/embeddings/<model>_<dim>_<recipe>_v<version>.parquet` y `run_summary.json` con `model_id`; código de salida ≠ 0 si `failed > 0` o si falla `preflight`
    - _Requirements: 4.2, 4.3, 4.4, 4.8, 4.12, 10.7_

- [x] 6. Reductor
  - [x] 6.1 Implementar `scripts/model/reducer.py`
    - `Reducer(n_components, model_id)` con validación 8 ≤ n ≤ 16 (error con valor y rango); `fit` con PCA por SVD sobre NumPy, signo fijado, exclusión de filas con NaN y error si hay menos filas válidas que componentes; `transform` con NaN en filas inválidas y error si la dimensión difiere; `explained_variance`; `save`/`load` en `.npz` float64
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x]* 6.2 Prueba de propiedad: forma de la proyección
    - **Property 11: Forma de la proyección del Reductor**
    - **Validates: Requirements 5.3, 5.8**
    - En `tests/test_reducer.py`

  - [x]* 6.3 Prueba de propiedad: varianza explicada acotada
    - **Property 12: Varianza explicada acotada**
    - **Validates: Requirements 5.4**
    - Comparar con `sklearn.decomposition.PCA` como referencia

  - [x]* 6.4 Prueba de propiedad: guardar y cargar
    - **Property 13: Ida y vuelta de guardar y cargar el Reductor**
    - **Validates: Requirements 5.5**

  - [x]* 6.5 Prueba de propiedad: componentes fuera de rango
    - **Property 14: Número de componentes fuera de rango**
    - **Validates: Requirements 5.6**
    - Incluir también el caso de dimensión distinta y de pocas filas válidas (Req. 5.7)

- [x] 7. Constructor_Tabla
  - [x] 7.1 Implementar el etiquetado y el muestreo en `scripts/model/table.py`
    - `make_cell_id`, `label_positives` (punto ERA5 más cercano con longitud escalada por `cos(lat)`, empates por menor latitud y luego menor longitud, hora redondeada, colisiones al `event_id` menor, omisión e informe de Eventos sin datos o fuera de región), `sample_unlabeled` (`default_rng(seed)`, sin reemplazo, razón 1–1000, excluye positivas), `assign_fold_groups`
    - _Requirements: 6.2, 6.3, 6.10, 6.11, 6.12_

  - [x]* 7.2 Prueba de propiedad: etiquetado del punto y hora más cercanos
    - **Property 16: Etiquetado del punto y hora más cercanos**
    - **Validates: Requirements 6.2**
    - En `tests/test_table.py`, con búsqueda exhaustiva de referencia

  - [x]* 7.3 Prueba de propiedad: un Evento por positivo
    - **Property 17: Un Evento por positivo**
    - **Validates: Requirements 6.10, 6.11**

  - [x]* 7.4 Prueba de propiedad: muestreo de no etiquetadas
    - **Property 18: Muestreo de no etiquetadas**
    - **Validates: Requirements 6.3**

  - [x] 7.5 Implementar rezagos, columnas por configuración y `build` en `scripts/model/table.py`
    - `CONFIGS`, `ERA5_FEATURES` (las 12 actuales, signo austral sin modificar), `LAGS`, `add_lags` sobre índice horario reindexado sin huecos (`<var>_lag{k}`, `<var>_d{k}`), `config_columns` (`baseline_era5` sin rezagos, `physical` con 112 columnas, `embeddings` con `emb_*` crudos), `build` con orden `(time, latitude, longitude)` y columnas clave `cell_id, time, date, hour_utc, latitude, longitude, label, event_id, fold_group`
    - Asociar Variables_GOES por Celda_Hora y embeddings por `cell_id`; NaN si no hay barrido en `(t − 60, t]`
    - _Requirements: 6.1, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.13_

  - [x]* 7.6 Prueba de propiedad: rezagos y diferencias
    - **Property 19: Rezagos y diferencias correctos**
    - **Validates: Requirements 6.5, 6.7**

  - [x]* 7.7 Prueba de propiedad: sin información del futuro
    - **Property 20: Sin información del futuro**
    - **Validates: Requirements 6.6**

  - [x]* 7.8 Prueba de propiedad: esquema por configuración y signo austral
    - **Property 22: Esquema por configuración y signo austral conservado**
    - **Validates: Requirements 6.1, 6.4**

  - [x]* 7.9 Prueba de propiedad: tabla determinista
    - **Property 23: Tabla determinista**
    - **Validates: Requirements 6.13**

  - [x] 7.10 Implementar la CLI `scripts/model/build_table.py`
    - `--stage select|build|infer`, `--config`, `--ratio`, `--seed`, `--catalog`, más las opciones de `common`
    - `select` escribe `cells.parquet` con `fold_group`; `build` escribe `data/model/<region>/tables/config=<config>/date=AAAA-MM-DD/part-0.parquet`; `infer` escribe todas las Celdas_Hora del rango sin etiquetas
    - Informar al terminar los Eventos omitidos y los perdidos por colisión
    - _Requirements: 6.1, 6.3, 6.11, 6.12, 8.1, 10.7_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ejecutar `make check` (o el equivalente con `uv run` en Windows). Ensure all tests pass, ask the user if questions arise.

- [x] 9. Validación_LOEO y Entrenador local
  - [x] 9.1 Implementar `scripts/model/loeo.py`
    - `XGB_PARAMS` del diseño (`binary:logistic`, `hist`, `n_estimators=1000`, `early_stopping_rounds=30`, `eval_metric=["logloss","aucpr"]`, `max_depth=4`, `min_child_weight=5`, `subsample=0.8`, `colsample_bytree=0.8`, `reg_lambda=1`, `learning_rate=0.05`), sin imputación de NaN
    - `compute_folds` (marca particiones de una sola clase), `scale_pos_weight` por partición, `inner_split` con `GroupShuffleSplit` sobre `fold_group` solo dentro del entrenamiento (reintentos hasta 10 y caída a 300 árboles sin parada temprana), `fit_xgb` con `random_state=seed`
    - `run_loeo` con `reducer_factory` ajustado solo con el entrenamiento de cada partición; `metrics` (0 si denominador 0), umbral 0,5, separación del caso de desarrollo (30–31 de mayo de 2019), `best_csi_threshold` y `pr_auc` informativos, `select_model` (CSI estricto, sin selección si falta `physical` o `embeddings`)
    - Registrar por partición `scale_pos_weight`, `best_iteration` y si hubo parada temprana
    - _Requirements: 5.2, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.11, 7.13_

  - [x]* 9.2 Prueba de propiedad: particiones idénticas entre configuraciones
    - **Property 24: Particiones idénticas entre configuraciones**
    - **Validates: Requirements 7.2, 7.13**
    - En `tests/test_loeo.py`, con XGBoost real, pocas filas y `n_estimators` reducido por parámetro de prueba

  - [x]* 9.3 Prueba de propiedad: sin fuga en la Validación_LOEO
    - **Property 25: Sin fuga en la Validación_LOEO**
    - **Validates: Requirements 7.3**

  - [x]* 9.4 Prueba de propiedad: cálculo y cotas de las Métricas
    - **Property 26: Cálculo y cotas de las Métricas**
    - **Validates: Requirements 7.4, 7.5**

  - [x]* 9.5 Prueba de propiedad: exclusión del caso de desarrollo
    - **Property 27: Exclusión del caso de desarrollo**
    - **Validates: Requirements 7.8**

  - [x]* 9.6 Prueba de propiedad: regla de selección del modelo
    - **Property 28: Regla de selección del modelo**
    - **Validates: Requirements 7.7, 7.11**

  - [x]* 9.7 Prueba de propiedad: validación interna sin fuga y peso de clase
    - **Property 31: Validación interna sin fuga y peso de clase por partición**
    - **Validates: Requirements 7.3, 5.2**

  - [x]* 9.8 Prueba de propiedad: el Reductor no ve el Evento retenido
    - **Property 15: El Reductor no ve el Evento retenido**
    - **Validates: Requirements 5.2**
    - Usar un `reducer_factory` espía que registra las filas de ajuste

  - [x] 9.9 Refactorizar `scripts/model/train_xgboost.py` para delegar en `table.py` y `loeo.py`
    - Conservar `--indices`, `--catalog`, `--out`, `--seed` y las salidas `model.json`, `metrics.json`, `importance.json`, `reporte.html`
    - Construir la tabla `baseline_era5` con `table.build` y evaluar con `loeo.run_loeo`; agregar al reporte PR-AUC y umbral de máximo CSI como informativos y la nota de que los resultados difieren de corridas históricas
    - _Requirements: 7.6, 7.9, 7.10, 9.6, 10.7_

  - [x]* 9.10 Prueba unitaria de paridad del script
    - En `tests/test_train_xgboost.py`, con índices y catálogo sintéticos en un directorio temporal: el script y `run_loeo` directo dan los mismos aciertos, omisiones y falsas alarmas con la misma semilla, y se escriben los cuatro archivos
    - _Requirements: 7.10, 10.3_

- [x] 10. Entrenamiento e inferencia en SageMaker
  - [x] 10.1 Implementar `scripts/model/sm_job/train_entry.py`
    - Leer hiperparámetros `config`, `seed`, `n-components` y los canales `/opt/ml/input/data/train` y `/opt/ml/input/data/folds`
    - Ejecutar `run_loeo` (con Reductor por partición en `embeddings`), entrenar el modelo final con la misma parada temprana y escribir en `/opt/ml/model/` `model.json`, `feature_columns.json`, `config.json` y `reducer.npz` (solo `embeddings`), y en `s3://<ml>/model/results/<run_id>/<config>/` los cuatro archivos de resultados
    - Rutas y cliente S3 inyectables para probar sin red
    - _Requirements: 5.2, 5.4, 7.1, 7.9_

  - [x] 10.2 Implementar `scripts/model/sm_job/inference.py`
    - `model_fn`, `input_fn` (`application/x-parquet`), `predict_fn` con `validate_schema` y `MissingColumnsError` que nombra todas las faltantes, NaN pasados tal cual a XGBoost, `output_fn` (`text/csv`) con `probability, date, hour_utc, latitude, longitude, config` en el orden de entrada
    - _Requirements: 8.1, 8.2, 8.3, 8.7_

  - [x]* 10.3 Prueba de propiedad: salida de inferencia
    - **Property 29: Salida de inferencia**
    - **Validates: Requirements 8.2, 8.7**
    - En `tests/test_inference.py`, con un modelo XGBoost diminuto entrenado en la prueba

  - [x]* 10.4 Prueba de propiedad: rechazo por columnas faltantes
    - **Property 30: Rechazo por columnas faltantes**
    - **Validates: Requirements 8.3**

  - [x] 10.5 Implementar la CLI `scripts/model/compare_runs.py`
    - Leer los `metrics.json` de las tres configuraciones y el estado de los trabajos (`FailureReason` si fallaron); escribir `comparacion.json` y `comparacion.html` con POD, FAR, CSI, conteos, Eventos evaluados, importancia ordenada, PR-AUC y umbral de máximo CSI informativos, caso de desarrollo aparte, particiones omitidas y modelo seleccionado
    - `--ec2-metrics` para informar la diferencia absoluta de POD, FAR y CSI de `baseline_era5` frente al flujo EC2 (umbral 0,01)
    - _Requirements: 7.6, 7.7, 7.8, 7.11, 7.13, 9.6, 10.7_

  - [x]* 10.6 Pruebas unitarias de `compare_runs.py`
    - En `tests/test_compare_runs.py`: una configuración fallida conserva las demás; falta `physical` o `embeddings` → sin selección; empate de CSI → `physical`; diferencia EC2 ≤ 0,01
    - _Requirements: 7.7, 7.11, 9.6, 10.3_

  - [x] 10.7 Implementar la CLI `scripts/model/launch_sagemaker.py` con subcomandos `train`, `transform` y `endpoint`
    - `train`: validar cada tabla (positivos y columnas requeridas) antes de crear trabajos, calcular `folds.json` una vez, subir tablas y particiones, crear los tres trabajos con `sagemaker.train.ModelTrainer` (`SourceCode(source_dir="scripts/model", entry_script="sm_job/train_entry.py")`, imagen de XGBoost con `image_uris.retrieve`, mismos hiperparámetros) en `ml_region`, esperar e invocar `compare_runs`
    - `transform`: `--start`, `--end`, `--region`; tabla de inferencia con `build_table.py --stage infer`, `model.tar.gz` del modelo seleccionado en `comparacion.json`, salida en `model/inference/<run_id>/` nuevo; ante fallo, informar causa y archivo sin tocar corridas previas
    - `endpoint`: desplegar un endpoint privado invocable solo con `InvokeEndpoint` firmado SigV4 y subcomando de borrado
    - El SDK de SageMaker y boto3 quedan detrás de funciones inyectables
    - _Requirements: 7.1, 7.2, 7.12, 8.1, 8.4, 8.6, 8.8, 9.3, 10.7_

  - [x]* 10.8 Pruebas unitarias de `launch_sagemaker.py` con SDK falso
    - En `tests/test_launch_sagemaker.py`: tabla sin positivos o sin columnas termina antes de crear trabajos; los tres trabajos reciben los mismos hiperparámetros y el mismo `folds.json`; `transform` usa el modelo seleccionado y un prefijo nuevo; el endpoint no crea acceso público
    - _Requirements: 7.1, 7.12, 8.4, 8.6, 8.8, 10.3_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ejecutar `make check` (o el equivalente con `uv run` en Windows). Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Infraestructura en Terraform (sin `apply`)
  - [x] 12.1 Actualizar `infra/terraform/variables.tf`
    - Agregar `ml_region` (por defecto `us-west-2`) con bloque `validation` y mensaje en español que indica la región requerida, y `enable_cohere` (bool)
    - Actualizar la descripción de `training_region` para dejar claro que la EC2 sigue en us-east-1 y que SageMaker y Bedrock usan `ml_region`, independiente de ella
    - _Requirements: 9.3, 9.4_

  - [ ] 12.2 Crear `infra/terraform/sagemaker.tf` y ampliar `outputs.tf`
    - Proveedor `aws.ml` con `region = var.ml_region`; bucket ML cifrado, con bloqueo de acceso público y prefijo `model/`
    - Rol `sagemaker_exec` con políticas inline: S3 del proyecto (lectura/escritura bajo `model/` y prefijo del Catálogo, `ListBucket` con condición `s3:prefix`), lectura y listado de `nsf-ncar-era5`, `noaa-goes16`, `noaa-goes19`, `bedrock:InvokeModel` acotado a los ARN de Titan y (si `enable_cohere`) Cohere Embed v4, CloudWatch Logs acotado a `/aws/sagemaker/*`, y `cloudwatch:PutMetricData` con recurso `*` y condición `StringLike` sobre `cloudwatch:namespace` = `/aws/sagemaker/*` como única excepción
    - Sin acciones `*`, `iam:*`, `s3:DeleteBucket` ni `s3:PutBucketPolicy`; sin `timestamp()` ni valores no deterministas; `training.tf` sin cambios
    - Salidas: nombre del bucket ML y ARN del rol
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.6_

  - [ ] 12.3 Validar el Terraform sin crear recursos
    - Si `terraform` está disponible: `terraform fmt -check` y `terraform init -backend=false` + `terraform validate` en `infra/terraform/`; corregir lo que reporten
    - Si no está disponible o `init` no puede descargar proveedores, omitir y dejar una nota en el resumen de la tarea
    - No ejecutar `terraform plan` contra la cuenta ni `terraform apply`
    - _Requirements: 9.4, 9.5_

- [ ] 13. Documento_Predictor y README
  - [ ] 13.1 Escribir `docs/modelo_predictor.md`
    - Objetivo, mesociclón ≠ tornado, tres etapas, PU/LOEO/métricas con fórmulas y enlaces a 6.1–6.3, cinco riesgos de embeddings con mitigación, justificación de rezagos con ~102 Eventos, convenciones australes (2.6), umbrales HSLC de 3.2 con unidad, sin corrección de paralaje, diagrama en texto con los nodos del glosario, comandos por componente con `--start`, `--end`, `--region`, `--force`
    - Configuración de XGBoost (parada temprana interna agrupada, `scale_pos_weight` por partición, NaN nativos, PR-AUC y umbral de máximo CSI informativos, restricciones monótonas como trabajo futuro)
    - Costos estimados en USD por trabajo de entrenamiento, por Batch Transform y por hora de endpoint con fecha de consulta; lista de recursos y comandos de borrado (endpoints y prefijos S3); probabilidades como candidatos y ERA5 no operativo; nota de que la cuenta debe permitir us-west-2
    - Valores numéricos tomados de `docs/mesociclones_chile.md`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.14, 8.5, 9.7, 9.8_

  - [ ] 13.2 Agregar a `README.md` el enlace relativo a `docs/modelo_predictor.md`
    - _Requirements: 1.13_

  - [ ]* 13.3 Pruebas unitarias del documento
    - En `tests/test_docs.py`: los umbrales HSLC coinciden con la sección 3.2 del Documento_Fuente, los enlaces relativos resuelven, el diagrama contiene todos los nodos y el README enlaza al documento
    - Solo lee archivos versionados del repositorio, no `data/`
    - _Requirements: 1.5, 1.9, 1.11, 1.13, 1.14, 10.3_

- [ ] 14. Final checkpoint - Ensure all tests pass
  - Ejecutar `make check` (o el equivalente con `uv run` en Windows). Ensure all tests pass, ask the user if questions arise.

## Notes

- Las sub-tareas con `*` son pruebas puras y se pueden omitir para un MVP más rápido. El Req. 10.1 solo queda cubierto por completo si se ejecutan las pruebas de propiedades marcadas como opcionales.
- Las pruebas del Codificador_Bedrock (5.5) no son opcionales porque el Req. 10.2 las exige.
- Las pruebas de propiedades usan Hypothesis dentro de `unittest.TestCase` (`max_examples=100`, `deadline=None`) y llevan el comentario `# Feature: multimodal-tornado-predictor, Property N: <título>`.
- Ninguna tarea crea recursos en AWS. El despliegue real (`terraform apply`, `launch_sagemaker.py train|transform|endpoint`) queda documentado en `docs/modelo_predictor.md` para que el equipo lo ejecute.
- `training.tf` se conserva hasta comprobar la paridad de `baseline_era5` ≤ 0,01 con `compare_runs.py --ec2-metrics`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "12.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "5.1", "6.1", "12.2"] },
    { "id": 2, "tasks": ["2.2", "2.7", "3.2", "3.5", "5.2", "5.6", "6.2", "7.1", "12.3"] },
    { "id": 3, "tasks": ["2.3", "2.8", "3.3", "3.6", "5.3", "6.3", "7.2", "7.5"] },
    { "id": 4, "tasks": ["2.4", "3.4", "5.4", "6.4", "7.3", "7.10", "9.1"] },
    { "id": 5, "tasks": ["2.5", "5.5", "6.5", "7.4", "9.2", "9.9", "10.1", "10.2", "10.5"] },
    { "id": 6, "tasks": ["2.6", "7.6", "9.3", "9.10", "10.3", "10.6", "10.7"] },
    { "id": 7, "tasks": ["7.7", "9.4", "10.4", "10.8", "13.1"] },
    { "id": 8, "tasks": ["7.8", "9.5", "13.2"] },
    { "id": 9, "tasks": ["7.9", "9.6", "13.3"] },
    { "id": 10, "tasks": ["9.7"] },
    { "id": 11, "tasks": ["9.8"] }
  ]
}
```

## Estado de avance (handoff)

Fecha: 2026-10-15. Rama: `feat/multimodal-tornado-predictor-wip`.

- Completos y verificados: grupos 1 a 11 (todas sus sub-tareas, incluidas las opcionales `*`) y la tarea 12.1.
- Pendientes: 12.2 (`sagemaker.tf` y `outputs.tf`), 12.3 (validar Terraform), 13.1–13.3 (`docs/modelo_predictor.md`, enlace en README, `tests/test_docs.py`) y 14 (checkpoint final). No quedó nada pendiente de los grupos 9–11.
- Último gate (2026-10-15): `ruff check` sin errores, `ruff format --check` con 66 archivos ya formateados, `pyright` con 0 errores y `unittest` con 139 pruebas OK en ~196 s.

Desviaciones del spec original ya aplicadas:

- El paquete se llama `scripts/model/sm_job/` y no `scripts/model/sagemaker/`, para no tapar al SDK `sagemaker` cuando `scripts/model` está en `sys.path`. `launch_sagemaker.py` lo comprueba al importar (`assert_real_sdk`).
- Se usa `sagemaker.train.ModelTrainer` (importado de `sagemaker.train.model_trainer`) en lugar de `sagemaker.xgboost.XGBoost`, que no existe en el SDK 3.21.0.
- Versiones exactas: `boto3==1.43.75`, `sagemaker==3.21.0` y `hypothesis==6.169.4` (desarrollo).
- En esta máquina `uv` no está en el PATH: usar `python -m uv run ...`.

Riesgos y próximos pasos:

- Terraform no está instalado en esta máquina. La 12.1 no se validó y la 12.3 requiere `terraform fmt -check`, `terraform init -backend=false` y `terraform validate` en `infra/terraform/` en un equipo que lo tenga.
- No se creó ningún recurso en AWS. El backend real de `launch_sagemaker.py` (`DefaultBackend`) no se ejecutó; solo se probó con un backend falso. Falta confirmar en AWS que el modo script de la imagen XGBoost 3.0-5 instala `sm_job/requirements.txt` y carga `inference.py` desde `SAGEMAKER_SUBMIT_DIRECTORY`.
- `train_xgboost.py` cambió de comportamiento (NaN conservados, hora del Catálogo redondeada, `--seed` fija también particiones internas y XGBoost, nueva forma de `metrics.json`). Hay que documentarlo en la 13.1.
