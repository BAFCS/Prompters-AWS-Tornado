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

## Cobertura de datos lograda (snapshot FINAL 2026-10-15 ~22:40)

El data lake quedó con un **dataset de eventos + control, multi-año, 6 bandas GOES**, construido con
flota multimáquina (ver `ARQUITECTURA_INGESTA.md`).

### ERA5 (`era5_store/*.zarr`) — variables atmosféricas
| Tanda | Rango | Nº |
|---|---|---|
| Base | 2025-10-15 → 2026-07-31 | 291 días |
| Eventos 2020-2025 (bloques 4d) | — | 111 días |
| Eventos 2016-2019 (bloques 4d) | — | 61 días |
| Control (negativos, muestreo sistemático) | 2016-2025 abr-sep | ~383 días |
| **Total ERA5** | 2016-2026 | **~555 días** |

### GOES (`goes_store/<fecha>/goes_YYYYMMDD_CNN.nc`) — 6 bandas, recortadas a Chile
| Bandas | Qué ven | Cobertura |
|---|---|---|
| C13 | IR ventana (topes nubosos) | ~700-730 días, 2018-2026 |
| C08 / C09 / C10 | vapor de agua alto / medio / bajo | ~730 c/u |
| C14 / C15 | split-window (overshooting) | ~720 c/u |

GOES-16 hasta 2025-04-04, GOES-19 desde entonces (GOES-East; GOES-18 es West, no ve Chile). Límite:
GOES-16 arranca dic-2017, por eso los días < 2018-03 solo tienen ERA5.

### Emparejamiento ERA5↔GOES (lo utilizable para entrenar)
- Mismos días, misma grilla (región `south-central-austral`, lat −30..−56, lon −76..−66).
- **~673 días** con ERA5 + C13+C08+C09; **~328** con las 6 bandas (creciendo al cierre).
- Distribución evento/control ~**1:4.6**; manifiesto en `scripts/ingest/etiquetas.json`.

### Relleno CDS
`era5_cds_year/` tiene 2019 + parcial 2026. El relleno del hueco ago-sep 2026 quedó **interrumpido**
(se perdió al reiniciar la cdslab en los reescalados de flota). Pendiente opcional.

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


## Qué está CORRIENDO ahora (cierre)
- **EC2 `mesocyclonic-test-cdslab`** (t3.medium): ociosa (el relleno CDS se interrumpió). Candidata a apagar.
- **EC2 `mesocyclonic-test-viewer`**: visor del clon.
- **EC2 `mesocyclonic-dev-*`**: NO TOCAR (entorno vivo del equipo).
- Bucket **público** de lectura (versionado en Terraform, `data_bucket_public=true`).

## Qué está APAGADO / destruido (ya cumplió)
- Todas las flotas de workers (ncar y GOES) — **destruidas** tras completar sus tandas.
  `ncar_fleet_size=0`, `goes_fleet_size=0`.

## Lecciones aprendidas (operativas)
- **Sharding real** = partir la lista en N archivos físicos (`goes_s*.json`); `--shard-index` sobre
  una lista única NO reparte.
- **8 workers/máquina** es el techo para GOES en c7i.2xlarge (más → OOM, cuelgue, SSM sin responder;
  se recupera con `reboot` por EC2 API).
- **AMI fija** (`var.worker_ami`) evita que Terraform recree instancias vivas.
- **Medir avance contando archivos en S3**, no por logs.
- **Python 3.11** en workers; `common.py` compatible (se quitó el generic PEP 695 de `retry`).

## Pendientes de cierre (opcionales)
1. Apagar la cdslab ociosa.
2. Reactivar el relleno CDS ago-sep 2026 si se quiere cerrar ese hueco (necesita reinyectar
   `.cdsapirc`; la API key quedó visible en chat → **rotarla**).
3. Al cierre del hackathon: revertir el bucket a privado (`data_bucket_public=false`).
