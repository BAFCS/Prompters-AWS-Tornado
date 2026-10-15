# data_pipeline — datos de entrenamiento del modelo de tornados

Genera la **submuestra** (positivos + negativos) y descarga sus datos (ERA5 + GOES) **en paralelo**.
Separa el diseño del muestreo (barato, instantáneo) de la descarga (lo costoso), para iterar rápido.

## Qué produce

En `data/model/`:

- `positives.parquet` — filas positivas amplificadas: cada tornado aporta una vecindad
  `3×3` celdas ERA5 a lo largo de `±2 h`, para cubrir el **movimiento** del tornado.
- `negative_days.parquet` — días SIN evento, estratificados por estación, lejos de cualquier
  tornado (zona de exclusión). Proporción objetivo **10:1** (negativos:positivos).
- Índices ERA5 (`data/crops/<region>/era5_indices/`) y recortes GOES, cacheados por día.

Cada fila lleva `split` (train/test **temporal**: los eventos recientes van a test) para validar
que el modelo generaliza a eventos futuros.

## Uso

```bash
# 1. Ver el plan de muestreo (NO descarga nada)
uv run python data_pipeline/build_data.py --plan

# 2. Probar la descarga con UN solo día
uv run python data_pipeline/build_data.py --materialize --one-day 2019-05-30

# 3. Materializar toda la muestra, 6 descargas en paralelo
uv run python data_pipeline/build_data.py --materialize --workers 6
```

## Parámetros del muestreo

| Opción | Defecto | Qué controla |
|---|---|---|
| `--neighbor` | 3 | lado de la vecindad espacial (3 → 3×3 celdas alrededor del tornado) |
| `--hours` | 2 | ventana temporal ±horas (cubre el desplazamiento del tornado) |
| `--ratio` | 10 | negativos por positivo |
| `--negative-days` | 25 | días sin evento, estratificados por estación |
| `--workers` | 6 | descargas de días en paralelo |

## Variables que baja

- **ERA5** (entorno): `u, v, t, z` (presión) + `10u, 10v, 2t, 2d, sp, cape` (superficie) → índices
  `cizalladura, SRH, VGP, STP, SHERBS3, LCL, gradientes`.
- **GOES** (la tormenta): bandas **C13** (tope frío, clave para severos), **C08** (vapor de agua),
  **C02** (textura del yunque).

## Notas

- La descarga de ERA5/GOES es el cuello de botella (bloques globales, ~GB por día). Se paga una vez
  y queda cacheado. Las descargas usan contexto `spawn` (s3fs no tolera `fork`).
- El catálogo solo tiene positivos; los "negativos" son días **no reportados**, no confirmados sin
  tornado. Es *positive-unlabeled*: tenerlo presente al interpretar las métricas.
