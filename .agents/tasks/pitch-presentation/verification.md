# Verificación · pitch `docs/presentation/mesociclones_chile_presentation.html`

Fecha: 15-oct-2026. Edge headless (Playwright, canal `msedge`) a 1920×1080, servido con `python -m http.server` en
`127.0.0.1:8765`, más una pasada abriendo el archivo como `file://`. Script: `verify.py` (borrado al terminar; su
salida se resume aquí).

## Resultado

| Comprobación | Resultado |
|---|---|
| Sintaxis del `<script>` (`node --check`) | exit 0 |
| Desbordes (texto, imágenes, foreignObject, QR fuera de 1000×560) | ninguno en las 10 diapositivas |
| Video de la diapositiva 1 (HTTP) | se reproduce y vuelve a 0 cada 5 s: muestras 0,59 → 4,58 → 0,02 → … → 4,74 → 0,17 |
| Video de la diapositiva 1 (`file://`) | igual: 2,03 → 4,59 → 0,01 → … → 4,70 → 0,12 |
| Demo (diapositiva 5) | iframe cargado con `https://d1m48zea07nk1y.cloudfront.net/`, a sangre: 1643×1075 de 1920×1080 px (86 % del ancho, toda la altura); a la derecha solo el QR (230 px) y «Escanéala»; decodifica en tema claro y oscuro |
| Tecla D (respaldo de la demo) | muestra la captura con «La demo no cargó aquí…» y «Abrir la demo ↗» (`slide_05_fallback_D.png`) |
| Diagrama Archify (diapositiva 4) | modo presentación de Archify (`present=1`), no `embed=1`: con `embed=1` Archify apaga el movimiento y casi toda la interacción. Ahora, sin nada guardado de antes: `data-motion="live"`, movimiento de reposo en marcha (72 animaciones); al pasar el mouse por un nodo resalta sus conexiones y atenúa el resto; barra (tema, preset, Live/Still, Export) y ROUTE / LENS / búsqueda / zoom visibles; igual por HTTP y por `file://`; con T pasa a `theme=dark`; con `prefers-reduced-motion` queda quieto. Tras hacer clic dentro del diagrama, al sacar el mouse el foco vuelve a la presentación (→ pasa a 5/10 sin clic extra) |
| Navegación | → recorre 1/10 … 10/10; Home 1/10; End 10/10; ← desde el final 9/10; clic avanza |
| QR decodificado (OpenCV) | generador: `https://d1m48zea07nk1y.cloudfront.net/` (versión 3, corrección M); diapositivas 5 y 7 renderizadas: la misma URL exacta |
| Pie de la diapositiva 7 | sin íconos de fondo encima, en tema claro y oscuro |

## Encabezados de la demo

`curl.exe -sI https://d1m48zea07nk1y.cloudfront.net/` → `HTTP/1.1 200 OK`, `server: uvicorn`, vía CloudFront; **sin
`X-Frame-Options` y sin `Content-Security-Policy`**, así que se puede embeber. `/_stcore/health` → 200. La URL anterior
(`d2vcu1id4v0sta`) también respondía sin esos encabezados, pero ya no aparece en el archivo.

## Video: `file://` frente a HTTP local

Antes el video venía de YouTube: por HTTP funcionaba, por `file://` YouTube mostraba «Error 153» y la diapositiva
quedaba con el fondo oscuro y el embudo dibujado. Además, en Edge headless se veían los botones del reproductor en el
centro (aunque `controls=0`) y el borde inferior del rótulo de Meganoticias («07:01 INÉDITO TORNADO…») detrás del crédito.

Ahora el clip es local, `docs/presentation/assets/tornado_estacion_central.mp4` (H.264, 1280×720, 5 s, sin audio,
337 KB; póster `tornado_estacion_central.jpg`). Se recortó a la toma vertical del teléfono, sin rótulo ni paneles del
noticiero, sobre un fondo desenfocado del mismo cuadro. Funciona igual por HTTP y por `file://`, y sin internet. Así se
resuelven también los botones y el rótulo: no hay reproductor ni banda. El crédito sigue visible en la diapositiva 1.

El video está en una capa HTML (`#heroLayer`) detrás del SVG de la diapositiva, no dentro del SVG: dentro de un
`foreignObject` Chromium lo dejaba negro aunque estuviera reproduciéndose. Si el archivo falla (`error`), la capa se
oculta y queda el embudo dibujado. Con `prefers-reduced-motion` no se reproduce y queda el póster.

## Diapositivas finales

Orden actual: la arquitectura (4) va antes de la demo (5), a pedido del equipo. Comprobado tras el cambio: 4/10 muestra Archify (tema claro y oscuro), 5/10 la demo con el QR, que decodifica la URL exacta; sin desbordes; → recorre las 10.

| N | Diapositiva | Qué cambió en esta pasada |
|---|---|---|
| 1 | Apertura: «Chile también tiene tornados» | video local; texto reducido a título + dos cifras (102 tornados y trombas documentados · 0 radares en 2019) |
| 2 | ¿Qué es un mesociclón y qué datos tenemos? | diagrama más grande, una frase; tarjetas GOES/ERA5/Catálogo con íconos y una línea cada una |
| 3 | Nuestra propuesta | tres bloques con íconos (predictor, visor, apoyo) y una línea cada uno |
| 5 | La demo en vivo | iframe a sangre de 856×560 (de 1000×560), sin marco, título ni logo; franja derecha con el QR (que también es enlace) y «Escanéala»; la URL en texto queda en la diapositiva 7 |
| 4 | Cómo funciona | diagrama de Archify en modo presentación, interactivo y en movimiento como el archivo original; marco de 960×440, maquetado a 1150 px; va antes de la demo |
| 6 | Solicitamos financiamiento | íconos (escudo, gráfico, diana) y dos líneas por columna |
| 7 | Gracias | nueva URL y QR; íconos de fondo fuera del pie |
| 8–10 | Anexo: HSLC · Variables derivadas · Cómo plantear el aprendizaje | sin cambios de contenido (en la 9 la letra de las viñetas baja de 14 a 13 para que no toque el borde) |

Lo que salió del texto de las diapositivas pasó a las notas del orador (comentarios HTML `<!-- NOTAS · … -->`).

Diapositivas originales eliminadas o condensadas (sin cambios desde el plan): «El problema en una página» → 1; «¿Qué es
un mesociclón?» y «Los datos de entrada» → 2; «Arquitectura en AWS» y «¿Por qué AWS?» → 4; «El valor que entregamos»,
«Cómo lo hemos afrontado» y «Próximos pasos» eliminadas; HSLC, variables y planteamiento de ML → anexo.

Opcionales adoptados: notas del orador (sí) y la línea «¿Por qué AWS?» (sí, abajo del diagrama de la diapositiva 4;
la frase de seguridad IAM / Session Manager pasó a las notas). Rechazados por decisión del usuario: métricas, hoja de
ruta, montos.

## Pendiente de revisar por el equipo

El diagrama de Archify (`archify/tornado-aws.architecture.json`) muestra AWS Batch / Lambda, SageMaker y API Gateway.
Según el plan (§0), el despliegue real en Terraform usa S3, EC2, CloudFront, IAM y Session Manager, y esos servicios no
aparecen en el código. La diapositiva 4 embebe el archivo tal cual. Si se quiere que coincida con lo desplegado, hay que
regenerar el diagrama.

## Capturas (carpeta `.agents/tasks/pitch-presentation/`)

- `slide_01.png` … `slide_10.png`: todas las diapositivas con sus pasos visibles, tema claro, por HTTP.
- `slide_02_dark.png` … `slide_07_dark.png`: tema oscuro.
- `slide_04_hover.png`: Archify con el mouse sobre un nodo; `slide_04_file_protocol.png`: Archify abierto como `file://`.
- `slide_01_video_check.png`: video en marcha; `slide_05_fallback_D.png`: respaldo de la demo (tecla D).
- De pasadas anteriores (diagnóstico del video de YouTube, ya no reflejan el archivo actual): `slide_01_file_protocol.png`,
  `slide_01_probe.png`, `slide_01_probe_sw.png`, `probe_direct.png`, `probe_noveil.png`; y, del orden anterior (demo en la 4, Archify en la 5),
  `slide_04_fallback_D.png` y `slide_05_file_protocol.png`.
