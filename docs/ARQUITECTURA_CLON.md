# Arquitectura del clon de pruebas y hoja de ruta

Documento de referencia para el equipo. Resume (1) qué construimos en el clon `test` y en qué
se diferencia del `dev` actual, (2) qué tecnologías de AWS están disponibles bajo los permisos
de la cuenta, y (3) el diseño de la **capa de consumo** (data lake + curación por granularidad +
actualización recurrente) para implementar cuando haya recursos libres, sin dañar lo que corre.

> Estado: **planificado y parcialmente validado**. La ingesta multi-fuente ya funciona (ver §1).
> La capa de consumo (§3) está diseñada, lista para construir más adelante.

---

## 1. Qué construimos en el clon `test` vs. el `dev` actual

El `dev` original procesa ERA5 **bajo demanda en cada entrenamiento** (lo baja cross-region cada
vez: el "bajar y subir" lento). El clon `test` construye un **data lake multi-fuente de Chile una
sola vez, en paralelo, reutilizable**.

| Aspecto | `dev` original | Clon `test` (mejoras) |
|---|---|---|
| Datos ERA5 | se re-bajan en cada corrida | ingeridos una vez a S3 (persistente) |
| Fuentes | solo ERA5 | ERA5 (ncar), ERA5 (CDS), **GOES** |
| Formato | NetCDF por corrida | **Zarr** + NetCDF, reutilizable sin rebajar |
| Método de ingesta | 1 EC2 secuencial | **flota de EC2 con sharding** (auto-configurables) |
| Velocidad (año ERA5) | ~45 h estimadas | **~1,75 h** (medido) — ~25× |
| CDS (Copernicus) | no usado | integrado (recorte en servidor: MB en vez de GB) |
| Infra como código | Terraform base | Terraform extendido + scripts de ingesta |
| Observabilidad | log local en la EC2 | `progreso_*.json` en S3 + panel |
| Aislamiento | entorno vivo | clon independiente (`-test-`), destruible |

**Datos ya ingeridos (verificados por `s3api`), recortados a Chile (lat −56..−30, lon −76..−66):**

- ERA5 ncar → `s3://<bucket>/era5_store/` — Zarr, 291 días (oct-2025 → jul-2026, límite de ERA5), ~2.6 GB.
- ERA5 CDS → `s3://<bucket>/era5_cds_year/` — NetCDF, en curso.
- GOES C13 → `s3://<bucket>/goes_store/` — NetCDF, año 2025-10 → 2026-10, en curso.

**Cobertura temporal (hallazgo):** el bucket público `nsf-ncar-era5` publica hasta ~jul-2026
(latencia del reanálisis). GOES es casi tiempo real. CDS/ERA5T suele ir más al día que ncar, por lo
que es la fuente indicada para rellenar el hueco reciente de ERA5 (ago-sep 2026).

---

## 2. Tecnologías de AWS disponibles (verificado por llamada real, sin AccessDenied)

Bajo el rol `WSParticipantRole` (cuenta de la hackathon), en **us-east-1**:

| Servicio | Disponible | Uso en el proyecto |
|---|---|---|
| EC2 (hasta `*.4xlarge`, sin GPU) | ✅ | ingesta (lo que usamos hoy) |
| S3 | ✅ | data lake |
| AWS Batch | ✅ | reemplazar la flota manual por array jobs gestionados |
| Step Functions | ✅ | orquestar ingesta → curación → entrenamiento |
| EventBridge Scheduler | ✅ | ingesta incremental automática (días nuevos) |
| SageMaker (CPU) | ✅ | fase de entrenamiento del modelo |
| ECS / Fargate | ✅ | pipeline en contenedores sin gestionar EC2 |
| Athena / Glue | ✅ | consultar índices/resultados con SQL |
| Lambda (1000 conc.) | ✅ | orquestación / inferencia bajo demanda |

**NO disponible** (deny explícito en la política IAM): GPU (familias `g*`/`p*`), instancias
`>=6xlarge`, crear recursos fuera de us-east-1, subir cuotas de servicio, Organizations/Support.

---

## 3. Capa de consumo (diseño para implementar cuando haya recursos)

Cierre de la arquitectura: que el modelo/repo **lea el data lake directo desde S3 en la nube** y
que el equipo pueda **seleccionar y curar** datasets bajo demanda, guardándolos de vuelta en S3.

### 3.1 Lectura directa desde S3 (sin descargar)

Los stores son Zarr/NetCDF en S3; `xarray` los abre en la nube con `s3fs` sin copiarlos a disco:

```python
import xarray as xr, s3fs
fs = s3fs.S3FileSystem()
ds = xr.open_zarr(s3fs.S3Map("s3://<bucket>/era5_store/era5_YYYYMMDD.zarr", s3=fs))
# ... o un dataset curado (ver 3.2)
```

Esto hace que el entrenamiento consuma el data lake sin re-descargar (elimina el "bajar y subir").

### 3.2 Selección y curación por granularidad (el "Desafío 2")

Un script/servicio `curate.py` que recibe los parámetros del equipo y produce un dataset curado:

- **Variables**: subconjunto de `u,v,t,z,10u,10v,2t,2d,sp,cape` (+ bandas GOES).
- **Ventana temporal**: rango de fechas + región.
- **Granularidad temporal** (una de):
  - `full` — todas las horas.
  - `every_Nh` — submuestreo cada N horas (`isel(time::N)`).
  - `mean_Nh` — promedio cada N horas (`resample(time=...).mean()`).
  - `minmax_Nh` — **binario max/min** cada N horas (`resample(...).max()` y `.min()`), para
    capturar extremos (útil en tiempo severo).
- **Recorte espacial**: Chile completo o sub-región más estrecha.

Salida: dataset Zarr/NetCDF en `s3://<bucket>/curated/<config-hash>/` **(mismo bucket = más rápido,
intra-región; o bucket vecino si se quiere separar)**. Un `catalog.json` indexa cada dataset curado
(parámetros, ruta, nº de pasos) para que el equipo elija el que le sirva sin regenerarlo.

### 3.3 Flujo de curación (orquestación)

```
Equipo elige (vars, ventana, granularidad)
        │
        ▼
curate.py  ──lee──► s3://.../era5_store, goes_store (data lake, en la nube)
        │ aplica submuestreo / promedio / minmax / recorte
        ▼
s3://.../curated/<config>/   +  catalog.json
        │
        ▼
Entrenamiento (SageMaker o EC2) lee el curado directo de S3
```

Para producción: **Step Functions** encadena curación → entrenamiento; **Fargate/Batch** corre
`curate.py` sin gestionar EC2.

### 3.4 Actualización recurrente (mantener el data lake al día)

Como la herramienta se entrega y debe mantenerse viva:

1. **Detectar lo pendiente**: un `catalog.json` del data lake registra qué días ya están. Un
   proceso compara contra lo disponible en la fuente (GOES casi tiempo real; ERA5 según publique
   ncar/CDS) y calcula los días faltantes.
2. **Bajar solo lo pendiente**: reutiliza los scripts de ingesta con `--skip-existing` (ya
   implementado), de modo que nunca re-baja lo que ya está.
3. **Descarga recurrente**: **EventBridge Scheduler** dispara la ingesta incremental (p. ej. cada
   noche). GOES se actualiza casi al día; ERA5 cuando la fuente publique nuevos meses.

```
EventBridge Scheduler (cron nocturno)
        │
        ▼
Lambda/Batch "detector" ──► compara catálogo vs. fuente ──► lista de días faltantes
        │
        ▼
Flota/Batch de ingesta (--skip-existing) ──► S3 data lake actualizado
```

### 3.5 Qué queda listo hoy y qué se construye después

**Listo hoy** (ya en el repo / S3):
- Ingesta de las 3 fuentes con flota de sharding + `--skip-existing`.
- Data lake de Chile en S3 (ncar completo; GOES/CDS en curso).
- Scripts: `ingest_ncar_parallel.py`, `ingest_cds_year.py`, `ingest_goes.py`, `panel_monitor.py`.

**Por construir cuando haya recursos libres** (sin dañar lo vivo):
- `curate.py` con las granularidades (full / every_Nh / mean_Nh / minmax_Nh) + `catalog.json`.
- Capa de lectura directa S3 integrada en el entrenamiento del repo.
- Orquestación con Step Functions + Batch/Fargate.
- Actualización recurrente con EventBridge Scheduler + detector de pendientes.

> Regla de implementación (acordada): validar siempre con una **tanda pequeña** antes de escalar, y
> que ninguna mejora rompa un flujo que ya corre. Lanzar solo cuando haya recursos libres.

---

## 4. Naturaleza de esta tanda: es de PRUEBAS

La ingesta actual (oct-2025 → oct-2026, variables y niveles reducidos) es una **tanda de prueba**
para validar el método, no la base definitiva. Sirvió para:

- Validar la arquitectura de ingesta (flota con sharding, 3 fuentes, Zarr, observabilidad).
- Medir los cuellos de botella reales de cada fuente.
- Confirmar que los datos quedan recortados a Chile y son correctos.

**Cuando esta tanda de prueba termine**, el plan es construir la **tanda completa** (abajo).

### 4.1 Plan de la "tanda completa" (futuro, con recursos libres)

Usando las mismas técnicas ya validadas (que ahora son más eficientes), pero con más detalle:

- **Más variables y niveles de presión**: recuperar los niveles bajos y variables que el pipeline
  original del repo ya usaba (clave para cizalladura/SRH, que viven cerca de la superficie). No
  recortar la ciencia por ahorrar transferencia.
- **Ventana espacial = TODO Chile**: ampliar el recuadro para cubrir el territorio completo (no solo
  south-central-austral), cuidando no excluir zonas de eventos (p. ej. Biobío ~−37°S).
- **Ventana temporal más amplia**: más años para tener suficientes casos positivos de entrenamiento.
- **Migrar de flota manual a Batch/Spot**: ingesta gestionada (AWS maneja cuota y apagado solo),
  más barata con Spot, sin levantar/destruir EC2 a mano.
- **Lanzar solo cuando haya recursos libres**, sin dañar flujos vivos.

---

## 5. Hallazgos de la auditoría multiagente (revisión crítica)

Se revisó el diseño con agentes independientes (arquitecto cloud, científico de datos
meteorológicos, FinOps/riesgos). Puntos a corregir antes de la tanda completa:

| # | Hallazgo | Acción |
|---|---|---|
| H1 | Recursos encendidos sin uso (gasto/cuota) | ✅ hecho: destruidas `ingest_ncar` y `ingest_goes` ociosas; falta autoapagado de flotas |
| H2 | Capa consumo asume store único; ingesta hizo 1 Zarr por día | unificar layout Zarr en la tanda completa |
| H3 | Data lake de prueba ingiere menos niveles/variables que el repo original | recuperar variables/niveles científicos en la tanda completa |
| H4 | Promediar (`mean_Nh`) borra la señal de tiempo severo (dura minutos) | priorizar `minmax_Nh` y `full`; cuidar signo austral de SRH |
| H5 | `chile_only` estrecho podía excluir eventos (Biobío) | ampliar a todo Chile en la tanda completa |
| H6 | `skip-existing`, `minmax_Nh`, `catalog.json` prometidos pero no todos implementados | implementar en la fase de consumo |
| H7 | QA de completitud: días saltados dejan huecos silenciosos | añadir validación de completitud al pipeline |
| H8 | IAM con `DeleteObject` global y API key CDS usada | reducir blast radius; rotar/revocar la key CDS tras la hackathon |

**Práctica acordada:** validar constantemente con revisión multiagente para asegurar que el rumbo
es correcto, no solo la ejecución.

---

## 6. Validación del relleno CDS y de la compatibilidad (2ª auditoría multiagente)

### 6.1 Relleno del hueco ERA5 con CDS — APTO como tanda de prueba, con reservas

- ✅ CDS y ncar son el mismo reanálisis ERA5 (intercambiables). CDS es la única fuente que llega a
  sep-2026 (ncar corta ~jul-2026). Se lanzó CDS para bajar **solo** el hueco ago-sep 2026.
- ⚠️ **Reserva 1 — evidencia limitada:** la coincidencia dif=0.000 K se midió con 1 variable (T),
  1 nivel (500 hPa), 1 día (2026-05-20, en zona de solape), como media espacial. Antes de tratarlo
  como base científica hay que ampliar la verificación (u, v, z, niveles bajos, superficie/CAPE, con
  máx|Δ|/RMSE, y un día en régimen reciente).
- ⚠️ **Reserva 2 — ERA5T preliminar:** el tramo ago-sep 2026 probablemente es ERA5T (`expver=5`),
  que ECMWF revisa al consolidar la ERA5 final (~2-3 meses). Mezclar ncar-final + CDS-ERA5T es válido
  para pruebas, pero hay que **etiquetar procedencia/versión por día** y **re-descargar ago-sep 2026**
  cuando salga la versión final.

### 6.2 Compatibilidad data lake ↔ capa de consumo — REQUIERE ARMONIZACIÓN (bloqueante)

El data lake tiene las 3 fuentes en formatos/esquemas distintos, y la capa de curación **no puede
construirse hasta armonizarlos**:

| Incompatibilidad | Detalle |
|---|---|
| Layout | ncar = 1 Zarr por día; `curate` asume store único → falla |
| Formato | Zarr (ncar) vs NetCDF (CDS, GOES) |
| Coords | `time`/`level` (ncar) vs `valid_time`/`pressure_level` (+ `expver`) (CDS) |
| Variables | nombres cortos (ncar) vs largos (CDS) |
| pl/sfc | ncar fusiona; CDS deja 2 NetCDF separados |
| GOES | grilla ABI geoestacionaria, necesita regrid a lat/lon de ERA5 |

**Armonización mínima necesaria antes de la curación:** renombrar coords/variables CDS→ncar,
colapsar `expver`, mergear pl+sfc de CDS, convertir CDS NetCDF→Zarr con el mismo chunking, regrid de
GOES (reutilizar `process_goes.py`), y materializar un **store único concatenado en `time`** por
fuente, con atributo de procedencia por paso. Más `catalog.json` del data lake y verificación de
completitud.

### 6.3 Qué se puede hacer YA vs. qué esperar

- **YA (sin riesgo):** terminar el relleno CDS ago-sep 2026; etiquetar procedencia por día; construir
  `catalog.json`; ampliar el script de verificación; priorizar `full` y `minmax_Nh` sobre `mean_Nh`.
- **ANTES de construir la curación (bloqueante):** armonización de esquema (§6.2), decidir layout de
  store, convertir CDS a Zarr, regrid GOES, implementar `minmax_Nh` y la actualización recurrente.
- **Por calendario:** re-descargar ago-sep 2026 cuando ECMWF publique la ERA5 final.

