# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Participantes de la hackathon** (AWS Breaking Barriers): perfil técnico, no necesariamente
  meteorólogos. Llegan al proyecto y en pocos minutos tienen que entender el problema (predecir qué
  tormentas del centro-sur de Chile desarrollan un mesociclón), qué datos hay y qué se ve en ellos.
- **Investigadores** (meteorología, ciencia de datos): exploran casos a fondo, comparan índices,
  sondeos y la evolución en satélite alrededor de cada evento.

## Product Purpose

Proyecto abierto para predecir tormentas mesociclónicas en Chile con el reanálisis ERA5 (el entorno)
y las imágenes GOES (la tormenta). El visor Streamlit es la puerta de entrada exploratoria: muestra
un caso real con sus datos crudos y sus índices derivados, explica qué significa cada cosa y deja
investigar libremente. Éxito: un participante sale sabiendo qué buscar y dónde aportar; un
investigador encuentra en segundos el sondeo, el índice o la imagen que necesita.

## Positioning

No hay radar meteorológico operativo en Chile: la única evidencia de las supercélulas viene de
reconstrucciones con satélite y reanálisis. El visor junta, para los mismos minutos y lugares, el
entorno ERA5 con índices calculados con el signo del hemisferio sur y los umbrales calibrados para
Chile, las imágenes GOES cada 10 minutos y los eventos del catálogo de tornados.

## Operating Context

- Herramienta local: `uv run streamlit run scripts/visor.py` sobre los recortes ya descargados en
  `data/recortes/<region>/` por los scripts de descarga y procesamiento. Sin despliegue público por
  ahora.
- Solo muestra días ya descargados. Caso de referencia: brote del 30–31 de mayo de 2019 (Biobío).
- Se usa en pantallas de escritorio, en sesiones de trabajo o en presentaciones de la hackathon.

## Capabilities and Constraints

- Datos: ERA5 (niveles de presión y superficie, horario, 0,25°), GOES-16 ABI L2 MCMIPF (16 bandas,
  2 km, cada 10 min), catálogo de 102 tornados/trombas (solo positivos, sin negativos).
- Trampas que el producto no puede ocultar: SRH tornádica negativa y supercélulas *left-mover* en el
  hemisferio sur; umbrales chilenos (VGP₀₋₁ > 0,1 m/s², SHERBE ≥ 1, STP *left-mover* ≤ −0,3);
  niveles bajos bajo tierra sobre los Andes; GOES sin corrección de paralaje.
- Todo el contenido en español.

## Brand Commitments

- Identidad visual del sitio del proyecto (`web/index.html`): tipografías Fraunces, Source Sans 3 y
  JetBrains Mono; paleta clara con `--ground #E4E9EB`, `--ink #0C1518`, acento verde azulado
  `#0E6A63`, severidad `#D2492A`, frío `#4C7FB8`, cálido `#C98A3C`. El visor usa el tema claro
  ("Cuaderno de campo"), elegido explícitamente.

## Evidence on Hand

- `docs/mesociclones_chile.md`: fuente de verdad (física, índices, umbrales, tareas abiertas).
- `data/tornados_chile.xlsx` (figshare): catálogo de eventos con hora UTC, EF, tipo y confianza.
- Recortes ERA5 y GOES del 30–31 de mayo de 2019 en `data/recortes/centro-sur-austral/`.
- No existe una etiqueta de "mesociclón" en el catálogo: no inventar confirmaciones de mesociclón;
  hablar de tornados reportados y de supercélulas reconstruidas por la literatura citada en docs/.

## Product Principles

1. Datos crudos primero, derivados después, y siempre se dice cuál es cuál.
2. El hemisferio sur es la regla: signos y umbrales australes por defecto, con la trampa explicada.
3. Explicar sin estorbar: la ayuda está al lado del dato, nunca bloquea la exploración.
4. Honestidad sobre los límites: ERA5 no resuelve un mesociclón; GOES tiene paralaje; el catálogo
   tiene sesgo de reporte.
