# Avance — merge-tornado-alert-app

Spec: `.kiro/specs/merge-tornado-alert-app/` · Rama: `merge/datos-modelo`
Bitácora detallada: `docs/logs/progreso.json`

## Sitio público (AWS)

**https://d1m48zea07nk1y.cloudfront.net/resultados/sitio/index.html**

CloudFront `E1QZXODGHESLF4` → bucket `mesocyclonic-dev-data-20261015215812490800000001` (cuenta `gpu`, us-east-1),
prefijo `resultados/sitio/` (ya permitido por la OAC). Republicar tras regenerar `demo_site/`: `make publish`.
Sitio público sin autenticación.

## Correr el prototipo (demo)

```bash
git checkout merge/datos-modelo && git pull && uv sync
make data/tornados_chile.xlsx                       # catálogo (si falta)
B=mesocyclonic-test-data-20261015013924290100000003  # bucket del Lago_Datos (lectura anónima)
uv run python scripts/model/sync_from_bucket.py --bucket $B --start 2019-05-30 --end 2019-05-31 --only era5
uv run python scripts/app/prototype.py --start 2019-05-30 --end 2019-05-31 --serve
# abre http://localhost:8000  → día 2019-05-30, mueve la hora 15→23 UTC
```

Salidas en `data/app/`: `predictions/pred_AAAAMMDD.csv` (+ `.meta.json`), `site/` y `alerts.jsonl`.
El prototipo usa el **Modelo_Sustituto** (CAPE × cizalladura 0–6 km); el sitio lo indica con una etiqueta.

## Rama y SHAs integrados

| Ref | SHA |
|---|---|
| origin/main | `cf59a73` |
| origin/intentos-nico | `ec238df` |
| origin/feat/multimodal-tornado-predictor-wip | `3cd882b` |
| origin/adapter-bucket (BAFCS) | `7274812` |
| Merges en la rama | `ecf305a` (Nico), `b48a44a` (modelo), `979e893` (adapter-bucket) |

## Estado de tareas

| Tarea | Estado |
|---|---|
| 0. Prototipo de demo | hecho (`scripts/app/prototype.py`, prueba sintética) |
| 1–6 (sincronización, bitácora, planificación, contratos, `make sync`, checkpoint) | hechas |
| 7.1 awsauth · 9.1 stub_model · 9.2 predictions | hechas |
| 7.2–7.5 adaptador | **reemplazadas** por `scripts/model/sync_from_bucket.py` (adapter-bucket) |
| 7.12 Reporte_Calidad sobre `sync_from_bucket` | pendiente |
| 8, 9.3, 9.4, 10–18 | pendientes (inferencia real, sitio definitivo, alertas configurables, run_day, terraform, e2e) |
| 19 push/PR · 20 terraform apply/subida | requieren confirmación |

`make check`: OK (191 pruebas) en el último commit.

## Pendientes y decisiones abiertas

- **Bucket del Lago_Datos legible sin credenciales**: confirmar si es intencional (riesgo de costo/exposición).
- `sync_from_bucket.py` no tiene Reporte_Calidad ni escrituras atómicas: un día subido a medias se procesa igual (tarea 7.12).
- Modelo real de Daniel aún sin artefactos (`model.json`): el prototipo usa el sustituto.
- `stash@{0}`: cambio de diagramas del Makefile del usuario, sin restaurar.
- Config `physical` necesita C08; Nico escribe `goes_<ymd>_C08.nc` cuando lo ingiere.
- Credenciales del perfil `default` (cuenta hackathon) expiradas; el bucket se lee anónimo.

## Seguir el avance desde la CLI

```bash
cat docs/logs/AVANCE.md
grep -nE '^\s*- \[[ x~-]\]' .kiro/specs/merge-tornado-alert-app/tasks.md
.venv/bin/python -c "import json;[print(e['timestamp'],e['estado'],e['tarea']) for e in json.load(open('docs/logs/progreso.json'))]"
git log --oneline -5 && git status --short
```

## Cómo retomar

Orden sugerido: 7.12 → 9.3 (infer real) → 10 (sitio definitivo) → 12 (alertas) → 14 (run_day sobre `sync_from_bucket`) → 15 (terraform/deploy) → 16–18.
Abrir `tasks.md` en Kiro y usar "Run All Tasks".

## Modelo híbrido real (2026-10-15)

- Modelos versionados en `models/` (`hibrido/`, `hibrido_holdout_20190530/`); sitio demo en `demo_site/`
  (`python -m http.server 8000 -d demo_site`). Métricas LOEO: CSI 0,345 (embeddings) vs 0,294 (physical)
  y 0,274 (baseline_era5). Detalle en `.agents/tasks/hibrido/real_report.md`.
- Snapshot de datos usados: `.agents/tasks/hibrido/{era5_snapshot,goes_snapshot,neg_days}.txt`.
- **Pendiente: reentrenar sin sesgo de fuente.** Los positivos usaron GOES de NOAA y los negativos GOES
  del bucket. El bucket ya trae GOES 2018–2026 (2.991 archivos, 21 días con evento con C08+C13; 2023–2024
  aún a medias; 2017 sin datos). Reentrenar con GOES del bucket para todos los días.

## Modelo híbrido v2 (2026-10-15, publicado)

- Reentreno con GOES **solo del bucket** para eventos y negativos (sin sesgo de fuente NOAA/bucket):
  35 días de evento (44 positivas) + 70 negativos estratificados por mes (`.agents/tasks/hibrido/v2_neg_days.txt`).
  GOES de NOAA de v1 apartado en `data/crops/_noaa_v1_backup/`.
- LOEO (37 eventos): CSI embeddings 0,298 · physical 0,309 · baseline 0,271 (v1: 0,345 / 0,294 / 0,274);
  retención 2019-05-30/31: embeddings 0,322, physical 0,385. Comprobación de sesgo: AUC día-evento vs
  negativo con GOES solo ≈ 0,45–0,55 en v1 y v2 (sin sesgo detectable). Sigue publicado embeddings.
- Artefactos: `models/v2/`, `demo_site_v2/`, `s3://mesocyclonic-model-905418466452/models/v2_2026-10-15/` y
  `sites/v2_2026-10-15/`. Sitio público ya en v2 (`make publish SITE_DIR=demo_site_v2`).
- Texto de métricas de la pestaña actualizado en `adapter-bucket` (`9d82a1d`): **requiere reiniciar la EC2**
  del visor (no hecho). Detalle: `.agents/tasks/hibrido/v2_report.md`.
- Pendiente: 2024-06-20 y 2025-05-17 sin C08 en el bucket (GOES en NaN solo en días de evento: posible pista).

## Pestaña "Mapa del modelo" en el visor de producción (2026-10-16)

- URL: https://d1m48zea07nk1y.cloudfront.net/mapa-modelo (junto a «Predecir»). Código en la rama de
  producción `adapter-bucket` (commits `f042530`, `5d6aa09`): `scripts/viewer/viewer_app/p_forecast.py`
  embebe `/resultados/sitio/index.html`.
- Redespliegue: la EC2 `i-06edee033ab05ac08` no está registrada en SSM, así que se paró, se le puso
  user-data multipart con `cloud_final_modules: [scripts-user, always]` (el mismo script de Terraform,
  ahora corre en cada arranque) y se volvió a iniciar. **Para redesplegar de ahora en adelante basta con
  reiniciar la instancia (stop/start)**, pero cambia el DNS público: hay que actualizar el origen
  `viewer-ec2` de CloudFront `E1QZXODGHESLF4` (hoy `ec2-34-237-2-186.compute-1.amazonaws.com`).
- **Deriva de Terraform:** user-data y origen de CloudFront cambiaron fuera del state de BAFCS. Un
  `terraform apply` revertiría la user-data (con `user_data_replace_on_change` podría recrear la EC2) y
  re-sincronizaría el origen. Avisar a BAFCS antes de aplicar; lo correcto es portar el cambio a
  `user_data.sh.tftpl` o usar una Elastic IP.
