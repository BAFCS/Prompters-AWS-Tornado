# Resolución de Impeccable audit y critique

Fecha: 7 de octubre de 2026. Worktree `.worktrees/impeccable-audit`, rama `impeccable-audit`, desde `origin/main` (`79dbf04`). Alcance: El proyecto, El caso, Mapas, Sondeo y Series, las cinco páginas de esa base. Se aplicaron todas las prioridades de ambos informes y las observaciones menores de la interfaz, sin dependencias nuevas.

## Resultados

| ID | Prioridad original | Problema | Resolución comprobada |
|---|---|---|---|
| A1 | P1 | Botones de panel con nombres de iconos | Texto visible con función y número: Anterior, Siguiente, Opciones y Quitar. |
| A2 | P1 | Punto arbitrario dependiente del ratón | «Elegir punto» con latitud/longitud, límites regionales y validación geográfica compartida; envío con Enter. |
| A3 | P1 | Cuatro imágenes con `alt="0"` | Descripciones de contenido y etapa elegida en imágenes nativas, conservando pantalla completa. |
| A4 | P1 | Seis mapas en tres columnas en teléfono | Una a tres columnas según ancho real; eje útil móvil de 56,58 a 207 px, con ejes compartidos. |
| A5 | P2 | Saltos H1→H3 | Primeras secciones en H2, subsecciones en H3. |
| A6 | P2 | Objetivos táctiles pequeños | Botones de altura mínima de 44 px; barra Plotly de 44 × 44 px en móvil/táctil y margen para no tapar títulos. |
| A7 | P2 | Prosa de portada demasiado ancha | Párrafos, notas y prosa de tarjetas hasta 68ch, conservando contenido científico. |
| C1 | P1 | Acceso a selección y controles | A1–A3; también nombres para abrir/cerrar la barra lateral. |
| C2 | P1 | Comparación móvil ilegible | A4/A6; seis paneles comprobados en ambos temas a 1440, 1024 y 390 px. |
| C3 | P2 | Entrada orientada primero al documento | «Explorar el caso de mayo de 2019» antes del bloque documental. |
| C4 | P2 | Orientación tardía y controles antes del dato | Guía de Sondeo antes de los gráficos; «Ajustes de mapas» agrupados en expansor. |
| C5 | P2 | Once favoritos sin propósito agrupado | Cuatro grupos: rotación, viento/perfil, enfriamiento y composición; búsqueda completa conservada. |

Los ID siguen [audit](impeccable-audit.md) y [critique](impeccable-critique.md); algunas filas corresponden al mismo defecto. Los informes iniciales y las críticas independientes A/B se mantienen como referencia. Las puntuaciones iniciales no se presentan como puntuaciones posteriores a los cambios.

## Observaciones menores resueltas

- Región en español y conversión de K a °C junto al mapa GOES.
- Selección por teclado mencionada en los estados sin punto de Sondeo y Series.
- Encabezado explícito para extremo del área y columna evaluada en El caso.
- Salir del recorrido restaura paneles, punto y hora anteriores. Punto introducido con teclado y restaurado en navegador; regresión automatizada de los tres valores.
- Cierre del último paso y enlace a cómo participar; recorrido completo comprobado en navegador.
- Rótulos de comparación y evento de Series a 12 px; evento separado del título y la leyenda.

`DESIGN.md` refleja los cambios implementados. El snapshot de critique quedó cerrado por el cambio de huella de `scripts/viewer.py`, conservando la historia.

## Validación

| Comprobación | Resultado |
|---|---|
| `uv run ruff check scripts tests` | Pasa |
| `uv run ruff format --check scripts tests` | 30 archivos con formato correcto |
| `uv run pyright` | 0 errores, 0 advertencias |
| `uv run python -m unittest discover -s tests -v` | 23 pruebas pasan |
| `git diff --check` | Pasa |
| Chromium | Cinco páginas × dos temas × tres tamaños; sin desbordamiento global ni excepciones de Streamlit en los estados recogidos |
| Seis mapas | Seis ejes en ambos temas; una columna en móvil/tablet, dos a 1440 px con barra abierta |
| Interacción | Coordenadas con Enter, selección compartida, entrada/salida y seis pasos del recorrido; botón de cambio de tema |
| Revisión independiente del diff | Sin defectos concretos nuevos encontrados |

Tres regresiones nuevas cubren disposición de seis mapas con ejes compartidos, rechazo de coordenadas inválidas sin perder el punto anterior y restauración del recorrido. La suite existente cubre acceso sin datos y contraste de tokens en ambos temas.

[Evidencia estructurada final](impeccable-resolucion-evidencia.json): 30 estados, con mediciones de Mapas recogidas después de terminar su renderizado. Las 30 capturas están en `.playwright-mcp/verified-*.png`, ignoradas por Git según la skill viewer. Datos reales enlazados desde el workspace, sin versionarlos.

## Límites

Caso histórico y Chromium; sin certificación con lector de pantalla ni benchmark de red lenta. La consola final no mostró errores. La navegación directa inicial produjo respuestas 404 de recursos internos bajo `/mapas/_stcore/`, sin excepción de JavaScript ni fallo de aplicación.

Las descripciones de imágenes y nombres de controles del framework se aplican mediante el vigía existente: la API instalada no expone esos atributos para las imágenes nativas. Un cambio del DOM de Streamlit exige volver a comprobarlos. La deriva de metadatos de Impeccable del informe inicial permanece como observación de configuración, fuera de los defectos de interfaz; gobiernan `PRODUCT.md`, `DESIGN.md` y las paletas implementadas.
