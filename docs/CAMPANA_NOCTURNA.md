# Campaña nocturna de experimentos — predictor de tornados (plan maestro)

Plan para orquestar, durante la noche, una serie de experimentos de modelado por **ensayo y error
honesto**: cada corrida se valida sin fuga (leakage), sin forzar métricas, y los resultados deciden
qué se lanza después. Todas las salidas se guardan en nuestro S3. No se toca v2 ni los artefactos
del equipo.

## Recursos disponibles (verificados)
- **Cuenta A (nuestra, 822870558093)**: rol WSParticipantRole, us-east-1, 256 vCPU CPU, sin GPU.
- **Cuenta B (admin, 905418466452)**: usuario admin, 256 vCPU CPU, **GPU cuota 0** (no usable sin
  ticket), lee nuestro bucket. Perfil `gpu` en ~/.aws/credentials.
- **Datos**: bucket público `mesocyclonic-test-data-...003` — ERA5 846 días + GOES 6 bandas +
  capa curada `curated/analysis_ready/` (a generar). Catálogo: ~37-48 eventos, último may-2025.
- **GPU**: no disponible (cuota 0). **No es bloqueante**: el panel descartó deep learning con ~37
  eventos; todo el plan corre en CPU (XGBoost), igual que v2 (~14 min/corrida).

## Principios NO negociables (para no engañarnos)
1. **Anti-leakage**: validación LOEO por **bloque de evento completo** (no por fila) + holdout
   temporal hacia may-2025. Todo preprocesamiento (escalado, PCA, π, umbral) se ajusta SOLO en el
   train del fold.
2. **No forzar métricas**: se reporta POD/FAR/CSI/PR-AUC con **dispersión entre folds** (IC por
   bootstrap de evento). Una mejora solo cuenta si es estable entre folds, no en promedio con
   varianza alta. El caso de desarrollo (may-2019) se reporta aparte, nunca se promedia.
3. **Honestidad temporal**: ninguna feature usa información del futuro del evento; el día "post" del
   bloque no alimenta features. Para el objetivo "próximos 60 min", las etiquetas se desplazan y las
   features se cortan en t.
4. **Baseline físico es el número a batir**: cualquier añadido (GOES, embeddings, augmentation) se
   adopta solo si supera al baseline bajo la MISMA validación.

## Experimentos (cola priorizada; cada uno guarda a s3://.../experimentos/campania/<id>/)

| id | Qué prueba | Insumo | Decide |
|---|---|---|---|
| **E0** | Capa curada completa ERA5+GOES (match) | fuentes | habilita todo |
| **E1** | Baseline físico ERA5 + rezagos t-1..t-3, LOEO+holdout | curada | nº de referencia |
| **E2** | E1 + ventanas largas t-1..t-6 + agregados [t-6h,t] | curada | ¿la historia larga suma? |
| **E3** | E2 + features GOES (BT_min, dBT/dt, split-window) | curada | ¿GOES suma sobre físico? |
| **E4** | **v3 lead-1h**: etiquetas desplazadas +1h, features cortadas en t | curada | ¿se puede anticipar? |
| **E5** | E3/E4 + balance: scale_pos_weight, umbral óptimo, reweighting PU | — | ¿mejora FAR/CSI? |
| **E6** | E5 + SMOTE SOLO dentro del fold (experimento acotado) | — | ¿ayuda o es espejismo? |
| **E7** | Embeddings GOES congelados (si E3 satura) → PCA → XGBoost | curada+img | ¿bate físico? |

Orden de ejecución: E0 → (E1,E2,E3 en serie corta) → revisar → E4 (el de mayor valor: anticipación)
→ E5/E6 sobre el mejor → E7 solo si queda tiempo y los anteriores saturan.

## Bucle de orquestación (lo que hago durante la noche)
1. Lanzo E0 (capa curada completa) en CPU.
2. Al terminar, corro E1-E3 (XGBoost, minutos c/u), **leo CSI/PR-AUC y dispersión**.
3. Según resultado, lanzo E4 (lead-1h) — el que responde "¿anticipa?".
4. Reviso, descarto lo que no bate baseline, lanzo el siguiente de la cola.
5. Registro cada corrida (tiempos, costos, métricas, qué se decidió) en un log acumulado.
6. Repito hasta agotar la cola o hasta que no haya mejora estable.

## Qué NO se hace
- GPU / CNN / LSTM / Transformer (pocos positivos; panel y v2 lo confirman).
- Tocar v2 ni los artefactos del equipo.
- Split aleatorio por fila. Aumentar antes de partir. Promediar el caso de desarrollo.
- Presentar probabilidades no calibradas como certezas (lo de Puerto Varas: señal, no veredicto).

## Entregable al amanecer
Un informe con: ranking de configuraciones por CSI/PR-AUC con IC, si v3 lead-1h logra anticipación
real, qué features importan, y una recomendación honesta de qué modelo usar — o la conclusión
honesta de que con ~37 eventos el techo es X. Todo en nuestro S3 + commit a intentos-nico.
