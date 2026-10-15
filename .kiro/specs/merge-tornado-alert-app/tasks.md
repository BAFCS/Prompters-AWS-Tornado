# Implementation Plan: merge-tornado-alert-app

## Overview

El plan avanza por pasos cortos y verificables:

1. Primera Sincronización de las ramas de Nico y Daniel en `merge/datos-modelo`.
2. Infraestructura mínima de registro: escritura atómica, Bitácora_Progreso y Documento_Planificación.
3. Pruebas de contrato tempranas, para detectar deriva desde el inicio, y Sincronización repetible (`make sync`).
4. Cadena de datos: Adaptador → Ejecutor_Inferencia → Generador_Sitio → Motor_Alertas → `run_day.py`.
5. Terraform del sitio y `deploy_site.py`, pruebas de repositorio y extremo a extremo sintético.
6. Sincronización final y, solo con confirmación explícita del usuario, push, PR y despliegue en AWS.

Lenguaje: Python 3 (el del repo), con `unittest`, ruff y pyright mediante `make check`. Todo el código nuevo vive en `scripts/app/` y `tests/test_app_*.py`.

### Convenciones para todas las tareas

- **Registro de progreso**: cada tarea termina agregando una Entrada_Bitácora con `uv run python scripts/app/progress_log.py --tarea "<n. título>" --estado <hecho|bloqueado> --notas "<resultado de make check; modos de falla revisados>" [--decision "..."]` sobre `docs/logs/progreso.json`. `estado` vale `hecho` si `make check` terminó con código 0 y `bloqueado` si no (Req. 9.7). La tarea 1 se ejecuta antes de que exista `progress_log.py`, así que su entrada se registra en la tarea 2.6.
- **git rerere** ya está activado en el repo local (`rerere.enabled=true`, `rerere.autoupdate=true`). En cada Sincronización se revisan igualmente las resoluciones reaplicadas contra las reglas del diseño.
- **Nunca** se hace `push`, `gh pr create`, `terraform apply` ni subidas a AWS salvo en las tareas 19 y 20, y solo después de la confirmación explícita del usuario.
- **Pruebas de propiedades**: bucles con `random.Random(SEED)` y `numpy.random.default_rng(SEED)` dentro de `unittest`, al menos 100 casos, `self.subTest(case=i, seed=SEED)` y el comentario `# Feature: merge-tornado-alert-app, Property N: <título>`.
- Ninguna prueba lee ni escribe `data/`, `docs/logs/progreso.json` ni `configs/` reales, ni usa red ni credenciales AWS (Req. 9.2 y 9.9).

## Tasks

- [x] 1. Primera Sincronización de ramas (sin push)
  - [x] 1.1 Crear `merge/datos-modelo` e integrar las cabezas vigentes
    - `git fetch origin` y registrar los SHA de `origin/main`, `origin/intentos-nico` y `origin/feat/multimodal-tornado-predictor-wip` con `git rev-parse` (anotarlos para la tarea 2.6)
    - Exigir árbol de trabajo limpio; `git checkout -b merge/datos-modelo origin/main`
    - `git merge --no-ff origin/intentos-nico` y luego `git merge --no-ff origin/feat/multimodal-tornado-predictor-wip`, sin rebase, squash ni force
    - No hacer push
    - _Requirements: 1.1, 1.2, 1.6, 1.12_
  - [x] 1.2 Resolver conflictos según las reglas del diseño y verificar
    - `pyproject.toml`: unión de dependencias de ambas ramas, cada una fijada con `==` a la versión de `uv.lock`; ante dos versiones, la más alta (anotar la elección para el Documento_Planificación)
    - `uv.lock`: regenerar con `uv lock` y verificar con `uv lock --check`
    - `README.md` y otros `.md`: conservar ambos textos bajo `### Desde intentos-nico` y `### Desde feat/multimodal-tornado-predictor-wip`, conservando el enlace a `docs/modelo_predictor.md`
    - `scripts/model/train_xgboost.py`: versión de Daniel; `infra/terraform/` (`outputs.tf`, `versions.tf`, `sagemaker.tf`): versión de la rama de origen
    - Verificar: sin marcadores de conflicto (`git grep`), `git merge-base --is-ancestor` para ambos SHA, `origin/main` sin cambios y `make check` (anotar resultado y archivos en conflicto)
    - Si se toca código de origen más allá del conflicto, anotar archivo, cambio y motivo
    - _Requirements: 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 1.11_

- [x] 2. Escritura atómica y Bitácora_Progreso
  - [x] 2.1 Implementar `scripts/app/atomic.py`
    - `write_bytes`, `write_text`, `write_json`, `write_dataset` con temporal en el mismo directorio, `fsync` y `os.replace`; elimina el temporal y relanza ante fallos
    - `locked(path)` con `fcntl.flock` exclusivo sobre `<path>.lock`
    - _Requirements: 3.3, 3.8, 4.12, 5.12_
  - [x] 2.2 Implementar `scripts/app/progress_log.py`
    - `STATES`, `validate`, `read` (`[]` si no existe; `LogError` "archivo corrupto"), `append` bajo `atomic.locked`, y `main` con `argparse` (`--tarea`, `--estado`, `--notas`, `--decision` repetible, `--timestamp`, `--file`)
    - Valida `timestamp` ISO 8601 con zona UTC, `tarea` de 1 a 200 caracteres y `estado` permitido; el mensaje nombra cada campo inválido
    - Crea directorios faltantes
    - _Requirements: 3.1, 3.2, 3.4, 3.6, 3.7_
  - [ ]* 2.3 Escribir prueba de propiedad de ida y vuelta de la bitácora
    - **Property 1: Ida y vuelta de la Bitácora_Progreso**
    - **Validates: Requirements 3.1, 3.2, 3.5, 3.6**
    - Archivo: `tests/test_app_progress_log.py`
  - [ ]* 2.4 Escribir prueba de propiedad de rechazo de entradas inválidas
    - **Property 2: Rechazo de entradas inválidas**
    - **Validates: Requirements 3.4**
  - [ ]* 2.5 Escribir prueba de propiedad de bitácora corrupta intacta
    - **Property 3: Bitácora corrupta intacta**
    - **Validates: Requirements 3.7**
  - [x] 2.6 Crear `docs/logs/progreso.json` con la entrada inicial
    - Ejecutar `progress_log.py` con `tarea = "sincronización"`, los tres SHA de la tarea 1, los conflictos resueltos, el resultado de `make check` y las decisiones de resolución (por ejemplo `boto3==1.43.75`)
    - Estado `hecho` o `bloqueado` según `make check`
    - _Requirements: 1.10, 1.13, 3.6_
  - [ ]* 2.7 Escribir pruebas unitarias de fallo de escritura atómica
    - Simular fallo de `os.replace` y de escritura del temporal con `unittest.mock`: archivo original intacto, temporal eliminado, código distinto de cero en el CLI
    - _Requirements: 3.8_

- [x] 3. Documento_Planificación
  - [x] 3.1 Escribir `docs/planificacion_merge.md`
    - Encabezados en orden: "Flujo", "Decisiones", "Preguntas abiertas", "Errores conocidos", "Riesgos", "Cambios al código de origen" y "Sincronización con ramas en movimiento"
    - Flujo de los 7 componentes con su entrada y salida; Generador_Sitio y Motor_Alertas leen el mismo CSV_Predicciones de forma independiente
    - Las 3 decisiones con fecha AAAA-MM-DD y motivo, más las resoluciones de la tarea 1.2 (pines de versiones)
    - Al menos 7 preguntas abiertas (región ML, cuenta de producción, calibración PU, umbrales, Zonas_Alerta, WhatsApp, autenticación) más la de 7.12 frente a 7.2 y la de política de fijación `==`; cada una con ≥2 opciones, componente afectado y estado `abierta`
    - Los 5 errores conocidos del Lago_Datos con mitigación y verificación del Reporte_Calidad, o "sin mitigación en v1"
    - Riesgos (sitio público, sin eventos etiquetados en 2025-10-15 → 2026-09-30, Modelo_Sustituto, índices de capa baja con 6 niveles) con impacto y mitigación o aceptación
    - Cambios al código de origen de la tarea 1.2, o "ninguno"
    - Tabla de archivos compartidos con responsable, acuerdo de coordinación y tabla de Sincronizaciones con la primera fila (6 columnas)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 2.10, 2.11, 1.3, 1.8_

- [x] 4. Constantes del Lago_Datos y pruebas de contrato tempranas
  - [x] 4.1 Implementar `scripts/app/lake_layout.py`
    - Prefijos, patrones, `LEVELS`, `PL_VARS`, `SFC_VARS`, `DIMS`, `CDS_RENAME`, `CDS_DROP`, `GOES_VAR`, `GOES_SHAPE`, `GOES_FILL`, `ERA5_IDX_PATTERN`, `GOES_LATLON_PATTERN` y `GOES_RES`, según el diseño
    - _Requirements: 9.15_
  - [x] 4.2 Implementar `scripts/app/contracts.py`
    - `Drift`, `missing_symbols` (con `ast`), `tuple_constant`, `sequence_drift`, `missing_members`, `layout_drift` y `format_drift`; sin importar `inference.py` ni `build_table.py`
    - _Requirements: 9.11, 9.12, 9.13, 9.15_
  - [x] 4.3 Crear `tests/app_synthetic.py` y `tests/test_app_contracts.py`
    - `app_synthetic.py`: `NoNetworkMixin` que parchea `socket.socket.connect` y vacía variables de credenciales AWS con `mock.patch.dict(os.environ)`
    - Contratos con Daniel: símbolos de `sm_job/inference.py`, `OUTPUT_COLUMNS` exacto (mensaje con esperado y encontrado), `ERA5_FEATURES` con `cape` y `shear_06`, `build_table.py --help` con `--stage infer` (con `subprocess`, `timeout=60`, y caída a `ast`)
    - Contrato con Nico: `EXPECTED_LAYOUT` transcrito de `docs/DATOS_AWS.md` frente a `lake_layout.py`
    - Si falta el código de Daniel, fallar con mensaje explícito, sin saltar
    - _Requirements: 9.9, 9.11, 9.12, 9.13, 9.14, 9.15_
  - [ ]* 4.4 Escribir prueba de propiedad del detector de deriva
    - **Property 25: Detector de deriva de contrato**
    - **Validates: Requirements 9.11, 9.12, 9.13, 9.15**

- [x] 5. Sincronización repetible (`make sync`)
  - [x] 5.1 Implementar `scripts/app/sync_branches.py`
    - `SyncShas`, `SyncResult`, `git` (sin shell), `record_shas`, `ensure_branch`, `merge_source` (`--no-ff`), `conflict_markers`, `sync_row` (6 celdas, SHA a 7 caracteres, `|` escapados), `append_sync_row` (atómico) y `main` con `--dry-run`, `--continue` y `--skip-check`
    - Árbol sucio: código 2 sin tocar nada; conflicto sin resolver: código 1, archivos listados, entrada `bloqueado` y merge en curso; `origin/main` cambiado al final: código 1
    - Al terminar, agrega la Entrada_Bitácora `sincronización` y la fila de la tabla
    - Nunca `push`, `rebase`, `reset`, `--squash` ni `--force`
    - _Requirements: 1.2, 1.6, 1.9, 1.10, 1.12, 1.13, 2.10_
  - [x] 5.2 Agregar el objetivo `sync` al `Makefile`
    - `sync: uv run python scripts/app/sync_branches.py`, sin modificar `check`
    - _Requirements: 1.13, 1.14_
  - [ ]* 5.3 Escribir prueba de propiedad de la fila de Sincronización
    - **Property 26: Ida y vuelta de la fila de Sincronización**
    - **Validates: Requirements 1.13, 2.10**
    - Archivo: `tests/test_app_sync.py`
  - [ ]* 5.4 Escribir pruebas de ejemplo de la Sincronización en un repo temporal
    - Repo `git init` local con `main` y dos ramas: crea la rama, dos merges con dos padres, SHA y fila registrados, sin `push`
    - Conflicto deliberado: código 1 y merge en curso
    - Revisión con `ast` de que ninguna llamada a `git` incluye `push`, `rebase`, `--squash`, `--force` ni `reset`
    - _Requirements: 1.2, 1.12, 1.13_

- [x] 6. Checkpoint - Bitácora, planificación, contratos y sincronización
  - Ejecutar `make check`; revisar los modos de falla del diseño que aplican (conflicto que rerere no resuelve, resolución reaplicada que rompe reglas, `origin/main` que avanza, deriva de contrato con Daniel y con Nico) y registrar hallazgos en la Bitácora_Progreso.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Adaptador del Lago_Datos
  - [ ] 7.1 Implementar `scripts/app/awsauth.py`
    - `CredentialsError` y `check(profile)` con `sts:GetCallerIdentity`; mensaje con el nombre del perfil (`default` si es `None`)
    - _Requirements: 4.11, 8.12_
  - [ ] 7.2 Implementar `scripts/app/lake.py`
    - `Lake`, `LocalLake`, `S3Lake` (s3fs con perfil, `awsauth.check` previo, descarga a temporal y renombrado en caché, Zarr con `fs.get(recursive=True)`), `open_lake` y las funciones de rutas relativas usando solo `lake_layout`
    - _Requirements: 4.5, 4.11, 9.15_
  - [ ] 7.3 Implementar las funciones ERA5 puras en `scripts/app/adapter.py`
    - `harmonize_cds` (renombrado, `number`/`expver` fuera, `provenance = "ERA5T"` si `expver == 5`), `select_store`, `check_era5` (variables, niveles, dimensiones, fracción de NaN contra umbral) y `era5_indices` (`process_era5.process_day(ds, ds, reg)` con `attrs` de nota y procedencia)
    - Sin literales de prefijos ni niveles propios
    - _Requirements: 4.1, 4.2, 4.8, 4.9_
  - [ ] 7.4 Implementar las funciones GOES puras en `scripts/app/adapter.py`
    - `decode_c13`, `encode_c13`, `group_hours`, `check_goes` (forma nativa = `GOES_SHAPE`, advertencia por hora vacía) y `goes_hours` (`mask_and_scale=False`, `nearest_index` una vez por día, `reproject` por hora)
    - _Requirements: 4.3, 4.4, 4.7, 4.9, 4.14_
  - [ ] 7.5 Implementar `process_day`, el Reporte_Calidad y `main` en `scripts/app/adapter.py`
    - Omisión si ya existe sin errores (salvo `--force`), `era5_store` con caída a `era5_cds_year`, Zarr ilegible como `era5_store_unreadable`, `source_missing` si no hay origen, escrituras atómicas y reporte siempre al final
    - Un día con error no detiene los siguientes; código distinto de cero solo ante credenciales o argumentos inválidos
    - CLI: `--source`, `--profile`, `--start`, `--end`, `--region`, `--out`, `--nan-threshold`, `--force`, `--cache`
    - _Requirements: 4.5, 4.6, 4.9, 4.10, 4.11, 4.12, 4.13_
  - [ ] 7.6 Extender `tests/app_synthetic.py` con generadores ERA5 y GOES
    - Datasets ERA5 pequeños con estructura `era5_store` y `era5_cds_year` equivalentes, y GOES int16 con `scale_factor`, `add_offset`, `_FillValue` y forma configurable
    - _Requirements: 9.2_
  - [ ]* 7.7 Escribir prueba de propiedad de ida y vuelta GOES
    - **Property 4: Ida y vuelta de la codificación GOES**
    - **Validates: Requirements 4.4, 4.14**
    - Archivo: `tests/test_app_adapter.py`
  - [ ]* 7.8 Escribir prueba de propiedad de confluencia ERA5
    - **Property 5: Confluencia de orígenes ERA5**
    - **Validates: Requirements 4.2, 4.15**
  - [ ]* 7.9 Escribir prueba de propiedad de verificaciones ERA5
    - **Property 6: Verificaciones ERA5 del Reporte_Calidad**
    - **Validates: Requirements 4.8, 4.9**
  - [ ]* 7.10 Escribir prueba de propiedad de horas GOES faltantes
    - **Property 7: Horas GOES faltantes**
    - **Validates: Requirements 4.3, 4.7**
  - [ ]* 7.11 Escribir pruebas unitarias del Adaptador
    - `era5_idx` con las 12 `ERA5_FEATURES`, reporte completo, día sin origen con continuidad, credenciales inválidas sin escrituras, fallo de `os.replace`, omisión y `--force`, S3 frente a local con `LocalFileSystem` de fsspec, grilla nativa distinta de 882 × 466
    - _Requirements: 4.1, 4.5, 4.6, 4.9, 4.10, 4.11, 4.12, 4.13_

- [ ] 8. Checkpoint - Adaptador
  - Ejecutar `make check`; revisar los modos de falla del diseño (credenciales expiradas, día GOES incompleto, ERA5 con NaN, Zarr escrito a medias, ERA5T, índices de capa baja burdos) y registrar hallazgos en la Bitácora_Progreso.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Ejecutor_Inferencia y lectura de predicciones
  - [ ] 9.1 Implementar `scripts/app/stub_model.py`
    - `CAPE_REF`, `SHEAR_REF`, `REQUIRED`, `score` (monótona, en [0, 1], NaN → 0) y `predict` con `OUTPUT_COLUMNS` y `config = "sustituto/<config>"`
    - _Requirements: 5.4, 5.7, 5.8_
  - [ ] 9.2 Implementar `scripts/app/predictions.py`
    - `SCHEMA`, `Predictions`, `InvalidPredictions`, `meta_path` y `load` (columnas exactas, `probability` en [0, 1] sin NaN, `hour_utc` 0–23, fecha AAAA-MM-DD, sin duplicados, metadatos con `modelo` válido)
    - _Requirements: 6.10, 7.13_
  - [ ] 9.3 Implementar `scripts/app/infer.py`
    - `choose_model` (real, sustituto o `InferError` con artefactos faltantes), `run` (importa `model_fn`/`predict_fn` de `sm_job/inference.py`; sustituto valida clave + `REQUIRED`), `to_csv_bytes` con `output_fn`, `metadata` y `main` (`--table`, `--model-dir`, `--out-dir`, `--config`, por defecto `baseline_era5`)
    - Todo se valida en memoria antes de escribir; CSV y `.meta.json` atómicos; mensajes que nombran archivos corruptos o columnas faltantes
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.9, 5.10, 5.11, 5.12_
  - [ ] 9.4 Extender `tests/app_synthetic.py` con Tablas_Inferencia, CSV_Predicciones y configuraciones de alertas
    - Generadores con semilla para tablas con NaN/infinitos/negativos, CSV válidos con metadatos y configuraciones de zonas, reglas y destinos
    - _Requirements: 9.2_
  - [ ]* 9.5 Escribir prueba de propiedad del Modelo_Sustituto
    - **Property 10: Modelo_Sustituto monótono y con NaN en cero**
    - **Validates: Requirements 5.7, 5.8**
    - Archivo: `tests/test_app_infer.py`
  - [ ]* 9.6 Escribir prueba de propiedad de conservación de filas
    - **Property 8: Conservación de filas en la inferencia**
    - **Validates: Requirements 5.3, 5.4, 5.5**
  - [ ]* 9.7 Escribir prueba de propiedad de columnas faltantes
    - **Property 9: Columnas faltantes en la inferencia**
    - **Validates: Requirements 5.6**
  - [ ]* 9.8 Escribir prueba de propiedad de determinismo
    - **Property 11: Determinismo de la inferencia**
    - **Validates: Requirements 5.9**
  - [ ]* 9.9 Escribir pruebas unitarias del Ejecutor_Inferencia
    - Paridad con `inference.predict_fn` usando un XGBoost de 5 árboles en memoria, ruta inexistente → sustituto, los 6 subconjuntos de artefactos parciales, Parquet y `model.json` corruptos, CSV previo intacto ante falla, NaN sin imputar al Modelo_Real
    - _Requirements: 5.1, 5.2, 5.7, 5.10, 5.11, 5.12_

- [ ] 10. Generador_Sitio y plantilla del sitio
  - [ ] 10.1 Crear `scripts/app/site_template/`
    - `index.html` con `<select id="day">` y `<input type="range" id="hour">` con `<label>`, descargo fijo en `<header>` sticky, `#stub-badge`, leyenda viridis de 5 intervalos, `#no-data` con `role="status"` y lista accesible de eventos
    - `app.js`: carga `days/index.json`, caché por día, `L.rectangle` sobre `L.canvas()` compartido, marcadores `L.divIcon` enfocables, sin `eval` ni `innerHTML` con datos (`textContent`)
    - `style.css` con contraste ≥ 4,5:1; Leaflet 1.9.4 vendorizado en `vendor/leaflet/` (`leaflet.js`, `leaflet.css`)
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.11, 6.15_
  - [ ] 10.2 Implementar `scripts/app/build_site.py`
    - `DEMO_DAY`, `day_payload`, `payload_rows`, `read_catalog` (hoja `Final_Table`, `viewer_app.data.coordinate`), `catalog_by_day`, `default_day`, `build` y `main` (CSV o `--pred-dir`, `--catalog`, `--out`, límite de 366)
    - Valida todos los CSV primero, omite inválidos con motivo en stderr, ninguno válido → código distinto de cero sin tocar la salida; arma en directorio temporal hermano y lo intercambia; día repetido → gana el `generado` más reciente con aviso; catálogo ausente → advertencia con la ruta
    - _Requirements: 6.1, 6.3, 6.4, 6.9, 6.10, 6.12, 6.13, 6.14_
  - [ ]* 10.3 Escribir prueba de propiedad de validación de CSV_Predicciones
    - **Property 12: Validación de CSV_Predicciones**
    - **Validates: Requirements 6.10, 7.13**
    - Archivo: `tests/test_app_site.py`
  - [ ]* 10.4 Escribir prueba de propiedad de ida y vuelta CSV → JSON
    - **Property 13: Ida y vuelta CSV → JSON del sitio**
    - **Validates: Requirements 6.12**
  - [ ]* 10.5 Escribir prueba de propiedad de la estructura del índice
    - **Property 14: Estructura del índice del sitio**
    - **Validates: Requirements 6.1, 6.3, 6.9**
  - [ ]* 10.6 Escribir prueba de propiedad de eventos por día
    - **Property 15: Eventos del catálogo por día**
    - **Validates: Requirements 6.4**
  - [ ]* 10.7 Escribir pruebas unitarias del sitio
    - Instantánea de `index.html` (descargo, leyenda y colores, `<label>`, `#stub-badge`, `#no-data`), contraste WCAG de los pares de `style.css`, ningún CSV válido deja la salida intacta, catálogo ausente
    - _Requirements: 6.5, 6.6, 6.7, 6.8, 6.11, 6.13, 6.14_

- [ ] 11. Checkpoint - Inferencia y sitio
  - Ejecutar `make check`; revisar los modos de falla del diseño (cambio de esquema de Daniel o `physical` sin C08, artefactos parciales o corruptos, día vacío, coordenadas del catálogo como texto, catálogo ausente, JSON grande, concurrencia) y registrar hallazgos en la Bitácora_Progreso.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Motor_Alertas y destinos
  - [ ] 12.1 Implementar `scripts/app/geo.py`
    - `Zone`, `ConfigError`, `validate_zone` (caja con mínimo < máximo, polígono ≥3 vértices sin autointersección, coordenadas en rango) y `contains` vectorizado con borde inclusivo
    - _Requirements: 7.1, 7.10_
  - [ ] 12.2 Implementar la lógica pura de `scripts/app/alerts.py`
    - `Rule`, `Alert`, `Config`, `load_config` (umbral [0, 100], ventana [0, 168] con 6 por defecto, destinos conocidos, zonas válidas; mensaje que nombra el elemento), `candidates` (máx × 100 > umbral, `index_max` a 1 decimal, orden por zona, fecha, hora), `suppress` (omite si `L <= t < L + ventana`) y `evaluate`
    - _Requirements: 7.1, 7.2, 7.3, 7.8, 7.10, 7.11, 7.12, 7.14, 7.15_
  - [ ] 12.3 Implementar `scripts/app/sinks.py`
    - `ConsoleSink`, `FileSink` (agrega con `open('a')` bajo `atomic.locked`), `SnsEmailSink` (cliente diferido), `WhatsAppStub` (stderr "WhatsApp no habilitado en v1", sin red) y `build_sinks` (`[]` → consola)
    - _Requirements: 7.4, 7.5, 7.6, 7.7_
  - [ ] 12.4 Implementar `main` de `scripts/app/alerts.py` y `configs/alerts.json`
    - Orden: configuración → predicciones (`predictions.load`) → estado bajo `atomic.locked` → `evaluate` → entrega por destino sin reintentos con fallos en stderr → estado atómico → código 1 si hubo fallos; zonas sin datos registradas
    - `awsauth.check` solo si hay `sns_email`; CLI `--pred`, `--config`, `--state`, `--profile`
    - `configs/alerts.json` con cajas aproximadas por región, una regla y destinos `archivo` y `consola`
    - _Requirements: 7.3, 7.4, 7.9, 7.13, 7.14, 7.15_
  - [ ]* 12.5 Escribir prueba de propiedad de validación de configuración
    - **Property 23: Validación de la configuración de alertas**
    - **Validates: Requirements 7.10**
    - Archivo: `tests/test_app_alerts.py`
  - [ ]* 12.6 Escribir prueba de propiedad de candidatas contra un modelo de referencia
    - **Property 16: Candidatas de alerta según un modelo de referencia**
    - **Validates: Requirements 7.1, 7.8, 7.14**
  - [ ]* 12.7 Escribir prueba de propiedad del invariante de supresión
    - **Property 17: Invariante de supresión**
    - **Validates: Requirements 7.2**
  - [ ]* 12.8 Escribir prueba de propiedad de idempotencia
    - **Property 18: Idempotencia del Motor_Alertas**
    - **Validates: Requirements 7.11**
  - [ ]* 12.9 Escribir prueba de propiedad de monotonía del umbral
    - **Property 19: Monotonía del umbral**
    - **Validates: Requirements 7.12**
  - [ ]* 12.10 Escribir prueba de propiedad de encadenamiento del estado
    - **Property 20: Encadenamiento del estado de supresión**
    - **Validates: Requirements 7.15**
  - [ ]* 12.11 Escribir prueba de propiedad de agregado JSONL
    - **Property 21: Agregado JSONL sin pérdida**
    - **Validates: Requirements 7.5**
  - [ ]* 12.12 Escribir prueba de propiedad de aislamiento de fallos
    - **Property 22: Aislamiento de fallos de destinos**
    - **Validates: Requirements 7.9**
  - [ ]* 12.13 Escribir pruebas unitarias del Motor_Alertas
    - Sin destinos → consola, `whatsapp` con `socket.socket` parcheado, `sns_email` con cliente `boto3` mock, `configs/alerts.json` del repo válido, CSV inválido sin entregas
    - _Requirements: 7.3, 7.4, 7.6, 7.7, 7.13_

- [ ] 13. Checkpoint - Motor_Alertas
  - Ejecutar `make check`; revisar los modos de falla del diseño (destino SNS caído, configuración inválida, credenciales expiradas con `sns_email`, ejecuciones concurrentes sobre estado y JSONL) y registrar hallazgos en la Bitácora_Progreso.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 14. Orquestador
  - [ ] 14.1 Implementar `scripts/app/run_day.py`
    - Encadena `adapter.process_day` → `build_table.main(["--stage", "infer", ...])` (con `extract_goes_features.main` solo si `config != baseline_era5`) → `infer` → `build_site` → `alerts` por cada CSV nuevo
    - Entrada `en_curso` y luego `hecho` o `bloqueado` por paso; ante `MissingColumnsError` sugiere `--config baseline_era5`
    - CLI: `--source`, `--profile`, `--start`, `--end`, `--config`, `--model-dir`, `--skip-site`, `--skip-alerts`
    - _Requirements: 2.1, 4.10, 5.6, 9.7_

- [ ] 15. Terraform del sitio y despliegue
  - [ ] 15.1 Agregar `infra/terraform/site.tf` y las ediciones acotadas
    - `site.tf`: `locals { site_prefix = "sitio/" }` y output `site_url`, con el proveedor por defecto
    - `s3.tf`: `Resource` de `AllowCloudFrontReadResults` como lista con `resultados/*` y `sitio/*`, sin otros cambios
    - `cloudfront.tf`: un `ordered_cache_behavior` `/sitio/*` hacia `results-s3`, `redirect-to-https`, GET/HEAD/OPTIONS, `compress = true`, después de `/resultados/*`
    - `infra/terraform/README.md`: sección "Sitio público sin autenticación"
    - No tocar `sagemaker.tf`, `outputs.tf`, `versions.tf`, `variables.tf` ni `training.tf`
    - Si `terraform` está instalado, `terraform -chdir=infra/terraform init -backend=false && terraform validate`; si no, anotarlo en la bitácora
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.10, 8.13, 8.14_
  - [ ] 15.2 Implementar `scripts/app/deploy_site.py`
    - `CONTENT_TYPES`, `plan_uploads` (error con archivo y extensión), `tf_outputs`, `upload` (aborta al primer fallo nombrando el archivo), `invalidate` (`/sitio/*`, imprime el Id)
    - Subcomando `infra`: `awsauth.check` → `terraform plan -out=tfplan` → confirmación escrita "sí" → `terraform apply tfplan`; sin confirmación, "sin cambios aplicados" y código 0
    - Subcomando `upload`: extensiones → credenciales → subida → invalidación → URL `https://<dominio>/sitio/index.html`
    - _Requirements: 8.5, 8.6, 8.7, 8.8, 8.9, 8.11, 8.12_
  - [ ]* 15.3 Escribir prueba de propiedad del plan de subida
    - **Property 24: Plan de subida del sitio**
    - **Validates: Requirements 8.5, 8.6**
    - Archivo: `tests/test_app_deploy.py`
  - [ ]* 15.4 Escribir pruebas unitarias del despliegue con mocks
    - Clientes S3 y CloudFront mock: invalidación solo tras subida completa, fallo de subida sin invalidación, `input` con "no" sin `terraform apply`, credenciales inválidas antes de subir
    - _Requirements: 8.7, 8.8, 8.11, 8.12_
  - [ ]* 15.5 Escribir pruebas de texto de Terraform en `tests/test_app_terraform.py`
    - `test_single_bucket_policy`, política con `resultados/*` y `sitio/*`, un único `ordered_cache_behavior` `/sitio/*`, `site_url` en `site.tf` y no en `outputs.tf`
    - _Requirements: 8.1, 8.2, 8.3, 8.13, 8.14_

- [ ] 16. Pruebas de repositorio y extremo a extremo
  - [ ] 16.1 Crear `tests/test_app_repo.py`
    - Sin marcadores de conflicto en `git ls-files`, dependencias de `pyproject.toml` fijadas con `==`, cada `scripts/<área>/*.py` con `main` y `argparse` responde a `--help` con código 0 (`subprocess` con tiempo límite), encabezados obligatorios de `docs/planificacion_merge.md`
    - Confirmar que `tests/test_docs.py` de Daniel corre sin cambios
    - _Requirements: 1.3, 1.9, 2.6, 9.6, 9.16_
  - [ ] 16.2 Crear `tests/test_app_e2e.py`
    - Lago_Datos local temporal (Zarr 3 × 3 con 2 horas y una celda con CAPE y cizalladura altas; GOES con forma reducida por parámetro) → `adapter` → `build_table` (`main` o `run` con raíces temporales) → `infer` (sustituto) → `build_site` → `alerts` con destino `archivo` y umbral bajo
    - Verifica `index.html` y al menos una Alerta en el JSONL; con `NoNetworkMixin`
    - _Requirements: 9.2, 9.4, 9.9_

- [ ] 17. Checkpoint final de implementación
  - Ejecutar `make check` y medir la duración de `unittest` (≤ 300 s); revisar toda la tabla de Error Handling del diseño y registrar hallazgos en la Bitácora_Progreso.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 9.1, 9.8, 9.10_

- [ ] 18. Sincronización final
  - [ ] 18.1 Ejecutar `make sync` contra las cabezas vigentes
    - Resolver a mano los conflictos que rerere no resuelva (`--continue`), revisar las resoluciones reaplicadas y usar `git rerere forget <archivo>` si rompen reglas
    - Si existe `terraform`, repetir `terraform validate` con `sagemaker.tf` presente
    - `make check` con código 0 sobre el commit resultante; nueva fila en la tabla de Sincronizaciones y Entrada_Bitácora
    - No hacer push
    - _Requirements: 1.2, 1.6, 1.7, 1.9, 1.10, 1.13, 1.14, 2.10, 8.14_

- [ ] 19. Publicación de la rama y PR (requiere confirmación explícita del usuario)
  - [ ] 19.1 Publicar `merge/datos-modelo`
    - **Pedir confirmación al usuario antes de ejecutar.** Solo si 18.1 dejó `make check` en código 0
    - `git push -u origin merge/datos-modelo`
    - _Requirements: 1.1, 1.6, 1.10_
  - [ ] 19.2 Abrir el PR hacia `main`
    - **Pedir confirmación al usuario antes de ejecutar.**
    - `gh pr create --base main` con título de menos de 70 caracteres y descripción con cambios, pruebas y pendientes
    - _Requirements: 1.7, 1.10, 1.14_

- [ ] 20. Despliegue en AWS (requiere confirmación explícita del usuario)
  - [ ] 20.1 Aplicar Terraform del sitio
    - **Pedir confirmación al usuario antes de ejecutar** e indicar el perfil: `default` = cuenta hackathon 822870558093; `gpu` = 905418466452. Las credenciales pueden estar expiradas: si `awsauth.check` falla, pedir al usuario que las renueve
    - `uv run python scripts/app/deploy_site.py infra --profile <perfil>`; revisar que el plan solo cambie la política del bucket de datos y la distribución
    - _Requirements: 8.1, 8.2, 8.3, 8.11, 8.12_
  - [ ] 20.2 Subir el sitio e invalidar la caché
    - **Pedir confirmación al usuario antes de ejecutar.**
    - `uv run python scripts/app/deploy_site.py upload --site data/app/site --profile <perfil>`; registrar el Id de invalidación y la URL `https://<dominio>/sitio/index.html` en la Bitácora_Progreso
    - _Requirements: 8.5, 8.7, 8.8, 8.9, 8.12_

## Notes

- Las sub-tareas con `*` son opcionales y pueden saltarse para un MVP más rápido. Las pruebas de contrato (4.3), de repositorio (16.1) y extremo a extremo (16.2) no son opcionales porque la Puerta_Calidad las exige (Req. 9.4, 9.6 y 9.11–9.16).
- Las tareas 19 y 20 nunca se ejecutan sin confirmación explícita del usuario.
- Las verificaciones manuales del diseño (navegador, `curl -I` con 403 fuera de los prefijos, `terraform plan`) quedan fuera de este plan.
- Cada tarea referencia criterios específicos para trazabilidad; los checkpoints validan de forma incremental.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1", "4.1", "4.2"] },
    { "id": 3, "tasks": ["2.2", "4.3", "5.1"] },
    { "id": 4, "tasks": ["2.3", "2.6", "4.4", "5.2", "5.3"] },
    { "id": 5, "tasks": ["2.4", "5.4", "7.1", "7.3", "7.6"] },
    { "id": 6, "tasks": ["2.5", "7.2", "7.4", "9.1", "9.2"] },
    { "id": 7, "tasks": ["2.7", "7.5", "7.7", "9.3", "10.1"] },
    { "id": 8, "tasks": ["7.8", "9.4", "10.2", "12.1"] },
    { "id": 9, "tasks": ["7.9", "9.5", "10.3", "12.2"] },
    { "id": 10, "tasks": ["7.10", "9.6", "10.4", "12.3"] },
    { "id": 11, "tasks": ["7.11", "9.7", "10.5", "12.4"] },
    { "id": 12, "tasks": ["9.8", "10.6", "12.5", "14.1", "15.1"] },
    { "id": 13, "tasks": ["9.9", "10.7", "12.6", "15.2"] },
    { "id": 14, "tasks": ["12.7", "15.3", "15.5"] },
    { "id": 15, "tasks": ["12.8", "15.4", "16.1"] },
    { "id": 16, "tasks": ["12.9", "16.2"] },
    { "id": 17, "tasks": ["12.10"] },
    { "id": 18, "tasks": ["12.11"] },
    { "id": 19, "tasks": ["12.12"] },
    { "id": 20, "tasks": ["12.13"] },
    { "id": 21, "tasks": ["18.1"] },
    { "id": 22, "tasks": ["19.1", "20.1"] },
    { "id": 23, "tasks": ["19.2", "20.2"] }
  ]
}
```
