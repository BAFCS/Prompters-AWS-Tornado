# Modelos entrenados (XGBoost híbrido de Daniel, config `embeddings`)

Artefactos compatibles con `scripts/model/sm_job/inference.py` (`model_fn`): `model.json`,
`feature_columns.json`, `config.json` y `reducer.npz` (PCA de los embeddings Titan).

| Carpeta | Entrenado con | Uso |
|---|---|---|
| `hibrido/` | 35 días con evento (44 positivas) + 40 días sin evento | días distintos de 2019-05-30/31 |
| `hibrido_holdout_20190530/` | lo mismo **sin** 2019-05-30 ni 2019-05-31 | predicción fuera de muestra del caso demo |

| `v2/hibrido/` | v2: 35 días con evento + 70 sin evento, GOES solo del bucket | sitio v2 (`demo_site_v2/`) |
| `v2/hibrido_holdout_20190530/` | v2 sin 2019-05-30 ni 2019-05-31 | fuera de muestra del caso demo (v2) |

Métricas LOEO y detalle: `.agents/tasks/hibrido/real_report.md` (v1), `.agents/tasks/hibrido/v2_report.md`
(v2) y `train_summary.json`.
Índice relativo (PU), no probabilidad calibrada.

Sitio ya generado en `demo_site/` (5 días): `python -m http.server 8000 -d demo_site` → http://localhost:8000
Para regenerar: `scripts/app/infer_grid.py --day D --model-dir models/hibrido_holdout_20190530 --yes`
y `scripts/app/prototype.py --start D --predictions-dir data/app/predictions`.
