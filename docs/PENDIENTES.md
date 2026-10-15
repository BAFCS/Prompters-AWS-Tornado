# Pendientes — rama `intentos-nico`

Lista de trabajo pendiente para que el equipo retome. Ordenada por prioridad. Validada con auditoría
multiagente (ver `ARQUITECTURA_CLON.md` §5-§6).

> **Estado actual:** la arquitectura de **ingesta** está montada y funcionando (clon aislado + data
> lake de 3 fuentes recortado a Chile en S3, ~16 GB). La capa de **consumo/actualización** está
> diseñada y documentada, **no desplegada**. Esto fue una **tanda de prueba** para validar el método.

## Qué está montado hoy ✅
- Clon aislado `environment=test` (us-east-1, no toca `dev`).
- Data lake en `s3://mesocyclonic-test-data-20261015013924290100000003/`:
  - ERA5 ncar (Zarr): ~291 días (2025-10-15 → 2026-07-31).
  - ERA5 CDS (NetCDF): parcial + relleno ago-sep 2026 en curso.
  - GOES C13 (NetCDF): ~351 días (2025-10-15 → 2026-09-30).
- Lógica de descarga acelerada (flota de EC2 con sharding) — ejecutada; las flotas se apagaron.
- EC2 encendidas: `test-viewer`, `test-cdslab` (relleno CDS). `dev` intacto.

## Pendientes

### P0 — Seguridad (hacer antes de cerrar la hackathon)
- [ ] **Rotar/revocar la API key de CDS** usada en `~/.cdsapirc` de la EC2 (quedó expuesta en el chat).
- [ ] **Reducir el `s3:DeleteObject`** de la política IAM del cdslab (`cdslab.tf`): hoy es sobre todo
      el bucket; acotar a los prefijos necesarios (blast radius).
- [ ] Al terminar, **revocar/renovar las credenciales temporales** del `WSParticipantRole`.

### P1 — Costos / operación
- [ ] **Autoapagado de flotas**: hoy se apagan a mano (`*_fleet_size=0`, `enable_ingest_fleet=false`).
      Añadir apagado automático al terminar el job (como hace la EC2 de training con `stop_after`).
- [ ] Destruir `test-cdslab` cuando el relleno ago-sep 2026 termine (revisar `experimentos/progreso.json`).
- [ ] Considerar `terraform destroy` del clon completo cuando ya no se use (deja costo en ~0).

### P2 — Armonización de esquemas (BLOQUEANTE para curar/entrenar)
Antes de construir la capa de curación/consumo (ver `ARQUITECTURA_CLON.md` §6.2):
- [ ] Renombrar coords/vars CDS→ncar (`valid_time`→`time`, `pressure_level`→`level`, `u10`→`10u`,
      `t2m`→`2t`, etc.) y colapsar `expver`.
- [ ] Mergear pl+sfc de CDS en un dataset único por día.
- [ ] Convertir CDS NetCDF → Zarr con el mismo chunking/dims que ncar.
- [ ] Regrid de GOES a la grilla lat/lon de ERA5 (reutilizar `scripts/pipeline/process_goes.py`).
- [ ] Materializar un **store único concatenado en `time`** por fuente + atributo de procedencia.

### P3 — Capa de consumo (tras P2)
- [ ] Implementar `curate_granularity.py` de verdad: `full`, `every_Nh`, `mean_Nh`, **`minmax_Nh`**
      (priorizar `full` y `minmax_Nh`; `mean_Nh` borra la señal de tiempo severo).
- [ ] `catalog.json` del data lake (días por fuente/variable) para detección de pendientes.
- [ ] Lectura directa S3 integrada al entrenamiento del repo (xarray + s3fs, sin descargar).
- [ ] QA de completitud (detectar días saltados/huecos silenciosos).

### P4 — Actualización recurrente (producción)
- [ ] EventBridge Scheduler (cron nocturno) + detector Lambda de días faltantes + ingesta
      incremental con `--skip-existing`.
- [ ] Migrar la flota manual de EC2 a **AWS Batch/Spot** (gestiona cuota y apagado solo).

### P5 — Tanda completa (base definitiva, con recursos libres)
- [ ] Recuperar variables/niveles científicos (más niveles bajos para cizalladura/SRH).
- [ ] Ampliar ventana espacial a **todo Chile** (no solo south-central-austral; no excluir Biobío).
- [ ] Más años para tener más casos positivos.
- [ ] Re-descargar ago-sep 2026 cuando ECMWF publique la ERA5 final (hoy es ERA5T preliminar).
- [ ] Ampliar validación CDS≡ncar (más variables/niveles/días, no solo 1).

## Regla de trabajo acordada
Validar siempre con una **tanda pequeña** antes de escalar; que ninguna mejora rompa un flujo que ya
corre; lanzar solo cuando haya recursos libres; validar el rumbo con revisión multiagente.
