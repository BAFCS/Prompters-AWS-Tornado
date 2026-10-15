# Planificación del merge `merge/datos-modelo`

Integración de `intentos-nico` (lago de datos, Nico) y `feat/multimodal-tornado-predictor-wip` (predictor, Daniel) en una rama nueva desde `main`, más una v1 de la aplicación de favorabilidad de tornados (sitio estático y alertas en modo demo). Spec: `.kiro/specs/merge-tornado-alert-app/`.

## Flujo

```
Lago_Datos → Adaptador → Tabla_Inferencia → Ejecutor_Inferencia → CSV_Predicciones ─┬→ Generador_Sitio
                                                                                     └→ Motor_Alertas
```

| # | Componente | Entrada | Salida |
|---|---|---|---|
| 1 | Lago_Datos (rama de Nico) | Descargas ERA5 (CDS/NCAR) y GOES-16 C13 | `era5_store/era5_AAAAMMDD.zarr`, `era5_cds_year/<AAAA>/<MM>/era5_{pl,sfc}_AAAAMMDD.nc`, `goes_store/<AAAA-MM-DD>/goes_AAAAMMDD.nc` |
| 2 | Adaptador (`scripts/app/adapter.py`) | Un día del Lago_Datos (S3 o directorio local) | `era5_indices/era5_idx_AAAAMMDD.nc`, `goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` y Reporte_Calidad `quality_AAAAMMDD.json` |
| 3 | Tabla_Inferencia (`build_table.py --stage infer`, rama de Daniel) | Entradas_Modelo de los Días_Utilizables | `inference/config=<config>/date=AAAA-MM-DD/part-0.parquet` |
| 4 | Ejecutor_Inferencia (`scripts/app/infer.py`) | Tabla_Inferencia + Modelo_Real o Modelo_Sustituto | CSV_Predicciones + metadatos (`modelo`, fecha de generación) |
| 5 | CSV_Predicciones | Salida del Ejecutor_Inferencia | `probability,date,hour_utc,latitude,longitude,config` |
| 6 | Generador_Sitio (`scripts/app/build_site.py`) | CSV_Predicciones + Catálogo `data/tornados_chile.xlsx` | Sitio_Estático (HTML, JS, Leaflet vendorizado, un JSON por día) |
| 7 | Motor_Alertas (`scripts/app/alerts.py`) | CSV_Predicciones + configuración de Reglas_Alerta y Zonas_Alerta | Alertas a `consola`, `archivo` (JSONL), `sns_email` (opcional) y `whatsapp` (stub) |

Generador_Sitio y Motor_Alertas leen el mismo CSV_Predicciones de forma independiente: ninguno depende de la salida del otro y pueden ejecutarse en cualquier orden.

## Decisiones

| Fecha | Decisión | Motivo |
|---|---|---|
| 2026-10-15 | Rama nueva `merge/datos-modelo` desde `origin/main` (cf59a73) | Revisar la integración en un PR sin tocar `main` ni las ramas de origen. |
| 2026-10-15 | Adaptador como módulo separado | Mejor arquitectura y eficiencia: conecta ambas ramas sin reescribir el código de Nico ni el de Daniel. |
| 2026-10-15 | Sitio estático en S3 + CloudFront con alertas en modo demo | Sin servidor que mantener; WhatsApp real queda fuera de la v1. |
| 2026-10-15 | `boto3==1.43.75` | Conflicto entre `>=` y `==` en `pyproject.toml`; se fija la versión resuelta en `uv.lock`. |
| 2026-10-15 | Todas las dependencias fijadas con `==` según `uv.lock` | Req. 1.3: versiones exactas y reproducibles (ver pregunta P9). |
| 2026-10-15 | `[tool.pyright] extraPaths` como unión de ambas ramas | Cada rama agregaba rutas propias; la unión mantiene pyright verde para ambos códigos. |
| 2026-10-15 | Configuración por defecto `baseline_era5` | `goes_store` solo trae C13 y `physical` necesita C08 (`goes_wv_ir_max` quedaría NaN). |
| 2026-10-15 | `git rerere` activado | Las Sincronizaciones repiten los mismos conflictos; rerere reutiliza la resolución. |
| 2026-10-15 | Cambios locales del usuario al Makefile de diagramas guardados en `stash@{0}` | Árbol limpio para el merge sin perder ese trabajo. No se toca el stash. |
| 2026-10-15 | Integrar `adapter-bucket`; su `sync_from_bucket.py` reemplaza las tareas 7.2–7.5 | Ya probado con datos reales; evita duplicar el adaptador. |
| 2026-10-15 | Prototipo `scripts/app/prototype.py` con Modelo_Sustituto | Necesidad de una demo funcional inmediata. |

## Preguntas abiertas

| # | Pregunta | Opciones consideradas | Componente afectado | Estado |
|---|---|---|---|---|
| P1 | ¿En qué región corre ML? | a) `us-east-1` (la cuenta del hackathon solo permite esta región); b) `us-west-2` (Daniel usa `ml_region = us-west-2` en `variables.tf`) | Despliegue, `sagemaker.tf`, Ejecutor_Inferencia | resuelta: a) `us-east-1` (`ml_region` validada a us-east-1) |
| P2 | ¿Cuál es la cuenta AWS de producción? | a) Hackathon 822870558093 (temporal, credenciales que expiran); b) cuenta gpu 905418466452 | Despliegue, Adaptador (origen S3) | abierta |
| P3 | ¿Se calibra el puntaje PU del modelo? | a) Mostrarlo como índice relativo sin calibrar (v1); b) calibrar (Platt/isotónica) con una prevalencia supuesta | Ejecutor_Inferencia, Generador_Sitio | abierta |
| P4 | ¿Qué umbrales de alerta usamos? | a) Umbral fijo único (p. ej. 50); b) umbral por zona; c) percentil histórico por zona | Motor_Alertas | abierta |
| P5 | ¿Cómo se definen las Zonas_Alerta? | a) Cajas lat/lon simples; b) polígonos de regiones administrativas de Chile; c) zonas de la historia climática de tornados | Motor_Alertas | abierta |
| P6 | ¿Qué falta para WhatsApp real? | a) WhatsApp Cloud API de Meta (cuenta Meta Business, número verificado, plantillas aprobadas, opt-in de destinatarios); b) proveedor intermedio (p. ej. Twilio) con los mismos requisitos; c) quedarse con `sns_email` | Motor_Alertas (Destino_Alerta `whatsapp`) | abierta |
| P7 | ¿El sitio necesita autenticación? | a) Público sin auth (v1); b) Cognito o Lambda@Edge con login; c) URL firmada de CloudFront | Despliegue, Sitio_Estático | abierta |
| P8 | Interacción entre la propiedad de subconjunto (Req. 7.12) y la supresión (Req. 7.2): subir el umbral puede hacer que se entregue una alerta que antes estaba suprimida | a) Verificar el subconjunto solo sobre candidatas y con ventana 0 (como está hoy); b) cambiar la semántica de supresión para que sea monótona | Motor_Alertas | abierta |
| P9 | ¿Fijamos con `==` también las dependencias heredadas de `main` (Req. 1.3)? | a) Fijar todo con `==` según `uv.lock` (aplicado hoy); b) fijar solo las dependencias nuevas y dejar `>=` en las heredadas | `pyproject.toml`, `uv.lock` | abierta |

## Errores conocidos

Errores del Lago_Datos (rama de Nico). El Adaptador no corrige el código de ingesta.

| Error | Mitigación en el Adaptador | Verificación del Reporte_Calidad |
|---|---|---|
| Días GOES incompletos marcados como completos | Cuenta escenas por hora y solo escribe `goes_latlon` para horas con ≥1 escena | `goes_hour_missing` (`advertencia` por hora vacía); forma nativa distinta de 466 × 882 → `error` |
| Ítems ERA5 con NaN marcados como completos | Calcula la fracción de NaN por variable; si supera `--nan-threshold` (0,05) no escribe `era5_idx` y el día no es utilizable | `era5_nan_fraction` (`error` si supera el umbral) |
| Escrituras Zarr no atómicas (Zarr a medias) | Captura el error de lectura o la falta de variables/niveles; usa `era5_cds_year` como alternativa si existe | `era5_store_unreadable` (`error`) y `era5_origin` indica el origen usado |
| Sobrescritura del JSON de progreso | El Adaptador no lee ese JSON: decide por la existencia y el contenido de los objetos | sin mitigación en v1 |
| `curate_granularity.py` incompatible con la estructura real | No se usa; el Adaptador lo reemplaza para esta ruta | sin mitigación en v1 |

## Riesgos

- **Bucket del Lago_Datos público (lectura anónima)**: cualquiera puede leer y generar costos de transferencia. Confirmar si es intencional o restringir con política de bucket.

| Riesgo | Impacto | Mitigación o aceptación |
|---|---|---|
| Sitio público sin autenticación | Cualquiera con la URL lo ve | Se acepta en v1. Se documenta en `infra/terraform/README.md`; el sitio no contiene credenciales ni datos personales (ver P7). |
| Sin eventos etiquetados en la ventana 2025-10-15 → 2026-09-30 | No se puede validar el modelo con eventos reales de esa ventana. Verificado: el Catálogo termina el 2025-05-25, hay 38 días con evento en la era GOES y solo 2019-05-30 está en el Lago_Datos | Se acepta en v1. La demo usa el Día_Demo 2019-05-30. |
| Uso del Modelo_Sustituto | El índice es heurístico (CAPE × cizalladura), no el modelo entrenado | Los metadatos marcan `modelo = sustituto` y el sitio y las alertas lo muestran con un descargo. Se reemplaza al tener artefactos del Modelo_Real. |
| Índices de capa baja con solo 6 niveles (1000–300 hPa) | `shear_01`, `srh_01`, `lcl` y `vgp_01` quedan suavizados | Se acepta en v1. Se anota en `attrs["note"]` de cada `era5_idx`. |
| Credenciales temporales que expiran (cuenta hackathon) | Adaptador o Despliegue fallan a mitad de una corrida | `awsauth.check` valida el perfil antes de escribir y termina con un mensaje que nombra el perfil; las salidas son atómicas. |

## Cambios al código de origen

Cambios en el commit de merge 44e9172, más allá de resolver conflictos (Req. 1.8):

| Archivo | Rama de origen | Cambio | Motivo |
|---|---|---|---|
| `scripts/ingest/ingest_cds_year.py`, `ingest_goes.py`, `ingest_goes_multiband.py`, `ingest_ncar_parallel.py`, `verif_cds_vs_ncar.py` | `intentos-nico` | Solo `ruff format` (espaciado), sin cambios de lógica | `make check` (ruff format --check) |
| `scripts/common.py` | ambas ramas / `main` | `# noqa: UP047` en `retry()` | El `TypeVar` es intencional: compatibilidad con Python 3.9 en EC2 |
| `pyproject.toml` | ambas ramas | `[tool.pyright] executionEnvironments` para `scripts/ingest` | `cdsapi` solo está instalado en EC2; pyright no debe exigirlo localmente |

| `scripts/model/build_sample_fast.py` | `adapter-bucket` | Anotaciones de tipo y `noqa: E402` | `make check` (ruff ANN001, pyright) |
| `scripts/model/bedrock_encoder.py` | `feat/multimodal-tornado-predictor-wip` | `.encode("utf-8", "surrogatepass")` en `cache_key` | La prueba de propiedad generaba texto con surrogates y fallaba con `UnicodeEncodeError` |

## Sincronización con ramas en movimiento

Las ramas de origen siguen avanzando, así que la integración se repite con `make sync` (`git merge --no-ff`, sin rebase, squash ni force-push, y sin push automático).

| Archivo compartido | Responsable |
|---|---|
| `infra/terraform/s3.tf` | Daniel / Bryan (por confirmar) |
| `infra/terraform/cloudfront.tf` | Daniel / Bryan (por confirmar) |
| `infra/terraform/outputs.tf` | Daniel / Bryan (por confirmar) |
| `infra/terraform/versions.tf` | Daniel / Bryan (por confirmar) |
| `infra/terraform/sagemaker.tf` | Daniel / Bryan (por confirmar) |
| `pyproject.toml` | Integrador de `merge/datos-modelo` |
| `uv.lock` | Integrador de `merge/datos-modelo` |
| `README.md` | Todos |

Acuerdo de coordinación: antes de modificar cualquiera de estos archivos se avisa al equipo en el canal del proyecto, indicando el archivo y el cambio. El integrador hace una Sincronización tras cada aviso de cambio fusionado. Los responsables "por confirmar" se ratifican en la próxima reunión y se registran como decisión con su fecha.

Modos de falla de `make sync` (`scripts/app/sync_branches.py`):

- Conflicto que `git rerere` no resuelve: termina con código 1, lista los archivos, deja el merge en curso y registra `bloqueado` en la Bitácora_Progreso. Se resuelve a mano, se hace `git add` y se retoma con `uv run python scripts/app/sync_branches.py --continue`.
- Resolución reaplicada por rerere que ya no respeta las reglas (p. ej. una versión con `>=` en `pyproject.toml` o un `extraPaths` incompleto): antes de abrir el PR se revisa `git rerere diff` en cada archivo que figuró como conflicto. Si la resolución guardada es incorrecta, `git rerere forget <archivo>` la descarta, se corrige a mano y se vuelve a correr `make check`.
- `origin/main` avanza durante la vuelta: el script vuelve a leerlo al final y termina con código 1 sin agregar fila; se repite la Sincronización.
- Marcadores de conflicto: se buscan líneas `<<<<<<<`, `=======` o `>>>>>>>` en archivos versionados. Un subrayado Markdown de exactamente siete `=` se detectaría como marcador; hoy ningún archivo versionado lo usa. Usar encabezados `#`.

### Sincronizaciones

| Fecha | SHA `intentos-nico` | SHA `feat/multimodal-tornado-predictor-wip` | SHA `origin/main` | Conflictos resueltos | Puerta_Calidad |
|---|---|---|---|---|---|
| 2026-10-15 | `ec238df` | `3cd882b` | `cf59a73` | `pyproject.toml` (boto3, extraPaths), `uv.lock` regenerado | `make check` OK (144 tests) |
| 2026-10-15 | `ec238df` | `3cd882b` (+ `adapter-bucket` `7274812`) | `cf59a73` | `pyproject.toml`/`uv.lock` (`zarr==3.4.1`) | `make check` OK (191 pruebas) |
