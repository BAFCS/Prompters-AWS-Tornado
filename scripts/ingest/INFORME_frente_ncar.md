# Frente NCAR — ingesta ERA5 por rango de bytes a Zarr

Script entregado: `scripts/ingest/ingest_ncar_zarr.py`

## Qué hace

Baja un día de ERA5 recortado a la región `south-central-austral` (Norte −30, Sur −56, Oeste −76,
Este −66) leyendo el Pool de Datos Abiertos `s3://nsf-ncar-era5/` **por rango de bytes**, y escribe
el resultado como un **store Zarr** en
`s3://mesocyclonic-test-data-20261015013924290100000003/era5_store/era5_AAAAMMDD.zarr`.

Variables (idénticas al frente CDS, para comparar justo):

- Niveles de presión: `u`, `v`, `t`, `z` (geopotencial).
- Superficie: `10u`, `10v`, `2t`, `2d`, `sp`, `cape`.
- Niveles del store final: 1000, 925, 850, 700, 500, 300 hPa (los mismos que pide CDS).

CLI: `uv run python scripts/ingest/ingest_ncar_zarr.py --date 2019-05-30`

## Cómo reutiliza la lógica existente

Importa `scripts/pipeline/download_era5.py` como módulo (`import download_era5 as era5`) y usa sus
primitivas sin duplicarlas:

- `pl_path` / `sfc_path`: claves S3 de los archivos diarios (presión) y mensuales (superficie).
- `read`: para presión, pide a S3 **exactamente los bytes** del bloque horario global
  (`get_chunk_info_by_coord` + `cat_file(start, end)`), lo descomprime (gzip + shuffle) y recorta
  el recuadro en memoria; para superficie lee solo el recuadro del archivo mensual con h5py.
- `day_hours`, `concat_parts`: localizan las 24 horas del día y unen las lecturas horarias.
- `common.REGIONS["south-central-austral"]`, `common.stamp`, `common.now`: región y metadatos.

El recorte a Chile es el mismo `indices()` de `download_era5` (latitudes 90→−90, longitudes
0→360 este). Las lecturas se hacen **en serie, en el proceso principal** (no con el
`ProcessPoolExecutor` del script original) para poder contabilizar los bytes de forma fiable; el
costo transferido es el mismo, solo cambia el paralelismo.

## Diferencia clave con NetCDF: salida Zarr en S3

En vez de `common.write` (NetCDF local con h5netcdf), se arma un único `xarray.Dataset` (presión +
superficie) y se escribe con `ds.to_zarr(mapper, mode="w", consolidated=True)` sobre un
`s3fs.S3Map`. El `s3fs` de destino usa **credenciales de la cuenta** (rol de instancia/entorno),
distinto del `s3fs(anon=True)` de la fuente abierta.

## Medición de tiempo y MB

- **Tiempo total**: `time.time()` alrededor de las lecturas + escritura del Zarr.
- **MB transferidos**: un `_ByteMeter` envuelve `cat_file` y las lecturas de los ficheros abiertos
  del `s3fs` anónimo, sumando todos los bytes leídos de `s3://nsf-ncar-era5/`.

El script reporta por `stdout`: tiempo total (s), MB transferidos y rendimiento (MB/s).

> Nota de equidad: el camino NCAR **transfiere el bloque global con los 37 niveles** aunque solo
> queremos 6 — el servidor no recorta niveles. Por eso los MB reportados son mayores que el tamaño
> del producto final; ese es precisamente el costo real que se compara contra el recorte
> server-side de CDS. El store final sí queda recortado a los 6 niveles de CDS.

## Verificación realizada (sin ejecutar la ingesta)

No se ejecutó nada en AWS ni se creó ningún recurso, según lo pedido. Se validó estáticamente:

- `uv run ruff check scripts/ingest/ingest_ncar_zarr.py` → **All checks passed!**
- `uv run ruff format --check …` → ya formateado.
- `uv run pyright scripts/ingest/ingest_ncar_zarr.py` → **0 errores**.
- `uv run python scripts/ingest/ingest_ncar_zarr.py --help` → imprime el uso (imports y argparse OK).

Cambio menor de configuración: se añadió `scripts/pipeline` a `extraPaths` de pyright en
`pyproject.toml` para que resuelva el import reutilizado `download_era5`. Pyright global no muestra
errores nuevos atribuibles a este frente (los únicos restantes son preexistentes en
`ingest_cds.py`, `run_cloud_training.py` y `train_xgboost.py`: deps opcionales y patrones ya
presentes en el repo).

## Supuestos y notas de entorno

- La fuente NSF NCAR vive en `us-west-2`; el laboratorio solo permite `us-east-1`. La lectura por
  rango de bytes cruza regiones y funciona igual (más lenta), con el mismo volumen de MB.
- El bucket de destino es regional: debe existir en la región donde corre el script, y el rol debe
  tener `s3:PutObject` sobre `era5_store/`.
- Para comparar contra el frente CDS: mismo `--date`, misma región y mismas variables/niveles.
