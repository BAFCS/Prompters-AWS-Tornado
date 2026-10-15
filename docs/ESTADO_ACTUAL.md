# Estado actual — dónde quedamos (snapshot 2026-10-15)

Foto operativa puntual para retomar sin perderse. (El diseño está en `ARQUITECTURA_CLON.md`; los
pendientes en `PENDIENTES.md`. Este archivo es el "¿en qué quedamos?".)

## Cuenta / acceso
- Cuenta `822870558093`, rol `WSParticipantRole`, **solo us-east-1**.
- Credenciales **temporales** en `~/.aws/credentials` (perfil `default` y `era5`). Caducan; si da
  `ExpiredTokenException`, renovar del portal.
- Terraform: binario portable en `C:\Users\ndelg\.local\terraform\terraform.exe`. Infra en
  `infra/terraform-test/` (state local ahí; `environment=test`).

## Bucket del data lake
`s3://mesocyclonic-test-data-20261015013924290100000003/`

## Cobertura de datos lograda (al 2026-10-15 ~10:00)
| Fuente | Prefijo S3 | Cobertura | Nº | Detalle |
|---|---|---|---|---|
| ERA5 ncar | `era5_store/*.zarr` | 2025-10-15 → **2026-07-31** (+2019-05-30) | 291 días | Zarr; 24h/día; 10 vars; 6 niveles |
| ERA5 CDS | `era5_cds_year/<AAAA>/<MM>/` | parcial 2025-10→2026-01 + **relleno ago-sep 2026 EN CURSO** | — | NetCDF (pl+sfc separados) |
| GOES C13 | `goes_store/<fecha>/` | 2025-10-15 → **2026-09-30** | 351 días | NetCDF; 144 escenas/día; imagen |

Límite ERA5 ncar = jul-2026 (el bucket público nsf-ncar-era5 no publica más reciente). CDS llega a
sep-2026 (verificado) → por eso rellena ago-sep 2026. Verificado CDS≡ncar: dif 0.000 K (T, 500 hPa,
2026-05-20).

## Qué está CORRIENDO ahora
- **EC2 `mesocyclonic-test-cdslab`** (t3.medium, running): corre el **relleno CDS ago-sep 2026** en
  background (`ingest_cds_year.py --start 2026-08 --end 2026-09`, log en `/tmp/relleno.log`,
  progreso en `s3://.../experimentos/progreso.json`). Al último chequeo: 1/122 pasos (lento por la
  cola de Copernicus). Es idempotente (`--skip-existing` no aplica aquí pero `ingest_cds_year` salta
  lo ya subido).
- **EC2 `mesocyclonic-test-viewer`** (t3.medium, running): visor del clon.
- **EC2 `mesocyclonic-dev-*`**: NO TOCAR (entorno vivo del equipo).

## Qué está APAGADO / destruido (ya cumplió)
- Flota ncar (6 workers) — destruida tras completar ncar.
- Flota GOES (6 workers) — destruida tras completar GOES.
- `ingest_ncar` (r7i) e `ingest_goes` (t3.large) — destruidas (`enable_ingest_fleet=false`).

## Cómo RETOMAR el relleno si se apagó la cdslab
```bash
cd infra/terraform-test
# si la cdslab fue destruida, recrearla:
terraform apply -var-file=test.tfvars -var="enable_cdslab=true"
# re-inyectar la API key de CDS a ~/.cdsapirc por SSM (ver DATOS_AWS.md)
# relanzar (salta lo ya hecho):
#   python scripts/ingest/ingest_cds_year.py --start 2026-08 --end 2026-09
```

## Decisión pendiente del usuario
Qué hacer con el relleno CDS (lento por cola): (a) dejarlo correr, (b) apagar cdslab y retomar otro
día, o (c) darlo por suficiente (ya está la mayor parte: ncar oct2025→jul2026 + GOES año completo).

## Rama git
`intentos-nico` (pusheada a origin). 3 commits: data lake + docs + pendientes.
