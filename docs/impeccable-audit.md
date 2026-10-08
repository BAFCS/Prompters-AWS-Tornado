# Impeccable audit — visor completo

Fecha: 2026-10-07. Base: `origin/main` (`79dbf04`). Alcance: El proyecto, El caso, Mapas, Sondeo y Series; componentes, estado, gráficos, capas y tema compartidos.

## Integridad de implementación

El sistema expresa un producto concreto: cuaderno de campo para reconstruir tormentas de Chile, con estado temporal compartido, rama left-mover, catálogo de eventos y criterios diferenciados de referencias. Los colores vienen de paletas comunes y se verifican contra la configuración de Streamlit. Veredicto: sistema coherente y específico del producto, con brechas de acceso y adaptación. El detector se incorporó después de terminar la evaluación A para evitar anclaje.

## Evidencia y límites

Ver `impeccable-audit-evidencia.md`. Datos reales del 30 de mayo de 2019, 20 pruebas OK, Ruff y Pyright limpios. Navegación de las cinco páginas a 1440×900, 1024×768 con barra lateral abierta y 390×844. La auditoría combina inspección estática y observación; no equivale a una certificación WCAG. No hay benchmark remoto ni prueba con NVDA/VoiceOver.

## Fortalezas verificadas

- Los contrastes de los pares definidos por la paleta y CSS pasan 4,5:1; elementos gráficos categóricos pasan 3:1 en las pruebas del repositorio. Predeterminadas de mapas aptas para daltonismo.
- El estado compartido conserva selecciones entre páginas. Recorrido guiado opcional, límites de paneles, escalas compatibles y fechas preparadas reducen errores.
- Lectura NetCDF diferida y caché de recursos versionada por mtime, caché de series, submuestreo configurable y límite de tres paneles GOES animados.
- Sin desbordamiento global en las quince combinaciones medidas. Sondeo se apila en tablet. La tabla usa desplazamiento local en teléfono.
- Mensajes de ausencia de datos, recuperación por selección de fecha y portada accesible sin recortes. Se distingue ausencia de reporte de ausencia de tornado.

## Comprobaciones que no generaron hallazgos

No hay evidencia de layout thrashing, animación automática bloqueante, uso excesivo de `will-change` ni nuevas dependencias de interfaz. GOES se anima solo a petición y tiene Pausa. No se atribuye incumplimiento por falta de `prefers-reduced-motion` a una animación de datos explícitamente solicitada. Los 404 iniciales del framework se registran sin tratarlos como fallo funcional.

## Salud técnica

| Dimensión | Puntos / 4 | Evidencia principal |
|---|---:|---|
| Accesibilidad | 2 | Contraste/controles nativos cuidados; selección espacial, nombres de acciones y alternativas de imágenes incompletos. |
| Rendimiento | 3 | Caché, lectura diferida y submuestreo; no se midió red lenta, P95 ni grandes sesiones. |
| Adaptación | 2 | Columnas y tablas se adaptan; figura multipanel no cambia distribución con ancho. |
| Tema | 4 | Paletas probadas y cambio real redibuja figuras en ambos temas. |
| Integridad de implementación | 3 | Sistema de dominio consistente; semántica de encabezados y algunos controles se desvía. |
| **Total** | **14/20** | **Bueno: corregir dimensiones débiles.** |

Puntuación de revisión acotada, no resultado de una certificación ni de un benchmark universal.

## Resumen ejecutivo

**7 problemas técnicos únicos: 0 P0, 4 P1, 3 P2, 0 P3.** Los tamaños táctiles se agrupan con la adaptación de controles para no multiplicar ruido por cada botón. La crítica agrupa los problemas de acceso en una prioridad de diseño y añade prioridades de orientación; sus conteos no se suman a estos.

## Hallazgos priorizados

| ID | Nivel | Problema / ubicación | Impacto y evidencia | Estándar | Recomendación / comando |
|---|---|---|---|---|---|
| A1 | P1 | Nombre accesible de botones de panel; `p_maps.py:68`, `:75`, `:104`. | Árbol accesible anuncia chevron_left, chevron_right, tune y close; no anuncia acción ni panel. DOM `aria-label` vacío. | WCAG 4.1.2, 2.4.6: nombre y propósito comprensibles. | Rótulos explícitos con panel y acción; conservar ayudas. `$impeccable harden`. |
| A2 | P1 | Selección de punto solo por clic; `p_maps.py:19`, `:277`; `charts.py:184`. | Investigar una celda fuera del catálogo exige apuntar a marcadores transparentes. Selector Evento cubre solo lugares catalogados. | WCAG 2.1.1: funcionalidad operable con teclado. | Alternativa de coordenadas que invoque `state.select_point`; comprobar teclado y foco. `$impeccable harden`. |
| A3 | P1 | Alternativas de figuras de portada; `p_project.py:90`, `:152`, `:203`. | Cuatro imágenes tienen `alt="0"`, un índice de Streamlit sin significado. Texto vecino contextualiza, pero la figura carece de descripción específica. | WCAG 1.1.1: equivalente textual de contenido informativo. | Asociar nombre y descripción que comuniquen relaciones/conclusión; mantener texto largo como alternativa. `$impeccable harden`. |
| A4 | P1 | Figura multipanel fija; `charts.py:85`, `:143`; `p_maps.py:238`. | A 390 px: figura 348 px, seis paneles, cada eje X 56,58 px y títulos de 13 px superpuestos. Comparación principal deja de ser legible. | Compromiso móvil de PRODUCT.md; no se declara fallo automático de WCAG 1.4.10 para una visualización bidimensional. | Una columna o alternancia por panel en ancho reducido, encuadre compartido. `$impeccable adapt`. |
| A5 | P2 | Encabezados saltan H1→H3 en proyecto/caso/sondeo. | Navegación estructural pierde niveles intermedios; confirmado por detector y DOM, no solo por nombre de función. | WCAG 1.3.1 como criterio de estructura; el salto aislado no demuestra por sí solo incumplimiento. | Elegir niveles según relación de secciones, sin alterar solo tamaño visual. `$impeccable harden`. |
| A6 | P2 | Botones táctiles compactos y barra de Plotly. | Paneles: 42×40 px; modos Plotly 24×22 px. Dificultan toque preciso en teléfono. | Objetivo de diseño 44×44 px; no confundir con mínimo WCAG 2.5.8 de 24 px y sus excepciones. | Ampliar controles propios y ofrecer acciones principales cómodas; comprobar separación antes de atribuir fallo AA al framework. `$impeccable adapt`. |
| A7 | P2 | Prosa demasiado ancha en portada; `theme.py:264`, `:269`. | Medidas de contenedor estiman 108 caracteres por línea y notas 121. El CSS permite 90ch y suprime el máximo en tarjetas; leer párrafos largos requiere más barrido visual. | Legibilidad editorial; no implica incumplimiento WCAG por sí sola. | Reducir ancho de prosa conservando figuras y tablas amplias. `$impeccable typeset`. |

## Detector y verificación de contexto

CLI archivado en `impeccable-detector-b.json`: `[]`. **No es evidencia de que la app esté limpia:** el detector está orientado a markup y no ofrece cobertura fiable de páginas Python Streamlit.

Escaneo en DOM real en cinco páginas: **101 alertas brutas** (46 proyecto, 17 caso, 13 mapas, 11 sondeo, 14 series). Son alertas de máquina, no 101 problemas verificados. Evidencia íntegra: `impeccable-browser-b.json` y `impeccable-critique-b.md`.

Confirmadas: jerarquía de encabezados y controles/alternativas revisadas por árbol accesible. La revisión humana agrega el bloqueo de selección espacial y el colapso de grilla móvil. Los avisos de contraste en elementos fuera de pantalla, recorte genérico de contenedores y paleta azul no justifican cambiar tokens o declarar problemas de marca. La paleta está fijada en PRODUCT.md y cubierta por pruebas; no se cambia por una heurística estética del detector.

## Patrones sistémicos

Los problemas de acceso concentran su origen en visualizaciones y controles propios encima de widgets nativos. La adaptación trabaja sobre columnas de Streamlit, pero no sobre subplots internos de Plotly. Esa diferencia explica por qué Sondeo se apila bien y Mapas de seis paneles sigue fallando. La semántica requiere revisarse junto al diseño visual, no inferirse de un aspecto legible.

## Acciones sugeridas

1. **P1 `$impeccable harden`**: nombres, coordenadas por teclado y alternativas de figuras (A1–A3); aprovechar la misma pasada para encabezados A5.
2. **P1 `$impeccable adapt`**: comparación multipanel legible y controles táctiles (A4, A6).
3. **P2 `$impeccable typeset`**: limitar ancho de prosa y notas de portada (A7).
4. **`$impeccable audit`**: repetir evaluación sobre flujos de teclado, móvil y ambos temas después de corregir.
5. **`$impeccable polish`**: pasada final de consistencia una vez resueltos los problemas funcionales.

No se aplicaron correcciones ni cambios de interfaz. Estos comandos pueden ejecutarse por separado o juntos, según el alcance que el usuario elija.
