---
name: Mesociclones en Chile · visor
description: Cuaderno de campo de un caso; entorno ERA5 y tormenta GOES a la misma hora y lugar, con el umbral chileno a la vista.
colors:
  niebla: "#E4E9EB"
  superficie: "#FFFFFF"
  superficie-2: "#F1F4F5"
  filete: "#C9D3D6"
  tinta: "#0C1518"
  tinta-2: "#33454B"
  apagado: "#64757B"
  acento: "#0E6A63"
  acento-suave: "#D6E8E5"
  severo: "#D2492A"
  severo-suave: "#F7E0D8"
  severo-texto: "#9A2F17"
  frio: "#4C7FB8"
  calido: "#C98A3C"
typography:
  display:
    fontFamily: "Fraunces, serif"
    fontWeight: 600
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
    fontWeight: 700
    letterSpacing: "0"
  body:
    fontFamily: "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
  lede:
    fontFamily: "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.08rem"
    fontWeight: 400
    lineHeight: 1.5
  nota:
    fontFamily: "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.86rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 600
  datos:
    fontFamily: "'JetBrains Mono', ui-monospace, Menlo, monospace"
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
    backgroundColor: "{colors.acento}"
    textColor: "{colors.superficie}"
    rounded: "{rounded.base}"
  button-secondary:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.base}"
  panel:
    backgroundColor: "{colors.superficie}"
    rounded: "{rounded.base}"
  ficha-marca-supera:
    backgroundColor: "{colors.severo-suave}"
    textColor: "{colors.severo-texto}"
    rounded: "{rounded.marca}"
  ficha-marca-bajo:
    backgroundColor: "{colors.superficie-2}"
    textColor: "{colors.apagado}"
    rounded: "{rounded.marca}"
  ficha-valor-supera:
    textColor: "{colors.severo}"
    typography: "{typography.datos}"
  paso:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.base}"
    padding: "{spacing.tarjeta}"
---

# Design System: Mesociclones en Chile · visor

## Overview

**Creative North Star: "El cuaderno de campo"**

El visor es la libreta de un caso meteorológico: una mesa de niebla clara sobre la que se apoyan hojas blancas con filete fino (mapas, sondeos, tablas), cada una con su dato medido en tipografía de máquina y su nota al margen en gris. Nada flota ni brilla; la jerarquía la dan el papel, el filete y dos colores con trabajo asignado: el verde azulado señala lo que el usuario eligió o puede accionar, el rojo señala tornados del catálogo y umbrales chilenos.

Densidad media-alta, de herramienta de trabajo: dos columnas en escritorio, explicación siempre al lado del dato y nunca encima. La identidad viene del sitio del proyecto (`web/index.html`, tema claro) y la construye Streamlit con tres capas: `.streamlit/config.toml` (widgets y fuentes), la plantilla plotly `cuaderno` y el CSS fino de `scripts/visor_app/tema.py`.

**Key Characteristics:**
- Fondo niebla en página y cabecera; superficies blancas con filete de 1 px y radio de 6 px.
- Dos colores semánticos estrictos: acento = elección/acción, severo = eventos y umbral chileno.
- Fraunces solo en el título de página; Source Sans 3 para todo lo demás; JetBrains Mono para cifras, coordenadas y horas.
- Cifras con coma decimal y dígitos tabulares.
- Sin sombras: profundidad por tono (niebla, blanco) y filete.

## Colors

Paleta fría y clara de papel y niebla, con un acento verde azulado y un rojo de severidad que nunca se mezclan en función.

### Primary
- **Verde liquen** (acento): botón primario, slider de hora, segmento activo, marca de "ahora" en la regla de tiempo, círculo del punto elegido en los mapas, línea vertical de la hora en las series y serie "punto". En gráficos es también el tono medio de la escala secuencial (blanco, acento suave, acento, tinta).
- **Liquen lavado** (acento-suave): selección de texto y paso intermedio de la escala secuencial.

### Secondary
- **Óxido de alerta** (severo): triángulos de evento en mapas y en la regla de tiempo, contorno y líneas del umbral chileno, y el valor de la ficha que supera un umbral calibrado (VGP₀₋₁ > 0,1; cizalle 0–1 km > 12; STP left-mover ≤ −0,3).
- **Óxido lavado** (severo-suave) con **óxido profundo** (severo-texto): la píldora "supera" de la ficha.

### Tertiary
- **Azul de tope frío** (frio) y **ocre templado** (calido): extremos de la escala divergente (centro casi blanco #F7F9FA, cero en el medio), capas 1–3 km y 3–6 km del hodógrafo, series GOES (temperatura mínima del tope, área fría). El frío es también el tramo de topes fríos del infrarrojo realzado.

### Neutral
- **Niebla** (niebla): fondo de la página principal, de la cabecera y de la barra lateral.
- **Papel** (superficie): paneles de gráficos, tablas, expansores, ficha y tarjeta de paso; fondo del área de trazado.
- **Papel gastado** (superficie-2): grilla de gráficos, separador interno de filas de la ficha, píldora "bajo", fondo secundario de widgets.
- **Filete** (filete): borde de 1 px de todo panel, ejes y encabezado de la ficha.
- **Tinta** (tinta): texto, costa en los mapas, temperatura del Skew-T, capa 0–1 km del hodógrafo.
- **Tinta media** (tinta-2): entradilla (lede) y viento medio del hodógrafo.
- **Apagado** (apagado): notas, captions, encabezados de tabla, referencias de índices sin umbral calibrado, horas de la regla.

### Named Rules
**La regla del rojo ganado.** El rojo solo aparece por un evento del catálogo o por un umbral chileno calibrado (su línea o un valor que lo cruza). Los índices sin umbral calibrado (SRH₀₋₁, SHERBS3, LCL, cizalle 0–6 km) no se pintan: llevan su referencia en texto apagado.

**La regla del acento que responde.** En la interfaz, el verde azulado marca solo lo elegido o accionable. En los gráficos puede ser el tono de la escala secuencial y del punto elegido, nunca un estado de alarma.

**La regla del infrarrojo sin rojo.** La escala IR realzada va de tinta (más frío, ≲ 200 K) por azules y blanco de nube a gris y suelo oscuro; no usa rojo, porque el rojo es de los eventos.

## Typography

**Display Font:** Fraunces (con serif)
**Body Font:** Source Sans 3 (con -apple-system, Segoe UI, sans-serif)
**Label/Mono Font:** JetBrains Mono (con ui-monospace, Menlo, monospace)

**Character:** Una serif de libro con personalidad para el nombre del caso, una sans humanista y sobria para leer y operar, y una mono de instrumento para lo que se midió.

### Hierarchy
- **Display** (Fraunces 600, tamaño del h1 de Streamlit, -0,01em): solo el título de cada página ("30 de mayo de 2019 · Biobío", "Mapas", "Sondeo", "Series").
- **Headline** (Source Sans 3 700, h2/h3 de Streamlit, sin tracking): subtítulos de sección ("Bitácora", "Entorno contra umbral chileno") y nombre del visor en la barra lateral. Fraunces no baja a este nivel.
- **Lede** (400, 1,08rem, 1,5, máx. 68ch, tinta-2): una frase bajo el título de página.
- **Body** (400, 1rem): texto de contexto y de expansores.
- **Nota** (400, 0,86rem, 1,45, máx. 75ch, apagado): advertencias y ayuda al lado del dato.
- **Label** (600, 0,78rem, apagado): encabezados de la ficha.
- **Datos** (JetBrains Mono, cifras tabulares): valores de la ficha, coordenadas, horas de la regla, etiquetas de hover en gráficos.

### Named Rules
**La regla de una sola serif.** Fraunces aparece una vez por página, en el h1.

**La regla del dato en mono.** Lo medido (valores, coordenadas, horas UTC) va en JetBrains Mono con cifras tabulares donde la plataforma lo permite; la prosa y las unidades no.

**La regla de la coma.** Separador decimal coma en ficha y gráficos (`separators=", "` en plotly; `_num` en la ficha), con 3 cifras significativas.

## Layout

Página ancha de Streamlit (`layout="wide"`) con barra lateral de niebla que lleva el estado compartido: región, día, hora UTC con la regla de tiempo debajo, evento, punto elegido y recorrido guiado. Navegación superior entre cuatro páginas (El caso, Mapas, Sondeo, Series).

Cada página: título Fraunces, lede, y luego pares de columnas. Mapas y gráficos lado a lado en dos columnas iguales (`gap="large"`; Mapas usa `"medium"`); bloque de texto o tablas en proporción 3:2. Nota bajo cada gráfico en apagado. Relleno superior del contenedor 2,2rem. En móvil las columnas se apilan (comportamiento de `st.columns`).

Los mapas conservan el aspecto real (escala y = 1/cos(latitud media)) y se encuadran por defecto en la zona de eventos con 2° de margen.

## Elevation & Depth

Sistema plano. La profundidad es tonal: niebla abajo, papel blanco con filete de 1 px encima. No hay sombras en paneles, tablas ni tarjetas; las leyendas de gráficos usan blanco al 80 % para no tapar datos.

**La regla de la hoja sobre la mesa.** Todo contenido de datos (gráfico, tabla, ficha, expansor) es una hoja blanca con filete sobre la niebla; el texto corrido va directo sobre la niebla, sin hoja.

## Shapes

Esquinas apenas suavizadas: 6 px en widgets (`baseRadius`) y paneles, 3 px en las píldoras de la ficha, 1 px en la marca de "ahora". Bordes de 1 px en filete; los widgets muestran borde (`showWidgetBorder`). Glifos de mapa: triángulo hacia arriba rojo con borde blanco para eventos, círculo abierto verde azulado de 22 px para el punto elegido.

## Components

### Buttons
- **Shape:** 6 px de radio (Streamlit `baseRadius`).
- **Primary:** fondo acento, texto blanco ("Empezar recorrido", "Siguiente"), ancho completo en la barra lateral, con icono Material.
- **Secondary:** papel con filete, texto tinta ("Anterior", "Empezar recorrido guiado" en El caso).
- **Tertiary:** solo texto con icono ("Salir del recorrido").

### Paneles de gráfico
- **Corner Style:** 6 px. **Background:** papel. **Border:** 1 px filete. **Internal Padding:** 6px 4px 2px.
- La plantilla `cuaderno`: título 15 px a la izquierda, grilla papel gastado, ejes en filete, sin ticks, hover en papel con filete y mono 12 px, colorbar de 12 px sin contorno.
- Limitación: el frontend de Streamlit ignora fondo y fuente de la plantilla, por eso `graficos._estilo` los fija en el layout de cada figura.

### Ficha "entorno contra umbral chileno"
La firma de los datos. Tabla HTML en papel con filete y radio 6 px: índice (con unidad en nota), valor en el punto y extremo de la zona en mono alineado a la derecha, umbral ("> 0,1") en mono o referencia en sans apagada de 0,8rem, y una píldora "supera" (óxido lavado) o "bajo" (papel gastado) solo en filas con umbral calibrado. El valor que supera pasa a severo, 600.

### Bitácora
`st.dataframe` en papel con filete, filas seleccionables que llevan hora y punto a todas las páginas. Limitación: `st.dataframe` no permite fuente por columna, así que la hora UTC sale en sans.

### Regla de tiempo
Componente firma compartido por todas las páginas, bajo el slider de hora en la barra lateral: pista de 18 px con línea base en filete, triángulos severos de 10×9 px por evento (title con hora y lugar), marca de "ahora" en acento (2×20 px) y extremos del día en mono 0,72rem apagado. HTML y CSS sin SVG, porque `st.html` sanea el SVG.

### Tarjeta de paso
Papel con filete, radio 6 px, relleno 10px 12px, 0,92rem. Primera línea con el contador y la hora UTC del paso en mono 600 acento de 0,8rem; debajo el texto del paso. Bajo la tarjeta, Anterior / Siguiente y Salir.

### Gráficos de dominio
- **Mapas:** costa en tinta 0,9 px; contorno del umbral chileno en severo 1,6 px; clic en una grilla invisible elige el punto.
- **Skew-T:** temperatura en tinta, punto de rocío en acento (2,4 px), parcela en apagado a rayas, isotermas en papel gastado.
- **Hodógrafo:** capas 0–1 km tinta, 1–3 km frío, 3–6 km cálido, 6–10 km apagado; Bunkers left-mover diamante relleno en acento, right-mover diamante abierto apagado.
- **Series:** umbral chileno en severo a rayas con anotación; eventos como líneas severas verticales (sólida 2 px el propio, punteada 1 px los demás); hora actual en acento 1 px.

## Do's and Don'ts

### Do:
- **Do** poner todo dato sobre una hoja blanca con filete #C9D3D6 y radio 6 px encima de la niebla #E4E9EB.
- **Do** reservar el rojo #D2492A para eventos del catálogo y umbrales chilenos calibrados; el resto de los índices lleva su referencia en texto apagado.
- **Do** usar el verde azulado #0E6A63 para lo elegido y lo accionable.
- **Do** escribir cifras con coma decimal y en JetBrains Mono tabular cuando la plataforma lo permita.
- **Do** usar frío #4C7FB8 y cálido #C98A3C para escalas divergentes centradas en cero.
- **Do** fijar fondo y fuente en el layout de cada figura plotly (`graficos._estilo`).

### Don't:
- **Don't** usar Fraunces fuera del h1 de página.
- **Don't** meter rojo en escalas de color (el IR realzado y la divergente no lo llevan).
- **Don't** pintar en rojo un índice sin umbral chileno calibrado ni usar umbrales norteamericanos.
- **Don't** añadir sombras: la profundidad es tonal.
