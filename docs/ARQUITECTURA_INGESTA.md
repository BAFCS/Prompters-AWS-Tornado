# Arquitectura del método de ingesta: de fuentes crudas a dataset listo para entrenar

Este documento describe **el método** que agregamos al proyecto para construir el data lake de
mesociclones. El flujo original del repositorio bajaba datos día a día de forma secuencial; aquí se
describe la evolución a un **proceso de ingesta multimáquina, selectivo en espacio-tiempo y con
salida lista para consumo**, que es lo que de verdad diferencia esta tanda.

> En una frase: **tomamos las fuentes crudas (ERA5 + GOES), las pasamos por una flota de EC2
> trabajadoras en paralelo, recortadas al bloque espacio-temporal que nos interesa, y las dejamos
> guardadas en S3 listas para usar — con un esquema anti-sesgo para entrenar.**

---

## 1. Panorama: las cuatro etapas

```
┌─ FUENTES ──────────┐   ┌─ FLOTA (workers) ─────┐   ┌─ SELECCIÓN ────────┐   ┌─ SALIDA ──────────┐
│ ERA5 nsf-ncar      │   │ N × EC2 c7i.2xlarge   │   │ bloque temporal:   │   │ S3 público        │
│ (Zarr, us-west-2)  │──▶│ sharding por sub-     │──▶│  eventos ±2d +     │──▶│ era5_store/*.zarr │
│ ERA5 Copernicus CDS│   │ listas; 8 procesos/   │   │  control sistemát. │   │ goes_store/*.nc   │
│ GOES-16/19 (us-e1) │   │ máquina; idempotente  │   │ bloque espacial:   │   │ + manifiesto de   │
│                    │   │ (skip-existing)       │   │  Chile recortado   │   │   etiquetas       │
└────────────────────┘   └───────────────────────┘   └────────────────────┘   └───────────────────┘
```

---

## 2. Etapa 1 — Fuentes multi-origen

No es una sola fuente, son tres, con tratos distintos:

| Fuente | Qué aporta | Acceso | Truco de rendimiento |
|---|---|---|---|
| **ERA5 `nsf-ncar-era5`** | variables atmosféricas (viento, T, geopotencial, CAPE…) | S3 público, us-west-2 | lectura por **rango de bytes** de bloques globales, recorte en memoria |
| **ERA5 Copernicus CDS** | relleno de días que ncar no tiene (post jul-2026) | API con cola | recorte en servidor (`area:`), pide solo MB |
| **GOES-16/19** | imágenes multiespectrales (6 bandas) | S3 público, us-east-1 | rango de bytes del HDF5 chunked; **misma región**, sin cruce |

El selector de satélite GOES conmuta solo: **GOES-16** hasta 2025-04-04, **GOES-19** desde entonces
(ambos son GOES-East, el que ve Chile; GOES-18 es West y no sirve).

---

## 3. Etapa 2 — Flota multimáquina con sharding (el corazón del método)

En vez de una máquina bajando día a día, se levanta una **flota de N EC2 idénticas** que trabajan
en paralelo. Claves del diseño:

- **Instancia**: `c7i.2xlarge` (8 vCPU, 16 GB) — respeta los límites de la cuenta (sin GPU, <6xlarge),
  us-east-1.
- **Reparto por sub-listas**: la lista de días objetivo se **parte en N trozos** (uno por worker).
  Cada worker baja solo su trozo. (Lección aprendida: el `--shard-index` sobre una `--days-file`
  única no reparte bien; partir la lista en archivos físicos sí garantiza el paralelismo real.)
- **Paralelismo intra-máquina**: cada worker corre **8 procesos** simultáneos. Para GOES, subir de 8
  reventaba la RAM (ensamblar imágenes es pesado) → 8 es el techo seguro en c7i.2xlarge.
- **Idempotencia**: `--skip-existing` salta lo que ya está en S3. Permite reintentar, reescalar o
  recuperarse de caídas sin rebajar nada.
- **Auto-bootstrap**: cada worker, al arrancar, instala su entorno (Python 3.11 + venv con
  xarray/zarr/s3fs/netCDF4/boto3), baja los scripts de `s3://<bucket>/code/` y ejecuta su tarea.
- **AMI fija**: se pinea la AMI (`var.worker_ami`) para que Terraform no recree instancias vivas
  cuando AWS publica una AMI nueva.

Resultado medido: ncar hizo **291 días en ~1.75 h** (vs ~45 h secuencial); el método escala
horizontal sumando máquinas.

Infra: `infra/terraform-test/worker_fleet.tf` + `worker_user_data.sh.tftpl`. Orquestadores:
`scripts/ingest/ingest_ncar_parallel.py`, `ingest_goes_multiband.py`.

---

## 4. Etapa 3 — Selección del bloque espacio-temporal

No se baja "todo": se elige deliberadamente **qué** bajar, para tener densidad de señal sin
desperdicio ni sesgo.

### Recorte espacial
Región `south-central-austral`: **lat −30 a −56, lon −76 a −66** (Chile centro-sur y austral).
Hardcodeada en `common.REGIONS`, idéntica para ERA5 y GOES → casan celda a celda.

### Recorte temporal — bloques alrededor de eventos + control
- **Bloques de evento**: por cada tornado del catálogo (2016-2025), un bloque de **4 días**
  (2 previos + día del evento + 1 posterior). Captura la gestación del entorno y el colapso.
- **Control (negativos)**: muestreo **sistemático** de bloques de 4 días en la misma temporada
  (otoño-invierno austral), **excluyendo** la vecindad de eventos, en ratio ~2:1 control:evento.
- **Manifiesto `etiquetas.json`**: marca cada bloque como `evento` o `control`.

**Por qué así (anti-sesgo):** una sola regla de muestreo para positivos y negativos, misma
estacionalidad, y manifiesto separado → la única diferencia estadística entre clases es el tornado,
no un artefacto del muestreo. El entrenamiento debe usar **leave-one-event-out** y estratificar por
año/temporada.

---

## 5. Etapa 4 — Salida lista para uso

- **ERA5** → `era5_store/era5_YYYYMMDD.zarr` (24 h, 10 variables, 6 niveles de presión).
- **GOES** → `goes_store/<fecha>/goes_YYYYMMDD_CNN.nc` (una banda por archivo).
- **Mismos días, misma grilla** → un consumidor cruza ERA5↔GOES por la fecha del nombre.
- **Bucket público** (lectura anónima, solo-TLS) → el equipo accede con `--no-sign-request`, sin
  credenciales. Cada archivo nuevo hereda el acceso público automáticamente (política con comodín).

El dataset final: **6 bandas GOES** (C13/C08/C09/C10/C14/C15) + **ERA5** (eventos + control),
2016-2026, recortado a Chile, con manifiesto de etiquetas. Analysis-ready.

---

## 6. Qué sumó este método sobre el flujo original

| Antes (flujo base) | Ahora (este método) |
|---|---|
| Descarga día a día, secuencial | **Flota multimáquina en paralelo** con sharding por sub-listas |
| Una fuente a la vez | **Multi-fuente** (ERA5 ncar + CDS + GOES) coordinadas |
| Bajar un rango continuo | **Selección espacio-temporal**: bloques alrededor de eventos + control |
| Datos crudos | **Dataset etiquetado anti-sesgo**, listo para entrenar |
| Reproceso completo si falla | **Idempotente** (skip-existing), reescalable, resiliente |
| — | **Bucket público** para compartir con el equipo sin credenciales |

---

## 7. Lecciones aprendidas (operativas)

- **Sharding real**: partir la lista en N archivos físicos, no confiar en `--shard-index` sobre una
  lista única.
- **8 workers/máquina** es el techo seguro para GOES en c7i.2xlarge (más → OOM y cuelgue).
- **AMI fija** evita que `terraform apply` recree instancias vivas al cambiar el "latest" de AWS.
- **Python 3.11+** en los workers; `common.py` se hizo compatible (se quitó el genérico PEP 695).
- **Medir el avance contando archivos reales en S3**, no por logs (que se pierden) ni por el
  progreso.json (que los sub-shards se pisan).
- **CDS es lento por diseño** (cola de Copernicus): sirve para rellenar huecos puntuales, no para
  cargas masivas; esas van por ncar/GOES con flota.
