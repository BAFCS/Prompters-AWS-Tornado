---
name: Mesociclones en Chile · visor
description: Cuaderno de campo de un caso; entorno ERA5 y tormenta GOES a la misma hora y lugar, con el umbral chileno a la vista, en tema claro y oscuro.
colors:
  fondo: "#F1FAEE"
  hoja: "#FFFFFF"
  hoja-2: "#EFF8F9"
  filete: "#BDD4D6"
  tinta: "#0E1A2C"
  tinta-2: "#1D3557"
  apagado: "#465463"
  accion: "#376284"
  accion-suave: "#A8DADC"
  seleccion: "#457B9D"
  severo: "#E63946"
  severo-suave: "#EFD7D0"
  frio: "#0072B2"
  calido: "#B07800"
  fondo-oscuro: "#172A46"
  hoja-oscuro: "#1D3557"
  hoja-2-oscuro: "#2C4362"
  filete-oscuro: "#475C75"
  tinta-oscuro: "#F1FAEE"
  tinta-2-oscuro: "#D4EDE7"
  apagado-oscuro: "#A9B8BE"
  accion-oscuro: "#A8DADC"
  accion-suave-oscuro: "#3D6E8E"
  seleccion-oscuro: "#A8DADC"
  severo-oscuro: "#E63946"
  severo-suave-oscuro: "#593652"
  frio-oscuro: "#56B4E9"
  calido-oscuro: "#E69F00"
typography:
  display:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontWeight: 600
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontWeight: 700
    letterSpacing: "0"
  body:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
  lede:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.08rem"
    fontWeight: 400
    lineHeight: 1.5
  nota:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.86rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 600
  datos:
    fontFamily: "'IBM Plex Mono', ui-monospace, Menlo, monospace"
    fontWeight: 400
    fontFeature: "tnum"
rounded:
  marca: "3px"
  base: "6px"
spacing:
  celda: "6px"
  tarjeta: "10px 12px"
components:
  button-primary:
    backgroundColor: "{colors.accion}"
    textColor: "{colors.hoja}"
    rounded: "{rounded.base}"
  button-primary-oscuro:
    backgroundColor: "{colors.accion-oscuro}"
    textColor: "{colors.hoja-oscuro}"
    rounded: "{rounded.base}"
  button-secondary:
    backgroundColor: "{colors.hoja}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.base}"
  button-secondary-oscuro:
    backgroundColor: "{colors.hoja-oscuro}"
    textColor: "{colors.tinta-oscuro}"
    rounded: "{rounded.base}"
  panel:
    backgroundColor: "{colors.hoja}"
    rounded: "{rounded.base}"
  panel-oscuro:
    backgroundColor: "{colors.hoja-oscuro}"
    rounded: "{rounded.base}"
  ficha-marca-supera:
    backgroundColor: "{colors.severo-suave}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.marca}"
  ficha-marca-supera-oscuro:
    backgroundColor: "{colors.severo-suave-oscuro}"
    textColor: "{colors.tinta-oscuro}"
    rounded: "{rounded.marca}"
  ficha-marca-bajo:
    backgroundColor: "{colors.hoja-2}"
    textColor: "{colors.apagado}"
    rounded: "{rounded.marca}"
  ficha-marca-bajo-oscuro:
    backgroundColor: "{colors.hoja-2-oscuro}"
    textColor: "{colors.apagado-oscuro}"
    rounded: "{rounded.marca}"
  ficha-valor-supera:
    textColor: "{colors.tinta}"
    typography: "{typography.datos}"
  ficha-valor-supera-oscuro:
    textColor: "{colors.tinta-oscuro}"
    typography: "{typography.datos}"
  paso:
    backgroundColor: "{colors.hoja}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.base}"
    padding: "{spacing.tarjeta}"
  paso-oscuro:
    backgroundColor: "{colors.hoja-oscuro}"
    textColor: "{colors.tinta-oscuro}"
    rounded: "{rounded.base}"
    padding: "{spacing.tarjeta}"
---

# Design System: Mesociclones en Chile · visor

## Overview

**Creative North Star: "El cuaderno de campo"**

El visor es la libreta de un caso meteorológico: un fondo sobre el que se apoyan hojas con filete fino (mapas, sondeos, tablas), cada una con su dato medido en tipografía de máquina y su nota al margen en gris. Nada flota ni brilla; la jerarquía la dan la hoja, el filete y pocos colores con trabajo asignado: el Steel Blue señala lo que el usuario puede accionar o eligió, el Strawberry Red marca tornados del catálogo y umbrales chilenos sin escribir nunca una palabra.

La paleta sale de cinco colores fijados por el usuario (Strawberry Red, Honeydew, Frosted Blue, Steel Blue y Deep Space Blue); los demás tonos son mezclas entre ellos. Hay dos temas que el visitante alterna desde el menú de Streamlit: claro (Honeydew de fondo, hojas blancas, Deep Space oscurecido de tinta) y oscuro (hojas Deep Space sobre un fondo más hondo, Honeydew de tinta, Frosted Blue de acción). Los mapas no usan la paleta: usan escalas estándar según el tipo de dato.

Densidad media-alta, de herramienta de trabajo: dos columnas en escritorio, explicación siempre al lado del dato y nunca encima. La identidad la construye Streamlit con cuatro capas: `.streamlit/config.toml` (widgets y fuentes, tablas `[theme.light]` y `[theme.dark]`), las plantillas plotly `cuaderno` y `cuaderno_oscuro`, el CSS fino de `scripts/visor_app/tema.py` (variables CSS de las dos paletas, conmutadas por `html[data-tema="oscuro"]`) y un vigía que detecta el cambio de tema y vuelve a ejecutar la página para redibujar los gráficos.

**Key Characteristics:**
- Fondo Honeydew (claro) o Deep Space hondo (oscuro); hojas con filete de 1 px y radio de 6 px.
- Roles de color estrictos: acción en la interfaz, selección dentro de los gráficos, rojo solo como marca de eventos y umbrales chilenos.
- IBM Plex Sans para títulos y texto; IBM Plex Mono para cifras, coordenadas y horas.
- Cifras con coma decimal y dígitos tabulares.
- Mapas con escalas estándar (Viridis, ColorBrewer, cmocean) elegibles por gráfico y marcadas según su aptitud para daltonismo.
- Sin sombras: profundidad por tono (fondo, hoja) y filete.

## Colors

Paleta fría de cinco colores de marca y sus mezclas, en dos temas con los mismos roles. Cada token claro tiene su par `-oscuro`; el rojo es el mismo en ambos.

### Primary
- **Steel Blue hondo** (accion; en oscuro **Frosted Blue**, accion-oscuro): acción en la interfaz. Botón primario, slider de hora, foco, enlaces, segmento activo, marca de "ahora" en la regla de tiempo, contador de la tarjeta de paso. El texto sobre el botón primario es la hoja de cada tema (blanco en claro, Deep Space en oscuro).
- **Frosted Blue** (accion-suave; en oscuro Steel Blue, accion-suave-oscuro): selección de texto en el navegador.
- **Steel Blue** (seleccion; en oscuro Frosted Blue, seleccion-oscuro): lo elegido dentro de un gráfico. Anillo del punto elegido en los mapas, serie "punto" y línea de la hora en Series, Bunkers left-mover en el hodógrafo, primer color categórico.

### Secondary
- **Strawberry Red** (severo): marca, no texto. Triángulos de evento en mapas (con borde del color de la hoja) y en la regla de tiempo, contorno del umbral chileno en mapas (1,6 px), línea a rayas del valor de comparación en Series, líneas verticales de eventos, triángulo junto al valor que supera en la ficha y junto a la cifra destacada de El proyecto, el giro del mesociclón en los diagramas.
- **Fresa lavada** (severo-suave; en oscuro severo-suave-oscuro): fondo de la píldora "Cumple el criterio" de la ficha, con texto en tinta encima.

### Tertiary
- **Azul de Okabe-Ito** (frio; frio-oscuro en oscuro) y **naranja de Okabe-Ito** (calido-oscuro en oscuro; en claro, oscurecido a `#B07800` para llegar a 3:1 sobre la hoja): series categóricas que la paleta no cubre, aptas para daltonismo. Frío: capa 1–3 km del hodógrafo. Cálido: punto de rocío del Skew-T, capa 3–6 km del hodógrafo, series "área GOES", flechas de cizalle y convergencia en los diagramas. Ninguno de los dos escribe texto largo; en los diagramas el frío rotula en tamaño grande.

### Neutral
- **Honeydew** (fondo; fondo-oscuro en oscuro): página principal y cabecera. En el tema claro, la barra lateral va un tono más oscura, `#BEE4E1` (Honeydew + 70 % Frosted Blue), para separarse del fondo; en el oscuro comparte el fondo-oscuro.
- **Hoja** (hoja; Deep Space Blue en oscuro, hoja-oscuro): paneles de gráficos, tablas, expansores, ficha, tarjeta de paso, contenedores de El proyecto; fondo del área de trazado y de las etiquetas de hover; halo del punto elegido y borde de los triángulos de evento.
- **Hoja lavada** (hoja-2): grilla de gráficos, isotermas del Skew-T, separador interno de filas de la ficha, píldoras "No cumple el criterio", "Sin criterio de decisión" y "Sin datos", fondo de los botones de animación de Mapas.
- **Filete** (filete): borde de 1 px de todo panel, ejes y encabezado de la ficha.
- **Tinta** (tinta): texto, costa en los mapas, temperatura del Skew-T, capa 0–1 km del hodógrafo, valor que supera en la ficha, rótulo del evento propio en Series.
- **Deep Space Blue** (tinta-2; menta pálida en oscuro): entradilla (lede), serie "área" en Series, viento medio del hodógrafo, contornos de geopotencial.
- **Pizarra** (apagado): notas, captions, encabezados de tabla, referencias de índices sin umbral calibrado, horas de la regla, rótulo "valor de comparación", parcela del Skew-T, capa 6–10 km del hodógrafo, Bunkers right-mover. `tema.py` anula el 60 % de opacidad que Streamlit aplica a `st.caption`.

### Escalas de los mapas
Las escalas de color de los mapas no son colores de marca: son escalas estándar con nombre de plotly, elegidas por el tipo de dato del producto (`Producto.tipo`, `Capa.tipo`) y cambiables por gráfico ("Escala de color" en el menú de ajuste de cada panel de Mapas y sobre cada mapa de El caso). Cada opción se rotula "apta" o "no apta para daltonismo".
- **Secuencial** (VGP, cizalle, CAPE, LCL, C08 − C13): Viridis por defecto; Cividis, Plasma, Magma, YlGnBu; Turbo (no apta).
- **Divergente** (SRH, STP, viento, vorticidad, ΔC13; cero al centro): PuOr por defecto; RdBu invertida, BrBG, Balance; Picnic (no apta).
- **Infrarrojo** (temperatura de brillo): grises con los topes fríos en blanco por defecto; Cividis y Viridis invertidas, Hielo; Turbo invertida (no apta).
- **Visible** (reflectancia): grises por defecto; Cividis.

### Named Rules
**El rojo marca, no escribe.** El Strawberry Red solo aparece como glifo o línea, y solo por un evento del catálogo o por un umbral chileno calibrado (su contorno, su línea o un valor que lo cruza). Nunca es texto, en ningún tamaño ni tema: las alertas van en tinta con el triángulo rojo al lado, y `redTextColor` (igual que `orangeTextColor`) está fijado a la tinta en `config.toml`, así que `st.error` y las insignias escriben en tinta. Los índices sin umbral calibrado (SRH₀₋₁, SHERBS3, LCL, cizalle 0–6 km) no se marcan: llevan su referencia en texto apagado.

**Acción y selección.** En la interfaz, el color de acción marca lo que se puede accionar (botón, slider, foco, "ahora"). Dentro de un gráfico, lo elegido (punto, serie del punto, hora actual) lleva el color de selección. Ninguno de los dos expresa alarma.

**Escalas estándar según el dato.** Un mapa se colorea con una escala estándar de su tipo de dato, nunca con colores de la marca. La predeterminada de cada tipo es siempre apta para daltonismo, y la divergente por defecto (PuOr) no lleva rojo, porque el rojo marca los eventos.

**Los dos temas AA.** Tinta, entradilla, notas y acción alcanzan 4,5:1 sobre el fondo y sobre la hoja en los dos temas; también el texto del botón primario sobre la acción y la tinta sobre la píldora "Cumple el criterio". `tests/test_escalas.py` lo comprueba: un color nuevo de texto entra con su prueba.

## Typography

**Display Font:** IBM Plex Sans 600 (la misma familia del cuerpo)
**Body Font:** IBM Plex Sans (con -apple-system, Segoe UI, sans-serif)
**Label/Mono Font:** IBM Plex Mono (con ui-monospace, Menlo, monospace)

**Character:** Una sola familia de instrumento, IBM Plex: la sans para leer, operar y titular, y su mono hermana para lo que se midió. Sin serif: la jerarquía la dan el peso y el tamaño.

### Hierarchy
- **Display** (IBM Plex Sans 600, tamaño del h1 de Streamlit, -0,01em): solo el título de cada página.
- **Headline** (IBM Plex Sans 700, h2/h3 de Streamlit, sin tracking): subtítulos de sección ("Bitácora", "Entorno contra umbral chileno") y nombre del visor en la barra lateral.
- **Lede** (400, 1,08rem, 1,5, máx. 68ch, tinta-2): una frase bajo el título de página o de sección.
- **Body** (400, 1rem): texto de contexto y de expansores; en todas las páginas, párrafos y listas de máx. 68ch.
- **Nota** (400, 0,86rem, 1,45, máx. 75ch, apagado): advertencias y ayuda al lado del dato.
- **Label** (600, 0,78rem, apagado): encabezados de la ficha.
- **Datos** (IBM Plex Mono, cifras tabulares): valores de la ficha, coordenadas, horas de la regla, etiquetas de hover en gráficos (12 px).

### Named Rules
**La regla de una sola familia.** Todo es IBM Plex: Sans para texto y títulos, Mono para datos. No se mezcla con serif ni con otra sans.

**La regla del dato en mono.** Lo medido (valores, coordenadas, horas UTC) va en IBM Plex Mono con cifras tabulares donde la plataforma lo permite; la prosa y las unidades no.

**La regla de la coma.** Separador decimal coma en ficha y gráficos (`separators=", "` en plotly; `_num` en la ficha), con 3 cifras significativas; las coordenadas salen de `componentes.coord` con signo menos tipográfico.

## Layout

Página ancha de Streamlit (`layout="wide"`) con barra lateral que lleva el estado compartido: región, día, hora UTC con la regla de tiempo debajo, evento, punto elegido y recorrido guiado. Navegación superior entre cinco páginas: El proyecto (por defecto, visible aunque no haya datos), El caso, Mapas, Sondeo y Series.

Cada página: título, lede, y luego pares de columnas. El caso y Sondeo ponen mapas y gráficos lado a lado en dos columnas iguales (`gap="large"`) y el texto o las tablas en proporción 3:2. Mapas es una grilla de 1 a 6 paneles en una sola figura plotly con ejes compartidos (el zoom va sincronizado); sobre ella, una barra de controles por panel en contenedores horizontales (`st.container(horizontal=True)`) que se parten en pantallas angostas, con un menú de ajuste (escala de color, nivel, contornos). Nota bajo cada gráfico en apagado. Relleno superior del contenedor 2,2rem (1,6rem más en El proyecto). En móvil las columnas se apilan (comportamiento de `st.columns`).

Los mapas conservan el aspecto real (escala y = 1/cos(latitud media)) y se encuadran por defecto en la zona de eventos con 2° de margen.

## Elevation & Depth

Sistema plano. La profundidad es tonal: fondo abajo, hoja con filete de 1 px encima. En oscuro la hoja es más clara que el fondo, igual que en claro la hoja blanca se separa del Honeydew. No hay sombras en paneles, tablas ni tarjetas; las leyendas de gráficos usan la hoja al 80 % para no tapar datos.

**La regla de la hoja sobre la mesa.** Todo contenido de datos (gráfico, tabla, ficha, expansor) es una hoja con filete sobre el fondo; el texto corrido de las páginas de datos va directo sobre el fondo, sin hoja.

## Shapes

Esquinas apenas suavizadas: 6 px en widgets (`baseRadius`) y paneles, 3 px en las píldoras de la ficha, 1 px en la marca de "ahora". Bordes de 1 px en filete; los widgets muestran borde (`showWidgetBorder`). Glifos: triángulo hacia arriba rojo con borde del color de la hoja para eventos (12 px en mapas, 10×9 px en la regla y la ficha); punto elegido como doble anillo, un halo ancho del color de la hoja y encima un anillo fino de selección, para que se separe de cualquier escala, también de los topes fríos.

## Components

### Buttons
- **Shape:** 6 px de radio (Streamlit `baseRadius`).
- **Primary:** fondo de acción, texto de la hoja ("Empezar recorrido", "Siguiente"), ancho completo en la barra lateral, con icono Material.
- **Secondary:** hoja con filete, texto tinta ("Anterior", "Empezar recorrido guiado" en El caso).
- **Tertiary:** solo texto con icono ("Salir del recorrido").

### Paneles de gráfico
- **Corner Style:** 6 px. **Background:** hoja. **Border:** 1 px filete. **Internal Padding:** 6px 4px 2px.
- Las plantillas `cuaderno` y `cuaderno_oscuro`: título 15 px a la izquierda, grilla en hoja lavada, ejes en filete, sin ticks, hover en hoja con filete y mono 12 px, colorbar de 12 px sin contorno, colores categóricos selección, tinta, cálido, frío, apagado, entradilla.
- Limitación: el frontend de Streamlit ignora fondo y fuente de la plantilla, por eso `graficos._estilo` los fija en el layout de cada figura con la paleta del modo activo.

### Ficha "entorno contra umbral chileno"
La firma de los datos. Tabla HTML en hoja con filete y radio 6 px: índice (con unidad en nota), valor en el punto y extremo de la zona en mono alineado a la derecha, umbral ("> 0,1") en mono o referencia en sans apagada de 0,8rem, y una columna Resultado con píldora en todas las filas: "Cumple el criterio" (fresa lavada, texto tinta) solo cuando un umbral calibrado se cruza; "No cumple el criterio", "Sin criterio de decisión" o "Sin datos" en hoja lavada con texto apagado. El valor que supera pasa a tinta 700 con un triángulo rojo delante.

### Bitácora
`st.dataframe` en hoja con filete, filas seleccionables que llevan hora y punto a todas las páginas. Limitación: `st.dataframe` no permite fuente por columna, así que la hora UTC sale en sans.

### Regla de tiempo
Componente firma compartido por todas las páginas, bajo el slider de hora en la barra lateral: pista de 18 px con línea base en filete, triángulos rojos de 10×9 px por evento (title con hora y lugar; la lista completa va en el `aria-label`, porque el title solo se ve con ratón), marca de "ahora" en acción (2×20 px) y extremos del día en mono 0,75rem apagado. HTML y CSS sin SVG, porque `st.html` sanea el SVG.

### Tarjeta de paso
Hoja con filete, radio 6 px, relleno 10px 12px, 0,92rem. Primera línea con el contador y la hora UTC del paso en mono 600 de acción, 0,8rem; debajo el texto del paso. Bajo la tarjeta, Anterior / Siguiente y Salir.

### Gráficos de dominio
- **Mapas:** escala estándar del tipo de dato; costa en tinta 0,9 px; contorno del umbral chileno en rojo 1,6 px; eventos como triángulos rojos con borde de hoja; punto elegido en doble anillo; clic en una grilla invisible elige el punto.
- **Skew-T:** temperatura en tinta 2,4 px, punto de rocío en cálido 2,4 px, parcela en apagado a rayas, isotermas en hoja lavada.
- **Hodógrafo:** capas 0–1 km tinta, 1–3 km frío, 3–6 km cálido, 6–10 km apagado; Bunkers left-mover diamante relleno en selección, right-mover diamante abierto apagado, viento medio en entradilla.
- **Series:** serie "punto" en selección, "área" en entradilla, "área GOES" en cálido; valor de comparación en rojo a rayas con rótulo apagado; eventos como líneas rojas verticales (sólida 2 px el propio, con su rótulo en tinta; punteada 1 px los demás); hora actual en selección 1 px.
- **Diagramas de El proyecto:** SVG con las variables de la paleta activa; rotulan en tinta, entradilla, apagado, acción o frío, nunca en rojo ni en cálido.

## Do's and Don'ts

### Do:
- **Do** poner todo dato sobre una hoja con filete y radio 6 px encima del fondo, en los dos temas.
- **Do** reservar el Strawberry Red #E63946 para glifos y líneas de eventos del catálogo y umbrales chilenos calibrados; las alertas en tinta con el triángulo rojo al lado.
- **Do** usar el color de acción (#376284 en claro, #A8DADC en oscuro) para lo accionable y el de selección (#457B9D en claro, #A8DADC en oscuro) para lo elegido dentro de un gráfico.
- **Do** colorear los mapas con la escala estándar de su tipo de dato (`escalas.TIPOS`) y dejar que la predeterminada sea apta para daltonismo.
- **Do** usar el azul y el naranja de Okabe-Ito para series categóricas que la paleta no cubre.
- **Do** escribir cifras con coma decimal y en IBM Plex Mono tabular cuando la plataforma lo permita.
- **Do** tomar los colores de `tema.colores()` y la plantilla de `tema.plantilla()`, y fijar fondo y fuente en el layout de cada figura plotly (`graficos._estilo`).
- **Do** añadir a `tests/test_escalas.py` todo color nuevo de texto, con su contraste AA en claro y oscuro.

### Don't:
- **Don't** escribir texto en rojo, ni siquiera en tamaño grande o en un diagrama.
- **Don't** introducir una serif ni una segunda sans junto a IBM Plex.
- **Don't** colorear un mapa con colores de la marca ni poner por defecto una escala con rojo o no apta para daltonismo.
- **Don't** marcar en rojo un índice sin umbral chileno calibrado ni usar umbrales norteamericanos.
- **Don't** fijar un hex en un gráfico o en el CSS fuera de `Paleta`: el color tiene que cambiar con el tema.
- **Don't** añadir sombras: la profundidad es tonal.
