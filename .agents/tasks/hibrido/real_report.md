# Predicción REAL con el modelo híbrido de Daniel (ERA5 + GOES + Titan)

Resumen: entrené la configuración `embeddings` de Daniel con todos los días de evento disponibles
(35) y 40 días sin evento, con etiquetas reales del Catálogo. Además entrené un modelo de
retención que no vio el 30 ni el 31 de mayo de 2019 y lo usé para predecir esos dos días en
http://localhost:8000. Fuera de muestra, los 5 tornados del 30-05-2019 y los 2 del 31-05-2019
quedan dentro del 1 % de celdas con el valor más alto de su hora. Ojo con la sección «Límites»:
hay un posible sesgo de fuente GOES entre los días de evento y los negativos.

## Datos usados (snapshot del 15-10-2026, ~19:50 hora local)

- Listas exactas: `.agents/tasks/hibrido/era5_snapshot.txt` (156 archivos ERA5),
  `goes_snapshot.txt` (1441 archivos horarios GOES) y `neg_days.txt` (40 negativos).
- Días de evento (35, todos los del Catálogo con hora UTC desde 2017-12-01): 2018-03-22,
  2018-03-23, 2018-09-30, 2019-05-30, 2019-05-31, 2019-06-13, 2019-10-28, 2020-04-25, 2020-05-03,
  2020-06-19, 2020-06-24, 2020-06-29, 2020-07-04, 2020-08-24, 2021-04-08, 2021-05-03, 2021-06-09,
  2021-08-19, 2022-03-08, 2022-07-01, 2022-08-15, 2023-06-02, 2023-06-07, 2023-06-25, 2023-06-26,
  2023-06-27, 2023-07-14, 2023-09-06, 2023-09-11, 2024-05-25, 2024-06-18, 2024-06-20, 2024-06-21,
  2025-05-17, 2025-05-25. En el snapshot, los 35 tenían GOES local (descargas NOAA, de 1 a 23 horas
  alrededor del evento), así que no quedó ningún día de evento sin GOES. El código sí los admite:
  sus columnas GOES y de embedding irían en NaN.
- Días negativos (40): no tienen Evento ni el día anterior ni el siguiente, tienen ERA5 y GOES
  (C13 + C08) en el bucket y están repartidos entre may-sep de 2018, 2019 y 2020, oct de 2025 y
  abr-jul de 2026. Los bajé con `sync_from_bucket --only both`, más el ERA5 del día anterior para
  los rezagos (en 2018-2020 el bucket no tiene ese día anterior: sus rezagos t-1..t-3 de 00-02 UTC
  quedan en NaN).
- No usé los negativos locales 2025-11-01..10, porque esos días no estaban en `neg_days.txt`. Así,
  todos los negativos salen del bucket con el mismo método.
- Horas candidatas (1126): en los días de evento, las horas con barrido GOES más las horas de sus
  eventos (208). En los negativos, las horas con GOES a ±2 h de la hora de algún evento (918).
- Celdas: 44 positivas y 1320 no etiquetadas (ratio 30), 1364 filas en 75 días. Quedaron 3 eventos
  fuera: 20180930-54 y 20200624-69 no tienen hora UTC, y 20200824-74 cae fuera de la región.
- Columnas: baseline_era5 tiene 12. physical tiene 112 (84 ERA5 y 28 GOES, con rezagos y
  diferencias). embeddings tiene 1136 de entrada (112 + 1024 `emb_*`). XGBoost ve 120, porque los
  embeddings pasan por una PCA de 8 componentes ajustada en cada partición.
- Modelo de retención: excluye 2019-05-30 y 2019-05-31. Quedan 73 días, 1147 filas y 37
  positivas.

## Corrección de la degeneración

El modelo anterior paraba en `best_iteration 0`: era un solo árbol y daba solo 2 valores. Lo
arreglé en `train_hybrid.py`, que ahora usa un `fit_xgb` propio. Si la validación interna tiene
menos de 10 positivas, entrena 300 árboles fijos sin parada temprana (la rama de respaldo de
`loeo`, con los mismos hiperparámetros). En esta corrida, las 44 particiones y el modelo final usaron
300 árboles.

Valores distintos predichos:
- sobre la tabla de entrenamiento: 1145 (embeddings), 1164 (physical) y 1299 (baseline);
- sobre la grilla de inferencia: 1598 en el 30-05-2019 (6678 celdas) y 942 en el 31-05-2019. Antes
  eran 2.

## Métricas LOEO (fuera de partición, umbral 0,5; sin contar el caso de desarrollo de mayo 2019)

Modelo completo (`data/model/hibrido`, 37 eventos evaluados):

| config | POD | FAR | CSI | H/M/FA | PR-AUC OOF | CSI máx. (umbral) | eventos detectados* |
|---|---|---|---|---|---|---|---|
| baseline_era5 | 0.459 | 0.595 | 0.274 | 17/20/25 | 0.347 | 0.298 (0.58) | 24/44 |
| physical | 0.405 | 0.483 | 0.294 | 15/22/14 | 0.455 | 0.359 (0.27) | 22/44 |
| embeddings | 0.514 | 0.486 | 0.345 | 19/18/18 | 0.503 | 0.348 (0.22) | 26/44 |

\* «Eventos detectados» incluye los 7 eventos de desarrollo (mayo 2019). Ese caso dio CSI 1,0 en
physical y embeddings, y 0,64 en baseline.

Modelo de retención (`data/model/hibrido_holdout_20190530`): baseline CSI 0.221 (PR-AUC 0.295),
physical CSI 0.309 (0.487) y embeddings CSI 0.377 (0.512), con 20/37 eventos detectados.

Según la regla de Daniel (embeddings si su CSI supera al de physical), la configuración elegida es
`embeddings` en los dos modelos. El modelo completo no detectó (embeddings) 18 eventos: 20180322-52,
20180323-53, 20190613-63, 20191028-64, 20200503-66, 20200619-68, 20200624-70, 20200629-72,
20210503-76, 20210609-77, 20220308-81, 20220815-83, 20230607-87, 20230626-89, 20230906-93,
20230911-94, 20240525-95 y 20240620-97.

## Bedrock (Titan `amazon.titan-embed-image-v1`, 1024 dim, us-east-1, receta ir_wv_v1, 224 px, 100 km)

- Entrenamiento completo: 1361 imágenes. Fueron 1356 llamadas nuevas y 5 salieron de la caché.
- Entrenamiento de retención: 1138 imágenes. Fueron 1096 llamadas nuevas, 40 de la caché y 2
  fallidas (esas filas quedan en NaN).
- Inferencia: 13 711 llamadas nuevas. Por día: 2021-06-09 4409, 2020-06-29 3427, 2023-06-26 2938 y
  2019-05-31 2937. El 2019-05-30 salió entero de la caché (5565 imágenes de la corrida anterior).
- Total nuevo: unas 16 160 llamadas, alrededor de 0,97 USD. Queda dentro de los topes (≤20 000 en
  entrenamiento y ≤15 000 en inferencia).

## Sitio (http://localhost:8000, el mismo servidor estático en data/app/site)

| día | modelo | evaluación | grilla | horas UTC |
|---|---|---|---|---|
| 2019-05-30 (por defecto) | hibrido_holdout_20190530 | fuera de muestra | 0,5° (stride 2) | 18–23 (15–17 sin GOES) |
| 2019-05-31 | hibrido_holdout_20190530 | fuera de muestra | 0,75° (stride 3) | 15–21 |
| 2020-06-29 | hibrido | en muestra | 0,75° | 14–20 |
| 2021-06-09 | hibrido | en muestra | 0,75° | 10–18 |
| 2023-06-26 | hibrido | en muestra | 0,75° | 15–20 |

- Cada JSON del día trae `modelo: real` y `modelo_info` (config, model_dir y evaluación). La
  insignia dice «fuera de muestra (día retenido)» o «en muestra (día de entrenamiento)», y la
  cabecera muestra el modelo y su carpeta.
- Agregué la casilla «Escala relativa al máximo del día». Se activa sola si el máximo del día queda
  bajo 50 %. Con ella, la leyenda muestra los valores reales y el recuadro de cada celda sigue
  mostrando el % absoluto. En estos días el máximo llega al ~99 %, así que la casilla arranca
  desactivada.
- La CLI de `prototype.py` solo acepta un rango continuo de días, así que armé el sitio con sus
  funciones (`load_real`, `day_payload`, `build_site` y `alerts`) para estos 5 días; ver el comando
  abajo. Hay 27 alertas en `data/app/alerts.jsonl`.

## ¿Coincide con los tornados reales del 30-05-2019? (fuera de muestra)

Sí. Para cada evento comparé el valor máximo en ≤0,55° del punto con el resto de la grilla en la
hora del evento (redondeada):

| evento | hora | máx. cerca | máx. de la hora | mediana de la hora | % de celdas por encima |
|---|---|---|---|---|---|
| San Andrés (Collipulli) | 22 | 0.991 | 0.991 | 0.001 | 0,0 % |
| Los Ángeles | 22 | 0.991 | 0.991 | 0.001 | 0,1 % |
| San Miguel de Itata (Yungay) | 19 | 0.766 | 0.810 | 0.002 | 0,2 % |
| Quilelto (San Carlos) | 19 | 0.708 | 0.810 | 0.002 | 0,4 % |
| Coihueco | 20 | 0.550 | 0.770 | 0.002 | 0,7 % |

- En la caja de los eventos (−38,5…−36, −73…−71), la media es 0,53; fuera de ella, 0,067.
- Del día, el 6 % de las celdas pasa 0,5, y la mediana es 0,003.
- El 31-05-2019 (también fuera de muestra) va en la misma línea: Talcahuano-Concepción 18 UTC da
  0,995 (0,4 % de celdas por encima) y Chanco 19 UTC da 0,968 (0,6 %).
- Hay falsas alarmas: valores altos fuera de la zona de los eventos. La media por hora sube a las
  21 UTC (0,16), entre los eventos.

## Límites (léase antes de sacar conclusiones)

1. Posible sesgo de fuente GOES. Todas las imágenes de los días de evento vienen de descargas
   NOAA locales (`download_goes.py`). Las de los negativos vienen del bucket, reproyectadas por
   `sync_from_bucket.py`. Si las dos tuberías dejan diferencias sistemáticas (máscara, nivel de
   valores, vecino más cercano), el modelo podría reconocer de dónde viene la imagen y no el
   ambiente tornádico.
   - Señales a favor de la señal real: baseline_era5, sin GOES, ya logra PR-AUC 0,35 y CSI 0,27.
     Fuera de muestra, la señal se concentra justo donde hubo tornados, y no en todo el día con
     evento.
   - Aun así, la mejora de physical/embeddings sobre baseline puede estar inflada. Para comprobarlo
     hay que usar negativos con GOES de NOAA (p. ej. 2025-11-01..10, que vienen de NOAA, o descargar
     más) o reprocesar los días de evento desde el bucket.
2. Hay pocos datos: 44 positivas y 37 eventos evaluados. Las métricas tienen mucha varianza.
3. Los días de evento solo tienen GOES unas horas alrededor del evento. Las no etiquetadas de esos
   días quedan cerca de los eventos en el tiempo, y en los negativos limité las horas a ±2 h de
   las horas de evento.
4. Las probabilidades no están calibradas: el `scale_pos_weight` vale 30 y las muestras son PU.
   Los valores ~99 % son relativos.
5. Los días 2020-06-29, 2021-06-09 y 2023-06-26 del sitio son en muestra, así que no sirven como
   validación.
6. En 2019-05-30 las 15–17 UTC no tienen GOES y las 18 UTC no tienen barrido en (t−60, t]. Esas
   horas no tienen embeddings.
7. El aviso del agente de GOES llegó durante la corrida. Este snapshot ya tenía GOES para los 35
   días de evento con hora, así que no hizo falta reentrenar.

## Cambios de código (sin commit)

- `scripts/app/train_hybrid.py`:
  - agregué `--neg-days-file`, `--exclude-days` y `--out`;
  - los días de evento ya no exigen GOES (`--require-goes` deja el comportamiento anterior);
  - las horas candidatas son coherentes entre días de evento y negativos;
  - entrena con un mínimo de 300 árboles cuando hay pocas positivas en la validación;
  - el resumen trae valores distintos, el modelo final y la detección por evento.
- `scripts/app/infer_grid.py`: el meta trae `evaluacion` y `en_entrenamiento`, a partir del
  `train_summary.json` del modelo.
- `scripts/app/prototype.py`: `load_real` devuelve también el meta, el JSON del día trae
  `modelo_info`, `max` y la insignia de fuera o en muestra, y agregué la escala relativa al máximo
  del día.
- `tests/test_app_infer_grid.py`: actualizado a la nueva firma.
- `make check`:
  - pruebas: OK;
  - ruff check: OK;
  - lo que falla está fuera de `scripts/app` y de `tests/test_app_*`, y no lo toqué: `ruff format`
    en `scripts/model/{build_sample_fast,demo_app,demo_hibrido}.py` y
    `scripts/pipeline/download_goes.py`, y pyright en `scripts/model/demo_app.py` y
    `scripts/ingest/*`.

## Comandos para reproducir

```
B=mesocyclonic-test-data-20261015013924290100000003
# negativos (día y día anterior), 6 en paralelo
for d in $(cat .agents/tasks/hibrido/neg_days.txt); do
  .venv/bin/python scripts/model/sync_from_bucket.py --bucket $B --start $d --only both; done
# modelo completo y de retención (Bedrock con perfil gpu)
AWS_PROFILE=gpu .venv/bin/python scripts/app/train_hybrid.py --neg-days-file .agents/tasks/hibrido/neg_days.txt \
  --max-neg-days 40 --ratio 30 --workers 6 --out data/model/hibrido
AWS_PROFILE=gpu .venv/bin/python scripts/app/train_hybrid.py --neg-days-file .agents/tasks/hibrido/neg_days.txt \
  --max-neg-days 40 --ratio 30 --workers 6 --exclude-days 2019-05-30 2019-05-31 --out data/model/hibrido_holdout_20190530
# inferencia
.venv/bin/python scripts/app/infer_grid.py --day 2019-05-30 --model-dir data/model/hibrido_holdout_20190530 --stride 2 --yes
.venv/bin/python scripts/app/infer_grid.py --day 2019-05-31 --model-dir data/model/hibrido_holdout_20190530 --hours 15 21 --stride 3 --yes
.venv/bin/python scripts/app/infer_grid.py --day 2021-06-09 --hours 10 18 --stride 3 --yes --work data/app/infer_work/20210609
.venv/bin/python scripts/app/infer_grid.py --day 2020-06-29 --hours 14 20 --stride 3 --yes --work data/app/infer_work/20200629
.venv/bin/python scripts/app/infer_grid.py --day 2023-06-26 --hours 15 20 --stride 3 --yes --work data/app/infer_work/20230626
# sitio con los 5 días reales (días no contiguos: funciones de prototype.py)
.venv/bin/python -c "import sys,json;from pathlib import Path;sys.path[:0]=['scripts','scripts/app'];import prototype as pt
P=Path('data/app/predictions');D=['2019-05-30','2019-05-31','2020-06-29','2021-06-09','2023-06-26']
R=[pt.load_real(P,d) for d in D];pt.build_site([pt.day_payload(df,'real',m) for df,m in R],pt.read_catalog(Path('data/tornados_chile.xlsx')),Path('data/app/site'))
pt.atomic.write_text(Path('data/app/alerts.jsonl'),''.join(json.dumps(x,ensure_ascii=False)+'\n' for df,_ in R for x in pt.alerts(df,'real')))"
```
