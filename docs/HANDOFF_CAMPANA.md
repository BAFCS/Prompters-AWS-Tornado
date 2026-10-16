# HANDOFF — campaña nocturna de modelado (continuar aquí)

Estado al cierre de esta sesión (contexto ~85%). Para retomar sin perder nada.

## PRESUPUESTO
- Límite de sesión: el usuario autorizó hasta ~2500 USD de agente Kiro; parar en 2500.
- Regla de traspaso: al retomar en nueva sesión, el límite nuevo = (lo que quede sin gastar al
  cerrar esta). Estimar el gastado y continuar con el remanente.

## CUENTAS AWS
- **A (datos, 822870558093)**: perfil `default`/`era5` en ~/.aws/credentials (TEMPORALES, caducan →
  si ExpiredToken, el usuario las renueva). Dueña del bucket de datos. **NO puede encender EC2**
  (deny explícito nuevo ws-dont-modify-policy). Solo lectura/escritura S3 de su bucket.
- **B (admin GPU, 905418466452)**: perfil `gpu` (AKIA, durable). Admin, SÍ lanza EC2 (256 vCPU CPU;
  GPU cuota 0 = no usable). Buckets propios: `mesocyclonic-model-905418466452` (destino),
  `sagemaker-aiwp-...`. **Aquí corre la campaña.**
- Infra B creada: rol/instance-profile `mesolab-ec2` (S3FullAccess+SSM), SG `sg-06612ad0ad64392be`,
  subnet `subnet-02a1f3734ba34cc0f`, AMI `ami-0cbf5991d1b4af4b6`.

## DATOS (listos)
- Capa curada ERA5+GOES: **846 días** en `s3://mesocyclonic-model-905418466452/curated/analysis_ready/<año>/curated_YYYYMMDD.parquet`
  (una fila por celda-hora; ERA5 superficie+850/500 + estadísticos 6 bandas GOES + dBT/dt C13 + flags).
- Scripts en `s3://mesocyclonic-test-data-...003/code/model/`: `match_era5_goes.py`,
  `train_campaign.py`, `dias_campana.json` (846 días). Fuente de verdad local: `scripts/model/`.

## EXPERIMENTOS (train_campaign.py)
Configs: baseline, windows, goes, lead1h (⭐ el clave: etiquetas +1h = anticipar 60 min), balance.
Validación: LOEO por día de evento + POD/FAR/CSI/PR-AUC con dispersión. Sin leakage.
Resultados a `s3://mesocyclonic-model-905418466452/experimentos/campania/<cfg>_lead<N>.json` y
`r<N>_out_<cfg>.txt` (stdout).

## BUGS RESUELTOS (en orden)
1. SSM no registra en esta AMI → NO depender de SSM; ejecutar vía user-data que sube resultados a S3.
2. Bucket B no es público → leer la curada CON credenciales (no --anon-src).
3. OOM en 16GB cargando 846 días → usar r7i.2xlarge (64GB) + submuestreo: días de evento completos
   (sample_frac=1.0), control al 0.12. Script ya lo hace.
4. positivos=0 → `Hour (UTC)` del catálogo viene "HH:MM:SS" (texto); parsear con split(":"). RESUELTO.
5. "sin folds válidos" con 55 positivos → event_id "fecha-N": usar rsplit("-",1)[0] para la fecha
   (no split, que daba el año). RESUELTO.
6. Aún "sin folds válidos" → inconsistencia de tipo en `df["date"]` (date vs str): en loeo_cv usar
   `df["date"].astype(str) == day_of_ev`. **ÚLTIMO FIX, en corrida 6 (i-059319ab47209330c).**

## HIPÓTESIS DEL BUG "sin folds válidos" (acotado, para arrancar directo)
RESUELTO: era `day_of_ev = ev.split("-")[0]` → daba el AÑO ("2024") en vez de la fecha; al filtrar
`date=="2024"` ningún día matcheaba → test vacío → fold inválido. **Fix aplicado**: usar
`ev_days = {e.rsplit("-",1)[0] ...}` y agrupar por fecha completa (train_campaign.py ya corregido y
subido a code/model/). Validado por lógica en local (carga 619k filas OK, etiqueta positivos OK).

## KPIs OBJETIVO (vara de éxito — imagen del equipo, Acto 3)
- ⭐ **POD ≥ 70%** sobre los tornados de 2026 NO vistos al entrenar (= nuestro holdout temporal). Base: 0/7.
- **FAR ≤ 50%** (base ~70%; base = días SHERBE≥1 sin tornado).
- **Alertas por tornado ≤ 2** (días que un experto revisa por acierto; base ~4).
- Nota: con ~37-55 positivos la vara es exigente; reportar honesto con IC. Si no se alcanza, plantear
  alternativas (no forzar).

## BLOQUEO ACTUAL (no es el modelo — es el user-data de la EC2)
El fix de folds YA está. El último obstáculo son errores de user-data en las EC2 entrenadoras:
- corrida 7: script buscado en /tmp en vez de /opt/code/model (ruta).
- corrida 8: `cd /opt/code/model: No such file or directory` → el bloque de setup (mkdir + aws s3 cp
  del código) NO se ejecutó antes del loop; probablemente el setup falló silencioso (sin set -e) o el
  `aws s3 cp s3://.../code/model/` no corrió. El loop arrancó sin el código descargado.
ARREGLO PARA LA PRÓXIMA: user-data con `set -e`, verificar que `/opt/code/model/train_campaign.py`
existe ANTES del loop (ej. `test -f ... || exit 1`), y subir el log de setup siempre. O más simple:
meter TODO (setup+corrida) en un script único que se baje primero y se ejecute, en vez de inline.
Alternativa robusta: usar SageMaker (rol AmazonSageMakerExecutionRole ya existe en cuenta B).

## HIPÓTESIS DEL BUG "sin folds válidos" (resuelto arriba; histórico)
`test["label"].sum()==0` se cumple siempre. Es decir: al tomar `test = df[df.date==día_evento]`, ese
subconjunto NO tiene el positivo. Causas probables a revisar EN ORDEN:
  1. **Índice desalineado**: `add_lags` hace `df.sort_values(...)` y luego `label_events` usa
     `df.loc[idx]=1` con `idxmin`. Verificar que el índice sea consistente (hacer
     `df.reset_index(drop=True)` ANTES de label_events, o marcar label por máscara booleana en vez de
     .loc[idx]).
  2. **day_of_ev vs df.date**: confirmar con un print que `df["date"].astype(str).unique()` contiene
     exactamente los strings que produce `ev.rsplit("-",1)[0]` (formato YYYY-MM-DD en ambos).
  3. Marcar el positivo ANTES de add_lags (reordenar no debe perder la etiqueta).
Arreglo sugerido rápido: en label_events, en vez de `df.loc[idx,"label"]=1`, usar una columna key
`(date,hour,lat,lon)` y asignar por merge; o `df=df.reset_index(drop=True)` al inicio de main y no
reordenar hasta después de etiquetar. Probar con --config baseline (rápido) antes de los 5.

## SIGUIENTE PASO AL RETOMAR1. Leer resultados de la corrida 6: `aws s3 ls .../experimentos/campania/` (perfil gpu) y los
   `*_lead*.json`. Si por fin hay folds válidos → comparar CSI de baseline/windows/goes/lead1h/balance.
2. Si lead1h da CSI razonable con dispersión declarada → es la prueba de que se puede ANTICIPAR 60min
   (la idea de juntar desplazamiento + predicción futura). Reportar honesto (IC amplios, ~37-55 pos).
3. Si aún "sin folds": depurar loeo_cv con un día concreto (imprimir ev_ids y sus conteos). El dataset
   y las etiquetas YA están bien (55 positivos, 48 días evento); es solo el agrupamiento de folds.
4. Terminar entrenadoras EC2 al acabar (perfil gpu): buscar tag mesotrain* y terminate.
5. Commitear a intentos-nico: scripts/model/train_campaign.py, match_era5_goes.py,
   docs/CAMPANA_NOCTURNA.md, docs/PROPUESTA_ENTRENAMIENTO.md (varios aún sin commit).

## INSTANCIAS VIVAS AL CIERRE (terminar las que sobren, perfil gpu)
- i-059319ab47209330c (mesotrain6) — corriendo la campaña con el último fix. Dejar hasta que termine,
  leer resultados, luego terminar.
- Las anteriores (mesotrain2/3/4/5, mesolab) ya terminadas.
