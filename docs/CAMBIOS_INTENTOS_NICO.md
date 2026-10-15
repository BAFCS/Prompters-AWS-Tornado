# Cambios de la rama `intentos-nico`

Resumen de lo nuevo que aporta esta rama respecto al `main`/repo original. Es una **tanda de
pruebas** para validar la optimización del flujo de datos; no modifica el pipeline ni el visor
existentes.

## Qué se agregó (todo nuevo, no toca lo existente)

### Infraestructura — `infra/terraform-test/`
Clon aislado del stack (`environment=test`) + extensiones para la ingesta:
- `cdslab.tf` — EC2 de laboratorio para ingesta CDS (Copernicus).
- `ingest_fleet.tf` — EC2 dedicadas de ingesta (ncar, GOES).
- `worker_fleet.tf` + `worker_user_data.sh.tftpl` — **flota de workers con sharding**,
  auto-configurables, escalable por `ncar_fleet_size` / `goes_fleet_size`.
- `test.tfvars` — config del clon (us-east-1, sin GPU, `t3.medium`, etc.).

### Scripts de ingesta — `scripts/ingest/`
- `ingest_cds.py` — ERA5 vía Copernicus CDS (recorte en servidor con `area=Chile`).
- `ingest_cds_year.py` — ingesta de un rango largo por día, con `progreso.json` a S3.
- `ingest_ncar_zarr.py` — ERA5 vía NSF NCAR (byte-range) → Zarr, con reintentos/timeout.
- `ingest_ncar_parallel.py` — orquestador paralelo (N días a la vez, sharding).
- `ingest_goes.py` — GOES-16/19 banda C13 → NetCDF, con sharding y `--skip-existing`.
- `curate_granularity.py` — (borrador) curación por granularidad; requiere armonización previa.
- `panel_monitor.py` — panel unificado que lee los `progreso_*.json`.
- `verif_cds_vs_ncar.py` — compara CDS vs ncar para validar equivalencia.

### Documentación — `docs/`
- `ARQUITECTURA_CLON.md` — diseño, diferencias con `dev`, tecnologías disponibles, capa de consumo,
  y hallazgos de dos auditorías multiagente.
- `DATOS_AWS.md` — dónde están los datos en S3 y cómo leerlos/tratarlos (para agentes).
- `CAMBIOS_INTENTOS_NICO.md` — este archivo.

## Qué se logró (medido)

- Data lake de Chile en S3 con 3 fuentes: ERA5 ncar (Zarr, ~291 días), ERA5 CDS (NetCDF), GOES
  (NetCDF, ~351 días). ~16 GB.
- Ingesta ERA5 ncar con flota de 6 workers: de ~45 h (secuencial) a **~1,75 h**.
- Verificado: datos recortados a Chile; CDS≡ncar (dif 0.000 K en el día probado); CDS llega a
  sep-2026 (rellena el hueco que ncar no cubre).

## Qué queda pendiente (ver ARQUITECTURA_CLON.md §6.3)

- Armonizar esquemas (ncar Zarr vs CDS NetCDF vs GOES) a un store único — **bloqueante** para la
  capa de curación.
- Implementar `minmax_Nh`, `catalog.json` del data lake y la actualización recurrente.
- Re-descargar ago-sep 2026 cuando salga la ERA5 final (hoy es ERA5T preliminar).
- Recuperar variables/niveles científicos y ampliar a todo Chile en la **tanda completa**.
- Migrar la flota manual a AWS Batch/Spot para producción.

## Cómo NO romper nada

- El `dev` vivo no se toca (state separado, nombres `-test-`).
- Las flotas se apagan con `*_fleet_size=0` y `enable_ingest_fleet=false`.
- Validar siempre con una tanda pequeña antes de escalar.
