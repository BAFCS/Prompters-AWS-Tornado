# GOES-16/19 para días de evento — informe

Resultado: 38/38 días de evento (≥ 2017-12-01) en
`data/crops/south-central-austral/goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc`: 244 archivos horarios con 1431 barridos, 1,24 GB.
Todos tienen C08 y C13. Además se sincronizaron 10 días negativos desde el bucket (2025-11-01..10, 24 h cada uno, C08 y C13, 1,32 GB).
El marcador `goes_20190530.done` se escribió apenas estuvo listo el día demo.

- Tiempo total: unos 91 min de reloj, con 6 días en paralelo y 4 lecturas S3 por día. Cada día de 5 horas toma de 6 a 8 min.
- Recortes crudos `goes/AAAAMMDD/`: se borraron después de que `process_goes` dejó todas sus horas en `goes_latlon/`. El directorio `goes/` quedó vacío.
- Orquestador: `.agents/tasks/hibrido/run_goes_events.py [workers] [días…]`. Los logs por día están en `logs/dl_*.log` y el estado en `logs/status_pass1.jsonl` y `logs/status.jsonl`. Las ventanas por día están en `logs/windows.json`.
- Ventana de horas por día: desde min(horas de evento) − 3 hasta max + 1, recortada a 0..23. Para "22-23:25" se toman las horas 22 y 23; para "16:20.00", la hora 16.
- Días sin hora conocida (2020-06-15, 2023-02-04, 2023-02-06): se usó 12–23 UTC por defecto. La fila con NaN en 2018-09-30 se ignoró porque ese día ya tiene 16:51.

## Estado por día

| día | ventana pedida | horas obtenidas (n) | bandas | sat | archivos | barridos/h | horas ausentes en NOAA |
|---|---|---|---|---|---|---|---|
| 2018-03-22 | 13–17 | 13–17 (5) | C08/C13 | G16 | 5 | 4 | — |
| 2018-03-23 | 3–7 | 3–7 (5) | C08/C13 | G16 | 5 | 4 | — |
| 2018-09-30 | 13–17 | 13–17 (5) | C08/C13 | G16 | 5 | 4 | — |
| 2019-05-30 | 15–23 | 18–23 (6) | C08/C13 | G16 | 6 | 3–6 | 15,16,17 (y 13–14) |
| 2019-05-31 | 15–20 | 15–20 (6) | C08/C13 | G16 | 6 | 6 | — |
| 2019-06-13 | 17–22 | 17–22 (6) | C08/C13 | G16 | 6 | 6 | — |
| 2019-10-28 | 18–22 | 18–22 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2020-04-25 | 4–8 | 4–8 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2020-05-03 | 17–21 | 17–21 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2020-06-15 | 12–23 | 12–23 (12) | C08/C13 | G16 | 12 | 6 | — |
| 2020-06-19 | 13–17 | 13–17 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2020-06-24 | 15–19 | 15–19 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2020-06-29 | 12–20 | 12–20 (9) | C08/C13 | G16 | 9 | 6 | — |
| 2020-07-04 | 17–22 | 17–22 (6) | C08/C13 | G16 | 6 | 6 | — |
| 2020-08-24 | 18–22 | 18–22 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2021-04-08 | 14–19 | 14–19 (6) | C08/C13 | G16 | 6 | 6 | — |
| 2021-05-03 | 19–23 | 19–23 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2021-06-09 | 7–18 | 7–18 (12) | C08/C13 | G16 | 12 | 6 | — |
| 2021-08-19 | 4–8 | 4–8 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2022-03-08 | 13–17 | 13–17 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2022-07-01 | 15–19 | 15–19 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2022-08-15 | 14–18 | 14–18 (5) | C08/C13 | G16 | 5 | 6 | — |
| 2023-02-04 | 12–23 | 12–23 (12) | C08/C13 | G16 | 12 | 6 | — |
| 2023-02-06 | 12–23 | 12–23 (12) | C08/C13 | G16 | 12 | 6 | — |
| 2023-06-02 | 18–22 | 18–22 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-06-07 | 10–14 | 10–14 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-06-25 | 14–18 | 14–18 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-06-26 | 13–20 | 13–20 (8) | C08/C13 | G16 | 8 | 6 | — (2.º intento) |
| 2023-06-27 | 16–20 | 16–20 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-07-14 | 17–21 | 17–21 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-09-06 | 12–16 | 12–16 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2023-09-11 | 16–20 | 16 (1) | C08/C13 | G16 | 1 | 6 | 17,18,19,20 |
| 2024-05-25 | 15–19 | 15–19 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2024-06-18 | 6–10 | 6–10 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2024-06-20 | 0–22 | 0–22 (23) | C08/C13 | G16 | 23 | 6 | — (2.º intento) |
| 2024-06-21 | 17–21 | 17–21 (5) | C08/C13 | G16 | 5 | 6 | — (2.º intento) |
| 2025-05-17 | 14–18 | 14–18 (5) | C08/C13 | G19 | 5 | 6 | — (2.º intento) |
| 2025-05-25 | 16–20 | 16–20 (5) | C08/C13 | G19 | 5 | 6 | — (2.º intento) |

Hay 4 barridos por hora antes de 2019-04-02 (modo 3 del ABI) y 6 desde esa fecha (modo 6).

## Fallas y causas

1. Hay huecos reales en NOAA, donde no existen carpetas `ABI-L2-MCMIPF` en `noaa-goes16`:
   - 2019-05-30, 13–17 UTC: la hora 18 trae solo 3 barridos. El evento de 19:00 pierde las horas t-3 (16) y la anterior a t-2. Los eventos de 19:20 a 23 tienen todos sus rezagos desde 18 UTC.
   - 2023-09-11, 17–20 UTC: el evento de 19:45 queda sin imagen, salvo la hora 16 (t-3). `ABI-L2-CMIPF` tiene el mismo hueco. Solo `ABI-L1b-RadF` (radiancias L1b) tiene esas horas, y `download_goes.py` no las soporta. No se rellenó.
2. Formato HDF5 distinto desde unos meses de 2023 en adelante: los archivos MCMIPF traen el filtro `shuffle` (más gzip). `download_goes.py` lo rechazaba con `assert ... not d.shuffle` ("filtros inesperados en /CMI_C08"), y fallaron los 14 días desde 2023-06-02 en adelante. Se corrigió con un cambio mínimo en `scripts/pipeline/download_goes.py`:
   - Si `d.shuffle`, cada bloque se reordena después de `zlib.decompress` (inverso del byte-shuffle).
   - El assert ahora exige gzip y chunks, y sin fletcher32.
   - Verificación: un bloque de 226×226 decodificado así es idéntico a la lectura directa de h5py (`np.array_equal == True`). `ruff` pasa.

   Con eso, el segundo intento completó los 14 días. Los logs fallidos quedaron en `logs/dl_*.fail1.txt`. Este cambio no está commiteado, según la instrucción.

## Formato vs lectores de Daniel

No hay incompatibilidad, así que no hizo falta `scripts/app/goes_fix_names.py`.

- Variables: `process_goes.py` escribe `C08` y `C13` (no `CMI_C08`), que son los nombres que piden `extract_goes_features.load_goes_file` y `rgb.py` / `compose_rgb.py`.
- Dimensiones `(time, latitude, longitude)` = (6, 1301, 501). La latitud va de −30 a −56 y la longitud de −76 a −66, con paso de 0,02°.
- Codificación `int16` con `scale_factor`, `add_offset` y `_FillValue=-1` en los atributos, al abrir con `mask_and_scale=False`. Ejemplo de 2019-05-30 20 UTC:
  - C08: escala 0,042250, desfase 138,05.
  - C13: escala 0,061453, desfase 89,62.
  - zlib nivel 4 con shuffle, chunks (1, 163, 126).
- Prueba con el lector real (`extract_goes_features.GoesReader`, bandas C08 y C13, `require_all`). Las tres horas dan 12 barridos en (t−1, t] y no falta ninguna banda:

  | hora | rango BT C13 |
  |---|---|
  | 2019-05-30 21 UTC | 219,1–289,1 K |
  | 2025-05-17 17 UTC (G19) | 221,4–311,9 K |
  | 2025-11-05 18:30 UTC (negativo del bucket) | 218,6–320,8 K |

- Detalle menor en los negativos del bucket (`sync_from_bucket.py`): re-codifica con escala 0,01 y desfase 250. Con eso, el entero −1 (relleno) equivale a 249,99 K, y los píxeles que caen justo en ese valor se leen como NaN. Es un bin de 0,01 K, no bloquea a nadie y no se tocó. Si se quiere corregir, convendría usar otro desfase, por ejemplo 200. El escalado también difiere del de los positivos (escala nativa ABI), pero los lectores decodifican archivo por archivo, así que da igual.

## Otros días ya presentes

`goes_latlon/` ya tenía, antes de esta tarea, 20180502, 20180615, 20180721, 20180804, 20180809, 20180813, 20180830, 20180928, 20190513 y 20190602. No se tocaron.
