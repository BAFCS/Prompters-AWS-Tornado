# Modelo híbrido v2 (2026-10-15): reentreno con GOES de una sola fuente

Resumen: reentrené las tres configuraciones (baseline_era5, physical, embeddings) con 35 días de
evento y 70 días negativos. Esta vez, el GOES de **todos** los días sale del bucket del equipo,
reproyectado con `sync_from_bucket.py`. En v1, el GOES de los días de evento venía de NOAA. La
corrida completa (modelo completo, retención e inferencia de 10 días) tardó ~33 min de reloj, y el
sitio v2 ya está publicado. En v2, la config embeddings queda por debajo de physical (CSI 0,298 vs
0,309), y el v1 había medido 0,345 vs 0,294. La comprobación de sesgo no encuentra un sesgo de
fuente medible ni en v1 ni en v2, así que la baja parece venir sobre todo de la varianza (otros
negativos, 37 eventos evaluados) y no de que se haya corregido una fuga.

## Datos (snapshot)

- Bucket `mesocyclonic-test-data-20261015013924290100000003` (lectura anónima). Tiene ERA5 de 846
  días (2016-2026) y GOES de 793 días; el inventario está en `data/model/v2/bucket_inventory.json`.
- Días de evento: los 35 días del Catálogo con hora UTC desde 2017-12, con 44 positivas.
  - 33 días tienen ERA5 + C08 + C13 en el bucket.
  - 2024-06-20 y 2025-05-17 no tienen C08. Entran sin GOES: sus Variables_GOES y embeddings
    quedan en NaN. El orquestador no baja GOES de un día si le falta C08 o C13.
  - Hay 3 eventos que no generan positivas: 20180930-54 y 20200624-69 no tienen hora, y
    20200824-74 cae fuera de la región.
- Días negativos: 70, listados en `.agents/tasks/hibrido/v2_neg_days.txt` y generados por
  `v2_pick_neg.py`.
  - Salen de 604 candidatos de 2018-2026 que tienen ERA5 + C08 + C13 y ningún Evento a ±1 día.
  - Las cuotas por mes dan 70 % a mayo-septiembre (49 días) y 3 días a cada uno de los otros meses.
  - 65 de los 70 tienen el ERA5 del día anterior, que se usa para los rezagos.
- GOES de NOAA (v1): moví las 38 carpetas de días de evento de `goes_latlon/` a
  `data/crops/_noaa_v1_backup/goes_latlon/`. No borré nada.
  - También borré de `data/model/south-central-austral/goes_features/` los 35 parquets de
    Variables_GOES calculados con NOAA. Quedaron respaldados, junto con las tablas y los embeddings
    de v1, en `data/model/_v1_intermediates_backup/`.
  - Los 50 días que siguen en `goes_latlon/` vienen todos del bucket.
- Horas candidatas: 2381 en total, 769 de días de evento y 1612 de días negativos. Celdas: 1364
  (44 positivas y 1320 no etiquetadas, ratio 30), en 105 días.
- Retención: excluye 2019-05-30 y 2019-05-31. Quedan 103 días, 1147 filas y 37 positivas.

## Optimización y tiempos (segundos de reloj; 10 núcleos, 24 GB)

| etapa | completo | retención |
|---|---|---|
| sync ERA5 + GOES (104 ERA5, 89 GOES; 8 procesos) | 409 | 0 (ya estaba) |
| Variables_GOES (8 procesos) | 71 | 0,1 |
| selección de celdas | 49 | 51 |
| compose RGB | 84 | 76 |
| Bedrock Titan (8 hilos) | 66 (1353 llamadas) | 61 (1102 llamadas) |
| build_table (8 procesos) | 80 | 61 |
| LOEO + modelo final, 3 configs | 52 | 41 |
| **total** | **~14 min** | **~5 min** |

La inferencia de los 10 días, en 2 tandas en paralelo de 8 hilos Bedrock cada una, tardó 585 s.

Cambios en `scripts/app/train_hybrid.py`:
- `--sync-goes` baja ERA5 (del día y del día anterior) y GOES, con un proceso
  `sync_from_bucket` por día y 8 a la vez. Se salta lo que ya está bajado.
- Bedrock corre en paralelo con `infer_grid.encode_parallel` (`--bedrock-workers 8`). Usa la misma
  caché y receta que `encode_bedrock`, y los reintentos con espera los hace `BedrockEncoder`.
- XGBoost usa `n_jobs=-1` (`tree_method=hist` ya venía).
- Los tiempos por etapa quedan en `train_summary.json` (`timings_s`).
- Agregué `--version` (la insignia del sitio) y `source_bias_check`.
- En los días de evento con GOES de día completo, las no etiquetadas se toman en las mismas horas
  del día que en los negativos. En esta corrida eso no cambió nada, porque los eventos cubren las
  24 horas.

## Métricas LOEO (fuera de partición, umbral 0,5, sin el caso de desarrollo de mayo de 2019; 37 eventos)

Modelo completo:

| config | v1 CSI | v2 POD | v2 FAR | v2 CSI | v2 H/M/FA | v1 PR-AUC | v2 PR-AUC | v2 CSI máx. (umbral) |
|---|---|---|---|---|---|---|---|---|
| baseline_era5 | 0.274 | 0.432 | 0.579 | 0.271 | 16/21/22 | 0.347 | 0.362 | 0.282 (0.24) |
| physical | 0.294 | 0.459 | 0.514 | **0.309** | 17/20/18 | 0.455 | **0.429** | 0.397 (0.28) |
| embeddings | 0.345 | 0.459 | 0.541 | 0.298 | 17/20/20 | 0.503 | 0.397 | 0.366 (0.18) |

Modelo de retención (sin 2019-05-30/31):

| config | v1 CSI | v2 CSI | v1 PR-AUC | v2 PR-AUC |
|---|---|---|---|---|
| baseline_era5 | 0.221 | 0.339 | 0.295 | 0.367 |
| physical | 0.309 | **0.385** | 0.487 | **0.512** |
| embeddings | 0.377 | 0.322 | 0.512 | 0.503 |

- Según la regla de Daniel (embeddings solo si su CSI supera al de physical), en v2 tocaría
  **physical**. Igual dejé embeddings como modelo publicado, por continuidad con la pestaña y con
  v1. La diferencia es de 1 acierto y 2 falsas alarmas sobre 37 eventos, que está dentro del ruido.
  Los artefactos de physical quedan en `data/model/v2/hibrido/physical/` por si se quiere cambiar.
- Caso de desarrollo (mayo de 2019, 7 eventos, modelo completo): CSI 0,78 en physical y
  embeddings, y 0,70 en baseline.
- Eventos detectados (embeddings, completo), contando los 7 de desarrollo: 24 de 44. Los no
  detectados son 20180323-53, 20190613-63, 20191028-64, 20200503-66, 20200619-68, 20200629-71/72,
  20210408-75, 20210503-76, 20210609-77, 20220308-81, 20220815-83, 20230607-87, 20230625-88,
  20230627-91, 20230906-93, 20230911-94, 20240525-95, 20240618-96 y 20250525-101.
- Degeneración: no hay. Los modelos finales dan 1166 valores distintos (embeddings), 1154
  (physical) y 1298 (baseline) sobre la tabla. En la grilla dan entre 1196 y 4692 valores por día.
- Importancias (embeddings, completo): vgp_01_lag2 0,155, vgp_01_lag3 0,081, stp_lm_lag2 0,063,
  cape_lag3 0,060, cape_lag1 0,041, gamma_03_d1 0,028 y stp_lm_lag3 0,027. Las domina ERA5 con
  rezago. Comprobé que no es una fuga por NaN: los rezagos tienen <1 % de NaN en todos los grupos.

## Comprobación de sesgo de fuente

Primero, el AUC (CV agrupada por día) de un XGBoost que, solo con filas no etiquetadas, distingue
«día de evento» de «día negativo». Si la fuente delatara la etiqueta, este AUC se acercaría a 1:

| entradas | v1 (NOAA en eventos) | v2 (todo del bucket) |
|---|---|---|
| 4 Variables_GOES (hora t) | 0.551 | 0.446 (retención 0.521) |
| embeddings Titan (PCA 8 por partición) | 0.524 | 0.538 |

Ninguna de las dos versiones muestra un sesgo de fuente detectable con estas variables. La mejora
de embeddings sobre physical en v1 (+0,05 CSI) no parece venir de la fuente. Con 37 eventos, esa
diferencia no es estable entre muestras de negativos.

Segundo, la media (y la desviación estándar) de las Variables_GOES en v2:

| variable | positivas (44) | no etiquetadas, días de evento (429) | días negativos (891) |
|---|---|---|---|
| goes_bt13_min (K) | 240,7 (16,5) | 256,6 (18,2) | 258,9 (20,0) |
| goes_wv_ir_max (K) | −10,8 (10,4) | −24,7 (13,4) | −26,6 (13,9) |
| NaN | 9,1 % | 1,2 % | 0,1 % |

Las no etiquetadas de los días de evento y las de los días negativos casi coinciden, con una
diferencia coherente con días algo más tormentosos. La brecha está entre positivas y no
etiquetadas, que es la señal buscada.

Hay un punto sospechoso: el 9 % de NaN GOES en las positivas viene de 2024-06-20 y 2025-05-17, que
no tienen C08. En las filas no etiquetadas, «GOES en NaN» pasa casi solo en esos dos días, y sus 3
eventos salieron detectados. El modelo puede estar usando «GOES en NaN» como pista. Para quitarla
hay que sacar esos días o bajarles C08, cuando esté en el bucket.

## Fuera de muestra: 2019-05-30 y 2019-05-31 (modelo de retención)

Para cada evento comparé el máximo a ≤0,55° del punto con el resto de la grilla de su hora:

| evento | hora UTC | máx. cerca | máx. hora | % de celdas por encima |
|---|---|---|---|---|
| San Andrés (Collipulli) | 22 | 0.982 | 0.982 | 0,0 % |
| Los Ángeles | 22 | 0.982 | 0.982 | 0,0 % |
| San Miguel de Itata | 19 | 0.994 | 0.997 | 0,1 % |
| Quilelto (San Carlos) | 19 | 0.992 | 0.997 | 0,3 % |
| Coihueco | 20 | 0.965 | 0.989 | 0,5 % |
| Talcahuano-Concepción (31) | 18 | 0.989 | 0.992 | 0,6 % |
| Chanco (31) | 19 | 0.996 | 0.996 | 0,0 % |

Los 7 eventos quedan en el 0,6 % superior de su hora, igual o mejor que en v1. En los días en
muestra, Cobquecura (2022-08-15, 0,02) y Puerto Saavedra (2023-06-07, 0,07) quedan bajos aun
estando en el entrenamiento.

## Bedrock (Titan `amazon.titan-embed-image-v1`, 1024 dim, us-east-1, ir_wv_v1, 224 px, 100 km)

- Entrenamiento: 1353 llamadas en el completo y 1102 en la retención (33 vinieron de la caché y 1
  falló).
- Inferencia: 20 239 llamadas.
- Total: **22 694 imágenes nuevas** (tope 25 000), unos 1,36 USD. Casi no hubo aciertos de caché,
  porque los PNG del bucket no son los de NOAA.

| día | modelo | evaluación | paso | horas UTC | llamadas |
|---|---|---|---|---|---|
| 2019-05-30 | holdout | fuera de muestra | 0,5° | 18–23 (las 18 sin barrido en t−60) | 5556 |
| 2019-05-31 | holdout | fuera de muestra | 0,75° | 16–20 | 2448 |
| 2021-06-09 | completo | en muestra | 0,75° | 14–17 | 1955 |
| 2020-06-29, 2023-06-26, 2023-07-14 | completo | en muestra | 0,75° | 18–20 | ~1470 c/u |
| 2018-03-22 | completo | en muestra | 0,75° | 15–17 | 1470 |
| 2022-08-15 | completo | en muestra | 0,75° | 16–18 | 1469 |
| 2025-05-25 | completo | en muestra | 0,75° | 17–19 | 1469 |
| 2023-06-07 | completo | en muestra | 0,75° | 12–14 | 1469 |

- 2019-05-31 va con paso 3 (no 2) para no pasar el tope.
- Las ventanas de horas cubren la mayoría de los eventos. Quedan fuera los eventos de 11 UTC
  (2021-06-09), 15 UTC (2020-06-29) y 16 UTC (2023-06-26).
- 2024-06-20, con 2 eventos, no se infiere porque no tiene C08.

## Dónde quedó todo

- Local:
  - `data/model/v2/hibrido/` y `data/model/v2/hibrido_holdout_20190530/` (con `physical/`,
    `baseline_era5/`, `results/` y `work/`);
  - predicciones en `data/app/predictions_v2/`;
  - sitio en `data/app/v2/site` y `demo_site_v2/`;
  - logs en `data/model/v2/logs/`.
- Git: `models/v2/{hibrido,hibrido_holdout_20190530}/` (los mismos 6 archivos que en v1) y
  `models/v2/v2_neg_days.txt`, `demo_site_v2/`.
- S3, en el bucket privado `mesocyclonic-model-905418466452` (SSE AES256, versionado):
  - `s3://mesocyclonic-model-905418466452/models/v2_2026-10-15/{hibrido,hibrido_holdout_20190530}/`,
    sin PNG ni canales;
  - en `models/v2_2026-10-15/`, también `train_summary.json`, `train_summary_holdout_20190530.json`,
    `v2_neg_days.txt`, `predictions/` y `v2_report.md`;
  - el sitio en `s3://mesocyclonic-model-905418466452/sites/v2_2026-10-15/`.
- v1 sigue intacto en `models/hibrido*`, `demo_site/`, `s3://…/models/v1_2026-10-15/` y
  `s3://…/sites/v1_2026-10-15/`.
- Público:
  - https://d1m48zea07nk1y.cloudfront.net/resultados/sitio/index.html (200) y `days/index.json`
    (200), con los 10 días v2. La insignia dice «… v2 · fuera de muestra» o «v2 · en muestra».
  - La pestaña https://d1m48zea07nk1y.cloudfront.net/mapa-modelo embebe esa URL, así que el mapa
    ya muestra v2.
  - El texto de métricas de la pestaña se actualizó en `adapter-bucket` (commit `9d82a1d`,
    `p_forecast.py`). Para que ese texto se vea, **hay que reiniciar la EC2 del visor**, y no la
    reinicié. Al reiniciarla cambia el DNS público, así que hay que actualizar el origen
    `viewer-ec2` de CloudFront (ver AVANCE).

## Reproducir

```
B=mesocyclonic-test-data-20261015013924290100000003
.venv/bin/python .agents/tasks/hibrido/v2_pick_neg.py 70
AWS_PROFILE=gpu .venv/bin/python scripts/app/train_hybrid.py --bucket $B --sync-goes \
  --neg-days-file .agents/tasks/hibrido/v2_neg_days.txt --max-neg-days 70 --ratio 30 --workers 8 \
  --bedrock-workers 8 --max-images 4000 --version v2 --out data/model/v2/hibrido
AWS_PROFILE=gpu .venv/bin/python scripts/app/train_hybrid.py --neg-days-file .agents/tasks/hibrido/v2_neg_days.txt \
  --max-neg-days 70 --ratio 30 --workers 8 --version v2 --exclude-days 2019-05-30 2019-05-31 \
  --out data/model/v2/hibrido_holdout_20190530
.venv/bin/python scripts/app/infer_grid.py --day 2019-05-30 --hours 18 23 --stride 2 \
  --model-dir data/model/v2/hibrido_holdout_20190530 --out data/app/predictions_v2 --work data/app/infer_work_v2/2019-05-30 --yes
#   (lo mismo para los demás días con --stride 3 y las horas de la tabla)
.venv/bin/python scripts/app/prototype.py --days 2019-05-30 2019-05-31 2021-06-09 2020-06-29 2023-06-26 \
  2018-03-22 2022-08-15 2023-07-14 2025-05-25 2023-06-07 --predictions-dir data/app/predictions_v2 --out data/app/v2
cp -R data/app/v2/site demo_site_v2 && make publish SITE_DIR=demo_site_v2
```
