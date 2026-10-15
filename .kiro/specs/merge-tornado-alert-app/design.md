# Design Document

## Overview

La versión 1 une las ramas de Nico (lago de datos) y de Daniel (predictor) en `merge/datos-modelo` y agrega un área nueva `scripts/app/` con piezas pequeñas y reemplazables:

1. **Adaptador** (`adapter.py`): convierte un día del Lago_Datos en las Entradas_Modelo reutilizando `process_era5.process_day` y la lógica de `process_goes` (`nearest_index`, `reproject`, `save`). No toca el código de Nico ni el de Daniel.
2. **Tabla_Inferencia**: se genera con el `build_table.py --stage infer` de Daniel, sin cambios.
3. **Ejecutor_Inferencia** (`infer.py`): importa `model_fn`/`predict_fn` de `sm_job/inference.py` para el Modelo_Real (paridad exacta) y usa `stub_model.py` cuando no hay artefactos.
4. **Generador_Sitio** (`build_site.py`): produce HTML + JS vanilla + Leaflet (vendorizado) + un JSON por día.
5. **Motor_Alertas** (`alerts.py` + `sinks.py`): reglas por zona con supresión y destinos `consola`, `archivo`, `sns_email`, `whatsapp` (stub).
6. **Despliegue** (`deploy_site.py` + `infra/terraform/site.tf` nuevo y dos cambios acotados en `s3.tf` y `cloudfront.tf`): sitio bajo `sitio/` del bucket existente, detrás de la distribución CloudFront existente.
7. **Bitácora_Progreso** (`progress_log.py`): JSON de solo agregado en `docs/logs/progreso.json`.
8. **Sincronización** (`sync_branches.py` + `make sync`): procedimiento repetible que vuelve a integrar las ramas en movimiento sin hacer push nunca.
9. **Pruebas de contrato** (`lake_layout.py` + `contracts.py` + `tests/test_app_contracts.py`): detectan deriva entre nuestro código y las interfaces de Nico y Daniel sin red ni AWS.

Principios de la v1: todo en UTC, todo archivo de salida se escribe de forma atómica, funciones puras separadas de la E/S (para pruebas con datos sintéticos y sin red), sin dependencias nuevas salvo `boto3`, que ya declaran ambas ramas.

### Hallazgos de la investigación que condicionan el diseño

Revisé los archivos de las ramas remotas en modo de solo lectura con `raw.githubusercontent.com`:

- `scripts/model/sm_job/inference.py` (Daniel): `model_fn(model_dir) -> Bundle` lee `feature_columns.json` con las claves `required`, `model` y `embedding`, `config.json` con `config` y, si existe, `reducer.npz`. `predict_fn(df, bundle)` valida con `validate_schema` y lanza `MissingColumnsError(missing)` con todas las faltantes. Los NaN se pasan a XGBoost sin imputar. `OUTPUT_COLUMNS = (probability, date, hour_utc, latitude, longitude, config)`.
- `scripts/model/table.py`: `ERA5_FEATURES` incluye las 12 variables `cape, shear_01, shear_03, shear_06, srh_01, srh_03, lcl, gamma_03, gamma_75, vgp_01, stp_lm, sherbs3`. `CONFIGS = (baseline_era5, physical, embeddings)`. Solo `baseline_era5` funciona sin GOES (12 columnas ERA5 en t).
- `scripts/model/build_table.py --stage infer` lee `data/crops/<region>/era5_indices/era5_idx_AAAAMMDD.nc` y, en `physical`, `data/model/<region>/goes_features/goes_feat_AAAAMMDD.parquet`. Escribe `data/model/<region>/inference/config=<config>/date=AAAA-MM-DD/part-0.parquet`.
- `scripts/model/extract_goes_features.py` necesita las bandas **C08 y C13**, pero `goes_store` solo trae **C13**. Por eso `goes_wv_ir_max` queda NaN y la configuración `physical` no es plenamente utilizable con el Lago_Datos actual. **Decisión v1**: la configuración por defecto es `baseline_era5`. El Adaptador igual produce `goes_latlon` (Req. 4.3) para habilitar `physical` cuando exista C08.
- `docs/DATOS_AWS.md` (Nico): bucket de prueba en la cuenta 822870558093 (`us-east-1`, credenciales temporales). La grilla ERA5 es de 105 × 41 (lat −56..−30, lon −76..−66), igual a `common.REGIONS["south-central-austral"]`. GOES tiene 144 escenas por día en 882 × 466 píxeles. El tramo ago–sep 2026 viene de ERA5T (`expver=5`).
- `process_era5.process_day(pl, sfc, reg)` solo usa `pl["time"]`, `sfc["time"]`, `sel(time=t)` y los nombres `u,v,t,z,10u,10v,2t,2d,sp,cape`, con `level` como coordenada vertical. El Zarr de `era5_store` ya fusiona pl y sfc con esos nombres, así que se pasa el mismo Dataset como `pl` y `sfc`.
- `common.stamp(reg)` agrega `created = now()`, así que dos ejecuciones nunca son idénticas byte a byte. La igualdad S3/local (Req. 4.5) se define sobre los datos y atributos, sin contar `created`.
- `pyproject.toml`: ambas ramas agregan `boto3` (Daniel `==1.43.75`, Nico `>=1.43.75`). Daniel agrega `sagemaker==3.21.0`. El resto usa `>=`. El Req. 1.3 pide fijar todo con `==`, así que la integración fija cada dependencia a la versión que resuelve `uv.lock`.
- **Las ramas de origen se siguen moviendo.** Al revisar de nuevo (`git ls-remote`), `intentos-nico` sigue en `0167b08`, pero `feat/multimodal-tornado-predictor-wip` avanzó a `3cd882b`. Ese avance agrega:
  - `infra/terraform/sagemaker.tf` (191 líneas): bucket de artefactos `aws_s3_bucket.ml` en `us-west-2` con su propio bloqueo público, cifrado y una política `aws_s3_bucket_policy.ml_tls_only` **sobre ese bucket ML**; el rol `aws_iam_role.sagemaker_exec`, con una política inline que lee `aws_s3_bucket.data` (prefijo `data/*`) **por IAM**, sin política de bucket sobre el bucket de datos; y Bedrock y CloudWatch acotados.
  - `outputs.tf` (+10): outputs `ml_bucket` y `sagemaker_exec_role_arn`.
  - `versions.tf` (+15): proveedor `aws` con `alias = "ml"` y `region = var.ml_region`. `variables.tf` define `ml_region` (por defecto `us-west-2`) y `enable_cohere`.
  - `docs/modelo_predictor.md`, un enlace a ese documento en `README.md` y `tests/test_docs.py`, que exige ese enlace, entre otras verificaciones.
- Consecuencias para nuestro diseño:
  - `sagemaker.tf` no declara otra política sobre el bucket de datos, así que no compite con `aws_s3_bucket_policy.data_tls_only` de `s3.tf` (AWS admite una sola política por bucket, y dos recursos sobre el mismo bucket se pisarían en cada `apply`).
  - Sí depende del nombre `aws_s3_bucket.data`, que no debe cambiar.
  - Nuestro output `site_url` no choca con los nombres nuevos y va en `site.tf`, así que no tocamos `outputs.tf`.
  - Los recursos del sitio usan el proveedor por defecto (`us-east-1`), no `aws.ml`.
- Los SHA citados en este documento (`cf59a73` de `main`, `0167b08`, `7f6de80` y `3cd882b`) son **notas históricas** del momento de la redacción. El procedimiento nunca los usa como valores fijos: cada Sincronización registra los SHA vigentes y verifica contra ellos (Req. 1.1, 1.2 y 1.13).

### Limitaciones conocidas que la v1 acepta y documenta

- Con solo 6 niveles de presión (1000–300 hPa), los índices de capa baja (`shear_01`, `srh_01`, `lcl`, `vgp_01`) quedan muy suavizados: entre la superficie y 925 hPa no hay niveles intermedios. Se documenta en el Documento_Planificación y en `attrs["note"]` de cada `era5_idx`.
- El puntaje es PU (positivo-no etiquetado), no una probabilidad. La interfaz lo llama Índice_Favorabilidad.
- El catálogo trae la fecha del evento (`Date (Gregorian Calendar)`) y una hora UTC aparte. Un evento cerca de medianoche UTC puede quedar en el día equivocado. La v1 usa la columna de fecha tal cual.

## Architecture

```mermaid
flowchart LR
    subgraph Lago_Datos["Lago_Datos (S3 o directorio local)"]
        ES[era5_store/era5_AAAAMMDD.zarr]
        EC[era5_cds_year/AAAA/MM/era5_pl|sfc_AAAAMMDD.nc]
        GS[goes_store/AAAA-MM-DD/goes_AAAAMMDD.nc]
    end
    ES --> AD[adapter.py]
    EC --> AD
    GS --> AD
    AD --> EI[data/crops/region/era5_indices/era5_idx_AAAAMMDD.nc]
    AD --> GL[data/crops/region/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc]
    AD --> QR[data/app/quality/quality_AAAAMMDD.json]
    EI --> BT[build_table.py --stage infer<br/>rama de Daniel]
    GL -. solo config physical .-> GF[extract_goes_features.py]
    GF -.-> BT
    BT --> TI[Tabla_Inferencia part-0.parquet]
    TI --> IN[infer.py]
    MR[(Modelo_Real<br/>model.json, feature_columns.json,<br/>config.json, reducer.npz)] -.-> IN
    IN --> CSV[pred_AAAAMMDD.csv + .meta.json]
    CSV --> BS[build_site.py]
    CAT[data/tornados_chile.xlsx] --> BS
    BS --> SITE[data/app/site/<br/>index.html, app.js, style.css,<br/>vendor/leaflet, days/AAAA-MM-DD.json]
    SITE --> DEP[deploy_site.py]
    DEP --> S3[(S3 sitio/*)] --> CF[CloudFront /sitio/*]
    CSV --> AL[alerts.py]
    CFG[configs/alerts.json] --> AL
    ST[(data/app/alerts_state.json)] <--> AL
    AL --> SK{sinks.py}
    SK --> C1[consola]
    SK --> C2[archivo JSONL]
    SK --> C3[sns_email]
    SK --> C4[whatsapp stub]
```

`run_day.py` encadena los pasos de un rango de días. Cada paso también se puede ejecutar por separado con su propio CLI. Generador_Sitio y Motor_Alertas leen el mismo CSV_Predicciones de forma independiente: si uno falla, el otro no se ve afectado.

### Estructura de archivos nuevos

```
scripts/app/
  atomic.py          # escritura atómica y bloqueo de archivo (compartido)
  awsauth.py         # verificación de credenciales por perfil (sts:GetCallerIdentity)
  lake_layout.py     # ÚNICO módulo de constantes del Lago_Datos (prefijos, patrones, variables, niveles)
  lake.py            # Origen S3 o local con la misma estructura de prefijos
  contracts.py       # comparadores puros de contrato (símbolos, columnas, constantes)
  sync_branches.py   # Sincronización repetible (CLI; nunca hace push)
  adapter.py         # Adaptador + Reporte_Calidad (CLI)
  stub_model.py      # Modelo_Sustituto (puro)
  infer.py           # Ejecutor_Inferencia (CLI)
  predictions.py     # lectura/validación de CSV_Predicciones + metadatos (compartido)
  build_site.py      # Generador_Sitio (CLI)
  geo.py             # Zona_Alerta: validación y punto en polígono/caja
  alerts.py          # Motor_Alertas (CLI)
  sinks.py           # Destinos_Alerta
  progress_log.py    # Bitácora_Progreso (CLI)
  deploy_site.py     # Despliegue (CLI: subcomandos infra y upload)
  run_day.py         # orquestador (CLI)
  site_template/
    index.html, app.js, style.css
    vendor/leaflet/leaflet.js, leaflet.css   # Leaflet 1.9.4 vendorizado
configs/alerts.json                          # versionado
infra/terraform/site.tf                      # recursos y outputs del sitio (nuevo)
docs/planificacion_merge.md
docs/logs/progreso.json
tests/test_app_*.py, tests/test_app_contracts.py, tests/app_synthetic.py
Makefile                                     # objetivo nuevo `sync` (no modifica `check`)
```

Cada script sigue la convención del repo: docstring con uso, `sys.path.insert(0, ...)` para importar `common` y los módulos hermanos, `main(argv: list[str] | None = None)` con `argparse` y nombres en inglés con comentarios en español. Para importar el código de Daniel, `infer.py` agrega `scripts/model` y `scripts/model/sm_job` a `sys.path`, igual que hace `inference.py`.

### Decisiones de diseño

| Decisión | Elección | Motivo |
|---|---|---|
| Leaflet | Vendorizar 1.9.4 en `site_template/vendor/leaflet/` | El sitio no depende de un CDN externo (si unpkg no responde, el sitio sigue funcionando), no requiere SRI y permite una CSP `script-src 'self'`. Las teselas base de OpenStreetMap siguen siendo externas: si fallan, la grilla y los marcadores se ven igual sobre fondo gris. |
| Íconos de marcador | `L.divIcon` con CSS (sin PNG) | Evita las imágenes por defecto de Leaflet. `L.marker` es enfocable con Tab y responde a Enter, a diferencia de `circleMarker`. |
| Renderizado de celdas | `L.rectangle` con `L.canvas()` compartido | Son unas 4.305 celdas por hora. En canvas se redibujan en menos de 2 s (Req. 6.15). |
| Formato del JSON por día | Ejes `lats`/`lons` explícitos y un arreglo plano de enteros 0–10000 (`probability × 10⁴`) o `null` por hora | El redondeo a 4 decimales es exacto y la ida y vuelta es verificable. Pesa unos 500 KB por día sin comprimir y CloudFront comprime con `compress = true`. |
| Configuración de alertas | JSON (`configs/alerts.json`) | Se lee con la biblioteca estándar y no agrega dependencias. |
| Pruebas de propiedades | Bucles con `random.Random(seed)` y `numpy.random.default_rng(seed)` dentro de `unittest`, 100 casos por propiedad | Respeta la Puerta_Calidad actual (`unittest`) sin agregar `hypothesis`, y la semilla fija hace reproducible cada falla (Req. 9.5). |
| Configuración por defecto del modelo | `baseline_era5` | `goes_store` no tiene C08 (ver hallazgos). |
| Concurrencia | Escritura atómica (`os.replace`) en todas las salidas y `fcntl.flock` en un archivo `.lock` para las lecturas-modificaciones-escrituras (bitácora, estado de supresión, JSONL de alertas) | Dos ejecuciones simultáneas no dejan archivos parciales y no pierden entradas de la bitácora. |
| Descarga S3 | Se baja el objeto diario completo una vez a un caché temporal (unos 60 MB por día de GOES) | Es más rápido y robusto que hacer lecturas por rango con `h5netcdf`. Si se paraleliza, se usa `common.pool` (spawn). |
| Sincronización | Script `scripts/app/sync_branches.py` y objetivo `make sync` que lo llama | Las ramas de origen siguen avanzando, así que la integración se repite. Un script con pasos fijos deja el registro de SHA, bitácora y tabla igual en cada vuelta. Se detiene ante conflictos sin resolver y **nunca** hace push ni abre PR. |
| Constantes del Lago_Datos | Un solo módulo `scripts/app/lake_layout.py` | Si Nico cambia la estructura, hay un único lugar que actualizar, y la prueba de contrato compara ese módulo con lo documentado en `docs/DATOS_AWS.md` (Req. 9.15). |
| Terraform del sitio | `site.tf` nuevo; en archivos compartidos solo una entrada en la lista `Resource` de la política del bucket y un `ordered_cache_behavior` | `s3.tf`, `cloudfront.tf`, `outputs.tf` y `versions.tf` también cambian en la rama de Daniel. Cuanto menor sea nuestro cambio en ellos, menos conflictos habrá en cada Sincronización (Req. 8.13 y 8.14). |

## Components and Interfaces

### `atomic.py`

```python
def write_bytes(path: Path, data: bytes) -> None:
    """Escribe en un temporal del mismo directorio (tempfile.mkstemp), fsync y os.replace.
    Si algo falla, elimina el temporal y relanza la excepción; el archivo final no cambia."""
def write_text(path: Path, text: str) -> None
def write_json(path: Path, obj: object) -> None   # UTF-8, ensure_ascii=False, indent=2
def write_dataset(ds: xr.Dataset, path: Path, encoding: dict | None = None) -> None
    """common.write sobre un temporal '.tmp.nc' y luego os.replace."""
@contextmanager
def locked(path: Path) -> Iterator[None]:
    """fcntl.flock exclusivo sobre '<path>.lock' (se crea si falta)."""
```

### `awsauth.py`

```python
class CredentialsError(SystemExit): ...
def check(profile: str | None) -> str:
    """Llama a sts:GetCallerIdentity con botocore.session.Session(profile=profile).
    Devuelve el ARN; si las credenciales no existen o expiraron (NoCredentialsError,
    ExpiredToken*, ClientError), lanza CredentialsError con el nombre del perfil ('default' si None)."""
```

### `lake_layout.py` (constantes del Lago_Datos)

Es el único lugar donde viven los supuestos sobre la estructura de Nico (Req. 9.15). `lake.py` y `adapter.py` importan de aquí y no definen literales propios.

```python
ERA5_STORE_PREFIX = "era5_store"
ERA5_CDS_PREFIX = "era5_cds_year"
GOES_STORE_PREFIX = "goes_store"
ERA5_STORE_PATTERN = "era5_store/era5_{ymd}.zarr"                 # ymd = AAAAMMDD
ERA5_CDS_PATTERN = "era5_cds_year/{yyyy}/{mm}/era5_{kind}_{ymd}.nc"  # kind in {"pl", "sfc"}
GOES_STORE_PATTERN = "goes_store/{iso}/goes_{ymd}.nc"             # iso = AAAA-MM-DD
LEVELS = (1000, 925, 850, 700, 500, 300)
PL_VARS = ("u", "v", "t", "z")
SFC_VARS = ("10u", "10v", "2t", "2d", "sp", "cape")
DIMS = ("time", "level", "latitude", "longitude")
CDS_RENAME = {"valid_time": "time", "pressure_level": "level",
              "u10": "10u", "v10": "10v", "t2m": "2t", "d2m": "2d"}
CDS_DROP = ("number", "expver")
GOES_VAR = "C13"
GOES_SHAPE = (466, 882)            # (y, x) = 882 × 466 según DATOS_AWS.md
GOES_FILL = -1
# Salidas que espera el pipeline de Daniel
ERA5_IDX_PATTERN = "era5_indices/era5_idx_{ymd}.nc"
GOES_LATLON_PATTERN = "goes_latlon/{ymd}/goes_{ymd}{hh}.nc"
GOES_RES = 0.02
```

### `contracts.py` (comparadores puros de contrato)

```python
@dataclass(frozen=True)
class Drift: name: str; expected: object; found: object   # found = None si falta
def missing_symbols(source: str, names: Iterable[str]) -> list[str]
    """Analiza con ast.parse los nombres definidos a nivel de módulo (def, class, asignación,
    asignación anotada e import) y devuelve los de `names` que faltan, en el orden pedido."""
def tuple_constant(source: str, name: str) -> tuple | None
    """Valor literal (ast.literal_eval) de una asignación de módulo `name = (...)`; None si falta
    o no es literal."""
def sequence_drift(name: str, expected: Sequence, found: Sequence | None) -> list[Drift]
def missing_members(expected: Iterable[str], found: Iterable[str]) -> list[str]
def layout_drift(expected: Mapping[str, object], module: ModuleType) -> list[Drift]
    """Una Drift por cada constante de `expected` ausente en `module` o con valor distinto."""
def format_drift(drifts: list[Drift]) -> str
    """'constante X: esperado <e>, encontrado <f>' por línea (Req. 9.12 y 9.15)."""
```

Usa `ast` en lugar de importar `inference.py` y `build_table.py`, porque al importarlos se cargarían `xgboost` y `sagemaker` y se ejecutarían efectos de módulo. `table.ERA5_FEATURES` se lee con `tuple_constant` por la misma razón. La opción `--stage infer` se verifica ejecutando `build_table.py --help` con `subprocess` (sin red, con tiempo límite) y buscando `infer` en la salida. Si `--help` falla, la prueba cae al análisis `ast` de la llamada `add_argument("--stage", choices=...)`.

### `lake.py`

```python
class Lake(Protocol):
    def exists(self, rel: str) -> bool: ...
    def fetch(self, rel: str) -> Path: ...  # ruta local (copia en caché si es S3)
def open_lake(source: str, profile: str | None, cache: Path) -> Lake:
    """'s3://bucket[/prefijo]' -> S3Lake (s3fs con el perfil); otra cosa -> LocalLake(dir).
    S3Lake llama antes a awsauth.check (Req. 4.11)."""
# rutas relativas del Lago_Datos, armadas solo con los patrones de lake_layout
def era5_store_rel(day: dt.date) -> str        # era5_store/era5_AAAAMMDD.zarr
def cds_rel(day: dt.date, kind: str) -> str    # era5_cds_year/AAAA/MM/era5_{pl|sfc}_AAAAMMDD.nc
def goes_rel(day: dt.date) -> str              # goes_store/AAAA-MM-DD/goes_AAAAMMDD.nc
```

`S3Lake.fetch` descarga primero a un temporal y luego lo renombra dentro del caché. Para el Zarr usa `fs.get(recursive=True)` sobre un directorio temporal y luego lo renombra. Así, ambos orígenes entregan a las funciones puras el mismo archivo local, y eso garantiza el Req. 4.5.

### `adapter.py`

Funciones puras (sin E/S):

```python
from lake_layout import CDS_RENAME, GOES_SHAPE, LEVELS, PL_VARS, SFC_VARS  # sin literales locales

def harmonize_cds(pl: xr.Dataset, sfc: xr.Dataset) -> xr.Dataset:
    """Renombra según CDS_RENAME, elimina 'number' y 'expver' (registra expver en attrs
    'provenance' = 'ERA5T' si expver==5), fusiona pl+sfc y selecciona LEVELS."""
def select_store(ds: xr.Dataset) -> xr.Dataset:
    """Selecciona LEVELS de era5_store (mismo esquema de salida que harmonize_cds)."""
def check_era5(ds: xr.Dataset, nan_threshold: float) -> list[Check]:
    """Presencia de PL_VARS+SFC_VARS, de cada nivel de LEVELS y de las dims time/level/
    latitude/longitude; fracción de NaN por variable (error si > umbral)."""
def era5_indices(ds: xr.Dataset, reg: common.Region) -> xr.Dataset:
    """process_era5.process_day(ds, ds, reg) + attrs note (6 niveles) y provenance."""

def decode_c13(raw: np.ndarray, scale: float, offset: float, fill: int = -1) -> np.ndarray:
    """float64: raw*scale+offset; NaN donde raw == fill (Req. 4.4)."""
def encode_c13(values: np.ndarray, scale: float, offset: float, fill: int = -1) -> np.ndarray:
    """int16: round((v-offset)/scale); fill donde v es NaN."""
def group_hours(times: np.ndarray) -> dict[int, np.ndarray]:
    """Índices de escenas por hora UTC 0..23 (solo horas con ≥1 escena)."""
def check_goes(ds: xr.Dataset) -> list[Check]:
    """Dimensiones nativas == GOES_SHAPE (error si no); escenas por hora (advertencia por hora vacía)."""
def goes_hours(ds: xr.Dataset, reg: common.Region, res: float = 0.02,
               radius: float = ...) -> Iterator[tuple[int, xr.Dataset]]:
    """Decodifica C13 explícitamente (open con mask_and_scale=False), calcula UNA vez
    process_goes.nearest_index para el día y aplica process_goes.reproject por hora."""
```

Orquestación de un día:

```python
@dataclass
class DayResult:
    day: dt.date
    report: QualityReport
    era5_written: bool
    goes_hours_written: list[int]
    skipped: bool  # ya existía y su reporte no tenía errores (Req. 4.13)

def process_day(lake: Lake, day: dt.date, out_root: Path, reg: common.Region,
                nan_threshold: float = 0.05, force: bool = False) -> DayResult
def main(argv: list[str] | None = None) -> None
    # --source (s3://... o dir) --profile --start --end --region --out (por defecto common.CROPS)
    # --nan-threshold (0..1) --force --cache
```

Flujo de `process_day`:

1. Si el reporte previo no tiene errores, existen las salidas y no se pidió `--force`, omite el día.
2. Resuelve el origen ERA5: primero `era5_store` y, si no está, `era5_cds_year` (pl y sfc).
3. Ejecuta `check_era5`. Si hay error, no escribe `era5_idx`.
4. Revisa GOES con `check_goes`. Si la grilla no mide 882 × 466, no escribe `goes_latlon`. Si no, escribe un archivo por hora con al menos una escena, con `save` y la codificación int16 original (`scale_factor`, `add_offset`, `_FillValue`).
5. Escribe el Reporte_Calidad, siempre al final y de forma atómica.

Si no hay ningún origen, el reporte lleva `source_missing` con severidad `error` (Req. 4.10). Un error en un día no detiene los siguientes. El código de salida es 0 salvo en los errores fatales: credenciales y argumentos inválidos.

### `stub_model.py`

```python
CAPE_REF = 1000.0   # J/kg
SHEAR_REF = 25.0    # m/s (shear_06)
REQUIRED = ("cape", "shear_06")
def score(cape: np.ndarray, shear: np.ndarray) -> np.ndarray:
    """clip(cape/CAPE_REF, 0, 1) * clip(shear/SHEAR_REF, 0, 1); NaN en cualquiera -> 0.
    Monótona no decreciente en ambos argumentos, valores en [0, 1]."""
def predict(df: pd.DataFrame, config: str) -> pd.DataFrame:
    """Mismas columnas y orden que inference.predict_fn (OUTPUT_COLUMNS), config = 'sustituto/<config>'."""
```

### `infer.py`

```python
ARTIFACTS = ("model.json", "feature_columns.json", "config.json")
class InferError(SystemExit): ...
def choose_model(model_dir: Path | None) -> Literal["real", "sustituto"]:
    """Todos presentes -> 'real'; ninguno o ruta inexistente -> 'sustituto';
    algunos -> InferError con los faltantes (Req. 5.10)."""
def run(table: pd.DataFrame, kind: str, model_dir: Path | None, config: str) -> pd.DataFrame:
    """'real': inference.model_fn + inference.predict_fn (importados, sin copiar código).
    'sustituto': valida KEY_INPUT + stub_model.REQUIRED y llama a stub_model.predict.
    MissingColumnsError -> InferError con la lista completa (Req. 5.6)."""
def to_csv_bytes(pred: pd.DataFrame) -> bytes:
    """inference.output_fn(pred, 'text/csv'), formato determinista (Req. 5.9)."""
def metadata(kind, rows, nan_rows, config, source_table) -> dict
def main(argv: list[str] | None = None) -> None
    # --table PATH(.parquet) --model-dir PATH --out-dir (data/app/predictions) --config
```

Primero valida y calcula todo en memoria. Si algo falla, termina con código distinto de cero sin escribir nada. Al final escribe `pred_AAAAMMDD.csv` y `pred_AAAAMMDD.meta.json`, cada uno de forma atómica (Req. 5.12). Si se escribe el CSV y falla el `.meta.json`, el lector lo trata como inválido (Req. 6.10 y 7.13), así que no se publica un CSV huérfano.

### `predictions.py` (compartido por sitio y alertas)

```python
SCHEMA = ("probability", "date", "hour_utc", "latitude", "longitude", "config")
@dataclass
class Predictions: df: pd.DataFrame; meta: dict; path: Path
class InvalidPredictions(ValueError): ...  # mensaje con el motivo
def meta_path(csv: Path) -> Path       # pred_X.csv -> pred_X.meta.json
def load(csv: Path) -> Predictions
    """Columnas exactas = SCHEMA; probability en [0,1] y sin NaN; hour_utc entero 0..23;
    fecha AAAA-MM-DD; sin duplicados (date,hour_utc,latitude,longitude); meta presente con
    'modelo' in {'real','sustituto'}. Si no, InvalidPredictions."""
```

### `build_site.py`

```python
DEMO_DAY = dt.date(2019, 5, 30)
def day_payload(df: pd.DataFrame, meta: dict) -> dict          # puro, ver Data Models
def payload_rows(payload: dict) -> pd.DataFrame                # inverso para la ida y vuelta
def read_catalog(path: Path) -> pd.DataFrame | None
    """Hoja Final_Table; usa viewer_app.data.coordinate para lat/lon con texto y comas;
    descarta filas sin fecha o sin coordenadas. None si no existe o no se puede leer."""
def catalog_by_day(cat: pd.DataFrame, days: set[str]) -> dict[str, list[dict]]
def default_day(days: list[str]) -> str                        # Día_Demo si está; si no, el más reciente
def build(csvs: list[Path], catalog: Path, out_dir: Path) -> int
def main(argv: list[str] | None = None) -> None
    # CSV... (o --pred-dir) --catalog data/tornados_chile.xlsx --out data/app/site
```

`build` valida todos los CSV primero. Cada CSV inválido se informa en stderr y se omite. Si ninguno es válido, termina con código distinto de cero sin tocar `out_dir` (Req. 6.13). Si es válido, arma el sitio en un directorio temporal hermano (`out_dir.tmp-XXXX`) y lo intercambia con `os.replace` sobre el directorio anterior, renombrado primero a `.old` y borrado al final. Si dos CSV traen el mismo día, gana el de `generado` más reciente y se informa una advertencia. El límite de 366 días se valida en el argumento.

`index.html` incluye:

- Un `<select id="day">` con su `<label>`.
- Un `<input type="range" id="hour" min="0" max="23">` con `<label>` y `aria-valuetext="HH UTC"`.
- El descargo fijo en un `<header>` con `position: sticky`.
- La etiqueta `#stub-badge`.
- La leyenda con 5 intervalos viridis (`#440154, #3b528b, #21918c, #5ec962, #fde725`, con texto oscuro o claro elegido para un contraste ≥ 4,5:1).
- El mensaje `#no-data` con `role="status"`.
- Una lista accesible de los eventos del día.

`app.js` carga `days/index.json` (lista de días y día por defecto), luego carga y guarda en caché el JSON de cada día al seleccionarlo y redibuja en el canvas. No usa `eval` ni `innerHTML` con datos: los textos del catálogo se insertan con `textContent`.

### `geo.py`

```python
@dataclass(frozen=True)
class Zone: name: str; kind: Literal["box", "polygon"]; coords: tuple[tuple[float, float], ...]
class ConfigError(SystemExit): ...
def validate_zone(raw: dict) -> Zone
    """Caja: lat_min < lat_max, lon_min < lon_max. Polígono: ≥3 vértices, sin
    autointersección (prueba O(n²) entre aristas no adyacentes). Coordenadas en rango."""
def contains(zone: Zone, lat: np.ndarray, lon: np.ndarray) -> np.ndarray
    """Máscara vectorizada; ray casting + prueba de punto sobre arista (borde incluido)."""
```

### `alerts.py`

```python
@dataclass(frozen=True)
class Rule: zone: str; threshold: float; suppression_hours: int
@dataclass(frozen=True)
class Alert: zone: str; date: str; hour_utc: int; index_max: float; threshold: float
             modelo: str; disclaimer: str = "Índice relativo; no es un pronóstico oficial"
@dataclass(frozen=True)
class Config: zones: dict[str, Zone]; rules: list[Rule]; sinks: list[dict]
def load_config(path: Path) -> Config           # ConfigError con el elemento inválido (Req. 7.10)
def candidates(pred: Predictions, cfg: Config) -> list[Alert]
    """Puro: por regla, zona y (date, hour_utc), máx(probability*100) de los puntos en la zona;
    una Alerta si máx > umbral. Orden: (zone, date, hour_utc)."""
def suppress(cands: list[Alert], state: dict[str, str], rules: list[Rule]
             ) -> tuple[list[Alert], list[dict], dict[str, str]]
    """Puro: recorre en orden cronológico por zona. Omite si existe una última emitida L y
    L <= t < L + ventana. Devuelve (emitidas, omisiones registradas, estado nuevo)."""
def evaluate(pred, cfg, state) -> tuple[list[Alert], list[dict], dict[str, str]]  # candidates + suppress
def main(argv: list[str] | None = None) -> None
    # --pred PATH.csv --config configs/alerts.json --state data/app/alerts_state.json --profile
```

Pasos de `main`:

1. Carga y valida la configuración. Si es inválida, termina con código distinto de cero antes de leer predicciones.
2. Carga las predicciones. Si son inválidas, termina con código distinto de cero (Req. 7.13).
3. Bajo `atomic.locked(state)`, lee el estado y llama a `evaluate`.
4. Entrega cada alerta a cada destino. Un fallo en un destino se informa en stderr y se sigue con los demás, sin reintentos.
5. Escribe el estado nuevo de forma atómica (Req. 7.15).
6. Termina con 1 si hubo fallos de entrega. Si no, con 0.

Las zonas sin puntos o sin filas se registran como `sin datos` (Req. 7.14).

Las candidatas con `t < L` (datos más antiguos que la última alerta emitida) se emiten, sin suprimirse. Si se reprocesa el mismo CSV, sus candidatas caen en `L <= t < L + ventana` (con ventana > 0) y no se duplican.

### `sinks.py`

```python
class Sink(Protocol):
    name: str
    def deliver(self, alert: Alert) -> None: ...   # lanza excepción si falla
class ConsoleSink: ...            # print(json.dumps(asdict(alert), ensure_ascii=False))
class FileSink:  path: Path       # append de una línea JSON bajo atomic.locked, open('a')
class SnsEmailSink: topic_arn: str; profile: str | None; region: str
                                  # boto3.Session(profile).client('sns').publish(Subject, Message)
class WhatsAppStub: ...           # escribe en stderr "WhatsApp no habilitado en v1" + alerta; sin red
def build_sinks(specs: list[dict], profile: str | None) -> list[Sink]
    """[] -> [ConsoleSink()] (Req. 7.4). Tipo desconocido -> ConfigError (se valida en load_config)."""
```

`FileSink` agrega con `open(path, "a")` bajo el bloqueo, sin reescribir el archivo, así que las líneas existentes no cambian. `SnsEmailSink` crea el cliente de forma diferida en el primer `deliver`, así que las pruebas sin red nunca lo construyen.

### `progress_log.py`

```python
STATES = ("pendiente", "en_curso", "hecho", "bloqueado")
DEFAULT = ROOT / "docs/logs/progreso.json"
class LogError(SystemExit): ...
def validate(entry: dict) -> list[str]          # nombres de campos inválidos (Req. 3.4)
def read(path: Path) -> list[dict]              # [] si no existe; LogError 'archivo corrupto'
def append(entry: dict, path: Path = DEFAULT) -> None
    """Bajo atomic.locked: validate -> read -> lista + [entry] -> atomic.write_json."""
def main(argv: list[str] | None = None) -> None
    # --tarea --estado --notas --decision (repetible) [--timestamp, por defecto ahora UTC] [--file]
```

### `deploy_site.py`

```python
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".json": "application/json",
                 ".png": "image/png", ".svg": "image/svg+xml"}
def plan_uploads(site: Path) -> list[tuple[Path, str, str]]
    """(archivo, clave 'sitio/<rel>', content-type); SystemExit si hay una extensión fuera de la lista."""
def tf_outputs(tf_dir: Path) -> dict            # terraform output -json: data_bucket, cloudfront_distribution_id
def upload(plan, bucket, profile) -> None       # boto3 s3.upload_file con ExtraArgs ContentType; aborta al primer fallo
def invalidate(dist_id, profile) -> str         # create_invalidation('/sitio/*'), devuelve el Id
def main(argv: list[str] | None = None) -> None
    # infra  --profile: awsauth.check -> terraform plan -out=tfplan -> input('¿Aplicar? escribe sí')
    #        -> terraform apply tfplan  (si no se escribe 'sí', termina sin aplicar)
    # upload --site data/app/site --profile [--bucket --distribution-id | lee tf_outputs]
    #        plan_uploads -> awsauth.check -> upload -> invalidate -> imprime https://<dominio>/sitio/index.html
```

Orden en `upload`: primero valida las extensiones, luego las credenciales y al final la red, así que un sitio inválido nunca llega a subirse. Un fallo de subida termina sin crear la invalidación (Req. 8.8). Una subida a medias puede dejar archivos nuevos y viejos mezclados en `sitio/`. Como no se invalida la caché, CloudFront sigue sirviendo la versión anterior hasta que vence el TTL. Ese riesgo se acepta en la v1 y se resuelve con un reintento de `upload`.

### Cambios Terraform (`infra/terraform`)

Archivo nuevo y propio:

- `site.tf`: `locals { site_prefix = "sitio/" }` y el output `site_url = "https://${aws_cloudfront_distribution.viewer.domain_name}/sitio/index.html"`. Cualquier recurso o output futuro del sitio va aquí. Usa el proveedor por defecto (`us-east-1`).

Cambios acotados en archivos compartidos (Req. 8.13):

- `s3.tf`: en el statement `AllowCloudFrontReadResults` de `aws_s3_bucket_policy.data_tls_only`, `Resource` pasa de una cadena a `["${aws_s3_bucket.data.arn}/resultados/*", "${aws_s3_bucket.data.arn}/sitio/*"]`. No cambia nada más: el bloqueo público, `DenyInsecureTransport` y la condición `AWS:SourceArn` sobre la distribución siguen igual.
- `cloudfront.tf`: un único `ordered_cache_behavior` nuevo con `path_pattern = "/sitio/*"`, `target_origin_id = "results-s3"`, `redirect-to-https`, GET/HEAD/OPTIONS, `compress = true` y la política `optimized`. Va después de `/resultados/*`. Como CloudFront evalúa por orden y los patrones no se solapan, el orden no cambia el resultado. El contenido viejo en caché se resuelve con la invalidación de cada `upload`.
- `README.md` de `infra/terraform`: sección "Sitio público sin autenticación" (Req. 8.10).

Archivos que no se tocan (Req. 8.14): `sagemaker.tf`, `outputs.tf`, `versions.tf`, `variables.tf` y `training.tf`.

Coexistencia con `sagemaker.tf`:

- La única política del bucket de datos sigue siendo `aws_s3_bucket_policy.data_tls_only` en `s3.tf`. AWS admite una sola política por bucket, y dos recursos `aws_s3_bucket_policy` sobre el mismo bucket se sobrescriben en cada `apply`.
- `sagemaker.tf` (en `3cd882b`) solo declara `aws_s3_bucket_policy.ml_tls_only` sobre `aws_s3_bucket.ml`, que es otro bucket, y accede al bucket de datos por IAM. Por eso hoy no hay choque.
- Si en una Sincronización futura alguna rama agrega statements para el bucket de datos, se fusionan dentro de `data_tls_only` en `s3.tf`. No se crea un segundo recurso de política. Se avisa antes al responsable según el acuerdo de coordinación, y la prueba `test_single_bucket_policy` (ver Testing Strategy) lo detecta.
- No se renombra `aws_s3_bucket.data`, porque `sagemaker.tf` lo referencia.
- Después de cada Sincronización se ejecuta `terraform -chdir=infra/terraform init -backend=false && terraform validate` con ambos archivos presentes (verificación manual, fuera de `make check`, porque requiere el binario de Terraform y descargar el proveedor).

Para cualquier otro prefijo, S3 responde 403 a CloudFront, porque la OAC solo tiene `GetObject` sobre los dos prefijos. El acceso directo a S3 queda denegado por el bloqueo público (Req. 8.4).

### `run_day.py`

```python
def main(argv: list[str] | None = None) -> None
    # --source --profile --start --end --config baseline_era5 --model-dir --skip-site --skip-alerts
```

Pasos:

1. `adapter.process_day` para cada día.
2. Para cada Día_Utilizable, `build_table.main(["--stage", "infer", "--config", cfg, "--start", d, "--force"])` (y antes `extract_goes_features.main` si `cfg != baseline_era5`).
3. `infer`.
4. `build_site` sobre todos los CSV de `data/app/predictions`.
5. `alerts` por cada CSV nuevo.

Cada paso registra una Entrada_Bitácora (`en_curso`, luego `hecho` o `bloqueado`).

### Procedimiento de Sincronización (Requisito 1)

Las ramas de origen siguen avanzando, así que la integración no es un merge único: es un procedimiento repetible que se ejecuta cada vez que alguna rama avanza y una última vez antes del PR (Req. 1.14). Ningún SHA queda fijo en el procedimiento: los valores de cada vuelta se leen de `origin` y se registran.

Pasos de cada Sincronización:

```bash
git fetch origin
# 1. Registrar los SHA vigentes (se guardan para los pasos 6 y 7)
git rev-parse origin/main origin/intentos-nico origin/feat/multimodal-tornado-predictor-wip
# 2. Rama: crearla en la primera vuelta; reutilizarla en las siguientes
git checkout -b merge/datos-modelo origin/main      # solo si la rama no existe
git checkout merge/datos-modelo                     # en las demás vueltas
# 3. Merges sin rebase, squash ni force-push (Req. 1.12)
git merge --no-ff origin/intentos-nico -m "sync: intentos-nico <sha>"
git merge --no-ff origin/feat/multimodal-tornado-predictor-wip -m "sync: predictor <sha>"
```

En el repo local está activado `git rerere` (`rerere.enabled=true` y `rerere.autoupdate=true`). Cuando se repite un conflicto ya resuelto en una vuelta anterior, git reaplica la resolución grabada y la deja en el índice. Igual se revisa: rerere repite el texto, no vuelve a aplicar las reglas, así que el paso 4 se verifica en cada vuelta.

4. Reglas de resolución de conflictos:

- **pyproject.toml**: unión de las dependencias de ambas ramas. Cada una se fija con `==` a la versión que resolvió `uv.lock`. Si una dependencia aparece con dos versiones, se queda la más alta y se registra en el Documento_Planificación (por ejemplo, `boto3==1.43.75`).
- **uv.lock**: no se resuelve a mano. Se regenera con `uv lock` y se verifica con `uv lock --check` (Req. 1.4).
- **README.md y otros `.md`**: se conservan ambos textos completos bajo `### Desde intentos-nico` y `### Desde feat/multimodal-tornado-predictor-wip`. En `README.md` se conserva el enlace `[...](docs/modelo_predictor.md)` que exige `tests/test_docs.py` (Req. 1.11).
- **scripts/model/train_xgboost.py**: la versión refactorizada de Daniel reemplaza a la de `main` y Nico (la copia de Nico es la de `main`). Queda registrado.
- **infra/terraform/** (`outputs.tf`, `versions.tf` y `sagemaker.tf`): se toma la versión de la rama de origen, porque nuestros cambios del sitio no tocan esos archivos. En `s3.tf` y `cloudfront.tf` se conservan los cambios de origen más nuestras dos ediciones acotadas.
- **infra/terraform-test/**: es un directorio aparte de Nico y entra sin conflicto.

5. Verificación:

```bash
git grep -nE '^(<<<<<<<|=======|>>>>>>>)( |$)' && exit 1   # Req. 1.9
uv lock --check                                             # Req. 1.4
git merge-base --is-ancestor <sha_nico_registrado> HEAD     # Req. 1.2
git merge-base --is-ancestor <sha_daniel_registrado> HEAD
make check                                                  # Req. 1.7; si falla, bitácora 'bloqueado'
git rev-parse origin/main                                   # debe coincidir con el SHA del paso 1 (Req. 1.6)
```

6. Se agrega una Entrada_Bitácora con `tarea = "sincronización"`. `estado` vale `hecho` o `bloqueado`, `notas` lleva los tres SHA, los conflictos y el resultado de `make check`, y `decisiones` lleva las resoluciones no triviales (Req. 1.10 y 1.13).
7. Se agrega una fila a la tabla de Sincronizaciones de `docs/planificacion_merge.md` (Req. 2.10).

Push y PR:

- No forman parte de la Sincronización.
- Se hacen solo con confirmación explícita del usuario, después de una Sincronización final con las cabezas vigentes y con `make check` en código 0 sobre ese commit (Req. 1.14).
- Comandos: `git push -u origin merge/datos-modelo` y luego `gh pr create --base main`.
- Si `make check` falla, no se abre PR (Req. 1.10). Si la falla viene de pruebas o tipado del código de origen, se corrige en un commit aparte y se registra en "cambios al código de origen" (Req. 1.8).

### `sync_branches.py` y `make sync`

**Decisión**: se implementa el script `scripts/app/sync_branches.py` y un objetivo `make sync` que lo invoca (`uv run python scripts/app/sync_branches.py`). El script automatiza los pasos 1, 2, 3, 5, 6 y 7. La resolución de conflictos (paso 4) queda manual cuando rerere no la resuelve sola.

```python
SOURCES = ("origin/intentos-nico", "origin/feat/multimodal-tornado-predictor-wip")
BRANCH = "merge/datos-modelo"
@dataclass(frozen=True)
class SyncShas: main: str; nico: str; daniel: str
@dataclass
class SyncResult: date: str; shas: SyncShas; conflicts: list[str]; gate: Literal["ok", "falla", "no ejecutada"]
def git(*args: str, check: bool = True) -> str      # subprocess.run(["git", *args]) sin shell
def record_shas() -> SyncShas
def ensure_branch(main_sha: str) -> None             # crea desde origin/main o hace checkout
def merge_source(ref: str) -> list[str]              # --no-ff; devuelve archivos en conflicto (sin resolver)
def conflict_markers() -> list[str]                  # git grep sobre archivos versionados
def sync_row(result: SyncResult) -> str              # puro: fila Markdown de la tabla
def append_sync_row(doc: Path, row: str) -> None     # agrega bajo la tabla, escritura atómica
def main(argv: list[str] | None = None) -> None
    # --dry-run (solo fetch y SHA) --continue (retoma tras resolver a mano) --skip-check
```

Comportamiento:

- **Nunca hace push**, no abre PR y no ejecuta `rebase`, `reset`, `--squash` ni `--force`. Una prueba revisa el código fuente con `ast` y falla si aparece cualquiera de esos argumentos en una llamada a `git`.
- Si un merge deja conflictos que rerere no resolvió, el script se detiene con código 1, lista los archivos, registra la Entrada_Bitácora `bloqueado` y deja el merge en curso para resolverlo a mano. `--continue` verifica que no queden marcadores, hace `git commit --no-edit` y sigue con la rama siguiente.
- Antes de empezar exige un árbol de trabajo limpio (`git status --porcelain` vacío). Si no lo está, termina con código 2 sin tocar nada.
- Al final compara `origin/main` con el SHA registrado y falla si cambió durante la vuelta (Req. 1.6).
- `--help` termina con 0 (Req. 9.6).

### Documento_Planificación (`docs/planificacion_merge.md`)

Encabezados obligatorios, en este orden (Req. 2.6): "Flujo", "Decisiones", "Preguntas abiertas", "Errores conocidos", "Riesgos", "Cambios al código de origen" y "Sincronización con ramas en movimiento".

Preguntas abiertas: además de las 7 del Req. 2.3, incluye las dos del Req. 2.11, con sus opciones:

- Interacción entre la propiedad de subconjunto (7.12) y la supresión (7.2). Opciones: verificar solo candidatas y ventana 0, como está hoy, o cambiar la semántica de supresión para que sea monótona.
- Fijar con `==` también las dependencias heredadas de `main`. Opciones: fijar todo, o fijar solo las dependencias nuevas y dejar `>=` en las heredadas.

Sección "Sincronización con ramas en movimiento":

| Archivo compartido | Responsable |
|---|---|
| `infra/terraform/s3.tf`, `cloudfront.tf`, `outputs.tf`, `versions.tf`, `sagemaker.tf` | Daniel / Bryan como responsables de infra (por confirmar) |
| `pyproject.toml`, `uv.lock` | Integrador de `merge/datos-modelo` |
| `README.md` | Todos |

Acuerdo de coordinación: antes de modificar cualquiera de estos archivos, se avisa al equipo en el canal del proyecto, indicando el archivo y el cambio. El integrador hace una Sincronización tras cada aviso de cambio fusionado. Los responsables marcados como "por confirmar" se ratifican en la próxima reunión del equipo y se registran como decisión con su fecha.

Tabla de Sincronizaciones (una fila por Sincronización, Req. 2.10):

| Fecha | SHA `intentos-nico` | SHA `feat/multimodal-tornado-predictor-wip` | SHA `origin/main` | Conflictos resueltos | Puerta_Calidad |
|---|---|---|---|---|---|
| AAAA-MM-DD | `0167b08` | `3cd882b` | `cf59a73` | `pyproject.toml`, `README.md` | ok / falla |

`sync_branches.sync_row` genera exactamente estas 6 columnas (SHA abreviados a 7 caracteres). La fila de ejemplo usa los SHA observados al redactar y es solo ilustrativa.

## Data Models

### CSV_Predicciones (`data/app/predictions/pred_AAAAMMDD.csv`)

```csv
probability,date,hour_utc,latitude,longitude,config
0.4123,2019-05-30,21,-36.75,-73.0,sustituto/baseline_era5
```

Lo escribe `inference.output_fn`, con el mismo formato en el Modelo_Real y en el Sustituto. En el Modelo_Real, `config` es el valor de `config.json`. Las filas siguen el orden de la Tabla_Inferencia.

### Metadatos (`pred_AAAAMMDD.meta.json`)

```json
{
  "modelo": "sustituto",
  "generado": "2026-10-20T14:03:11Z",
  "filas": 99180,
  "filas_con_nan": 120,
  "config": "baseline_era5",
  "tabla": "data/model/south-central-austral/inference/config=baseline_era5/date=2019-05-30/part-0.parquet",
  "model_dir": null
}
```

### Reporte_Calidad (`data/app/quality/quality_AAAAMMDD.json`)

```json
{
  "day": "2019-05-30",
  "generado": "2026-10-20T14:00:00Z",
  "source": "s3://bucket",
  "era5_origin": "era5_store",
  "provenance": "ERA5",
  "goes_scenes_per_hour": {"0": 6, "1": 6, "...": 0, "23": 6},
  "era5_nan_fraction": {"u": 0.0, "cape": 0.0},
  "era5_levels_present": [1000, 925, 850, 700, 500, 300],
  "goes_native_shape": [466, 882],
  "goes_output_shape": [1301, 501],
  "outputs": {"era5_idx": "…/era5_idx_20190530.nc", "goes_hours": [0, 1, 2]},
  "checks": [
    {"name": "goes_hour_missing", "target": "13", "severity": "advertencia", "detail": "sin escenas"},
    {"name": "era5_nan_fraction", "target": "cape", "severity": "ok", "value": 0.0}
  ]
}
```

`severity` vale `ok`, `advertencia` o `error`. Un día es Día_Utilizable cuando ningún `checks[].severity` es `error`. `era5_origin` vale `era5_store`, `era5_cds_year` o `null`.

### JSON de día del sitio (`site/days/AAAA-MM-DD.json`)

```json
{
  "date": "2019-05-30",
  "modelo": "sustituto",
  "config": "sustituto/baseline_era5",
  "generado": "2026-10-20T14:03:11Z",
  "lats": [-30.0, -30.25, "…"],
  "lons": [-76.0, -75.75, "…"],
  "cell": 0.25,
  "scale": 10000,
  "hours": {"21": [4123, null, 0, "…"]},
  "events": [{"lat": -36.82, "lon": -73.05, "fecha": "2019-05-30", "hora_utc": "21:30",
              "localidad": "Los Ángeles", "fuente": "…"}]
}
```

`hours[h][i * len(lons) + j]` es `round(probability × 10000)` en la celda `(lats[i], lons[j])`, o `null` si no hay dato. Las horas sin filas no aparecen y el sitio muestra "Sin datos para esta hora". El Índice_Favorabilidad mostrado es `v / 100` %. `site/days/index.json` vale `{"days": ["2019-05-30", ...], "default": "2019-05-30"}`.

### Configuración de alertas (`configs/alerts.json`)

```json
{
  "zones": [
    {"name": "Biobío", "box": {"lat_min": -38.5, "lat_max": -36.4, "lon_min": -73.8, "lon_max": -71.0}},
    {"name": "Ñuble", "polygon": [[-36.0, -72.9], [-36.0, -71.0], [-37.2, -71.0], [-37.2, -72.9]]}
  ],
  "rules": [{"zone": "Biobío", "threshold": 60, "suppression_hours": 6}],
  "sinks": [{"type": "archivo", "path": "data/app/alerts.jsonl"}, {"type": "consola"}]
}
```

Los vértices van como `[lat, lon]`. Los tipos de destino válidos son `consola`, `archivo` (`path`), `sns_email` (`topic_arn` y `region` opcional) y `whatsapp`. Si se omite, `suppression_hours` vale 6. La v1 trae cajas aproximadas por región y su definición precisa queda como pregunta abierta.

### Alerta (línea JSONL)

```json
{"zone": "Biobío", "date": "2019-05-30", "hour_utc": 21, "index_max": 72.4, "threshold": 60,
 "modelo": "sustituto", "disclaimer": "Índice relativo; no es un pronóstico oficial"}
```

### Estado de supresión (`data/app/alerts_state.json`)

```json
{"version": 1, "last_emitted": {"Biobío": "2019-05-30T21:00:00Z"}}
```

### Entrada_Bitácora (`docs/logs/progreso.json`)

```json
[
  {"timestamp": "2026-10-20T14:10:00Z", "tarea": "merge intentos-nico",
   "estado": "hecho", "notas": "make check OK; revisados: conflictos pyproject, README",
   "decisiones": ["boto3==1.43.75 (versión más alta)"]}
]
```

`timestamp` debe terminar en `Z` o `+00:00`. `tarea` tiene entre 1 y 200 caracteres. `notas` es texto. `decisiones` es una lista de textos.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Las propiedades se aplican a la lógica pura de `scripts/app/`: validadores, transformaciones y reglas. La E/S (S3, SNS, Terraform, navegador) se cubre con pruebas de ejemplo, mocks y verificación manual (ver Testing Strategy).

Reflexión aplicada para eliminar redundancia:

- 3.1, 3.2 y 3.6 se cubren con la ida y vuelta de la bitácora (Propiedad 1).
- 4.4 se une a la ida y vuelta de 4.14 (Propiedad 4).
- 4.2 queda dentro de la confluencia 4.15 (Propiedad 5).
- 4.8 y 4.9 se unen en una sola propiedad de verificaciones ERA5 (Propiedad 6).
- 5.3, 5.4 y 5.5 se unen en la conservación de filas (Propiedad 8).
- 5.7 (sustituto) y 5.8 se unen en las propiedades del Modelo_Sustituto (Propiedad 10).
- 6.10 y 7.13 comparten el validador `predictions.load` (Propiedad 12).
- 6.1, 6.3 y 6.9 se unen en la estructura del índice del sitio (Propiedad 14).
- 7.1, 7.8 y 7.14 se unen en una prueba contra un modelo de referencia (Propiedad 16).
- 8.5 y 8.6 se unen en `plan_uploads` (Propiedad 24).
- 9.11, 9.12, 9.13 y 9.15 comparten los comparadores de `contracts.py` (Propiedad 25). La comparación contra los archivos reales de Daniel y de `lake_layout.py` es una prueba de ejemplo.
- 1.13 y 2.10 se cubren con la ida y vuelta de `sync_row` (Propiedad 26). El resto del Requisito 1 es flujo de git y se verifica con un ejemplo sobre un repo temporal y con la checklist manual.

### Property 1: Ida y vuelta de la Bitácora_Progreso

*For any* secuencia de 0 a 100 Entradas_Bitácora válidas, agregarlas una por una sobre un archivo inexistente (en un directorio que tampoco existe) y luego leer la bitácora devuelve la misma secuencia, en el mismo orden y con valores idénticos. Tras cada agregado, la lectura es igual a la lectura anterior más la nueva entrada al final.

**Validates: Requirements 3.1, 3.2, 3.5, 3.6**

### Property 2: Rechazo de entradas inválidas

*For any* Entrada_Bitácora válida a la que se le invalida un subconjunto no vacío de campos (campo ausente, `timestamp` sin zona UTC, `tarea` vacía o de más de 200 caracteres, `estado` fuera de la lista), `append` termina con error, el mensaje nombra exactamente esos campos y el archivo existente queda igual byte a byte.

**Validates: Requirements 3.4**

### Property 3: Bitácora corrupta intacta

*For any* contenido de archivo que no sea JSON válido o cuyo elemento raíz no sea un arreglo, `append` de una entrada válida termina con error de "archivo corrupto" y el archivo queda igual byte a byte.

**Validates: Requirements 3.7**

### Property 4: Ida y vuelta de la codificación GOES

*For any* arreglo int16 con valores aleatorios, con píxeles en `_FillValue` (-1) en posiciones aleatorias y con `scale_factor` > 0 y `add_offset` aleatorios, `decode_c13` da NaN exactamente en las posiciones con -1, y `encode_c13(decode_c13(x))` reproduce `x` en todas las posiciones (los -1 vuelven como -1).

**Validates: Requirements 4.4, 4.14**

### Property 5: Confluencia de orígenes ERA5

*For any* campo ERA5 sintético con los 6 niveles de presión, una grilla pequeña y entre 1 y 3 horas, `era5_indices(harmonize_cds(pl_cds, sfc_cds))` y `era5_indices(select_store(zarr_equivalente))` coinciden en todas las variables y celdas con diferencia absoluta ≤ 1e-6 (los NaN se comparan en la misma posición).

**Validates: Requirements 4.2, 4.15**

### Property 6: Verificaciones ERA5 del Reporte_Calidad

*For any* Dataset ERA5 sintético al que se le quita un subconjunto aleatorio de variables, niveles o dimensiones esperados y se le inyecta una fracción aleatoria de NaN por variable, y *for any* umbral en [0, 1], `check_era5` marca con severidad `error` exactamente las variables, niveles o dimensiones faltantes y las variables con fracción de NaN estrictamente mayor que el umbral. `process_day` escribe `era5_idx` solo si no hay errores.

**Validates: Requirements 4.8, 4.9**

### Property 7: Horas GOES faltantes

*For any* subconjunto de horas UTC 0–23 con escenas (incluido el vacío y el completo), el Reporte_Calidad lista con severidad `advertencia` exactamente las horas sin escenas, y el Adaptador escribe exactamente un archivo `goes_AAAAMMDDHH.nc` por cada hora con al menos una escena.

**Validates: Requirements 4.3, 4.7**

### Property 8: Conservación de filas en la inferencia

*For any* Tabla_Inferencia sintética con N filas (0 ≤ N ≤ 500), con NaN, infinitos o negativos aleatorios en las columnas de entrada, el CSV_Predicciones tiene N filas en el mismo orden, con `date`, `hour_utc`, `latitude`, `longitude` y `config` iguales a la entrada y `probability` finita en [0, 1]. Los metadatos informan `filas = N` y `filas_con_nan` igual al número de filas con algún NaN en las columnas de entrada.

**Validates: Requirements 5.3, 5.4, 5.5**

### Property 9: Columnas faltantes en la inferencia

*For any* subconjunto no vacío de columnas requeridas (clave más entrada del modelo seleccionado) que se quita de una Tabla_Inferencia válida, el Ejecutor_Inferencia termina con un código de salida distinto de cero, el mensaje lista exactamente las columnas quitadas y el directorio de salida no contiene ni CSV ni metadatos nuevos.

**Validates: Requirements 5.6**

### Property 10: Modelo_Sustituto monótono y con NaN en cero

*For any* par de filas que solo difieren en que la segunda tiene `cape` ≥ y `shear_06` ≥ que la primera, `score` de la segunda es ≥ al de la primera. *For any* fila con NaN en `cape` o en `shear_06`, `score` vale 0.

**Validates: Requirements 5.7, 5.8**

### Property 11: Determinismo de la inferencia

*For any* Tabla_Inferencia válida, dos ejecuciones con la misma entrada y los mismos artefactos producen CSV_Predicciones idénticos byte a byte y metadatos idénticos salvo `generado`.

**Validates: Requirements 5.9**

### Property 12: Validación de CSV_Predicciones

*For any* CSV_Predicciones válido generado al azar, `predictions.load` lo acepta. *For any* mutación de uno de los tipos siguientes, lo rechaza con un motivo que nombra la falla:

- columna ausente, sobrante o renombrada;
- `probability` fuera de [0, 1] o NaN;
- `hour_utc` fuera de 0–23;
- fila duplicada;
- metadatos ausentes o sin `modelo`.

**Validates: Requirements 6.10, 7.13**

### Property 13: Ida y vuelta CSV → JSON del sitio

*For any* CSV_Predicciones válido de un día, `payload_rows(day_payload(df, meta))` reproduce el mismo conjunto de filas (`date`, `hour_utc`, `latitude`, `longitude`) y `probability` redondeada a 4 decimales.

**Validates: Requirements 6.12**

### Property 14: Estructura del índice del sitio

*For any* conjunto de entre 1 y 30 CSV válidos con días aleatorios (con repeticiones), el Generador_Sitio escribe exactamente un `days/AAAA-MM-DD.json` por cada día distinto. `index.json["days"]` está en orden cronológico estricto, y `index.json["default"]` es 2019-05-30 si ese día está y, si no, el día más reciente.

**Validates: Requirements 6.1, 6.3, 6.9**

### Property 15: Eventos del catálogo por día

*For any* catálogo sintético (con coordenadas numéricas o como texto con comas decimales) y cualquier conjunto de días, `catalog_by_day` asigna a cada día exactamente los eventos con esa fecha y coordenadas interpretables, cada uno con `fecha`, `localidad` y `fuente`.

**Validates: Requirements 6.4**

### Property 16: Candidatas de alerta según un modelo de referencia

*For any* CSV_Predicciones sintético (incluido el vacío) y cualquier configuración válida de zonas (cajas y polígonos, con puntos colocados a propósito sobre los bordes) y umbrales, `candidates` produce el mismo conjunto que una implementación de referencia ingenua: un ciclo punto por punto con la prueba de borde inclusiva. Ese conjunto tiene a lo sumo una Alerta por (zona, fecha, hora) y solo si el máximo × 100 supera estrictamente el umbral. Cada Alerta trae todos los campos del Req. 7.8, con `index_max` redondeado a 1 decimal. Las zonas sin puntos no producen Alertas.

**Validates: Requirements 7.1, 7.8, 7.14**

### Property 17: Invariante de supresión

*For any* lista de candidatas, ventana en [0, 168] y estado inicial, en la salida de `suppress`:

- dos Alertas emitidas consecutivas de una misma zona (y la primera respecto de la última del estado inicial, si `t ≥ L`) están separadas por al menos la ventana;
- cada omisión registrada tiene una emitida previa de la misma zona a menos de la ventana;
- emitidas ∪ omitidas = candidatas.

**Validates: Requirements 7.2**

### Property 18: Idempotencia del Motor_Alertas

*For any* CSV_Predicciones, configuración y estado inicial, dos llamadas a `evaluate` con el mismo estado inicial producen listas de Alertas iguales campo a campo y el mismo estado final.

**Validates: Requirements 7.11**

### Property 19: Monotonía del umbral

*For any* CSV_Predicciones, configuración y umbral mayor que el original para una regla (con el resto de la configuración fijo), el conjunto de Alertas candidatas que devuelve `candidates`, antes de aplicar `suppress`, es subconjunto del conjunto obtenido con el umbral original. *For any* configuración en la que esa regla tiene `suppression_hours = 0` y *for any* estado de supresión inicial, el conjunto de Alertas emitidas por `evaluate` con el umbral mayor también es subconjunto del emitido con el umbral original y el mismo estado inicial. Con ventana > 0 no se afirma inclusión entre emitidas: una alerta temprana que desaparece puede liberar una posterior que antes se suprimía.

**Validates: Requirements 7.12**

### Property 20: Encadenamiento del estado de supresión

*For any* lista de candidatas ordenada cronológicamente y partida en dos tramos consecutivos, ejecutar `suppress` sobre el primer tramo y luego sobre el segundo con el estado resultante produce las mismas emitidas y el mismo estado final que ejecutarlo sobre la lista completa.

**Validates: Requirements 7.15**

### Property 21: Agregado JSONL sin pérdida

*For any* archivo JSONL previo (o inexistente) y cualquier lista de Alertas, después de entregarlas con `FileSink` el archivo empieza con el contenido previo intacto y luego trae exactamente una línea JSON parseable por Alerta, en orden.

**Validates: Requirements 7.5**

### Property 22: Aislamiento de fallos de destinos

*For any* lista de Alertas y conjunto de destinos falsos en el que cada destino falla en un subconjunto aleatorio de entregas, cada destino recibe un intento por Alerta (sin reintentos). Cada fallo se registra con destino, zona, fecha, hora y motivo, y el código de salida es distinto de cero si y solo si hubo al menos un fallo.

**Validates: Requirements 7.9**

### Property 23: Validación de la configuración de alertas

*For any* configuración válida generada al azar, `load_config` la acepta. *For any* mutación de un único elemento de los tipos siguientes, la rechaza nombrando ese elemento:

- umbral fuera de [0, 100];
- ventana fuera de [0, 168];
- destino desconocido;
- polígono con menos de 3 vértices o autointersectado (por ejemplo, un "moño");
- caja con mínimo ≥ máximo;
- coordenadas fuera de rango.

**Validates: Requirements 7.10**

### Property 24: Plan de subida del sitio

*For any* árbol de archivos sintético, `plan_uploads` asigna a cada archivo la clave `sitio/<ruta relativa>` y el `Content-Type` de la tabla del Req. 8.5 si todas las extensiones son admitidas. Si al menos una no lo es, termina con error nombrando un archivo con extensión no admitida y su extensión, sin devolver un plan.

**Validates: Requirements 8.5, 8.6**

### Property 25: Detector de deriva de contrato

*For any* fuente Python sintética que define un conjunto aleatorio de nombres a nivel de módulo (funciones, clases, asignaciones e imports), y *for any* subconjunto de nombres requeridos que se quita de esa fuente, `missing_symbols` devuelve exactamente los nombres quitados. *For any* mapa de constantes esperadas y cualquier módulo que difiere en un subconjunto aleatorio de esas constantes (ausentes o con otro valor), `layout_drift` devuelve una `Drift` exactamente por cada constante divergente, con su valor esperado y el encontrado, y `format_drift` nombra cada una. Con un módulo sin cambios, ambas devuelven listas vacías.

**Validates: Requirements 9.11, 9.12, 9.13, 9.15**

### Property 26: Ida y vuelta de la fila de Sincronización

*For any* `SyncResult` (fecha, tres SHA de 40 caracteres hexadecimales, lista de 0 a 10 archivos en conflicto, incluidos nombres con `|` o espacios, y resultado de la Puerta_Calidad), `sync_row` produce una fila Markdown con exactamente 6 celdas en el orden de la tabla de Sincronizaciones. Interpretar esa fila devuelve la misma fecha, los SHA abreviados a 7 caracteres, la misma lista de conflictos (los `|` escapados) y el mismo resultado.

**Validates: Requirements 1.13, 2.10**

## Error Handling

| Modo de falla | Dónde se detecta | Respuesta |
|---|---|---|
| Credenciales AWS expiradas o ausentes (cuenta de prueba con credenciales temporales) | `awsauth.check` antes de cualquier escritura en `adapter`, `alerts` (solo si hay `sns_email`) y `deploy_site` | `SystemExit` con código 2: "credenciales inválidas o expiradas para el perfil '<perfil>'; renueva y reintenta". No se escribe nada (Req. 4.11 y 8.12). |
| Día GOES incompleto (error conocido de Nico: marcado como completo) | `check_goes` con escenas por hora | `advertencia` por hora vacía. Solo se escriben las horas presentes (Req. 4.7). |
| ERA5 con NaN (error conocido de Nico) | `check_era5` con la fracción de NaN | `error` si supera el umbral. No se escribe `era5_idx` y el día no es utilizable (Req. 4.8). |
| Zarr escrito a medias (error conocido de Nico, escritura no atómica) | `xr.open_zarr` lanza error o faltan variables o niveles | Se captura y queda como verificación `error` (`era5_store_unreadable`). Si hay CDS para ese día, se usa como alternativa y el reporte lo indica en `era5_origin`. |
| JSON de progreso de Nico sobrescrito | El Adaptador no lo usa: decide por la existencia y el contenido de los objetos | Sin mitigación adicional en v1. |
| `curate_granularity.py` incompatible con la estructura real | No se usa | "sin mitigación en v1". El Adaptador lo reemplaza para esta ruta. |
| ERA5T (`expver=5`) en ago–sep 2026 | `harmonize_cds` | `provenance = "ERA5T"` en el reporte y en `attrs` del `era5_idx`. No bloquea. |
| Índices de capa baja burdos (6 niveles) | Por diseño | Nota en `attrs` y en el Documento_Planificación. No bloquea. |
| Cambio de esquema en las columnas de Daniel (`feature_columns.json` nuevo o configuración `physical` sin C08) | `inference.validate_schema` y `MissingColumnsError` | Código distinto de cero con la lista completa (Req. 5.6). `run_day` sugiere usar `--config baseline_era5`. El sustituto solo exige `cape` y `shear_06`, así que funciona con una tabla solo de ERA5. |
| Artefactos parciales del modelo | `infer.choose_model` | Error con los faltantes. Nunca cae en el sustituto sin aviso (Req. 5.10). |
| Artefacto o Parquet corrupto | `try` alrededor de `model_fn` y `read_parquet` | Error que nombra el archivo, sin escritura (Req. 5.11). |
| Día vacío (sin filas) | `infer` con N = 0 | CSV con encabezado solamente. El sitio no lo incluye por no tener horas. `alerts` informa las zonas sin datos y termina con 0. |
| Coordenadas del catálogo como texto con comas | `viewer_app.data.coordinate` | Se interpretan. Las filas sin coordenadas se descartan con un aviso del total descartado. |
| Catálogo ausente | `read_catalog` devuelve `None` | Sitio sin marcadores y advertencia con la ruta en stderr (Req. 6.14). |
| Zona horaria | Todas las fechas son `datetime` con `tz=UTC`. Los `timestamp` se validan con `datetime.fromisoformat` y `utcoffset() == 0` | Una entrada sin zona se rechaza (Req. 3.4). |
| JSON del sitio grande | Formato entero compacto + `compress = true` en CloudFront | Unos 500 KB sin comprimir por día. Se carga de forma diferida, día por día. |
| CDN de Leaflet no disponible | Leaflet está vendorizado | No aplica. Si las teselas de OSM fallan, se usa fondo neutro y la grilla y los marcadores siguen visibles. |
| Caché de CloudFront con datos viejos | `deploy_site upload` invalida `/sitio/*` | Si la invalidación falla, termina con un código distinto de cero y lo indica. Los datos se ven al vencer el TTL. |
| Ejecuciones concurrentes sobre los mismos archivos | `atomic.write_*` en todas las salidas y `atomic.locked` en la bitácora, el estado de alertas y el JSONL | No hay archivos parciales y gana la última escritura completa. El sitio se intercambia completo. |
| Destino de alerta caído (SNS) | `try` por destino | Se registra y se sigue con los demás, con salida distinta de cero al final (Req. 7.9). |
| Configuración de alertas inválida | `load_config` antes de leer predicciones | Error nombrando el elemento (Req. 7.10). |
| Extensión no admitida en el sitio | `plan_uploads` antes de las credenciales y la red | Error con el archivo y la extensión (Req. 8.6). |
| Operador no confirma `terraform apply` | `deploy_site infra` | Termina con 0 sin aplicar, después de mostrar "sin cambios aplicados". |
| Deriva de contrato con Daniel (falta `model_fn`, `predict_fn`, `output_fn`, `OUTPUT_COLUMNS` o `MissingColumnsError`; `OUTPUT_COLUMNS` cambia; `ERA5_FEATURES` pierde `cape` o `shear_06`; `--stage infer` desaparece) | `tests/test_app_contracts.py` en `make check`, tras cada Sincronización | La prueba falla nombrando cada símbolo o variable faltante, o mostrando la secuencia esperada y la encontrada (Req. 9.11–9.14). Se registra en la bitácora como `bloqueado` y se avisa a Daniel antes de adaptar `infer.py` o `stub_model.py`. |
| Deriva de contrato con Nico (prefijos, patrones, variables, niveles o forma GOES distintos de `docs/DATOS_AWS.md`) | `tests/test_app_contracts.py` contra `lake_layout.py` | La prueba falla con cada constante divergente, su valor esperado y el encontrado (Req. 9.15). Se corrige solo `lake_layout.py` y la expectativa de la prueba, después de confirmarlo con Nico. |
| Conflicto en una Sincronización que rerere no resuelve | `sync_branches.merge_source` | Se detiene con código 1, lista los archivos, registra `bloqueado` y deja el merge en curso. Nunca hace push. Se retoma con `--continue`. |
| Resolución reaplicada por rerere que ya no cumple las reglas (por ejemplo, borra el enlace a `docs/modelo_predictor.md`) | `tests/test_docs.py`, `uv lock --check` y la prueba de fijación `==` dentro de `make check` | La Puerta_Calidad falla y la vuelta queda `bloqueado`. Se corrige a mano y se borra la resolución grabada con `git rerere forget <archivo>`. |
| `origin/main` avanza durante una Sincronización | `sync_branches` compara al final con el SHA registrado | Termina con código 1 y pide repetir la Sincronización. La rama no se publica. |
| Segunda política sobre el bucket de datos (otra rama agrega `aws_s3_bucket_policy` sobre `aws_s3_bucket.data`) | `test_single_bucket_policy` (escaneo de texto de `infra/terraform/*.tf`) | Falla nombrando ambos recursos. Se fusionan los statements dentro de `data_tls_only` en `s3.tf` y se coordina con el responsable de infra. |
| `terraform validate` falla con `sagemaker.tf` presente | Verificación manual tras cada Sincronización | La rama no se publica hasta corregirlo. Si el error es de `sagemaker.tf`, se avisa a Daniel y no se edita el archivo (Req. 8.14). |

Convenciones de salida: los mensajes de error van a stderr, en español y con el prefijo `error:`, y las advertencias con `aviso:`, igual que `build_table.py`. Código 0 es éxito, 1 son fallas de datos o entrega y 2 son argumentos o credenciales inválidos (el comportamiento de `argparse`).

## Testing Strategy

Todas las pruebas usan `unittest` (Puerta_Calidad actual: `make check` = ruff check → ruff format --check → pyright → unittest). Los datos son sintéticos y se generan en memoria o en `tempfile.TemporaryDirectory()`. Ninguna prueba lee ni escribe `data/`, `docs/logs/progreso.json` ni `configs/` reales: las rutas se inyectan por argumento.

### Pruebas basadas en propiedades

- **Biblioteca**: no se agrega `hypothesis`. Cada propiedad es un método `unittest` con un bucle de **al menos 100 casos** generados con `random.Random(SEED)` y `numpy.random.default_rng(SEED)`. Cada prueba fija `SEED` como constante de clase, y el mensaje de falla incluye la semilla y el índice del caso (`self.subTest(case=i, seed=SEED)`), así que una falla se reproduce exactamente (Req. 9.5). Esto evita una dependencia nueva y mantiene el tiempo bajo control. Si el equipo prefiere minimizar contraejemplos automáticamente, `hypothesis` puede agregarse más adelante como dependencia de desarrollo fijada.
- **Una prueba por propiedad**. Cada una lleva el comentario `# Feature: merge-tornado-alert-app, Property N: <título>`.
- **Costo**: la Propiedad 5 usa grillas de 3 × 3 y entre 1 y 3 horas, porque `process_day` interpola perfiles por columna. Las Propiedades 8, 9 y 11 usan el Modelo_Sustituto, y un XGBoost de 5 árboles entrenado en memoria para la parte real. Así, el conjunto completo debería terminar muy por debajo de 300 s (Req. 9.10). Lo mido al implementar.
- Archivos: `tests/test_app_progress_log.py` (P1–P3), `test_app_adapter.py` (P4–P7), `test_app_infer.py` (P8–P11), `test_app_site.py` (P12–P15), `test_app_alerts.py` (P16–P23), `test_app_deploy.py` (P24), `test_app_contracts.py` (P25) y `test_app_sync.py` (P26). Los generadores compartidos van en `tests/app_synthetic.py` (Datasets ERA5 y GOES pequeños, Tablas_Inferencia, CSV y configuraciones).

### Pruebas de ejemplo y de error

- **Adaptador**:
  - `era5_idx` con las 12 `ERA5_FEATURES` y dims `time, latitude, longitude` (4.1).
  - Reporte completo (4.6).
  - Día sin origen, con continuidad al día siguiente (4.10).
  - Credenciales inválidas simuladas con `unittest.mock.patch` sobre `awsauth.check` y verificación de que no se escribió nada (4.11).
  - Fallo de `os.replace` simulado (4.12).
  - Omisión y `--force` (4.13).
  - S3 contra local con un `S3Lake` cuyo `s3fs` se reemplaza por un `fsspec` `LocalFileSystem` sobre un directorio temporal (4.5).
  - Grilla nativa distinta de 882 × 466 (4.9).
- **Inferencia**:
  - Paridad con `inference.predict_fn` usando un modelo pequeño real (5.1).
  - Ruta inexistente que lleva al sustituto (5.2).
  - Los 6 subconjuntos de artefactos parciales (5.10).
  - Parquet y `model.json` corruptos (5.11).
  - CSV previo intacto ante una falla (5.12).
  - NaN que llegan al Modelo_Real sin imputar (5.7).
- **Sitio**:
  - Prueba de instantánea de `index.html`: descargo, leyenda con 5 intervalos y colores viridis, `<label>` en cada control, `#stub-badge` y `#no-data` (6.5–6.8 y 6.11).
  - Cálculo de contraste WCAG de los pares de color de `style.css` (6.8).
  - Ningún CSV válido deja la salida intacta (6.13).
  - Catálogo ausente (6.14).
- **Alertas**:
  - Sin destinos, se usa la consola (7.4).
  - `whatsapp` con `socket.socket` parcheado para fallar si se usa (7.7).
  - `sns_email` con cliente `boto3` mock que recibe `publish` (7.6).
  - `configs/alerts.json` del repo se valida (7.3).
- **Despliegue**:
  - Cliente S3 y CloudFront mock: invalidación solo tras subida completa (8.7).
  - Fallo de subida sin invalidación (8.8).
  - `input` mockeado con "no", sin llamada a `terraform apply` (8.11).
  - Credenciales inválidas antes de subir (8.12).
- **Contratos** (`tests/test_app_contracts.py`, sin red ni AWS; los archivos reales se leen como texto):
  - `scripts/model/sm_job/inference.py` define `model_fn`, `predict_fn`, `output_fn`, `OUTPUT_COLUMNS` y `MissingColumnsError` (`missing_symbols` sobre `ast`). El mensaje nombra cada faltante (9.11).
  - `OUTPUT_COLUMNS == ("probability", "date", "hour_utc", "latitude", "longitude", "config")`. Si no, el mensaje muestra la secuencia esperada y la encontrada (9.12).
  - `scripts/model/table.py`: `ERA5_FEATURES` contiene `cape` y `shear_06` (`tuple_constant`) (9.13).
  - `build_table.py --help` (con `subprocess`, `timeout=60`) termina con 0 y lista `infer` como valor de `--stage`. Si falla, el mensaje dice "la opción --stage infer no está disponible" (9.14).
  - `lake_layout.py` coincide con un mapa `EXPECTED_LAYOUT` en la prueba que transcribe `docs/DATOS_AWS.md` de `intentos-nico`: prefijos, patrones, variables, `LEVELS`, `CDS_RENAME` y `GOES_SHAPE` (9.15). Otra prueba verifica con `ast` que `adapter.py` y `lake.py` no definen literales de prefijos ni de niveles propios, para que exista un único módulo de constantes.
  - Si el código de Daniel aún no está en el árbol (antes de la primera Sincronización), estas pruebas fallan con un mensaje explícito. No se saltan.
- **Documentación**: `tests/test_docs.py` de Daniel corre sin cambios dentro de `unittest` (9.16) y protege el enlace del README en cada Sincronización (1.11).
- **Sincronización** (`tests/test_app_sync.py`):
  - Repo git temporal (`git init` local, sin red) con una rama `main` y dos ramas de origen. `sync_branches` crea `merge/datos-modelo`, hace dos merges `--no-ff` (con dos padres cada uno), registra los SHA y la fila, y no ejecuta `push`. `git` se envuelve para registrar los argumentos.
  - Un conflicto deliberado detiene el script con código 1 y deja el merge en curso.
  - Revisión con `ast` de `sync_branches.py`: ninguna llamada a `git` incluye `push`, `rebase`, `--squash`, `--force` ni `reset`.
- **Terraform** (escaneo de texto de `infra/terraform/*.tf`, sin binario de Terraform):
  - `test_single_bucket_policy`: a lo sumo un `aws_s3_bucket_policy` cuyo `bucket` referencia `aws_s3_bucket.data`.
  - La política de `s3.tf` incluye `resultados/*` y `sitio/*` en `AllowCloudFrontReadResults`.
  - `cloudfront.tf` tiene exactamente un `ordered_cache_behavior` con `/sitio/*`.
  - `site_url` está declarado en `site.tf` y no en `outputs.tf` (8.13).
- **Repositorio**:
  - Sin marcadores de conflicto en `git ls-files` (1.9).
  - `pyproject.toml` con todas las dependencias fijadas con `==` (1.3).
  - Cada `scripts/<área>/*.py` con `def main` y `argparse` responde a `--help` con código 0 (9.6), con `subprocess` y un tiempo límite.
  - Encabezados obligatorios del Documento_Planificación (2.6).
- **Sin red** (9.9): `tests/app_synthetic.py` expone `NoNetworkMixin`, que parchea `socket.socket.connect` para lanzar error durante las pruebas de `scripts/app/`, y define `AWS_PROFILE`, `AWS_ACCESS_KEY_ID` y otras credenciales vacías con `mock.patch.dict(os.environ)`.

### Extremo a extremo sintético (Req. 9.4)

`tests/test_app_e2e.py` arma en un directorio temporal un Lago_Datos local:

- un Zarr `era5_store` de 3 × 3 y 2 horas, con CAPE y cizalladura altas en una celda;
- un `goes_store` pequeño, con su grilla de 882 × 466 parcheada a una forma reducida mediante un parámetro.

Luego ejecuta `adapter` → `build_table.main([... "--stage", "infer", "--config", "baseline_era5"])` con raíces temporales → `infer` (sustituto) → `build_site` → `alerts` con destino `archivo` y umbral bajo. Verifica que existe `index.html` y que el JSONL tiene al menos una Alerta.

`build_table.run` recibe `crops_root` y `model_root` como argumentos, así que se pueden inyectar. Si `main` no expone esas raíces por CLI, la prueba llama a `build_table.run` directamente. No hace falta modificar el código de Daniel.

### Verificaciones manuales (fuera de `make check`)

- `terraform -chdir=infra/terraform init -backend=false && terraform validate` tras cada Sincronización, con `sagemaker.tf` presente (8.14). Luego se revisa `terraform plan`: solo debe cambiar la política del bucket de datos y la distribución (8.1–8.3). Finalmente, `curl -I https://<dominio>/sitio/index.html` (8.9).
- `curl -I https://<dominio>/<otra-clave>` debe devolver 403 (8.4).
- Navegador: centrado del mapa, foco con Tab y flechas, Enter sobre los marcadores, actualización en menos de 2 s y etiqueta de sustituto (6.2–6.4, 6.7, 6.15). La validación completa de WCAG requiere probar con tecnologías de asistencia y una revisión experta.
- Checklist de git del Requisito 1 en cada Sincronización (1.1, 1.2, 1.4–1.6, 1.12–1.14). La mayor parte la automatiza `make sync`. Push y PR quedan siempre manuales y con confirmación del usuario.

Los requisitos ya resuelven la interacción de 7.12 con la supresión (Propiedad 19). Esa interacción y la política de fijación `==` de 1.3 se mantienen como preguntas abiertas para el equipo en `docs/planificacion_merge.md` (Req. 2.11), sin bloquear el diseño.
