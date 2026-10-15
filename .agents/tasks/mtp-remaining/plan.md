# Implementation Plan — multimodal-tornado-predictor (tareas restantes)

Repo (checkout principal, SIN worktree): `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado` (en adelante ROOT).
Fuente de verdad: `.kiro/specs/multimodal-tornado-predictor/{requirements,design,tasks}.md`, `AGENTS.md`, `CLAUDE.md`.
Artefactos FEAT: `ROOT/.agents/tasks/mtp-remaining/task-multimodal-tornado-predictor/` (context.json + features/FEAT-00N.json). El flujo se dividió en 4 FEAT secuenciales: FEAT-001 = grupos 1–4, FEAT-002 = 5–8, FEAT-003 = 9–11, FEAT-004 = 12–14. Después vienen un bucle de ajuste y revisión que termina cuando `ROOT/.agents/tasks/mtp-remaining/review.json` tiene `verdict` = `APPROVED`, y un paso final.

## Reglas invariantes (aplican a cada ítem)

- `uv` NO está en PATH: usar siempre `python -m uv ...`. Cuando la spec dice `uv run X` o `uv add X`, ejecutar `python -m uv run X` / `python -m uv add X`. No hay pytest: las pruebas corren con `unittest`.
- Gate completo (equivale a `make check`), desde ROOT:
  `python -m uv run ruff check scripts tests; python -m uv run ruff format --check scripts tests; python -m uv run pyright; python -m uv run python -m unittest discover -s tests -v`
  Los cuatro deben terminar con código 0.
- Prueba de un módulo: `python -m uv run python -m unittest tests.test_<mod> -v` (desde ROOT; `tests` se importa como paquete de nivel superior vía discover — si falla el import usar `python -m uv run python -m unittest discover -s tests -p "test_<mod>.py" -v`).
- Orden: tasks.md grupo 1 → 14, una subtarea a la vez. El checkbox de una subtarea en `tasks.md` pasa de `[ ]`/`[ ]*` a `[x]`/`[x]*` SOLO después de implementarla y de que su verificación pase. El grupo padre se marca `[x]` cuando todas sus subtareas están `[x]`. Nunca tocar 12.1 (ya `[x]`).
- No hacer commits ni push (ninguna tarea lo pide). No crear recursos de AWS: nada de `terraform apply/plan`, nada de llamadas reales a SageMaker/Bedrock/boto3. Todo cliente AWS va detrás de una función/parámetro inyectable y se prueba con dobles.
- Pruebas: `unittest` + Hypothesis (`@settings(max_examples=100, deadline=None)`), comentario `# Feature: multimodal-tornado-predictor, Property N: <título>`, sin red, sin `data/`, sin credenciales. Los archivos de prueba agregan al `sys.path` `ROOT/scripts` y `ROOT/scripts/model` (patrón de `tests/test_scorecard.py`). Entradas en `tempfile.TemporaryDirectory`.
- Estilo: ruff (E,W,F,I,B,UP,SIM,C4,NPY,ANN), pyright basic; anotar parámetros y retornos; docstring en cada módulo y función; docstrings/comentarios/mensajes en español, identificadores en inglés. Tras editar, `python -m uv run ruff check --fix scripts tests` y `python -m uv run ruff format scripts tests`.
- `tasks.meta.json` es historial de Kiro: no editarlo.

## Decisiones de diseño (tomadas; no reabrir)

1. **`scripts/model/sagemaker/` → `scripts/model/sm_job/`.** Un paquete llamado `sagemaker` dentro de `scripts/model` tapa al SDK real cuando `scripts/model` es `sys.path[0]` (al correr cualquier script de esa carpeta, en las pruebas y como `source_dir` del contenedor). Se renombra en TODO: tasks.md (1.1, 10.1, 10.2, 10.7), design.md (árbol de módulos línea ~164, títulos «Entrenador»/«Servicio_Inferencia», texto de `launch_sagemaker.py train`), código, pruebas y docs. No debe existir nunca `scripts/model/sagemaker/`.
2. **Versiones exactas (Req. 10.6).** El 1.1 parcial dejó `>=`. Se fijan con `python -m uv add boto3==1.43.75 sagemaker==3.21.0` y `python -m uv add --dev hypothesis==6.169.4` (ya resueltas en `uv.lock`, sin cambio de versiones). `sm_job/requirements.txt`: `xgboost==3.4.1`, `pyarrow==25.0.1`, `scikit-learn==1.9.1` (versiones de `uv.lock`).
3. **SDK de SageMaker v3.** `sagemaker==3.21.0` NO tiene `sagemaker.xgboost.XGBoost` (verificado: `ModuleNotFoundError`). Se usa `sagemaker.train.ModelTrainer` con `SourceCode(source_dir="scripts/model", entry_script="sm_job/train_entry.py", requirements="sm_job/requirements.txt")`, `Compute(instance_type="ml.m5.xlarge", instance_count=1)`, `training_image=sagemaker.core.image_uris.retrieve("xgboost", region=ml_region, version="3.0-5")`, `hyperparameters={"config","seed","n-components"}` e `InputData(channel_name="train"|"folds", data_source=s3_uri)`; `.train(wait=True)`. Transform y endpoint usan el cliente boto3 `sagemaker` (`create_model`, `create_transform_job`, `describe_transform_job`, `create_endpoint_config`, `create_endpoint`, `delete_endpoint`, `delete_endpoint_config`, `delete_model`). Actualizar el texto de 10.7 en tasks.md y la línea de `launch_sagemaker.py train` en design.md.
4. **Prueba de que se importa el SDK real.** `launch_sagemaker.py` hace `import sagemaker` a nivel de módulo y una función `assert_real_sdk()` (llamada al importar) que termina con `SystemExit` en español si `Path(sagemaker.__file__).resolve()` está dentro de `scripts/model`. Así `python -m uv run python scripts/model/launch_sagemaker.py --help` (código 0) demuestra el SDK real, y `tests/test_launch_sagemaker.py` afirma que `sagemaker.__file__` resuelve bajo `ROOT/.venv` (o `sys.prefix`) con `scripts/model` en `sys.path[0]`.
5. **Higiene de imports en el contenedor.** El contenedor solo recibe `scripts/model` (no `scripts/common.py`) y tiene numpy/pandas/xgboost/sklearn/pyarrow. Por eso `loeo.py`, `reducer.py`, `table.py` y `sm_job/*` no importan `common`, `xarray`, `h5py`, `s3fs` ni `fsspec` a nivel de módulo; `table.py` usa `from __future__ import annotations` e `if TYPE_CHECKING: import common`, y recibe la región como objeto con `.contains(lat, lon)`. `sm_job/train_entry.py` e `inference.py` insertan `Path(__file__).resolve().parents[1]` y su propia carpeta en `sys.path`.
6. **Paquete de inferencia.** Para Batch Transform/endpoint, `launch_sagemaker.py` arma un `sourcedir.tar.gz` (función pura y probada) con `inference.py` (copia de `sm_job/inference.py`) en la raíz, más `reducer.py`, `table.py` y `requirements.txt`; el modelo se crea con `Environment={"SAGEMAKER_PROGRAM": "inference.py", "SAGEMAKER_SUBMIT_DIRECTORY": <s3 del tar>}`. No verificable sin AWS: se documenta en `docs/modelo_predictor.md`.
7. **pyright resuelve los módulos hermanos.** En `pyproject.toml` `[tool.pyright] extraPaths = ["scripts", "scripts/model", "scripts/viewer"]` (posible gracias al renombre: con `sagemaker/` ahí, pyright también resolvería el SDK al paquete local).
8. **Línea base roja.** Hoy el gate falla antes de empezar: `ruff format --check` marca `scripts/model/run_cloud_training.py` y `scripts/model/train_xgboost.py`, y pyright da 8 errores en esos dos archivos (`fsspec.open(...)` tipado como lista, `pd.DataFrame` asignado con `list[str]`, `object.save_model`). Se arreglan en 1.1 sin cambiar comportamiento (formato; `typing.cast`/variables tipadas; `train_full` devuelve `xgb.XGBClassifier`).
9. **`fold_group` determinista.** El `hash()` de Python está aleatorizado para `str`; se usa `int(hashlib.sha256(f"{cell_id}|{seed}".encode()).hexdigest()[:16], 16) % n`.
10. **Catálogo y features ERA5.** `ERA5_FEATURES` (las 12 de `train_xgboost.FEATURES`) y `normalize_catalog(raw: pd.DataFrame) -> pd.DataFrame` (fecha, `lat`, `lon`, `hour_utc`, `coordinate`) viven en `table.py` (puros); `train_xgboost.py` y `build_table.py` leen el Excel con fsspec y delegan. `train_xgboost.FEATURES = table.ERA5_FEATURES`.
11. **Parámetros de prueba para XGBoost.** `fit_xgb`/`run_loeo` aceptan `xgb_overrides: dict | None` (p. ej. `{"n_estimators": 20}`) para que las pruebas sean rápidas; los valores por defecto son exactamente `XGB_PARAMS`.
12. **Hypothesis.** Agregar `.hypothesis/` a `.gitignore`.
13. **Caché S3.** `S3Cache.put` usa `put_object` (atómico en S3); el `.tmp` + `os.replace` aplica a `LocalCache`.

## Tareas (orden de tasks.md)

### Grupo 1 — Dependencias y estructura base

- [ ] 1.1 Terminar la tarea cancelada sin descartar cambios parciales.
      a) `git status` / `git diff pyproject.toml` (esperado: boto3, sagemaker, hypothesis con `>=`; `uv.lock` regenerado; `variables.tf` de 12.1 — no tocar). b) Fijar versiones exactas (Decisión 2) con `python -m uv add ...`; luego `python -m uv sync`. c) Renombre (Decisión 1): crear `scripts/model/sm_job/__init__.py` (docstring en español que explica por qué no se llama `sagemaker`) y `scripts/model/sm_job/requirements.txt`; actualizar tasks.md/design.md (Decisiones 1 y 3). d) `extraPaths` de pyright (Decisión 7) y `.hypothesis/` en `.gitignore`. e) Línea base verde (Decisión 8).
      Files: pyproject.toml, uv.lock, scripts/model/sm_job/__init__.py, scripts/model/sm_job/requirements.txt, .gitignore, scripts/model/run_cloud_training.py, scripts/model/train_xgboost.py, .kiro/specs/multimodal-tornado-predictor/tasks.md, .kiro/specs/multimodal-tornado-predictor/design.md
      Verify: `python -m uv run python -c "import sagemaker, boto3, hypothesis; print(sagemaker.__file__)"` imprime una ruta bajo `.venv`; `Test-Path scripts/model/sagemaker` es False; el gate completo pasa (40 pruebas existentes OK).

### Grupo 2 — Extractor_GOES

- [ ] 2.1 `scripts/model/goes_features.py` puro: `FILL_VALUE=-1`, `COLD_THRESHOLD_K=213.15`, `MIN_VALID_FRACTION=0.5`, `GOES_FEATURES=("goes_bt13_min","goes_cold_frac","goes_wv_ir_max","goes_cooling_rate")`; `decode` (NaN donde `raw==fill` antes de `raw*scale+offset`, float64), `valid_mask`, `window_features(bt13, bt08)` (si fracción válida de C13 < 0,5 → todo NaN; `goes_wv_ir_max` solo con píxeles válidos en ambas bandas, NaN si no hay), `cooling_rate(early, late, dt_min)` = `(early-late)*15/dt_min` si `15<=dt<=30` y ambos finitos, si no NaN; `select_scan` (máx. con `t-60min < s <= t`, `None`), `select_pair` (Δt∈[15,30], el más cercano a 15).
      Files: scripts/model/goes_features.py
      Verify: `python -m uv run pyright` y `python -m uv run ruff check scripts` sin errores.
- [ ] 2.2–2.6 Propiedades 1, 2, 3 (límites 0 %, 49 %, 50 %), 4 y 21 en `tests/test_goes_features.py` (una subtarea = un método de prueba; marcar cada una al pasar).
      Verify: `python -m uv run python -m unittest discover -s tests -p "test_goes_features.py" -v` pasa.
- [ ] 2.7 CLI `scripts/model/extract_goes_features.py`: `common.parser(__doc__, "los días")` + `--window-deg 0.25`; lee ERA5 lat/lon de `data/crops/<region>/era5_indices/era5_idx_AAAAMMDD.nc` para los puntos, abre `goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` con `xr.open_dataset(..., mask_and_scale=False, engine="h5netcdf")` y decodifica con los atributos de `C08`/`C13`; para `t` usa archivos de `t` y `t-1` (nunca `s>t`); aviso y omisión de archivos sin banda y de días sin archivos; escribe `data/model/<region>/goes_features/goes_feat_AAAAMMDD.parquet` (columnas del modelo de datos) vía `.tmp`+rename; salta lo existente salvo `--force`. Funciones de E/S con rutas como parámetro (raíz inyectable) para probar.
      Files: scripts/model/extract_goes_features.py
      Verify: `python -m uv run python scripts/model/extract_goes_features.py --help` sale con 0; gate de ruff/pyright.
- [ ] 2.8 `tests/test_extract_goes_features.py` con NetCDF sintéticos `int16` (scale/offset/_FillValue=-1) en directorio temporal: banda faltante con aviso, día sin archivos, salto de existentes y `--force`, columnas de salida.
      Verify: `python -m uv run python -m unittest discover -s tests -p "test_extract_goes_features.py" -v`.

### Grupo 3 — Compositor_RGB

- [ ] 3.1 `scripts/model/rgb.py` puro: `Channel`, `Recipe`, `RECIPES` (`ir_wv` v1, `airmass` v1 con los límites de design.md), `validate_recipe` (`SystemExit`/`ValueError` nombrando receta y campo; también `lower>=upper`), `normalize` (clip, lineal, `np.rint`, uint8), `denormalize`, `compose` → `ComposeResult(rgb, normalized, missing_frac)` (relleno `fill` por canal, NEAREST a `size` ∈ [224,1024]), `to_png_bytes` (Pillow, sin metadatos, `compress_level=6`, `optimize=False`).
      Files: scripts/model/rgb.py
      Verify: ruff + pyright limpios.
- [ ] 3.2–3.4 Propiedades 5, 6, 7 en `tests/test_rgb.py`.
      Verify: `... -p "test_rgb.py" -v` pasa.
- [ ] 3.5 CLI `scripts/model/compose_rgb.py` (opciones de `common` + `--cells`, `--recipe`, `--recipe-version`, `--size`, `--window-km`): valida receta antes de procesar; omite y registra en `skipped.parquet` (motivo) Celdas_Hora con < 50 % válidos o bandas faltantes; escribe PNG en `data/model/<region>/rgb/<recipe>_v<version>/AAAAMMDD/<cell_id>.png` y `manifest.parquet` (`cell_id, png_path, sha256, recipe, recipe_version, scan_start, window_km, size_px, scale_px_per_px, missing_frac`); escoge el barrido con `goes_features.select_scan`.
      Verify: `--help` sale con 0; ruff/pyright.
- [ ] 3.6 `tests/test_compose_rgb.py`: receta/versión inexistente, límite inferior ≥ superior, banda faltante, ventana < 50 %, contenido del manifiesto.
      Verify: `... -p "test_compose_rgb.py" -v`.

### Grupo 4 — CHECKPOINT 1
- [ ] 4 Ejecutar el gate completo; corregir todo fallo antes de seguir. Marcar `[x]` solo con los 4 pasos en 0.

### Grupo 5 — Codificador_Bedrock

- [ ] 5.1 `scripts/model/bedrock_encoder.py`: `ModelSpec`, `MODELS` (titan `amazon.titan-embed-image-v1` 1024 (256/384/1024); cohere-v4 `cohere.embed-v4:0` 1536 (256/512/1024/1536)), `cache_key` (sha256 de `f"{sha256_png}|{model_id}|{dim}|{recipe_version}"`), `EmbeddingCache` Protocol, `LocalCache` (`.npy`, `.tmp` + `os.replace`), `S3Cache(client, bucket, prefix)`; `BedrockEncoder(client, control, spec, dim, cache, sleep=time.sleep)`; `preflight(region)` con `control.get_foundation_model(modelIdentifier=...)` → `SystemExit` nombrando modelo y región; `encode` con cuerpo solo imagen base64 + parámetros del modelo; `ThrottlingException` (por `error.response["Error"]["Code"]`) → esperas `[1,2,4,8,16]` y luego fallida; otros errores/timeout → fallida con `error_type`, sin caché; validación longitud y finitos; `run` → `RunSummary(encoded, cached, failed, failures)`. `make_clients(region)` crea los clientes boto3 con `Config(read_timeout=30, retries={"max_attempts": 0})` (no se llama en pruebas).
      Verify: ruff/pyright.
- [ ] 5.2–5.4 Propiedades 8, 9, 10 en `tests/test_bedrock_encoder.py` con `FakeBedrockRuntime`, `FakeBedrockControl`, `MemoryCache` (definidos en el archivo).
- [ ] 5.5 Pruebas obligatorias (mismo archivo): dimensión, caché sin llamar al doble, esperas `[1,2,4,8,16]` con `sleep` falso, `preflight` con modelo no disponible termina sin escribir caché, `--force` reemplaza la caché.
      Verify (5.2–5.5): `... -p "test_bedrock_encoder.py" -v`.
- [ ] 5.6 CLI `scripts/model/encode_bedrock.py` (`--model {titan,cohere-v4}` titan por defecto, `--dim`, `--manifest`, `--cache {local,s3}`): escribe `data/model/<region>/embeddings/<model>_<dim>_<recipe>_v<version>.parquet` (`cell_id, model_id, dim, emb_0000…`) y `run_summary.json`; `sys.exit(1)` si `failed>0` o falla `preflight`. Constructor de clientes inyectable en `run_cli(argv, client_factory=...)`; añadir a `tests/test_bedrock_encoder.py` una prueba de la CLI con fábrica falsa (Titan por defecto, Cohere seleccionable, código de salida).
      Verify: `--help` sale con 0; prueba del archivo pasa.

### Grupo 6 — Reductor

- [ ] 6.1 `scripts/model/reducer.py`: `Reducer(n_components, model_id)` valida 8..16 (`ValueError` con valor y rango); `fit` SVD NumPy sobre matriz centrada de filas sin NaN, signo fijado (mayor |valor| positivo), error si filas válidas < n; `transform` (NaN en filas inválidas, error si dimensión distinta, con esperado y recibido); `explained_variance()`; `save`/`load` `.npz` float64 (`mean, components, explained_variance_ratio, n_components, model_id, input_dim`).
- [ ] 6.2–6.5 Propiedades 11, 12 (con `sklearn.decomposition.PCA` de referencia), 13, 14 (+ dimensión distinta y pocas filas) en `tests/test_reducer.py`.
      Verify: `... -p "test_reducer.py" -v`.

### Grupo 7 — Constructor_Tabla

- [ ] 7.1 `scripts/model/table.py` (Decisiones 5, 9, 10): `ERA5_FEATURES`, `normalize_catalog`, `make_cell_id` (`AAAAMMDDHH_<lat:+07.2f>_<lon:+07.2f>`), `label_positives` (longitud escalada por `cos(lat)`, empates menor lat y luego menor lon, hora redondeada, colisión → `event_id` menor, omitidos con motivo, `event_id = AAAAMMDD-<fila>`), `sample_unlabeled` (`default_rng(seed)`, sin reemplazo, ratio 1..1000, excluye positivas, aviso si faltan), `assign_fold_groups` (positivas = `event_id`; no etiquetadas por sha256 entre Eventos del día o, si no hay, de todos).
- [ ] 7.2–7.4 Propiedades 16, 17, 18 en `tests/test_table.py`.
- [ ] 7.5 Mismo módulo: `CONFIGS`, `GOES_FEATURES` (reusar de `goes_features` sólo si no rompe la Decisión 5 — `goes_features.py` es puro numpy, se puede importar), `LAGS=(1,2,3)`, `add_lags` (reindex horario por punto sin huecos, `groupby([lat,lon]).shift(k)`, `<var>_lag{k}`, `<var>_d{k}`, sin eliminar filas), `config_columns` (`baseline_era5`=12, `physical`=112, `embeddings`=112 + `emb_*`), `build` (orden `(time, latitude, longitude)`, columnas clave `cell_id, time, date, hour_utc, latitude, longitude, label, event_id, fold_group` + `config_columns`; GOES por Celda_Hora, embeddings por `cell_id`, NaN si falta).
- [ ] 7.6–7.9 Propiedades 19, 20, 22, 23 en `tests/test_table.py`.
      Verify (7.1–7.9): `... -p "test_table.py" -v`.
- [ ] 7.10 CLI `scripts/model/build_table.py` (`--stage select|build|infer`, `--config`, `--ratio`, `--seed`, `--catalog` + `common`): `select` → `cells.parquet`; `build` → `data/model/<region>/tables/config=<config>/date=AAAA-MM-DD/part-0.parquet`; `infer` → todas las Celdas_Hora sin etiquetas; informa omitidos y colisiones. Añadir una prueba de humo de la CLI en `tests/test_table.py` con NetCDF ERA5 sintético y catálogo `.xlsx` sintético (openpyxl) en temporal.
      Verify: `--help` sale con 0; prueba pasa.

### Grupo 8 — CHECKPOINT 2
- [ ] 8 Gate completo; corregir fallos.

### Grupo 9 — Validación_LOEO y Entrenador local

- [ ] 9.1 `scripts/model/loeo.py` (sin `common`): `XGB_PARAMS` exacto de design.md, `INNER_VAL_FRACTION=0.2`, `THRESHOLD=0.5`, `DEV_DATES`; `Fold` dataclass + `folds_to_json`/`folds_from_json`; `compute_folds` (un fold por `event_id` positivo; `skipped` si el train tiene una sola clase), `scale_pos_weight`, `inner_split` (`GroupShuffleSplit` solo sobre las filas de train; reintentos `seed+i` hasta 10; `None` → 300 árboles sin parada temprana), `fit_xgb(..., xgb_overrides=None)`, `run_loeo(table, feats, folds, seed, reducer_factory=None, xgb_overrides=None)` (Reductor ajustado SOLO con train de la partición; test = `fold_group == held`), `metrics`, `best_csi_threshold`, `pr_auc` (`average_precision_score`), separación del caso de desarrollo, `select_model`, `train_final`; registro por partición `scale_pos_weight`, `best_iteration`, `early_stopping`; `LoeoResult.to_metrics_json(config)` con la forma de `metrics.json`. Sin imputación de NaN; sin fuga.
- [ ] 9.2–9.8 Propiedades 24, 25, 26, 27, 28, 31, 15 en `tests/test_loeo.py` (XGBoost real, pocas filas, `xgb_overrides={"n_estimators": 20}`; reducer espía para la 15). Para las que entrenan, `max_examples` puede bajarse con justificación en comentario si 100 ejemplos tardan > 60 s, pero intentar 100 primero.
      Verify: `... -p "test_loeo.py" -v`.
- [ ] 9.9 Refactor `scripts/model/train_xgboost.py`: conserva `--indices`, `--catalog`, `--out`, `--seed` y las 4 salidas; arma `baseline_era5` con `table.build` y evalúa con `loeo.run_loeo`; reporte con PR-AUC y umbral de máximo CSI informativos y nota de diferencia con corridas históricas. `_write` se queda en el script; `sm_job/train_entry.py` tiene su propio escritor con cliente S3 inyectable. `run_cloud_training.py` debe seguir funcionando con la misma CLI.
- [ ] 9.10 `tests/test_train_xgboost.py`: índices y catálogo sintéticos en temporal; script vs `run_loeo` directo dan mismos conteos con la misma semilla; se escriben los 4 archivos.
      Verify: `... -p "test_train_xgboost.py" -v`.

### Grupo 10 — SageMaker (paquete `sm_job`)

- [ ] 10.1 `scripts/model/sm_job/train_entry.py`: `main(argv=None, input_dir=Path("/opt/ml/input/data"), model_dir=Path("/opt/ml/model"), s3_client=None, results_uri=None)`; hiperparámetros `--config`, `--seed`, `--n-components`, `--results-uri`; lee canales `train` (Parquet) y `folds` (`folds.json`); `run_loeo` (Reductor por partición en `embeddings`), modelo final con la misma parada temprana; escribe `model.json`, `feature_columns.json`, `config.json`, `reducer.npz` (solo `embeddings`) y sube los 4 resultados a `<results_uri>/<config>/` con el cliente inyectado. Prueba en `tests/test_train_entry.py` con directorios temporales y S3 falso.
- [ ] 10.2 `scripts/model/sm_job/inference.py`: `Bundle`, `MissingColumnsError`, `validate_schema`, `model_fn`, `input_fn` (`application/x-parquet`), `predict_fn` (NaN tal cual; en `embeddings` aplica `reducer.npz`), `output_fn` (`text/csv`: `probability,date,hour_utc,latitude,longitude,config` en orden de entrada).
- [ ] 10.3–10.4 Propiedades 29 y 30 en `tests/test_inference.py` (modelo XGBoost diminuto entrenado en la prueba).
      Verify (10.1–10.4): `... -p "test_train_entry.py"` y `... -p "test_inference.py"` pasan.
- [ ] 10.5 CLI `scripts/model/compare_runs.py`: lee los `metrics.json` (local o S3 vía lector inyectable) y estados (`FailureReason`); escribe `comparacion.json` / `comparacion.html` con lo pedido; `--ec2-metrics` informa |ΔPOD|,|ΔFAR|,|ΔCSI| de `baseline_era5` y si ≤ 0,01.
- [ ] 10.6 `tests/test_compare_runs.py`: config fallida conserva las demás; falta `physical`/`embeddings` → sin selección; empate → `physical`; diferencia EC2 ≤ 0,01.
- [ ] 10.7 CLI `scripts/model/launch_sagemaker.py` (Decisiones 3, 4, 6) con subcomandos `train`, `transform`, `endpoint` (`deploy`/`delete`): `--ml-region us-west-2`, `--role-arn`, `--bucket`, `--run-id`. `train`: valida tablas (positivos, columnas requeridas) ANTES de crear trabajos, `compute_folds` una vez → `folds.json`, sube, crea los tres trabajos con la fábrica `make_trainer` (ModelTrainer real por defecto), espera e invoca `compare_runs`. `transform`: tabla con `build_table.py --stage infer` (función inyectable), modelo seleccionado de `comparacion.json`, salida en `model/inference/<run_id>/` nuevo; fallo → causa y archivo, sin tocar corridas previas. `endpoint`: solo `InvokeEndpoint` SigV4, sin API Gateway/URL pública; borrado. Todo SDK/boto3 entra por un objeto `Backend` inyectable.
- [ ] 10.8 `tests/test_launch_sagemaker.py` con backend falso: tabla sin positivos o sin columnas termina antes de crear trabajos; los tres trabajos con mismos hiperparámetros y mismo `folds.json`; `transform` usa el modelo seleccionado y prefijo nuevo; el endpoint no crea acceso público; el SDK real no está tapado (Decisión 4); `sourcedir.tar.gz` contiene `inference.py` en la raíz.
      Verify (10.5–10.8): pruebas pasan; `python -m uv run python scripts/model/launch_sagemaker.py --help` sale con 0; `python -m uv run python scripts/model/compare_runs.py --help` sale con 0.

### Grupo 11 — CHECKPOINT 3
- [ ] 11 Gate completo; corregir fallos.

### Grupo 12 — Terraform (sin apply)

- 12.1 YA HECHA `[x]`. No tocar `variables.tf` salvo que 12.3 detecte un error real.
- [ ] 12.2 `infra/terraform/sagemaker.tf`: `provider "aws" { alias = "ml"; region = var.ml_region; default_tags ... }` (en `versions.tf` junto a los otros proveedores o en `sagemaker.tf`; elegir `versions.tf` por consistencia); `data "aws_caller_identity" "current" {}`; `aws_s3_bucket.ml` (`provider = aws.ml`, `bucket_prefix = "${var.project_name}-${var.environment}-ml-"`), SSE AES256, public access block; `aws_iam_role.sagemaker_exec` (assume `sagemaker.amazonaws.com`) y `aws_iam_role_policy` inline desde `data "aws_iam_policy_document"` con: Get/PutObject en `${ml}/model/*` y `${data}/data/*` (prefijo del Catálogo, ver `training_user_data.sh.tftpl`), ListBucket con condición `s3:prefix` (`model/*`, `data/*`); GetObject/ListBucket en `nsf-ncar-era5`, `noaa-goes16`, `noaa-goes19`; `bedrock:InvokeModel` en `arn:aws:bedrock:${var.ml_region}::foundation-model/amazon.titan-embed-image-v1` + Cohere con `dynamic`/`concat` según `enable_cohere`; logs en `arn:aws:logs:${var.ml_region}:${account}:log-group:/aws/sagemaker/*` y `:log-stream:*`; `cloudwatch:PutMetricData` `*` con `StringLike cloudwatch:namespace = /aws/sagemaker/*`. Nada de acciones `*`, `iam:*`, `s3:DeleteBucket`, `s3:PutBucketPolicy`, `timestamp()`, `uuid()`. `outputs.tf`: `ml_bucket` y `sagemaker_execution_role_arn`. `training.tf` sin cambios.
      Verify: revisión manual (Terraform ausente) con checklist de IAM; `git diff --stat infra/terraform/training.tf` vacío.
- [ ] 12.3 Validar: `Get-Command terraform`. Si existe: `terraform fmt -check`, `terraform init -backend=false`, `terraform validate` en `infra/terraform`. Si NO existe (estado actual): no instalar; revisión manual (sintaxis HCL, llaves, referencias a recursos/variables existentes, proveedor `aws.ml` en todos los recursos ML, formato alineado a 2 espacios) y nota en `ROOT/.agents/tasks/mtp-remaining/terraform-validation.md` + en `findings` del FEAT. Nunca `plan`/`apply`.

### Grupo 13 — Documento_Predictor y README

- [ ] 13.1 `docs/modelo_predictor.md` (español) con todo lo de tasks.md 13.1; umbrales HSLC copiados de la sección 3.2 de `docs/mesociclones_chile.md` con unidad; diagrama en texto con los nodos del glosario; comandos con `python -m uv run`/`uv run` y `--start --end --region --force`; rutas `scripts/model/sm_job/`; costos en USD con fecha de consulta (si no se puede consultar la web, marcar como estimación con fecha de redacción); recursos y comandos de borrado; nota de cuenta us-west-2; riesgo del contenedor (Decisión 6).
- [ ] 13.2 Enlace relativo en `README.md` a `docs/modelo_predictor.md`.
- [ ] 13.3 `tests/test_docs.py`: umbrales = sección 3.2 (parseados de ambos documentos), enlaces relativos resuelven, diagrama con todos los nodos, README enlaza. Solo archivos versionados.
      Verify: `... -p "test_docs.py" -v`.

### Grupo 14 — CHECKPOINT FINAL
- [ ] 14 Gate completo en verde; todas las casillas de tasks.md en `[x]`; `git status` muestra solo cambios esperados; `scripts/model/sagemaker/` no existe; ningún commit nuevo.
