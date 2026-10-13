# AGENTS.md

Guía para agentes de código (Claude Code, Codex, etc.) que trabajan en este repositorio.

## Qué es este repositorio

Proyecto abierto de la hackathon [Breaking Barriers](https://www.taurusmkt.com/breakingbarrierschile)
para predecir qué tormentas del centro-sur de Chile desarrollan un mesociclón, con el reanálisis ERA5
y las imágenes del satélite GOES. Trae scripts para bajar y procesar los datos, figuras, un visor
Streamlit y el documento del proyecto.

`docs/mesociclones_chile.md` es la fuente de verdad: física, datos, variables, planteamiento del
modelo, arquitectura en AWS y tareas abiertas (sección 8). Antes de proponer un índice, una etiqueta o
un modelo, revisar lo que dice ahí.

## Convenciones

- **Idioma.** Documentación, docstrings, comentarios, textos de interfaz y mensajes de commit en
  español. Código en inglés: módulos, identificadores, flags de la CLI, rutas de datos, variables y
  atributos NetCDF.
- **Estilo.** ruff (reglas `E`, `W`, `F`, `I`, `B`, `UP`, `SIM`, `C4`, `NPY`, `ANN`; se ignoran `E501`
  y `C408`) y pyright en modo `basic`. Se anotan parámetros y retornos de toda función, no las
  variables. Cada módulo y función lleva docstring.
- **Dependencias.** Python con **uv**; toda dependencia nueva va con `uv add` (o `uv add --dev`),
  nunca con `pip`. El repo no es un paquete instalable.
- **Datos.** `data/` y los formatos de datos (`*.nc`, `*.xlsx`, `*.parquet`, `*.zarr`, ...) están en
  `.gitignore`: se descargan o se generan, nunca se versionan. Tampoco credenciales (`.env`, `.aws/`).

## Comandos

```bash
uv sync        # entorno con dependencias y herramientas de desarrollo
make check     # ruff, formato, pyright y pruebas: tiene que pasar antes de abrir una PR
make fix       # corrige lo que ruff sabe corregir y formatea
make data      # catálogo, costa y GOES de las figuras (salta lo que ya existe)
make viewer    # visor en local, recarga al guardar
```

Sin `make` (Windows), los comandos equivalentes están en el `Makefile` y funcionan tal cual.
Claude Code y Codex corren `.agents/hooks/ruff.sh` tras cada edición de un `.py`: formatea y
devuelve al agente lo que ruff no corrige solo (en Codex se aprueba una vez con `/hooks`).

## Mapa del repositorio

| Ruta | Qué hay |
|---|---|
| `scripts/common.py` | Lo compartido: regiones (`REGIONS`, `--region`, `--bbox`), fechas, rutas, acceso anónimo a S3 y la proyección del ABI. Se importa como `import common`. |
| `scripts/pipeline/` | Bajan ERA5 y GOES recortados y calculan índices. Escriben en `data/crops/<region>/`. |
| `scripts/figures/` | Las figuras de `figs/` que usa el documento. |
| `scripts/viewer/` | El visor Streamlit (`viewer.py` y el paquete `viewer_app/`). |
| `tests/` | Pruebas con `unittest` (y AppTest de Streamlit para el visor). |
| `docs/` | El documento del proyecto. |

## Agregar trabajo nuevo

- **Un script de línea de comandos** (descargar, procesar, armar una tabla, entrenar) sigue el patrón
  de `scripts/pipeline/`: `main()` con `argparse`, opciones `--start`, `--end`, `--region` y `--force`
  de `common`, salida en `data/...`, y salta lo que ya existe. Si lee S3 en paralelo, procesos con
  contexto `spawn` (s3fs no tolera `fork`). Va en una carpeta de `scripts/` según su área (por
  ejemplo `scripts/model/`), que agrega `scripts/` a `sys.path` para importar `common`.
- **Exploración en cuadernos**: en `notebooks/`, con `uv add --dev jupyterlab` si hace falta. Lo que
  se vuelva reutilizable pasa a un script.
- **Pruebas**: lo que tenga lógica propia (un índice, una etiqueta, un recorte) deja una prueba en
  `tests/` que no necesite datos descargados.
- **Si cambia el documento o un cálculo**, revisar los textos del visor que lo citan
  (`viewer_app/texts.py` y `viewer_app/variables.py`).

## Visor

Lo que no hay que romper al tocarlo (el detalle está en los docstrings de `viewer.py`,
`viewer_app/layout.py` y `viewer_app/theme.py`):

- Cada producto de `viewer_app/products.py` necesita su ficha en `viewer_app/variables.py`, y cada
  referencia, su lugar en `viewer_app/p_references.py` (las pruebas lo comprueban).
- Los colores viven en `.streamlit/config.toml` y en `viewer_app/theme.py`: se cambian en los dos.
- Las columnas se piden con `theme.columns`, no con `st.columns`, para que se apilen en tablet.
- Problema, Datos, Starter kit y Referencias se muestran sin datos (`NO_DATA_PAGES` en `viewer.py`).
  El criterio de éxito, las decisiones abiertas y las tareas se escriben una vez en `p_project.py` y
  se muestran también en Starter kit.

## Despliegue

`Dockerfile` y `compose.yaml` arman el visor con los scripts; `data/` va montado como volumen. En
AWS el despliegue es a mano: la página Starter kit del visor explica cómo preparar una EC2 en
us-west-2 y abrir el visor por un túnel de Session Manager.

## Trampas del dominio (detalle en `docs/`)

- **Hemisferio sur**: la SRH tornádica es negativa y las supercélulas favorecidas son *left-movers*.
  MetPy/SHARPpy usados tal cual dan índices con el signo cambiado.
- **Régimen HSLC**: los umbrales norteamericanos (STP ≥ 1, etc.) no sirven; los calibrados para Chile
  son `VGP₀₋₁ > 0,1 m/s²`, `SHERBE ≥ 1`, `STP` (rama *left-mover*) `≤ −0,3`.
- **ERA5**: usar `s3://nsf-ncar-era5/` (`s3://era5-pds/` está deprecado y no tiene niveles de presión).
  Cada archivo de nivel de presión pesa ~1,4 GB (una variable, un día, el globo) y no admite recorte
  en el servidor: cada hora es un bloque global de ~50–65 MB que se transfiere entero y se recorta en
  memoria. Sobre los Andes el nivel de 1000 hPa está bajo tierra: enmascarar por presión de
  superficie o usar viento a 10 m.
- **GOES**: Chile lo ve GOES-East (`noaa-goes16` dic 2017–abr 2025, `noaa-goes19` desde abr 2025,
  us-east-1). GOES se guarda con su codificación original (`int16` con `scale_factor`/`add_offset`).
  Nada corrige paralaje todavía: desplaza los topes ~21 km a 53°S (tope de 12 km).
- **Catálogo**: 102 eventos, solo positivos (sin negativos). Columnas clave: `Register` (confianza de
  la etiqueta), `Tornado`/`Waterspout` (dos vías físicas), `Hour (UTC)` (cruce con GOES). Que un día
  no tenga registro no prueba que no hubo tornado.
