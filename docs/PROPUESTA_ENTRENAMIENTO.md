# Propuesta de entrenamiento y capa curada analysis-ready

Documento de diseño. **No modifica los flujos de entrenamiento ni las fuentes existentes**
(`era5_store/`, `goes_store/` quedan intactos). Describe (1) una capa de datos nueva, curada y
emparejada ERA5↔GOES bajo un prefijo aparte del bucket, y (2) las mejoras de modelado que esa capa
habilita, con el veredicto de un panel de debate técnico.

> Objetivo: dejar los datos **listos para consumir por un modelo**, y preparado el siguiente escalón
> de mejoras por si los experimentos actuales no dan buena métrica — todo **sumando una fuente
> nueva, sin romper lo que ya existe**.

---

## 1. La realidad que condiciona todo (números reales)

- **Pocos positivos independientes**: ~48 fechas de evento en el lake, pero días consecutivos son la
  misma situación sinóptica → **~30-40 eventos independientes**; solo **~31** con ERA5 + 6 bandas
  GOES completas.
- **GOES desde 2018** (los eventos 2016-2017 solo tienen ERA5).
- **Catálogo termina may-2025**: no hay eventos posteriores → los días 2025-10→2026 son solo
  inferencia/OOT, nunca test etiquetado.
- **Grillas distintas**: ERA5 0.25°/horaria (24/día); GOES ~2 km/sub-horaria (~144 escenas/día).
- **PU learning**: el catálogo es solo-positivos; los bloques de control son "no etiquetados", NO
  negativos duros.

**Consecuencia honesta**: el techo de rendimiento lo fija la escasez de positivos, no el método.
Las métricas tendrán intervalos de confianza amplios. El valor está en un baseline físico auditable
bien validado + el valor incremental (medido) de GOES y de técnicas de desbalance.

---

## 2. La capa curada (fuente NUEVA, no destructiva)

Prefijo nuevo en el bucket: **`curated/analysis_ready/`** (no toca `era5_store/` ni `goes_store/`).

### Qué contiene
Una tabla por día (Parquet), **una fila por celda-hora** de la grilla ERA5, con:
- **Variables ERA5** (las físicas: viento, T, geopotencial por nivel, CAPE, 10u/10v/2t/2d/sp).
- **Estadísticos GOES por celda** (regrillando los ~144 píxeles de 2 km que caen en cada celda
  ERA5 de 0.25°, de fino a grueso): por banda, `BT_min`, media, p10/p50, y fracción fría
  (<235/220/210 K). Para la banda IR ventana (C13): además `dBT/dt` (tasa de enfriamiento del tope).
- **Flags de calidad**: `goes_valid_frac`, `n_scans_hora`, banda ausente→NaN (nunca 0),
  `terreno_alto` (Andes, 1000 hPa bajo tierra).
- **Clave**: `(date, hour_utc, lat, lon)`. Mismos días y grilla que ERA5 → casa 1-a-1.

### Reglas de limpieza/match
- **Regrillar siempre de fino a grueso** (GOES→celda ERA5); nunca interpolar ERA5 hacia GOES.
- **Alineación temporal**: colapsar las escenas sub-horarias a la hora ERA5 con `BT_min` (extremo,
  la convección es intermitente) + percentiles + `ΔBT_min` como tendencia.
- **Match "1-a-1"** = una celda ERA5 ↔ sus píxeles GOES contenidos, colapsados a UNA fila (no
  píxel-a-píxel).
- **NaN explícitos**, nunca imputar con 0; descartar C02 y escaneos NaN/imposibles.
- **Paralaje** (GOES-East ~1 celda a 53°S, sin corregir): guardar versión celda-estricta y versión
  vecindad 3×3 que lo absorbe.

Script: `scripts/model/match_era5_goes.py` (patrón pipeline: `--start/--end/--region/--force`,
idempotente, salta lo ya escrito). Lectura anónima de las fuentes públicas; escritura al prefijo
`curated/`.

---

## 3. Mejoras de modelado habilitadas (sobre el flujo actual)

El flujo actual (XGBoost + features físicas ERA5 + rezagos t-1..t-3 + LOEO + POD/FAR/CSI) es sólido
pero deja señal sin usar. Mejoras concretas, en orden de retorno/riesgo:

| Mejora | Qué cambia | Riesgo | Retorno |
|---|---|---|---|
| **GOES como features** | hoy el modelo NO usa GOES; añadir BT_min, dBT/dt, C08−C13 | bajo | alto |
| **Ventanas t-1..t-5/t-6** | los bloques de 4 días dan 48-72 h de historia (hoy solo t-3) | bajo | medio-alto |
| **Split reforzado** | LOEO por bloque completo + holdout temporal hacia may-2025 | bajo | alto (honestidad) |
| **Balance de clases** | `scale_pos_weight`, umbral óptimo (no 0.5), reweighting PU | bajo | medio |
| **SMOTE / augmentation** | solo DENTRO del fold de train; imágenes: rot/flip | medio ⚠️ | incierto |
| **Embeddings GOES congelados** | backbone de teledetección → PCA → XGBoost | medio | incierto |

### Veredicto del panel de debate (cerrado)
- **Modelo base**: XGBoost regularizado sobre features físicas (hemisferio sur: SRH/STP negativos),
  **NO deep learning desde cero** (sobreajusta con ~31 positivos).
- **Fusión ERA5+GOES**: **tardía primero** (GOES como escalares en el mismo XGBoost); embeddings
  **después y solo si** el baseline satura, siempre congelados y medidos cabeza a cabeza.
- **Validación**: LOEO dejando fuera el **bloque de 4 días completo** + holdout temporal reciente
  como chequeo de drift. Reportar **dispersión entre folds**, no solo la media.
- **DL se gana el derecho a existir solo si bate el baseline físico bajo validación honesta.**

### Balance y augmentation — la trampa a evitar
- **Siempre dentro del fold de entrenamiento, después de partir.** Aumentar antes de partir =
  leakage masivo con positivos correlacionados → métricas infladas que colapsan en operación.
- SMOTE interpola en espacio de features: puede crear puntos físicamente imposibles → usar con
  cuidado y medir contra el baseline con la MISMA validación.
- Augmentation de **imágenes** (rot/flip/desplazamiento) sí es físicamente válido y hasta ayuda con
  el paralaje — reservado para el camino de embeddings/CNN.

---

## 4. Pipeline end-to-end (reproducible, no destructivo)

```
fuentes crudas (era5_store/, goes_store/)   [INTACTAS]
        │  (lectura anónima)
        ▼
scripts/model/match_era5_goes.py            [NUEVO]
        │
        ▼
curated/analysis_ready/*.parquet            [FUENTE NUEVA en el bucket]
        │
        ▼
features + ventanas (t-1..t-5, agregados [t-6h,t], deltas)   dentro del fold
        │
        ▼
XGBoost regularizado + PU (scale_pos_weight/umbral/π por fold)
   (+ GOES tardío; + embeddings congelados como experimento)
        │
        ▼
validación: LOEO por bloque + holdout temporal 2024-2025  →  POD/FAR/CSI con IC por bootstrap
```

---

## 5. Fases (esfuerzo / riesgo / retorno)

- **Fase 0** — Auditoría de completitud por evento/banda/hora + folds.json determinista. Bajo/bajo/alto.
- **Fase 1** — Capa curada `curated/analysis_ready/` (match ERA5↔GOES). Medio/bajo/alto. **Es lo que
  falta hoy para que entrenar sea trivial.**
- **Fase 2** — Baseline tabular ERA5 reforzado (ventanas largas, regularización, split honesto). Bajo/bajo/alto. **El número a batir.**
- **Fase 3** — Añadir features GOES tabulares (fusión tardía). Medio/bajo/medio-alto.
- **Fase 4** — Balance/augmentation dentro del fold, medido. Bajo-medio/medio/incierto.
- **Fase 5** — Embeddings GOES congelados. Medio-alto/medio/incierto.
- **Fase 6 (futuro)** — CNN/SSL propios. Solo si se amplía sustancialmente el nº de positivos.

---

## 6. Honestidad

Con ~31 positivos y PU, **ningún enfoque garantiza skill robusto**; LOEO tendrá varianza alta. El
objetivo realista es un **detector útil con FAR controlado**, auditable, con GOES sumando señal
medible — no un CSI alto en absoluto. La capa curada deja los datos **listos para consumir** y el
plan deja preparado el siguiente escalón por si los experimentos actuales no rinden.
