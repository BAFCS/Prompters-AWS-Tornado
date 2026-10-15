# Avance — merge-tornado-alert-app

Spec: `.kiro/specs/merge-tornado-alert-app/` · Rama: `merge/datos-modelo` (sin push)
Bitácora detallada: `docs/logs/progreso.json`

## Rama y SHAs integrados

| Ref | SHA |
|---|---|
| origin/main | `cf59a73` |
| origin/intentos-nico | `ec238df` |
| origin/feat/multimodal-tornado-predictor-wip | `3cd882b` |
| Commits de merge | `ecf305a` (Nico), `b48a44a` (modelo), `44e9172` (pins `==` + ajustes make check) |

Todo lo posterior a `44e9172` **no está commiteado**: `scripts/app/`, `tests/test_app_*.py`,
`tests/app_synthetic.py`, `docs/planificacion_merge.md`, `docs/logs/`, y cambios en
`.gitignore`, `Makefile` (target `sync`) y `pyproject.toml` (`extraPaths` + `scripts/app`).

## Estado de tareas

| Tarea | Estado |
|---|---|
| 1. Primera Sincronización | hecha |
| 2.1 atomic.py · 2.2 progress_log.py · 2.6 progreso.json | hechas |
| 3.1 planificacion_merge.md | hecha |
| 4.1 lake_layout.py · 4.2 contracts.py · 4.3 pruebas de contrato | hechas |
| 5.1 sync_branches.py · 5.2 `make sync` | hechas |
| 6. Checkpoint (make check OK, 163 pruebas) | hecho |
| 7.1 awsauth.py | hecha |
| 9.1 stub_model.py | hecha |
| 9.2 predictions.py | escrita; sus pruebas pasan en `make check` (falta marcarla en tasks.md) |
| 7.3 adapter.py (ERA5) | **interrumpida** — el archivo no existe |
| 7.6 generadores sintéticos ERA5/GOES | **interrumpida** — no se agregaron |
| 7.2, 7.4, 7.5, 8, 9.3, 9.4, 10–18 | pendientes |
| 19 push/PR · 20 terraform apply/subida | pendientes, **requieren tu confirmación** |

Las pruebas de propiedad opcionales (`*`) no se han ejecutado.

## Pendientes y decisiones abiertas

- **`make check` falla (1 error, código de Daniel)**: `tests/test_bedrock_encoder.py::CacheKeyTest.test_key_distinguishes_components`. Hypothesis encontró un texto con surrogate (`\ud800`) que `scripts/model/bedrock_encoder.cache_key` no puede codificar en UTF-8 (`UnicodeEncodeError`). Es un bug de la rama del modelo, no de `scripts/app/`; avisar a Daniel (p. ej. `encode('utf-8', 'surrogatepass')` o restringir la estrategia de la prueba). Las 189 pruebas restantes pasan.

- `stash@{0}`: tu cambio de diagramas en el `Makefile`, sin restaurar (compatible con el target `sync`).
- Config `physical` bloqueada: C08 no confirmado en S3; Nico ahora escribe `goes_<ymd>_CNN.nc` por banda.
- Credenciales del perfil `default` (cuenta hackathon) expiradas.
- `make sync` no acepta argumentos: retomar con `uv run python scripts/app/sync_branches.py --continue`.
- `sync_branches.py` no commitea la bitácora ni la tabla: commitear antes de la próxima sincronización (árbol sucio la aborta).

## Seguir el avance desde la CLI

```bash
cat docs/logs/AVANCE.md
grep -nE '^\s*- \[[ x~-]\]' .kiro/specs/merge-tornado-alert-app/tasks.md     # checkboxes del spec
.venv/bin/python -c "import json;[print(e['timestamp'],e['estado'],e['tarea']) for e in json.load(open('docs/logs/progreso.json'))]"
git log --oneline -5 && git status --short
```

## Cómo retomar

Orden sugerido: 9.2 (verificar) → 7.3 → 7.2 / 7.4 → 7.5 → 7.6 → 8 → 9.3 → 9.4 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18.
Abre `tasks.md` y usa "Run All Tasks" (o "Start task" en cada ítem).
