---
version: 1
slug: "scripts-viewer-py"
primary_target: "scripts/viewer.py"
related_targets: []
---

# Visor ERA5 + GOES

Scope: app Streamlit `scripts/viewer.py` + `scripts/viewer_app/`. Visitor mode: **Operate** (exploración de datos), con una portada que también hace de **Read** breve.

Audiencia: participantes de la hackathon (entender el caso en minutos) e investigadores (explorar a fondo). Tarea: ver qué pasó, cuándo y dónde; comparar entorno ERA5 e índices australes con la tormenta en GOES; inspeccionar sondeo, hodógrafo y series alrededor de cada evento. Restricción: solo días descargados; todo en español.

## Direction contract

THESIS: un cuaderno de campo de un caso. Cada página cruza el entorno (ERA5) con la tormenta (GOES) a la misma hora y lugar, con el umbral chileno a la vista y la trampa austral explicada al lado del dato. Rechaza el dashboard genérico de mapas sueltos con colorbar y selectbox.

OWN-WORLD: fondo niebla #E4E9EB, superficies blancas con filete #C9D3D6, tinta #0C1518. Verde azulado #0E6A63 solo para selección, foco y acción. Rojo #D2492A reservado a eventos y a valores que superan un umbral chileno. IBM Plex Sans en títulos y texto; IBM Plex Mono para horas UTC, coordenadas y valores medidos. Mapas con costa en tinta fina y triángulos rojos de evento.

STORY: el visitante entiende que el 30-may-2019 hubo cinco tornados en cuatro horas en el Biobío, ve que el entorno superó los umbrales chilenos donde ocurrieron y cuándo se enfriaron los topes; luego elige un evento o un punto y baja al sondeo y a las series.

FIRST VIEWPORT (El caso): título IBM Plex Sans 600 con fecha y región, una frase de contexto. Debajo, a todo el ancho: mapa (60 %) con GOES C13 de la hora elegida y los eventos; a la derecha (40 %) la bitácora de eventos ordenada por hora UTC (hora mono, lugar, EF, tipo), cada fila lleva a ese momento. Bajo la bitácora, una ficha compacta "entorno vs umbral chileno" (VGP₀₋₁, SRH₀₋₁ LM, cizalle 0–1 km, STP LM) con el máximo regional de esa hora. Acción primaria: "Empezar recorrido" en la barra lateral.

Signature interaction: la regla de tiempo compartida. Un slider UTC común a todas las páginas con las horas de los eventos marcadas; elegir un evento fija hora y punto en todas las páginas a la vez.

FORM: estructura A (páginas con estado compartido vía st.navigation), elegida por el usuario en el brainstorming; sin concept-seed porque el usuario fijó la estructura.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
