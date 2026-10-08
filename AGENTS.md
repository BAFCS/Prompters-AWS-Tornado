# AGENTS.md

Guía para agentes de código (Claude Code, Codex, etc.) que trabajan en este repositorio.

## Qué es este repositorio

Proyecto abierto (AWS Hackathon) para predecir qué tormentas del centro-sur de Chile desarrollan
un mesociclón, usando el reanálisis ERA5 y las imágenes GOES. Hoy el repo es sobre todo
**documentación, tres scripts de figuras, scripts de descarga y procesamiento de datos y un visor
interactivo**. La documentación, los docstrings, los comentarios, los textos de la interfaz y los mensajes de commit
están en **español**; el código va en **inglés**: módulos, identificadores, claves de estado, flags de la
CLI, rutas de datos, variables y atributos NetCDF y clases CSS. Las URL visibles del visor (`url_path` de
las páginas y anclas de El proyecto) siguen en español porque son parte de la interfaz.

- `docs/mesociclones_chile.md` es el documento principal y la fuente de verdad del proyecto
  (física, datos, variables, planteamiento del modelo, arquitectura AWS, tareas abiertas en la sección 8).
- `docs/mesociclones_chile.pdf` se genera desde el `.md` con un conversor markdown→LaTeX que **no está
  en el repo**; no se puede regenerar desde aquí.

## Entorno y comandos

Python gestionado con **uv** (`pyproject.toml`, `uv.lock`, `.python-version`); no es un paquete
instalable (`tool.uv.package = false`). Lint y formato con **ruff** (reglas `E`, `W`, `F`, `I`, `B`,
`UP`, `SIM`, `C4`, `NPY`, `ANN`; se ignoran `E501` y `C408`). Tipos con **pyright** (modo `basic`,
solo `scripts/`, con `pandas-stubs`). Convención: se anotan parámetros y retornos de toda función o
método (lo exige `ANN`), no las variables; cada módulo y función lleva docstring en español. Toda dependencia nueva se declara con `uv add`, nunca con `pip`.

```bash
uv sync                              # crea .venv con dependencias + grupo dev
uv run python scripts/figures/figs_era5.py   # ejecutar un script
uv run streamlit run scripts/viewer/viewer.py  # visor interactivo ERA5 + GOES
uv run streamlit run scripts/viewer/viewer.py --server.runOnSave true  # recarga al guardar
uv run ruff check scripts            # lint (uv run ruff check --fix para autocorregir)
uv run ruff format scripts           # formato
uv run pyright                       # chequeo de tipos
uv run python -m unittest discover -s tests -v  # regresiones de fichas, catálogo y acceso sin datos
uv add <pkg> / uv add --dev <pkg>    # añadir dependencias
```

Claude Code (`.claude/settings.json`) y Codex (`.codex/hooks.json`) corren `.agents/hooks/ruff.sh` tras
cada edición: aplica `ruff check --fix` y `ruff format` al `.py` editado y devuelve al agente lo que
ruff no corrige solo. En Codex, el hook se aprueba una vez con `/hooks`. La skill `viewer`
(`.agents/skills/viewer/`, enlazada desde `.claude/skills/`) explica cómo revisar el visor en el
navegador con Playwright MCP.

Las pruebas de regresión del visor viven en `tests/` y usan `unittest` y AppTest de Streamlit.
`ruff check`, `ruff format --check` y `pyright` pasan limpios: mantenerlo así.
Para validar un cambio en un script de figuras, regenerar la figura y compararla con la versión
anterior (las figuras son deterministas: mismo entorno y datos dan los mismos píxeles).

## Scripts de figuras

Viven en `scripts/figures/`. Estructura de `scripts/`: `figures/` (figuras), `pipeline/` (descarga y
procesamiento), `viewer/` (visor y `viewer_app/`) y `common.py` (compartido). `PRODUCT.md`,
`DESIGN.md` y `.impeccable/` siguen en la raíz porque Impeccable los busca ahí (no tiene opción para moverlos).

Cada script es un programa lineal sin funciones `main` ni argumentos: carga datos, dibuja y guarda
en `figs/`. Los accesos a HDF5 pasan por `common.dataset()`, que acota el tipo a `h5py.Dataset`
(`figs_era5.py` y `figs_goes.py` importan `common`, como los scripts de datos). Las rutas son relativas a la raíz del repo (`ROOT`, `OUT = figs/`, `DATA = data/`).
Comparten una paleta y `rcParams` copiados en cada archivo (`ACC`, `SEV`, `COLD`, `WARM`, `MUT`,
`INK`, `LINE`), que coinciden con la paleta de `scripts/viewer/viewer_app/theme.py` (salvo `MUT`: el visor usa
un apagado más oscuro porque va sobre fondo niebla).

| Script | Figura | Entrada |
|---|---|---|
| `figs_catalog.py` | fig1, fig2 | `data/tornados_chile.xlsx` (figshare, hoja `Final_Table`) y `data/coast.zip` (shapefile de costa; Natural Earth 10m reproduce la figura) |
| `figs_era5.py` | fig4 | lee directo de `s3://nsf-ncar-era5/` (anónimo, s3fs + h5py) |
| `figs_goes.py` | fig3 | `data/goes/*.nc`: archivos GOES-16 `ABI-L2-CMIPF` banda 13 del 30-may-2019 (día 150) ~21:30–21:50 UTC |

## Scripts de datos y visor

A diferencia de los de figuras, son programas de línea de comandos con `main()` y `argparse`
(`--help` muestra las opciones). Viven en `scripts/pipeline/`; comparten `scripts/common.py`, que importan como módulo
(`import common`, declarado *first-party* para isort; cada punto de entrada añade `scripts/` a `sys.path`): regiones (`REGIONS`, `--region`, `--bbox`),
fechas (`--start`, `--end`), rutas, acceso S3 anónimo y la proyección del ABI (`latlon_abi`).
Escriben NetCDF comprimido (gzip + shuffle) en `data/crops/<region>/`, saltan lo que ya existe
(`--force` lo rehace) y reparten las lecturas en procesos con contexto `spawn` (s3fs no tolera
`fork`). Ambas descargas leen el índice de bloques del HDF5 y piden a S3 solo los bytes necesarios.

| Script | Hace | Salida |
|---|---|---|
| `download_era5.py` | ERA5 niveles de presión y superficie, recortado; un archivo por día | `era5_pl/era5_pl_AAAAMMDD.nc`, `era5_sfc/era5_sfc_AAAAMMDD.nc` |
| `download_goes.py` | GOES `ABI-L2-MCMIPF` (16 bandas, 2 km), recortado en la grilla fija; un archivo por hora | `goes/AAAAMMDD/goes_AAAAMMDDHH.nc` |
| `process_goes.py` | Reproyecta GOES a lat/lon regular (vecino más cercano, sin alterar valores) | `goes_latlon/AAAAMMDD/goes_AAAAMMDDHH.nc` |
| `process_era5.py` | Índices australes por columna (cizalladura, Bunkers *left-mover*, SRH, VGP₀₋₁, STP LM sin CIN, SHERBS3, LCL), vectorizados con las fórmulas de MetPy | `era5_indices/era5_idx_AAAAMMDD.nc` |
| `viewer.py` | App Streamlit de varias páginas (`st.navigation`); el código de las páginas vive en `scripts/viewer/viewer_app/` | — |

```bash
uv run python scripts/pipeline/download_era5.py --start 2019-05-30          # región south-central-austral
uv run python scripts/pipeline/download_goes.py --start 2019-05-30
uv run python scripts/pipeline/process_goes.py  --start 2019-05-30
uv run python scripts/pipeline/process_era5.py  --start 2019-05-30          # tras download_era5.py
uv run streamlit run scripts/viewer/viewer.py
```

**Visor** (`scripts/viewer/viewer.py` + paquete `scripts/viewer/viewer_app/`, importado como *first-party* igual que
`common`): páginas El proyecto, Datos, El caso, Mapas, Sondeo y Series. El proyecto (`viewer_app/p_project.py`,
diagramas en `viewer_app/diagrams.py`) presenta el proyecto con elementos de Streamlit: es la
página por defecto y se muestra aunque no haya datos. Datos (`viewer_app/p_data.py`) es el catálogo
de datos: una ficha por variable de docs §4–5 (qué es, por qué importa, fórmula, criterio chileno,
cuidado, insumos y fuentes), también sin datos; `?v=<clave>` muestra una sola ficha. Las fichas, la
bibliografía y el buscador viven en `viewer_app/variables.py`, que es además la fuente de la ayuda
«Qué estás viendo» de Mapas: todo producto nuevo de `products.py` necesita su ficha
(`tests/test_variables.py` lo comprueba). La barra lateral (región, día, regla de tiempo,
evento, recorrido guiado) vive en `viewer.py` para que sus widgets sobrevivan al cambio de página; el
estado compartido está en `viewer_app/state.py` (`restore`/`save` copian los widgets de cada
página bajo `_<key>`). La página Mapas es una grilla de 1 a 6 paneles en una sola figura plotly con ejes compartidos (el zoom va
sincronizado); `theme.map_columns()` mide el ancho real del cuerpo (1 a 3 columnas); con una sola, los controles van en un desplegable. Cada panel muestra un producto de `viewer_app/products.py` (claves `idx:`, `sfc:`, `pl:`,
`goes:`, `rgb:`), calculado por `viewer_app/layers.py` (incluye el RGB Airmass); la lista de paneles vive en
`st.session_state["panels"]` (`state.Panel`), no en widgets, y el recorrido guiado la fija con `Step.panels`. Los textos, umbrales y el recorrido guiado salen de `docs/` y están en
`viewer_app/texts.py` y `viewer_app/variables.py`: si cambia el documento o un cálculo, hay que
actualizarlos. El tema (claro y oscuro) está en
`.streamlit/config.toml` (`[theme.light]`, `[theme.dark]`) y `viewer_app/theme.py` (`LIGHT`, `DARK`;
`theme.colors()` da la paleta del modo activo): si cambia un color, hay que cambiarlo en los dos
(`tests/test_colorscales.py` comprueba que coinciden y que los textos cumplen WCAG AA).
Streamlit no vuelve a ejecutar la app al cambiar de tema, así que el CSS usa variables de las dos
paletas y un script (`theme._WATCHER`) marca `<html data-theme>` y pulsa un botón oculto para redibujar
plotly; también lo pulsa si Python dibujó con otro modo que el del navegador (pasa en la primera carga). El botón de la barra (`theme.mode_button`) alterna el modo eligiendo la opción del menú ⋮ de Streamlit (por eso `client.toolbarMode = "viewer"`). Las escalas de color de los mapas son estándar y viven en `viewer_app/colorscales.py`, por tipo de
dato (`products.Product.kind`); cada panel guarda la suya en `Panel.colorscale`. Las columnas de las
páginas se piden con `theme.columns(spec, key)`, no con `st.columns`: se apilan cuando cada una
quedaría con menos de 26rem, así que funcionan en tablet con la barra abierta. La excepción es la
fila de controles de Mapas, que va alineada con los paneles de la figura. `PRODUCT.md` y
`.impeccable/` guardan el contexto de diseño del visor.

GOES se guarda con su codificación original (`int16` con `scale_factor`/`add_offset`), así que no
pierde precisión. Ninguno corrige paralaje todavía.

## Datos

`data/` y los formatos de datos (`*.nc`, `*.xlsx`, `*.zarr`, ...) están en `.gitignore`: los datos se
descargan, nunca se versionan. El catálogo, la costa y las imágenes de `figs_goes.py` se bajan a mano:

```bash
mkdir -p data/goes
curl -L -o data/tornados_chile.xlsx https://ndownloader.figshare.com/files/56272544
curl -L -o data/coast.zip https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip
aws s3 cp --no-sign-request --recursive s3://noaa-goes16/ABI-L2-CMIPF/2019/150/21/ data/goes/ \
  --exclude '*' --include '*M6C13*s201915021[345]*'
```

## Trampas del dominio (ver `docs/` para el detalle)

- **Hemisferio sur**: la SRH tornádica es negativa y las supercélulas favorecidas son *left-movers*.
  MetPy/SHARPpy usados tal cual dan índices con el signo cambiado.
- **Régimen HSLC**: los umbrales norteamericanos (STP ≥ 1, etc.) no sirven; los calibrados para Chile
  son `VGP₀₋₁ > 0,1 m/s²`, `SHERBE ≥ 1`, `STP` (rama *left-mover*) `≤ −0,3`.
- **ERA5**: usar `s3://nsf-ncar-era5/` (`s3://era5-pds/` está deprecado y no tiene niveles de presión).
  Cada archivo de nivel de presión pesa ~1,4 GB (una variable, un día, el globo) y no admite recorte
  en el servidor: cada hora es un bloque global de ~50–65 MB que hay que transferir entero y recortar
  en memoria (`download_era5.py`). En superficie los bloques son pequeños y sí se lee solo el recuadro. Sobre los Andes
  el nivel de 1000 hPa está bajo tierra: enmascarar por presión de superficie o usar viento a 10 m.
- **GOES**: Chile lo ve GOES-East (`noaa-goes16` dic 2017–abr 2025, `noaa-goes19` desde abr 2025,
  us-east-1). `figs_goes.py` implementa a mano la proyección directa del ABI; la inversa es `common.latlon`. El paralaje
  desplaza los topes nubosos ~21 km a 53°S (tope de 12 km).
- **Catálogo**: 102 eventos, solo positivos (sin negativos). Columnas clave: `Register` (confianza de
  la etiqueta), `Tornado`/`Waterspout` (dos vías físicas), `Hour (UTC)` (cruce con GOES).
