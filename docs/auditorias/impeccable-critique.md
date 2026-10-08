Method: dual-agent (A: /root/critique_design · B: /root/critique_evidence)

# Impeccable critique — toda la app

Fecha: 2026-10-07. Objetivo estable: `scripts/viewer/viewer.py` y `scripts/viewer/viewer_app/`. Base: `origin/main`, `79dbf04`. Visitante: Operate, con portada Read. Evaluación A terminada antes de incorporar evidencia B; acceso al perfil Playwright serializado, evaluaciones independientes.



## Veredicto de especificidad

El visor expresa su propio dominio: reconstrucción de eventos chilenos, satélite y reanálisis al mismo tiempo y lugar, convenciones australes y límites científicos explícitos. La libreta con filetes, IBM Plex y colores con función sirve a la tarea. El mayor margen de mejora está en acceso y orden de lectura, no en sustituir su identidad.

## Salud del diseño

Se conserva la puntuación de la evaluación A independiente. Todas las heurísticas aplican.

| Heurística | Puntos / 4 | Hallazgo principal |
|---|---:|---|
| Visibilidad del estado | 3 | Contexto global oculto en móvil. |
| Correspondencia con mundo real | 3 | Siglas requieren ayuda contextual. |
| Control y libertad | 3 | El recorrido reemplaza paneles elegidos. |
| Consistencia | 3 | Ayudas y escalas cambian de posición. |
| Prevención de errores | 3 | Comparación con extremo del área exige leer nota. |
| Reconocimiento frente a recuerdo | 2 | Iconos y explicación posterior a instrumentos. |
| Flexibilidad y eficiencia | 3 | Paneles, zoom compartido, selección global y CSV. |
| Estética y minimalismo | 2 | Texto y decisiones retrasan el dato móvil. |
| Recuperación de errores | 3 | Recuperación depende de controles globales. |
| Ayuda y documentación | 3 | Ayuda rica, entrada operativa corta ausente. |
| **Total** | **28/40** | **Bueno** |

## Lo que funciona

1. Honestidad científica: diferencia entorno, nube y tornado reportado; cumplir criterios no confirma un tornado.
2. Contexto compartido: hora, evento y punto sobreviven a navegar; comparación sincronizada y CSV ayudan al investigador.
3. Identidad coherente: paletas claras/oscuras, escalas científicas y columnas que se apilan donde corresponde.

## Prioridades de diseño

| ID | Prioridad | Problema y ubicación | Impacto | Cambio recomendado | Comando |
|---|---|---|---|---|---|
| C1 | P1 | Punto arbitrario solo por clic y nombres vacíos de controles; `p_maps.py:68`, `:75`, `:104`, `:277`; `charts.py:184`. | Sam puede explorar eventos, pero no cualquier celda con teclado; acciones de iconos ambiguas y cuatro imágenes con alt="0". | Nombres explícitos, alternativa de coordenadas que use el estado compartido y descripción específica de figuras. | `$impeccable harden` |
| C2 | P1 | La figura conserva 2–3 columnas al estrecharse; `charts.py:85`. | Con seis paneles, figura de 348 px y ejes X de 56,58 px: títulos superpuestos y comparación ilegible. | Una columna o alternar paneles manteniendo mismo encuadre. | `$impeccable adapt` |
| C3 | P2 | Portada larga y acción documental, sin acción del cuerpo para explorar el caso; `p_project.py:36`. | Jordan puede salir al documento sin descubrir el instrumento. | Acción corta de explorar el caso junto al objetivo; limitar ancho de prosa y conservar material científico. | `$impeccable onboard` |
| C4 | P2 | Ayuda de Sondeo después de dos gráficos y tabla; controles de Mapas antes del dato; `p_sounding.py:90`, `:120`; `p_maps.py:205`, `:309`. | Interpretación exige recorrer muchos elementos antes de recibir orientación. | Pregunta breve de lectura junto al gráfico y ajustes secundarios agrupados. | `$impeccable layout` |
| C5 | P2 | Once favoritos en una sola botonera; `p_maps.py:43`, `products.py:28`. | Primera comparación exige escanear índices y bandas sin propósito recomendado. | Agrupar por tarea y ofrecer tres o cuatro comparaciones iniciales; conservar buscador completo. | `$impeccable distill` |

No se detectó P0 en las tareas revisadas. C1 integra dos problemas relacionados de acceso; el audit los cuenta por separado para su seguimiento técnico.

## Carga cognitiva y viaje emocional

Tres fallos claros de siete criterios: chunking, una decisión a la vez y opciones mínimas. Agrupación y jerarquía pasan; contexto compartido reduce memoria y existe revelación progresiva. Carga moderada, alta localmente en Mapas para principiantes. Cinco destinos principales resultan razonables para la tarea; no se recomienda eliminarlos por un límite numérico.

La entrada gana confianza por el caso chileno y sus límites. El primer valle aparece al decidir entre siglas sin una comparación sugerida. El pico es conectar el mismo evento con nube, perfil y evolución. La ayuda tardía y los avisos extensos rebajan ese pico en móvil. El CSV ofrece salida útil al investigador; el recorrido podría terminar enlazando una tarea de aporte ya documentada.

## Personas y observaciones menores

- **Alex:** paneles, exploración directa y CSV útiles; comparar en móvil y recuperar configuración anterior al recorrido requieren atención.
- **Jordan:** tarda en descubrir exploración desde la portada y en elegir entre once favoritos; ayuda de Sondeo llega tarde.
- **Sam:** eventos y tablas aportan alternativas textuales; faltan selección arbitraria por teclado, nombres claros y descripción específica de figuras.

Región muestra una clave técnica inglesa; instrucciones de zoom hablan de rueda del ratón en teléfono; K y °C exigen conversión aunque el texto la explica. La nota de extremo del área podría convertirse en encabezado explícito. Estos puntos no desplazan las prioridades anteriores.

## Preguntas para la siguiente decisión

1. Prioridad: accesibilidad de selección/control o comparación móvil.
2. Alcance: resolver primero P1 o incluir también entrada y orientación P2.

Los reportes A y B completos se conservan en `docs/auditorias/impeccable-critique-a.md` y `docs/auditorias/impeccable-critique-b.md`. La auditoría técnica y su evidencia se guardan aparte.

## Cruce de evaluaciones

A detectó por observación y lectura la selección por ratón, los nombres ambiguos, la secuencia tardía de ayuda y la distribución fija. B confirmó nombres accesibles literales de iconos, `alt="0"` en cuatro figuras y el caso extremo de seis mapas con 56,58 px de eje útil. Coinciden en acceso y móvil. B añadió el salto H1→H3 en tres páginas y prosa ancha en portada, registrados como A5/A7 en la auditoría. No se adoptan las falsas oclusiones de Plotly: sus rectángulos de interacción no prueban texto tapado.

El CLI devolvió `[]` sobre Python, sin cobertura fiable del markup generado. El detector en navegador produjo 101 alertas: 46 proyecto, 17 caso, 13 mapas, 11 sondeo y 14 series. **No son 101 defectos:** se descartaron avisos sobre elementos ocultos del framework, colores fijados por el brief y recortes que no mostraron pérdida de contenido. Los avisos de longitud/densidad son señales para evaluar lectura; no prueban incumplimiento. Las pruebas de tokens contrastan con el aviso bruto de contraste en elementos ocultos, sin demostrar que cualquier texto posible cumpla AA.

## Riesgos y límites del resultado

Datos reales de un caso y comprobaciones visuales acotadas; no lector de pantalla real ni benchmark de red lenta. Sondeo se apila bien en tablet; el fallo móvil pertenece a la grilla interna de Mapas. La portada sin datos se comprobó con AppTest. Las cinco páginas de esta base fueron cubiertas; no se revisó la página Datos de otra rama porque no forma parte de `origin/main` evaluado.

Impeccable detectó deriva de contexto: sidecar `.impeccable/design.json` anterior a DESIGN.md y `buildPath` no declarado. Además el surface brief conserva una paleta antigua distinta del contrato de PRODUCT.md/DESIGN.md. Se registra la discrepancia sin repararla; la paleta implementada y fijada por el usuario gobierna esta revisión. Esta observación de herramientas no se cuenta como defecto visual de la app.

La navegación interna en oscuro quedó estable en Mapas, El caso, Sondeo y Series, con servidor/DOM dark y fondo Plotly `#1D3557`; regreso a claro en Series correcto. No se encontró fallo de sincronización de tema.
