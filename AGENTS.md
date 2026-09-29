# AGENTS.md

Guía para agentes de código (Claude Code, Codex, etc.) que trabajan en este repositorio.

## Qué es este repositorio

Proyecto abierto (AWS Hackathon) para predecir qué tormentas del centro-sur de Chile desarrollan
un mesociclón, usando el reanálisis ERA5 y las imágenes GOES. Hoy el repo es sobre todo
**documentación más tres scripts de figuras**; el plan es escribir nuevos scripts de análisis a
partir de ellos. Todo el contenido, los comentarios y los mensajes de commit están en **español**.

- `docs/mesociclones_chile.md` es el documento principal y la fuente de verdad del proyecto
  (física, datos, variables, planteamiento del modelo, arquitectura AWS, tareas abiertas en la sección 8).
- `docs/mesociclones_chile.pdf` se genera desde el `.md` con un conversor markdown→LaTeX que **no está
  en el repo**; no se puede regenerar desde aquí.
- `web/index.html` es un sitio autocontenido (SVG y CSS en línea). `web/artifact.html` es el mismo
  contenido sin `<html>/<head>`, derivado a mano de `index.html`: si se edita uno, hay que replicar el
  cambio en el otro. `web/figs/*.jpg` son versiones comprimidas de `figs/*.png`.

## Entorno y comandos

Python gestionado con **uv** (`pyproject.toml`, `uv.lock`, `.python-version`); no es un paquete
instalable (`tool.uv.package = false`). Lint y formato con **ruff** (reglas `E`, `W`, `F`, `I`, `B`,
`UP`, `SIM`, `C4`, `NPY`; se ignoran `E501` y `C408`). Tipos con **pyright** (modo `basic`, solo
`scripts/`, con `pandas-stubs`). Toda dependencia nueva se declara con `uv add`, nunca con `pip`.

```bash
uv sync                              # crea .venv con dependencias + grupo dev
uv run python scripts/figs_era5.py   # ejecutar un script
uv run ruff check scripts            # lint (uv run ruff check --fix para autocorregir)
uv run ruff format scripts           # formato
uv run pyright                       # chequeo de tipos
uv run jupyter lab                   # notebooks (jupyterlab + ipywidgets en el grupo dev)
uv add <pkg> / uv add --dev <pkg>    # añadir dependencias
```

No hay tests. `ruff check`, `ruff format --check` y `pyright` pasan limpios: mantenerlo así.
Para validar un cambio en un script de figuras, regenerar la figura y compararla con la versión
anterior (las figuras son deterministas: mismo entorno y datos dan los mismos píxeles).

## Scripts de figuras

Cada script es un programa lineal sin funciones `main` ni argumentos: carga datos, dibuja y guarda
en `figs/`. Los accesos a HDF5 pasan por un helper `dataset()` que acota el tipo a `h5py.Dataset`. Las rutas son relativas a la raíz del repo (`ROOT`, `OUT = figs/`, `DATA = data/`).
Comparten una paleta y `rcParams` copiados en cada archivo (`ACC`, `SEV`, `COLD`, `WARM`, `MUT`,
`INK`, `LINE`), que coinciden con las variables CSS de `web/index.html`.

| Script | Figura | Entrada |
|---|---|---|
| `figs_catalogo.py` | fig1, fig2 | `data/tornados_chile.xlsx` (figshare, hoja `Final_Table`) y `data/coast.zip` (shapefile de costa; Natural Earth 10m reproduce la figura) |
| `figs_era5.py` | fig4 | lee directo de `s3://nsf-ncar-era5/` (anónimo, s3fs + h5py); escribe `data/era5_cache.npy` |
| `figs_goes.py` | fig3 | `data/goes/*.nc`: archivos GOES-16 `ABI-L2-CMIPF` banda 13 del 30-may-2019 (día 150) ~21:30–21:50 UTC |

`data/` y los formatos de datos (`*.nc`, `*.xlsx`, `*.zarr`, ...) están en `.gitignore`: los datos se
descargan, nunca se versionan. No hay script de descarga; a mano:

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
  en el servidor: leer por rangos de bytes con `s3fs` + `h5py` como en `figs_era5.py`. Sobre los Andes
  el nivel de 1000 hPa está bajo tierra: enmascarar por presión de superficie o usar viento a 10 m.
- **GOES**: Chile lo ve GOES-East (`noaa-goes16` dic 2017–abr 2025, `noaa-goes19` desde abr 2025,
  us-east-1). `figs_goes.py` implementa la proyección geoestacionaria del ABI a mano. El paralaje
  desplaza los topes nubosos ~20 km a 53°S.
- **Catálogo**: 102 eventos, solo positivos (sin negativos). Columnas clave: `Register` (confianza de
  la etiqueta), `Tornado`/`Waterspout` (dos vías físicas), `Hour (UTC)` (cruce con GOES).
