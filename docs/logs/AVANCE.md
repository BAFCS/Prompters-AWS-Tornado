# Avance — merge-tornado-alert-app

Spec: `.kiro/specs/merge-tornado-alert-app/` · Rama: `merge/datos-modelo`
Bitácora detallada: `docs/logs/progreso.json`

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
