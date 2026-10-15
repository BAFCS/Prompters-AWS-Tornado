# Inferencia del modelo híbrido sobre la grilla — 2019-05-30

## Comandos

```
uv run --no-sync python scripts/app/infer_grid.py --day 2019-05-30 --dry-run   # estimación
uv run --no-sync python scripts/app/infer_grid.py --day 2019-05-30 --yes       # 6678 ≤ 15000 imágenes
uv run --no-sync python scripts/app/prototype.py --start 2019-05-30 --end 2019-05-31 \
    --predictions-dir data/app/predictions
```

Log: `.agents/tasks/hibrido/logs/infer_20190530.log` (y `infer_20190530_run1.log`, primera corrida
cortada por el timeout de la herramienta; sus embeddings quedaron en la caché).

## Salidas

- `data/app/predictions/pred_20190530.csv` (6678 filas = 1113 celdas × 6 horas) + `.meta.json`
  con `modelo: "real"` y `config: "embeddings"`. El modelo viene de `data/model/hibrido`
  (artefactos de las 18:24).
- `data/app/site/days/2019-05-30.json`: `modelo: "real"`, insignia "Modelo XGBoost híbrido
  (ERA5 + imágenes GOES)", `step: 0.5`, horas 18–23 y los 5 eventos. El 2019-05-31 sigue con el
  sustituto (no tiene CSV real). El servidor en :8000 ya sirve el JSON nuevo (HTTP 200).

## Grilla y Bedrock

- Grilla ERA5 105×41 con stride 2 → 53×21 = 1113 puntos (0,5°). Ventana 15–23 UTC.
- 15, 16 y 17 UTC: sin archivos GOES (noaa-goes16 no los tiene); se omitieron y quedan en
  `horas_sin_goes`.
- 18 UTC: tiene archivo, pero ningún barrido cae en (t-60 min, t]. Las 1113 celdas no tienen
  RGB/embedding ni variables GOES en t (NaN que se pasan tal cual a XGBoost, igual que en SageMaker).
- Imágenes: 5565 (19–23 UTC). Titan `amazon.titan-embed-image-v1`, dim 1024, us-east-1, perfil
  `gpu`, receta ir_wv_v1, 224 px, 100 km (los mismos parámetros del entrenamiento). Hubo unas
  5562 llamadas a Bedrock en total (≈5560 en la corrida 1, 2 en la 2), 3 salieron de la caché
  del entrenamiento y no falló ninguna. Caché: `data/model/embeddings/cache/`.
- NaN (filas): GOES en t 1113, sin embedding 1113 (las de las 18 UTC) y 0 en ERA5 en t. 4452
  filas tienen algún NaN, por los rezagos GOES t-1..t-3 de las horas sin GOES.

## Máximo del índice por hora

| Hora UTC | Máx % | Celdas en 52,8 % |
|---|---|---|
| 18 | 52.8 | 85 |
| 19 | 52.8 | 83 |
| 20 | 52.8 | 74 |
| 21 | 52.8 | 72 |
| 22 | 52.8 | 105 |
| 23 | 52.8 | 98 |

## Alertas (umbral 20 %, supresión 6 h)

Las 4 zonas alertan a las 18 UTC con 52,8 %: Maule-Ñuble, Biobío, Araucanía y Los Ríos-Los Lagos.
Después no se repiten por la supresión.

## ¿Coincide con los 5 tornados?

Solo en parte, y el resultado no sirve como validación:

- El modelo actual está degenerado: `best_iteration: 0` y lo entrenaron con 55 celdas (5
  positivas). Solo da dos valores, 48,4 % (6161 celdas) y 52,8 % (517 celdas). Todas las celdas
  quedan sobre el umbral de 20 %, así que alertan todas las zonas.
- Hay señal espacial. Dentro de la caja de los eventos (lat −38,5…−36, lon −73…−71) el 63 % de las
  celdas queda en 52,8 %, contra el 6 % fuera de ella. Los 5 tornados (Quilelto 19:00, Yungay
  19:20, Coihueco 20:06, Los Ángeles 21:57 y Collipulli 22–23) tienen 52,8 % a ≤0,5° en su hora.
- No hay señal temporal. El valor alto aparece en todas las horas, incluso a las 18 UTC antes del
  primer evento, y también en zonas sin eventos (Los Lagos, −42,5°).
- Es una evaluación dentro de la muestra, porque 2019-05-30 es el día de entrenamiento.

Conclusión: el flujo de punta a punta funciona (ERA5 + GOES → Titan → `inference.predict_fn` →
mapa y alertas). Para que el mapa discrimine hay que reentrenar con más días y eventos.
`infer_grid.py` se puede volver a correr igual: la caché evita pagar de nuevo las imágenes.

## Decisiones tomadas sin confirmación (modo autónomo)

- Usé `--yes`, porque 6678 imágenes están dentro del tope de 15000.
- Las Variables_GOES y los PNG se calculan en `data/app/infer_work/` (no en `data/model/`), para
  no pisar los artefactos del entrenamiento. La caché de embeddings sí es la compartida.
- Las Variables_GOES se recalculan en cada corrida, por si la descarga GOES seguía en curso.
- Usé los artefactos que había (el informe de entrenamiento `train_report.md` todavía no
  existía). Si el modelo se reentrena, hay que volver a correr los dos comandos de arriba.
- El prototipo no pisa un CSV real con el sustituto, aunque se corra sin `--predictions-dir`.
