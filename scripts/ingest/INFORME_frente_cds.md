# Informe — frente_cds

## Entregable

`scripts/ingest/ingest_cds.py`: script Python autónomo que descarga ERA5 recortado a Chile
desde el Climate Data Store (CDS) de Copernicus con el paquete `cdsapi` y sube los NetCDF al
bucket del experimento.

## Qué hace

- `--date AAAA-MM-DD` (obligatorio): día a descargar. Argparse con `dt.date.fromisoformat`.
- Recorte **solo a Chile** con `area=[-30, -76, -56, -66]` en orden **Norte, Oeste, Sur, Este**
  (lo que exige el CDS), equivalente a la región `south-central-austral` del proyecto.
- Dataset `reanalysis-era5-pressure-levels`: `u_component_of_wind`, `v_component_of_wind`,
  `temperature`, `geopotential`; niveles 1000, 925, 850, 700, 500 y 300 hPa; las 24 horas;
  `data_format=netcdf`.
- Dataset `reanalysis-era5-single-levels`: `10m_u_component_of_wind`,
  `10m_v_component_of_wind`, `2m_temperature`, `2m_dewpoint_temperature`, `surface_pressure`,
  `convective_available_potential_energy` (= 10u, 10v, 2t, 2d, sp, cape); las 24 horas.
- Reporta por `stdout`: tiempo y MB de **cada archivo**, y el **tiempo total** con la tasa
  agregada en MB/s.
- Sube los dos `.nc` a
  `s3://mesocyclonic-test-data-20261015013924290100000003/era5_cds/<date>/` con **boto3**
  (`region_name=us-east-1`).

## Decisiones y supuestos

- Asume que `~/.cdsapirc` ya existe con la clave; el cliente CDS la lee solo.
- Salida local en `data/era5_cds/<date>/` (dos archivos: `era5_pl_AAAAMMDD.nc`,
  `era5_sfc_AAAAMMDD.nc`). `data/` está en `.gitignore`, consistente con el proyecto.
- `--no-upload` permite probar solo la descarga; `--bucket` permite otro destino.
- Manejo de errores:
  - CDS 403 (credenciales inválidas o licencia del producto sin aceptar) y errores de
    cola/espera (`queue`/`timeout`/408) se traducen a mensajes claros en `stderr`.
  - S3 403/AccessDenied (sin `PutObject` o bucket en otra región) se traduce igual.
  - Códigos de salida: 1 = falta `cdsapi`/`~/.cdsapirc`; 2 = falla la descarga; 3 = falla la
    subida; 0 = OK.
- Nada se ejecuta al importar: todo bajo `main()` con `raise SystemExit(main())`.
- `download_format=unarchived` para obtener un `.nc` directo (y no un `.zip`), ya que la nueva
  API del CDS (CDS-Beta) por defecto puede empaquetar la respuesta.

## Verificación

- Compila sin errores con `python -m py_compile` (Python 3.14.2 local): `COMPILE_OK`.
- Convenciones del repo cumplidas: docstring de módulo y de cada función en español, código en
  inglés, type hints en parámetros y retornos, patrón `main()` + argparse como en
  `scripts/pipeline/`.
- **No se ejecutó** el script (no se descargó nada del CDS ni se tocó AWS), según lo pedido.
  `uv run ruff` no se pudo correr en este entorno (uv no disponible/offline); el chequeo de
  estilo queda pendiente de correr en la EC2 de laboratorio con `make check`.

## Notas sobre el experimento

- Ventaja frente a `download_era5.py`: el CDS recorta en el servidor, por lo que la
  transferencia es del tamaño del recuadro (MB), no del bloque global (~11 GB/día). El costo es
  la latencia de la cola del CDS.
- La EC2 `mesocyclonic-test-cdslab` (t3.medium, us-east-1) tiene credenciales de rol, así que
  boto3 subirá sin configurar claves. El bucket debe estar en us-east-1 (us-west-2 está
  denegado por IAM).
