# Plan de implementación: pitch para financiadores (presentación HTML)

Archivo único a editar en el lugar (sin worktree, sin commits):
`c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`

Todo texto visible en español de Chile. Se mantiene el estilo actual: colores (`:root` y temas), las fuentes `@font-face` embebidas (Figtree/Kalam, líneas 8–89), el motor SVG de diapositivas y pasos, el filtro "boil", la navegación por teclado/clic y el tema claro/oscuro (tecla T). Cambian el contenido y la estructura.

## 0. Hechos verificados (no volver a derivarlos)

| Hecho | Fuente en el repo / verificación |
|---|---|
| Objetivo: predecir qué tormentas del centro-sur de Chile desarrollan un mesociclón, con ERA5 + GOES | `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\AGENTS.md` ("Qué es este repositorio") |
| 30–31 de mayo de 2019: tornados en Los Ángeles y Talcahuano–Concepción (Biobío); daños estructurales, personas heridas y una víctima fatal | `docs\mesociclones_chile.md` §1 (línea ~28) |
| Catálogo "Tornados y Trombas en Chile": 102 eventos 1554–2025; 68 en 2015–2025; CC BY 4.0, doi:10.6084/m9.figshare.25119566 | `docs\mesociclones_chile.md` §1; `AGENTS.md` (Catálogo) |
| "La ausencia de un registro no permite asegurar que no ocurrió un evento" (eventos en el mar, zonas rurales, de noche) | `docs\mesociclones_chile.md` §1 |
| En 2019 Chile no tenía radares meteorológicos ni sistema de alerta de tornados (Vicencio et al., 2021); 7-nov-2025 la U. de Valparaíso adjudicó un radar móvil (no es una red nacional) | `docs\mesociclones_chile.md` §3.7 |
| Mesociclón: columna de aire en rotación de 2–10 km dentro de una tormenta convectiva profunda; con mesociclón persistente = supercélula; puede dar granizo grande, ráfagas destructivas y tornados; ≤ 30 % de las supercélulas producen tornado | `docs\mesociclones_chile.md` §2.1 |
| ERA5: reanálisis, estado de la atmósfera hora a hora desde 1940, 0,25°, en `s3://nsf-ncar-era5` (us-west-2). Es histórico: NO es una fuente en tiempo real | `AGENTS.md` (ERA5); `docs\mesociclones_chile.md` §1, §3.7, §4.1 |
| GOES (GOES-East): `noaa-goes16` (dic-2017–abr-2025) y `noaa-goes19` (desde abr-2025), us-east-1; 16 bandas; imagen cada 10 min | `AGENTS.md` (GOES); `docs\mesociclones_chile.md` §1 |
| El repo NO usa radar (no hay radar operacional disponible) | `docs\mesociclones_chile.md` §3.7 |
| Modelo: clasificador XGBoost sobre índices ERA5 + catálogo (positivos/no etiquetados), validación dejar-un-evento-afuera, métricas POD/FAR/CSI | `scripts\model\train_xgboost.py` (docstring); `infra\terraform\README.md` ("Entrenar el modelo XGBoost") |
| Servicios AWS REALMENTE desplegados (Terraform): Amazon S3 (bucket privado, cifrado, solo TLS: `data/` + `resultados/`), Amazon EC2 (visor Streamlit en Docker, `t3.large`), una 2.ª EC2 de entrenamiento (genera índices ERA5 y entrena; se apaga sola), Amazon CloudFront (única entrada pública HTTPS; sirve también `/resultados/*` desde S3 vía OAC), AWS IAM (roles de solo lectura / lectura-escritura), AWS Systems Manager Session Manager (acceso sin SSH), VPC/security group (solo tráfico desde CloudFront) | `infra\terraform\*.tf` (`s3.tf`, `ec2.tf`, `training.tf`, `cloudfront.tf`, `iam.tf`, `network.tf`); `infra\terraform\README.md` |
| Datos públicos leídos desde AWS Open Data: `nsf-ncar-era5`, `noaa-goes16/19` | `AGENTS.md`; `docs\mesociclones_chile.md` §7 |
| Región: Terraform despliega en us-east-1 (`variables.tf`: `region` y `training_region` = us-east-1; la cuenta de la hackathon deniega us-west-2). `AGENTS.md` dice "EC2 en us-west-2 a mano": hay contradicción, por eso NO se muestran regiones en las diapositivas | `infra\terraform\variables.tf`; `AGENTS.md` (Despliegue) |
| NO usados en el código fuente (solo "sugeridos" en `docs\mesociclones_chile.md` §7): SageMaker, AWS Batch, Lambda, API Gateway, SNS/SQS. `scripts\model\sm_job\` solo tiene `__pycache__`. La diapositiva actual "Arquitectura en AWS" y "¿Por qué AWS?" los presentan como usados: NO repetirlos. Existe además `infra\stack.py` (CDK: ECS Fargate + ALB) como alternativa no usada en la demo actual | `scripts\model\sm_job\`, `infra\README.md`, `infra\terraform\README.md` ("alternativa a la carpeta infra/") |
| Demo: https://d2vcu1id4v0sta.cloudfront.net/ es el visor Streamlit (`<title>Streamlit</title>`, `/_stcore/health` = 200). Páginas: Problema, Datos, Caso de estudio, Mapas, Starter kit, Referencias | `curl` del 15-oct-2026; `scripts\viewer\viewer.py` líneas 51–58 |
| Encabezados de la demo (curl -I, 15-oct-2026): SIN `X-Frame-Options` y SIN `Content-Security-Policy` → se puede embeber en iframe | `curl.exe -sI https://d2vcu1id4v0sta.cloudfront.net/` |
| Video de apertura: «Confirmado inédito tornado en Estación Central tras décadas sin registros en la Región Metropolitana», canal Meganoticias (YouTube, id `Hg_xaSDeL0E`) | oEmbed `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=Hg_xaSDeL0E&format=json` |
| Métricas del prototipo (`/resultados/metrics.json`): POD 0,3, FAR 0,0, CSI 0,3 sobre 10 eventos (corrida acotada). Por decisión del usuario NO hay diapositiva de métricas; no se citan en las diapositivas | CloudFront `/resultados/metrics.json` |
| Equipo: Bryan Cabezas · Renato Gutiérrez · Nicolás Delgado · Daniel Zanelli · Steve Jurado. Reto: R. Rondanelli (CR2), F. Förster y P. Badilla (IDIA, U. de Chile). Repo: github.com/BAFCS/Prompters-AWS-Tornado (coincide con `git remote`) | diapositiva de cierre actual (líneas ~676–691); `git remote -v` |

## 1. Decisiones del usuario (obligatorias)

1. Crédito visible del video en la diapositiva 1 (Meganoticias, YouTube).
2. SIN diapositiva de impacto/métricas: el impacto se muestra en la demo en vivo.
3. SIN hoja de ruta (roadmap).
4. SIN montos ni marcadores de montos: la diapositiva de financiamiento es solo cualitativa.
5. SÍ notas del orador por diapositiva, como comentarios HTML, en español.

## 2. Decisiones de diseño (las toma este plan)

- D1 · Se mantiene el motor SVG (`viewBox 0 0 1000 560`, funciones `slide/T/D/S/step`, `render()`). El video y el dashboard se insertan con `<foreignObject>` en la capa `calm` (sin filtro), porque así escalan con el `viewBox` igual que el resto. Nada que deba escanearse o leerse con nitidez (QR, iframes) va en `#world`: el filtro `#boil` lo deformaría y rompería el QR.
- D2 · Los iframes se cargan a un tamaño "lógico" grande y se escalan con CSS `transform: scale()` dentro del `foreignObject` (video 1920×1080 → escala 1000/1920; dashboard 1280×840 → escala 0,5 en un hueco de 640×420), para que Streamlit se vea en su diseño de escritorio y no en el apilado de tablet.
- D3 · Video: YouTube IFrame Player API cargada dinámicamente desde JS (`https://www.youtube.com/iframe_api`), con `playerVars {start:0, end:5, autoplay:1, mute:1, loop:1, playlist:"Hg_xaSDeL0E", controls:0, modestbranding:1, playsinline:1, rel:0, disablekb:1, iv_load_policy:3}` (+ `origin: location.origin` solo si el protocolo es http/https). Bucle garantizado por dos vías: `onStateChange` ENDED (0) → `seekTo(0,true)` + `playVideo()`, y un `setInterval` de 200 ms que hace `seekTo(0,true)` si `getCurrentTime() >= 5`. Respaldo: un fondo oscuro con el embudo dibujado está SIEMPRE debajo; el `foreignObject` del video se oculta si llega `onError`, si no hay estado PLAYING en 8 s, si `navigator.onLine === false` o si `prefers-reduced-motion: reduce` (en ese caso ni se carga la API). En `file://` YouTube suele fallar (error 153): la nota del orador indica servir con `python -m http.server`.
- D4 · Dashboard: iframe con carga diferida (se asigna `src` la primera vez que se muestra la diapositiva 4), `title`, `loading="lazy"`, `referrerpolicy="strict-origin-when-cross-origin"`, `allow="fullscreen"`. Como los encabezados permiten framing, el iframe es el camino principal; el respaldo (captura + botón "Abrir demo") se muestra si `navigator.onLine === false` o si el orador pulsa la tecla `D` (alternar iframe/captura) por si la red del lugar falla.
- D5 · QR generado offline con `segno==1.6.6` en un venv temporal FUERA del repo (no se agrega dependencia al proyecto; `AGENTS.md` prohíbe `pip` para dependencias del proyecto, y esto es una herramienta de un solo uso). Se incrusta como cadena SVG dentro del `<script>` y se inserta con `DOMParser` en la capa `calm`, negro sobre blanco en ambos temas. Verificación de decodificación con `opencv-python-headless==4.10.0.84` del mismo venv temporal.
- D6 · Navegación por hash `#N` (1-based) que abre la diapositiva N con todos sus pasos visibles: sirve al orador y permite capturas de verificación con Edge headless.
- D7 · Ganchos `onShow/onHide` por diapositiva en `render()` para pausar/reanudar el video y cargar el iframe; región `aria-live` que anuncia el título de cada diapositiva.
- D8 · Las diapositivas técnicas útiles para preguntas (HSLC, variables, planteamiento de ML) NO se pierden: pasan a un "Anexo" después del cierre. Las que contienen afirmaciones no respaldadas por el repo (SageMaker, Batch/Lambda) se eliminan.
- D9 · Notas del orador: un bloque de comentarios HTML `<!-- NOTAS · Diapositiva N · ... -->` justo antes del `<script>` principal, uno por diapositiva (incluido el anexo), en español.
- D10 · Adoptados de lo opcional: notas del orador (sí), una línea "¿por qué AWS?" dentro de la diapositiva del pipeline (sí). Rechazados: diapositiva de métricas, roadmap, montos (decisión del usuario).

## 3. Secuencia final de diapositivas

| N | Título | Origen |
|---|---|---|
| 1 | Apertura con video (problema y relevancia) | reemplaza "0 · title" y "1 · the problem" |
| 2 | ¿Qué es un mesociclón y qué datos tenemos? | reemplaza "2 · physics" y "4 · data sources" |
| 3 | Nuestra propuesta | nueva |
| 4 | La demo en vivo (dashboard 2/3 + QR 1/3) | nueva |
| 5 | Cómo funciona en AWS | reemplaza "7 · AWS architecture" y "why AWS" |
| 6 | Solicitamos financiamiento | nueva; reemplaza "impact / value" |
| 7 | Gracias (equipo, contacto, QR) | reemplaza "9 · closing" |
| 8–10 | Anexo · El régimen chileno: HSLC / Anexo · Variables derivadas / Anexo · Cómo plantear el aprendizaje | se mueven "3 · Chilean regime", "5 · features", "6 · ML framing" sin cambiar su contenido salvo el título |

Eliminadas del flujo: "El problema en una página" (condensada en 1), "¿Qué es un mesociclón?" (condensada en 2; los "cuatro ingredientes" quedan en `docs\mesociclones_chile.md` §2.2), "Los datos de entrada" (condensada en 2; las "trampas" técnicas quedan en `AGENTS.md`), "Arquitectura en AWS" y "¿Por qué AWS?" (afirmaban SageMaker/Batch/Lambda no usados; sustituidas por 5), "El valor que entregamos" (decisión 2), "Cómo lo hemos afrontado" (lo cubre la demo), "Próximos pasos" (decisión 3; la idea de nuevas fuentes pasa a "Perfeccionar" en 6).

---

# Implementation Plan

Comandos de verificación comunes (PowerShell; se usan en los ítems):

- V-JS (sintaxis de los `<script>` en línea):
  ```powershell
  $h = Get-Content -Raw -Encoding UTF8 "c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html"; $i = 0; foreach ($m in [regex]::Matches($h, '(?s)<script>(.*?)</script>')) { $f = "$env:TEMP\pitch_js_$i.js"; Set-Content -Path $f -Value $m.Groups[1].Value -Encoding UTF8; node --check $f; "script $i exit $LASTEXITCODE"; $i++ }
  ```
  Esperado: `exit 0` en cada script.
- V-SHOT N (captura de la diapositiva N con todos sus pasos):
  ```powershell
  & "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1600,900 --virtual-time-budget=10000 --screenshot="$env:TEMP\pitch_sN.png" "file:///c:/Users/zanel/OneDrive/Documentos/Prompters/Prompters-AWS-Tornado/docs/presentation/mesociclones_chile_presentation.html#N"
  ```
  Luego abrir `$env:TEMP\pitch_sN.png` con la herramienta de lectura de imágenes y revisar: sin texto encimado, nada recortado, textos en español, contraste legible. Repetir agregando `?theme=dark` no aplica: para tema oscuro, revisar a mano con la tecla T (anotar el resultado).
- Venv temporal (fuera del repo): `$env:TEMP\pitch-qr`.

- [ ] 1. Generar el QR offline y comprobar que decodifica exactamente la URL.
      Crear el venv temporal e instalar versiones fijas: `python -m venv "$env:TEMP\pitch-qr"; & "$env:TEMP\pitch-qr\Scripts\python.exe" -m pip install segno==1.6.6 opencv-python-headless==4.10.0.84`. Escribir un script temporal `$env:TEMP\pitch-qr\make_qr.py` que: `qr = segno.make("https://d2vcu1id4v0sta.cloudfront.net/", error="m", micro=False)`; guarde `qr.save("$TEMP/pitch-qr/qr.png", scale=10, border=4)`; guarde `qr.svg_inline(scale=1, border=4, dark="#000", light="#fff", nl=False, omitsize=False)` en `qr_inline.svg` (una sola línea, con `viewBox`); decodifique `qr.png` con `cv2.QRCodeDetector().detectAndDecode` y haga `assert data == "https://d2vcu1id4v0sta.cloudfront.net/"`.
      Files: `$env:TEMP\pitch-qr\make_qr.py`, `$env:TEMP\pitch-qr\qr.png`, `$env:TEMP\pitch-qr\qr_inline.svg` (temporales, fuera del repo).
      Verify: `& "$env:TEMP\pitch-qr\Scripts\python.exe" "$env:TEMP\pitch-qr\make_qr.py"` termina sin `AssertionError` e imprime la URL decodificada.

- [ ] 2. Extender el motor sin cambiar todavía el contenido.
      En el `<style>` final agregar: `.t-white{fill:#fff}`, `.t-smile{fill:#FF9900}` (texto sobre fondo oscuro fijo, contraste ≥ 4.5:1 sobre `#161E2D`), `.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}`, `.fo-box{width:100%;height:100%;overflow:hidden}`, `.fo-scale{transform-origin:0 0}`, `.fo-scale iframe{border:0;display:block}`, `.hero-video iframe{pointer-events:none}` y `svg a text{cursor:pointer;text-decoration:underline}`. En el `<body>` agregar `<div id="srSlide" class="sr-only" aria-live="polite"></div>` dentro de `#app`. En el script agregar (junto a los helpers de la sección "slide + step engine"):
      - `const XHTML = "http://www.w3.org/1999/xhtml"; const DEMO_URL = "https://d2vcu1id4v0sta.cloudfront.net/";`
      - `FO(x, y, w, h, innerW, innerH)`: crea `<foreignObject>` en `cur.calm`, con `div.fo-box` > `div.fo-scale` de `innerW×innerH` px y `transform: scale(w/innerW)`; lo registra en `cur.items` con el paso actual (`kind:"fade"`); devuelve `{fo, host}`.
      - `const QR_SVG = '<contenido de qr_inline.svg del ítem 1>';` y `qrBlock(x, y, size)`: `DOMParser` → `documentElement`, fija `x,y,width,height`, `shape-rendering="crispEdges"`, `role="img"`, `aria-label="Código QR: abre la demo en https://d2vcu1id4v0sta.cloudfront.net/"`; lo envuelve en un `<a href=DEMO_URL target="_blank" rel="noopener">` dentro de `cur.calm`; un `rect` blanco detrás con borde `roughRect` `s-muted` (el borde también en calm). Nunca en `#world`.
      - `link(x, y, text, href, opts)`: `<a>` SVG con `href`, `target="_blank"`, `rel="noopener"`, `aria-label`, y un `<text>` dentro (en calm, sin boil); se registra en `cur.items`.
      - En `slide()` dejar `onShow`/`onHide` como propiedades opcionales; en `render()` guardar `lastSi` y, cuando cambie `si`, llamar `slides[lastSi].onHide?.()` y `slides[si].onShow?.()` (también en el primer render); actualizar `#srSlide` con `"Diapositiva N de M: " + (title || cur.alt)` (agregar `alt` opcional a cada diapositiva sin título).
      - Navegación por hash: al iniciar y en `hashchange`, si `location.hash` es `#N` válido, `si = N-1; shown = slides[si].steps-1; render()`.
      - Agregar tecla `D` al `keydown` (alternar iframe/captura de la demo, se conecta en el ítem 6) y actualizar el `toast` de `?` con "D: demo/captura".
      Nota: la regla CSS `svg#stage *` no aplica (el SVG se llama `#scene`); no depender de ella. El clic en el escenario llama `next()` salvo en `<a>`; los iframes interactivos no propagan clics, así que no avanzan.
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS sin errores; V-SHOT 1 y V-SHOT 10 muestran las diapositivas actuales igual que antes (el hash funciona y nada cambió visualmente).

- [ ] 3. Diapositiva 1 · Apertura con video (reemplaza los bloques "0 · title" y "1 · the problem").
      `slide("")` con `alt = "Apertura: Chile también tiene tornados"`. Capas (todas en calm, en este orden): (a) `rect` 0,0,1000,560 `fill="#161E2D"` y el embudo dibujado del título actual (path `M860 380 Q910 385 …` y nube) en blanco/`#FF9900` como póster de respaldo; (b) `FO(0, -1, 1000, 563, 1920, 1080)` con clase `hero-video`, que contiene `<div id="heroVideo">` y el atributo `aria-hidden="true"` en el `foreignObject` (es decorativo; el contenido se describe en texto); (c) velo `rect` 0,0,1000,560 `fill="#161E2D" opacity="0.62"` para contraste. Logo: `image` con `LOGO.aws_white` en (900,16,76) (no `awsMark`, que cambia con el tema).
      Texto (blanco, centrado): paso 0: `T(500,90,"Predicción de tormentas mesociclónicas en Chile · Equipo Prompters",{size:14,cls:"t-white"})`; `T(500,200,"Chile también tiene tornados",{size:46,cls:"t-white"})`; `T(500,255,"y hoy casi nadie los ve venir",{size:30,cls:"t-smile"})`. Paso 1 (tamaño 17, `t-white`, `lh 1.5`, y 320–420): "30 y 31 de mayo de 2019: tornados en Los Ángeles y Talcahuano–Concepción (Biobío)", "daños estructurales, personas heridas y una víctima fatal", "102 tornados y trombas documentados en Chile, y muchos sin registro", "En 2019 Chile no tenía radares meteorológicos ni un sistema de alerta de tornados". Paso 0, pie (size 11, `t-white`, opacidad 0.85, y=540): "Video: Meganoticias, «Confirmado inédito tornado en Estación Central tras décadas sin registros en la Región Metropolitana» · YouTube". El `iframe` que cree la API lleva `title="Video de fondo sin sonido: noticia de Meganoticias sobre un tornado en Estación Central"` y `tabindex="-1"`.
      JS del video (según D3): función `initHeroVideo()` llamada desde `onShow` la primera vez; si `reduce` o `!navigator.onLine` → ocultar el FO y salir. Si no, definir `window.onYouTubeIframeAPIReady`, inyectar el `<script src="https://www.youtube.com/iframe_api">`, crear `new YT.Player("heroVideo",{width:1920,height:1080,videoId:"Hg_xaSDeL0E",playerVars:{…D3…},events:{onReady, onStateChange, onError}})`; `onReady`: `mute()`, `playVideo()`; bucle con ENDED + `setInterval` 200 ms (`>= 5` → `seekTo(0,true)`); watchdog de 8 s sin PLAYING → ocultar FO; `onError` → ocultar FO. `onHide` → `pauseVideo()`; `onShow` (ya creado) → `playVideo()`.
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 1 (en `file://` y headless el video probablemente no carga: debe verse el póster oscuro con el texto blanco legible y el crédito). Prueba manual adicional servida por http: `python -m http.server 8000 --directory "c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation"` (en segundo plano), abrir `http://localhost:8000/mesociclones_chile_presentation.html` en Edge, confirmar que el video corre sin sonido y vuelve a 0 s cada 5 s; detener el servidor después. Si no se puede observar el video, dejarlo anotado como "no verificado en navegador".

- [ ] 4. Diapositiva 2 · Contexto del problema (reemplaza "2 · physics" y "4 · data sources").
      `slide("¿Qué es un mesociclón y qué datos tenemos?")`. Izquierda (x 60–470): reutilizar el dibujo actual de nube + corriente ascendente rotatoria (los `closedCircle` y curvas `s-blue` del bloque "2 · physics"), centrado en (260,300), con etiqueta "aire que sube girando" (size 13, `t-blue`) y un `<title>`/`aria-label` en el grupo: "Diagrama: tormenta con una corriente de aire ascendente que gira". Texto paso 0 (x=60, anchor start, size 18, y 120): "Un mesociclón es una columna de aire que gira, de 2 a 10 km,", "dentro de una tormenta fuerte. Si persiste, la tormenta se llama supercélula." Paso 1 (size 15, `t-muted`, y 470): "Puede traer granizo grande, ráfagas destructivas y tornados.", "No todas lo hacen: cerca de 3 de cada 10 supercélulas producen un tornado."
      Derecha (x 520–950), paso 2: encabezado "Los datos que existen" (size 20, `t-red`, boil) y tres tarjetas `roughRect` 420×70 en y = 170, 260, 350: "Satélite GOES · ve las nubes desde arriba cada 10 minutos" (`s-gold`), "Reanálisis ERA5 · el estado de la atmósfera, hora a hora desde 1940" (`s-blue`), "Catálogo de eventos · 102 tornados y trombas (1554–2025)" (`s-red`). Paso 3 (size 14, `t-muted`, y 470, x 735 centrado): "Radar: Chile no tenía red de radares en 2019; el primero (móvil) se adjudicó en 2025", "Todos estos datos son abiertos y ya están en la nube de AWS".
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 2 sin solapes entre el diagrama, el texto y las tarjetas.

- [ ] 5. Diapositiva 3 · Nuestra propuesta (nueva).
      `slide("Nuestra propuesta")`. Paso 0 (size 20, y 120, centrado): "Anticipar qué tormentas pueden empezar a girar", (size 16, `t-muted`): "y mostrarlo de forma simple, abierta y accesible desde cualquier teléfono". Tres bloques `roughRect` 260×170 en x = 60, 370, 680, y = 175, unidos con `arrowPath`, uno por paso (1, 2, 3):
      1) "El predictor" (`s-red`): "aprende de los tornados documentados en Chile", "señala días y zonas con condiciones favorables para un mesociclón".
      2) "El visor" (`s-blue`): "mapas, imágenes satelitales y casos reales", "en el navegador, sin instalar nada".
      3) "El apoyo" (`s-violet`): "información para meteorólogos, equipos de emergencia y comunidades", "la base para futuras alertas tempranas".
      Paso 4 (size 14, `t-muted`, y 470): "Hoy trabaja con datos históricos; para alertas en tiempo real se necesitan validación y datos al instante" (honestidad: ERA5 no es tiempo real, `docs\mesociclones_chile.md` §1 y §3.7). Sin jerga de ML (no decir XGBoost, PU learning, features).
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 3 legible, flechas entre bloques.

- [ ] 6. Diapositiva 4 · La demo en vivo (dashboard ~2/3 + QR ~1/3). Depende de los ítems 1 y 2.
      `slide("La demo en vivo")`. Izquierda: marco `roughRect(30, 96, 640, 420)` `s-ink`; `FO(30, 96, 640, 420, 1280, 840)` con `<iframe title="Demo en vivo: visor de tormentas mesociclónicas en Chile" referrerpolicy="strict-origin-when-cross-origin" allow="fullscreen" loading="lazy">`, `src` asignado en el primer `onShow` (D4). Debajo del FO (en calm, antes en el orden del DOM) un grupo de respaldo oculto por defecto: captura (si existe) en `image` 640×420 + `T` "La demo no cargó aquí: escanea el código o abre el enlace" + `link` "Abrir la demo ↗". Siempre visible bajo el marco: `link(350, 538, "Abrir la demo en otra pestaña ↗", DEMO_URL, {size:13,cls:"t-blue"})`. Mostrar el respaldo y ocultar el FO si `!navigator.onLine`; la tecla `D` alterna ambos.
      Captura de respaldo: `& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --hide-scrollbars --window-size=1280,840 --virtual-time-budget=25000 --screenshot="$env:TEMP\pitch-qr\demo.png" "https://d2vcu1id4v0sta.cloudfront.net/"`; revisar la imagen: si muestra el visor (no una pantalla en blanco o "Please wait…"), convertirla con `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\.venv\Scripts\python.exe` + Pillow (12.3.0 ya instalado) a JPEG de 960 px de ancho, calidad 70, e incrustarla como `data:image/jpeg;base64,…` con `alt`/`aria-label` "Captura del visor de la demo". Si la captura no muestra el visor, omitir la imagen y dejar solo el texto + enlace (decisión fija, no preguntar).
      Derecha (x 700–970): `T(835,130,"Ábrela en tu teléfono",{size:20,cls:"t-red",boil:true})`; `qrBlock(735,150,200)`; `T(835,385,"Escanea el código",{size:14,cls:"t-muted"})`; `link(835,412,"d2vcu1id4v0sta.cloudfront.net",DEMO_URL,{size:13,cls:"t-blue"})`; `T(835,450,["Mapas, imágenes satelitales","y el caso de 2019, en vivo"],{size:14,cls:"t-muted",lh:1.4})`. Todo en paso 0.
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 4 y decodificar el QR de la captura: `& "$env:TEMP\pitch-qr\Scripts\python.exe" -c "import cv2,sys; d,_,_=cv2.QRCodeDetector().detectAndDecode(cv2.imread(sys.argv[1])); print(repr(d)); assert d=='https://d2vcu1id4v0sta.cloudfront.net/'" "$env:TEMP\pitch_s4.png"` → imprime la URL exacta. Revisar en la captura que el iframe ocupa ~2/3 y el QR ~1/3. Repetir `curl.exe -sI https://d2vcu1id4v0sta.cloudfront.net/` y confirmar que siguen sin aparecer `X-Frame-Options` ni `Content-Security-Policy` (si aparecen, dejar el respaldo visible por defecto y anotarlo).

- [ ] 7. Diapositiva 5 · Cómo funciona en AWS (reemplaza "7 · AWS architecture" y "why AWS").
      `slide("Cómo funciona en AWS")`. Seis nodos `roughRect` 240×88 con cabecera (size 17, boil, color del servicio) y subtítulo en lenguaje simple (size 13, `t-muted`, 2 líneas). Fila 1 (y 120, izquierda → derecha, x 60/380/700): ① "Amazon S3 · datos abiertos" — "imágenes GOES y reanálisis ERA5 públicos (AWS Open Data)" (`s-red`); ② "Amazon EC2 · procesa y aprende" — "calcula las condiciones de cada día y entrena el predictor" (`s-gold`); ③ "Amazon S3 · datos del proyecto" — "recortes de Chile y resultados, privado y cifrado" (`s-red`). Flecha hacia abajo desde ③. Fila 2 (y 290, derecha → izquierda, x 700/380/60): ④ "Amazon EC2 · el visor" — "la aplicación web en un contenedor" (`s-gold`); ⑤ "Amazon CloudFront · acceso seguro" — "una URL pública con HTTPS" (`s-violet`); ⑥ "Personas" — "en el computador o el teléfono" (`s-blue`). Pasos: 0 = ①, 1 = ②③, 2 = ④⑤⑥. Paso 3 (size 13, `t-muted`, y 430): "Seguridad: AWS IAM (permisos mínimos) · AWS Systems Manager (acceso sin SSH) · solo CloudFront llega al visor". Paso 4 (size 17, y 480): "¿Por qué AWS? Los datos ya viven ahí: procesamos junto a ellos y pagamos solo lo que usamos". El grupo del diagrama lleva `aria-label` que describa el flujo completo en una frase. No nombrar SageMaker, Batch, Lambda ni regiones (ver §0). Eliminar el texto "Diagrama interactivo (Archify)…".
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 5: seis nodos sin solapes, flechas en el sentido correcto.

- [ ] 8. Diapositiva 6 · Solicitamos financiamiento (reemplaza "impact / value" y "8 · how we approached it").
      `slide("Solicitamos financiamiento")`. Paso 0: `T(500,120,["para mantener, escalar y perfeccionar el sistema,","brindando un apoyo esencial a la ciudadanía"],{size:21,lh:1.4})`. Tres columnas `roughRect` 260×200 en x = 60, 370, 680, y = 190 (pasos 1–3), cabecera size 22 boil y 3 viñetas size 14 `t-muted`:
      - "Mantener" (`s-red`): "operación continua del visor en AWS", "datos y resultados al día", "seguridad y monitoreo".
      - "Escalar" (`s-blue`): "más años del archivo histórico", "todo el centro-sur y más regiones", "más personas conectadas a la vez".
      - "Perfeccionar" (`s-gold`): "más casos revisados con la comunidad meteorológica", "imágenes satelitales más precisas", "nuevas fuentes: radar y rayos".
      Paso 4 (size 17, y 460): "Información abierta para comunidades, equipos de emergencia y meteorólogos de Chile". Sin montos, sin marcadores de montos, sin fechas ni hoja de ruta.
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 6; buscar en el archivo que no quedan cifras de dinero (`Select-String -Pattern 'USD|\$ ?\d|CLP|millones' <archivo>` sin coincidencias en el texto de diapositivas).

- [ ] 9. Diapositiva 7 · Cierre y anexo (reemplaza "9 · closing / team"; mueve HSLC, variables y ML después).
      `slide("")`, `alt = "Cierre: gracias"`, `awsMark(cur,900,16,76)`. Columna izquierda (centro x 390): `T(390,130,"Gracias",{size:52,cls:"t-red"})`, `D(gust(250,530,160,9),"s-red",1.6)`, `T(390,205,"Equipo Prompters",{size:24,boil:true})`, `T(390,238,["Bryan Cabezas · Renato Gutiérrez · Nicolás Delgado","Daniel Zanelli · Steve Jurado"],{size:16,lh:1.4})`, `T(390,300,"Reto propuesto por R. Rondanelli (CR2), F. Förster y P. Badilla (IDIA, U. de Chile)",{size:12,cls:"t-muted"})`, `link(390,335,"github.com/BAFCS/Prompters-AWS-Tornado","https://github.com/BAFCS/Prompters-AWS-Tornado",{size:15,cls:"t-blue"})`. Derecha: `qrBlock(770,120,170)` y `T(855,318,"Prueba la demo",{size:15,cls:"t-muted"})`. `logoBand(400)` (logos AWS, CR2, U. de Chile, FCFM). Pie (size 12, `t-muted`, y 525): "Código, visor y catálogo abiertos · catálogo: doi:10.6084/m9.figshare.25119566 · CC BY 4.0". Todo en paso 0 salvo el pie (paso 1).
      Anexo: mover los bloques "3 · Chilean regime", "5 · features" y "6 · ML framing" detrás del cierre, cambiando solo los títulos a "Anexo · El régimen chileno: HSLC", "Anexo · Variables derivadas", "Anexo · Cómo plantear el aprendizaje". Borrar los bloques "why AWS", "impact / value", "8 · how we approached it" y el antiguo "Próximos pasos" si quedaran restos. Actualizar el `aria-label` del `<svg id="scene">` a "Presentación: predicción de tormentas mesociclónicas en Chile, propuesta de financiamiento".
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 7 y decodificar el QR de `pitch_s7.png` con el comando del ítem 6 (URL exacta); V-SHOT 8, 9 y 10 muestran el anexo; el contador `slideNo` indica "/ 10".

- [ ] 10. Notas del orador, accesibilidad y pasada final.
      Insertar justo antes del `<script>` principal un comentario HTML por diapositiva (`<!-- NOTAS · Diapositiva N · Título -->` + 2–4 frases en español). Contenido mínimo:
      1: "Dejar correr el video unos segundos. Contar que en 2019 dos tornados golpearon el Biobío y que en Santiago se confirmó uno en Estación Central. Mensaje: el riesgo existe y no tenemos cómo verlo venir. Si el video no carga, el fondo oscuro se mantiene; para el video, servir la carpeta con `python -m http.server 8000` y abrir http://localhost:8000/mesociclones_chile_presentation.html."
      2: "Explicar el mesociclón en una frase: aire que sube girando dentro de una tormenta. Recalcar que no hay radar y que los datos de satélite y reanálisis son abiertos."
      3: "Tres piezas: predictor, visor, apoyo. Aclarar con honestidad que hoy usa datos históricos y que las alertas requieren validación."
      4: "Invitar a escanear el QR. Mostrar Mapas y Caso de estudio. Tras usar el iframe, hacer clic en la columna derecha para devolver el foco al teclado. Si falla la red, tecla D para la captura."
      5: "Recorrer el flujo de arriba hacia abajo: datos abiertos, procesamiento en EC2, almacenamiento en S3, visor en EC2 y CloudFront hacia las personas."
      6: "Pedir el apoyo: mantener, escalar, perfeccionar. No dar cifras; ofrecer conversarlas después."
      7: "Agradecer, dejar el QR en pantalla durante las preguntas."
      8–10: "Material de respaldo para preguntas técnicas; no se presenta en el pitch."
      Pasada de accesibilidad: todos los iframes con `title`; video con `aria-hidden` y `tabindex="-1"`; QR con `role="img"` + `aria-label`; diagramas de las diapositivas 2, 3 y 5 con `aria-label`; enlaces con texto descriptivo; texto sobre el video solo en blanco/`#FF9900` sobre el velo `#161E2D` 0.62; no usar `--faint` para texto. Revisar el tema oscuro a mano (tecla T) en las diapositivas 2–7: el QR sigue negro sobre blanco y los textos son legibles. Borrar temporales: `Remove-Item -Recurse -Force "$env:TEMP\pitch-qr", "$env:TEMP\pitch_js_*.js", "$env:TEMP\pitch_s*.png"` (solo al terminar la verificación). No hacer commit.
      Files: `c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado\docs\presentation\mesociclones_chile_presentation.html`
      Verify: V-JS; V-SHOT 1–10 revisadas una por una; QR de las diapositivas 4 y 7 decodifica exactamente `https://d2vcu1id4v0sta.cloudfront.net/`; `git -C "c:\Users\zanel\OneDrive\Documentos\Prompters\Prompters-AWS-Tornado" status --short` muestra solo el HTML modificado (además del `.dockerignore` borrado que ya estaba) y ningún commit nuevo.

## Supuestos y huecos

- No hay correo de contacto en el repo: el cierre usa el repositorio de GitHub como contacto. Si el equipo quiere un correo, se agrega después.
- El video depende de YouTube en línea; con `file://` o sin red queda el póster oscuro (comportamiento aceptado). No se descarga el video (derechos de Meganoticias/YouTube).
- La región de despliegue es contradictoria entre `AGENTS.md` (us-west-2) y Terraform (us-east-1): por eso no aparece en las diapositivas.
- El orden de capas: los textos boil van en `#world`, que se dibuja encima de `#calm`, así que quedan sobre el video y el velo; los textos no boil de la diapositiva 1 deben crearse después del velo dentro de la misma capa calm.
