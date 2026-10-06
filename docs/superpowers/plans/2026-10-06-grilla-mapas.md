# Grilla de mapas con zoom sincronizado — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el par fijo de mapas ERA5 | GOES de la página «Mapas» por una grilla de 1 a 6
paneles con el zoom sincronizado, en la que cada panel muestra cualquier producto (índice o campo
ERA5, banda o derivado GOES, RGB Airmass), con contornos ERA5 opcionales sobre los paneles GOES.

**Architecture:** Un catálogo único de productos (`productos.py`) da claves con prefijo de fuente;
`capas.py` convierte una clave y una hora en una `Capa` (matriz o RGB, con su escala); `graficos.grilla`
dibuja todas las capas en **una sola figura plotly** con `make_subplots` y ejes compartidos (así el zoom
y el desplazamiento quedan sincronizados). La lista de paneles vive en `st.session_state["paneles"]`
(fuente de verdad, sobrevive al cambio de página) y `p_mapas.py` la edita con callbacks.

**Tech Stack:** Python 3.13, Streamlit 1.64 (`st.pills`, `st.popover(disabled=)`,
`st.plotly_chart(config=, on_select=)`), plotly 6 (`make_subplots`, `go.Heatmap`, `go.Image`,
`go.Contour`), xarray, numpy. Sin dependencias nuevas.

**Spec:** las decisiones tomadas con Pablo en la conversación del 2026-10-06, copiadas en
«Decisiones» abajo. Contexto previo del visor: `docs/superpowers/specs/2026-10-02-visor-exploratorio-design.md`.

## Decisiones

- Grilla de paneles libres en lugar de «ERA5 a la izquierda, GOES a la derecha».
- **Zoom sincronizado**: una sola figura con subgráficos de ejes compartidos.
- La página arranca con **un panel RGB Airmass** a ancho completo (o el primer índice ERA5 si el día no
  tiene GOES). Se agregan paneles con «Agregar panel»; cada uno se quita con su ×.
- RGB elegido: **Airmass** (C08−C10, C12−C13, C08 invertido): solo infrarrojo, sirve de día y de noche.
- Disposición automática: 1 → 1×1, 2 → 1×2, 3–4 → 2×2, 5–6 → 2×3. Tope: **6 paneles**.
- **Contornos ERA5 opcionales por panel GOES/RGB**, con el umbral chileno en rojo.
- **Animación ±1 h** de todos los paneles GOES a la vez (tope de 3 paneles animados); ERA5 queda fijo.
- Cambiar de canal: selector por panel con los **favoritos primero (★)**, botones **◀ ▶** que recorren
  el grupo del producto, y en «Agregar panel» una botonera (`st.pills`) de favoritos.
- **Sin tests en el repo**: cada tarea se verifica con ruff, pyright, un script de comprobación
  (heredoc, nada se guarda) y, al final, AppTest de Streamlit y una revisión visual de Pablo.

## Global Constraints

- Todo en español: docstrings, comentarios, textos de la interfaz y mensajes de commit.
- Toda función y método lleva anotados parámetros y retorno, y docstring en español (ruff `ANN`).
- `uv run ruff check scripts`, `uv run ruff format --check scripts` y `uv run pyright` pasan limpios
  al terminar cada tarea.
- Estilo del código vecino: llamadas largas en una línea con `# fmt: skip` cuando el formateador las
  rompería mal; `from visor_app import ...` para módulos hermanos; `import comun` como primer partido.
- El rojo (`tema.SEVERE`) se reserva para eventos del catálogo y líneas de umbral chileno.
- Sin dependencias nuevas (`pyproject.toml` no cambia).
- `graficos.mapa` sigue existiendo: lo usa `p_caso.py`.
- Datos de referencia para verificar: región `centro-sur-austral`, día 2019-05-30 (ya descargado en
  `data/recortes/centro-sur-austral/`). GOES latlon: 1301×501 puntos (0,02°), de −30 a −56 y de −76 a −66.
  ERA5: 105×41 puntos (0,25°).
- Las verificaciones en Python se corren desde la raíz del repo con
  `uv run python - <<'EOF' ... EOF` e insertan `scripts` en `sys.path`. Los avisos
  `missing ScriptRunContext` de Streamlit en modo *bare* son esperables y se ignoran.

## Review Focus

1. **Día sin GOES o sin ERA5**: el panel inicial cae al primer índice ERA5; los paneles cuyo producto no
   existe ese día no se dibujan y se avisa con una nota, sin borrarlos (vuelven al cambiar de día).
   → Lo cubre la Task 5, paso 4 (filtro `visibles` + `st.caption`).
2. **ΔC13 en la primera imagen del día** (no hay imagen anterior): el panel queda vacío con un título
   que lo explica, sin desordenar la numeración de la grilla. → Task 2 (`capas.vacia`) y Task 5.
3. **Quitar todos los paneles**: la página muestra un aviso y el botón de agregar sigue disponible; no
   se dibuja una figura vacía. → Task 5, paso 4.
4. **Volver a «Mapas» desde otra página o tras el recorrido guiado**: los paneles y sus opciones
   (nivel, contorno) siguen como estaban, porque la fuente de verdad no es un widget. → Task 4 y Task 5,
   verificación con AppTest en el paso 6.
5. **Clic para elegir punto en un panel GOES** (antes solo funcionaba en el mapa ERA5): todo panel lleva
   la grilla invisible de ERA5 y el clic elige el punto en cualquiera. → Task 3 y Task 5.

---

## Estructura de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `scripts/visor_app/productos.py` | Crear | Catálogo único (claves `idx:`, `sfc:`, `pl:`, `goes:`, `rgb:`), favoritos, orden, vecino ◀ ▶ y las constantes de rango que hoy están en `p_mapas.py`. |
| `scripts/visor_app/capas.py` | Crear | `Capa` y el cálculo de cada producto a una hora: ERA5 (con nivel), bandas GOES, ΔC13, C08−C13, Airmass, viento 850 hPa. |
| `scripts/visor_app/graficos.py` | Modificar | Agregar `disposicion`, `z_fondo` y `grilla` (figura de subgráficos sincronizados). |
| `scripts/visor_app/estado.py` | Modificar | `Panel` y la API de paneles; el recorrido fija paneles en lugar de `era5_var`/`goes_prod`. |
| `scripts/visor_app/textos.py` | Modificar | `Paso.paneles` en lugar de `era5`/`goes`; ayuda del Airmass. |
| `scripts/visor_app/p_mapas.py` | Reescribir | Controles de la grilla y de cada panel, la figura, el clic, la animación y la ayuda. |
| `AGENTS.md` | Modificar | Párrafo del visor: grilla, módulos nuevos. |

---

### Task 1: Catálogo único de productos

**Files:**
- Create: `scripts/visor_app/productos.py`

**Interfaces:**
- Consumes: `datos.Dia`, `datos.abre(ruta) -> xr.Dataset`, `componentes.CORTOS`, `componentes.unidad(u: str) -> str`.
- Produces:
  - `DIVERGENTES: set[str]`, `OCULTOS: set[str]`, `RANGOS: dict[str, tuple[float, float]]`,
    `RANGO_GOES: dict[int, tuple[float, float]]` (copiados tal cual de `p_mapas.py`).
  - `DERIVADOS: dict[str, tuple[str, set[str]]]` (clave → etiqueta y bandas que necesita), `FAVORITOS: tuple[str, ...]`.
  - `@dataclass(frozen=True) class Producto(clave: str, etiqueta: str, corta: str, grupo: str)` con
    propiedades `fuente -> str`, `variable -> str`, `es_goes -> bool`.
  - `catalogo(d: datos.Dia) -> dict[str, Producto]`
  - `ordenados(cat: dict[str, Producto]) -> list[str]`
  - `vecino(clave: str, cat: dict[str, Producto], paso: int) -> str`

- [ ] **Step 1: Escribir `productos.py`**

```python
"""Catálogo único de lo que puede mostrar un panel de la página Mapas: ERA5, bandas GOES y derivados.

Cada producto tiene una clave con prefijo de fuente (``idx:``, ``sfc:``, ``pl:``, ``goes:`` o ``rgb:``)
para que ERA5 y GOES convivan en una sola lista sin que choquen los nombres de variable.
"""

from dataclasses import dataclass

from visor_app import componentes, datos

DIVERGENTES = {"u", "v", "w", "vo", "d", "10u", "10v", "100u", "100v", "srh_01", "srh_03", "stp_lm"}
OCULTOS = {"u_lm", "v_lm", "u_rm", "v_rm", "u_06", "v_06", "altura_sfc"}
RANGOS = {  # rangos fijos para comparar horas y días; el resto usa percentiles 1–99
    "vgp_01": (0.0, 0.3), "srh_01": (-300.0, 300.0), "srh_03": (-600.0, 600.0),
    "cizalle_01": (0.0, 25.0), "cizalle_03": (0.0, 35.0), "cizalle_06": (0.0, 45.0),
    "stp_lm": (-1.5, 1.5), "sherbs3": (0.0, 2.0), "lcl": (0.0, 2500.0),
}  # fmt: skip
RANGO_GOES = {
    **dict.fromkeys(range(1, 7), (0.0, 1.0)),
    7: (200.0, 320.0), 8: (200.0, 250.0), 9: (205.0, 265.0), 10: (210.0, 275.0),
    **dict.fromkeys(range(11, 17), (190.0, 300.0)),
}  # fmt: skip
DERIVADOS = {  # clave → (etiqueta, bandas que necesita)
    "rgb:airmass": ("RGB Airmass", {"C08", "C10", "C12", "C13"}),
    "goes:dT": ("Enfriamiento del tope en 10 min (ΔC13)", {"C13"}),
    "goes:C08-C13": ("C08 − C13 (tope en la tropopausa)", {"C08", "C13"}),
}
FAVORITOS = (
    "rgb:airmass", "goes:C13", "goes:dT", "goes:C08-C13", "goes:C02",
    "idx:vgp_01", "idx:srh_01", "idx:stp_lm", "idx:sherbs3", "idx:cizalle_01", "idx:lcl",
)  # fmt: skip


@dataclass(frozen=True)
class Producto:
    """Un producto elegible para un panel: su clave, cómo se nombra y a qué grupo pertenece."""

    clave: str
    etiqueta: str  # para la lista: "Índice · VGP₀₋₁ [m/s²]"
    corta: str  # para títulos y botones: "VGP₀₋₁"
    grupo: str  # "Índices", "Superficie", "Presión", "GOES bandas" o "GOES derivados"

    @property
    def fuente(self) -> str:
        """Prefijo de la clave: ``idx``, ``sfc``, ``pl``, ``goes`` o ``rgb``."""
        return self.clave.partition(":")[0]

    @property
    def variable(self) -> str:
        """La clave sin el prefijo (nombre de la variable, banda o derivado)."""
        return self.clave.partition(":")[2]

    @property
    def es_goes(self) -> bool:
        """Si el producto sale de las imágenes GOES (banda, derivado o RGB)."""
        return self.fuente in {"goes", "rgb"}


def catalogo(d: datos.Dia) -> dict[str, Producto]:
    """Productos disponibles el día ``d``: índices, superficie, presión, bandas GOES y derivados."""
    out: dict[str, Producto] = {}
    for prefijo, ruta, grupo in (("idx", d.idx, "Índices"), ("sfc", d.sfc, "Superficie"),
                                 ("pl", d.pl, "Presión")):  # fmt: skip
        if ruta is None:
            continue
        ds = datos.abre(ruta)
        for v in map(str, ds.data_vars):
            if v in OCULTOS:
                continue
            a = ds[v].attrs
            nombre = componentes.CORTOS.get(v) or str(a.get("long_name", v))
            u = componentes.unidad(str(a.get("units", "")))
            clave = f"{prefijo}:{v}"
            out[clave] = Producto(clave, f"{grupo} · {nombre}" + (f" [{u}]" if u else ""), nombre, grupo)
    if d.goes:
        ds = datos.abre(d.goes[0])
        bandas = [str(b) for b in ds.data_vars]
        for b in bandas:
            um = str(ds[b].attrs.get("longitud_onda_um", "")).replace(".", ",")
            out[f"goes:{b}"] = Producto(f"goes:{b}", f"GOES · {b} · {um} µm", f"{b} {um} µm", "GOES bandas")
        for clave, (etiqueta, necesita) in DERIVADOS.items():
            if necesita <= set(bandas):
                corta = etiqueta.split(" (")[0]
                out[clave] = Producto(clave, f"GOES · {etiqueta}", corta, "GOES derivados")
    return out


def ordenados(cat: dict[str, Producto]) -> list[str]:
    """Claves del catálogo con los favoritos primero, en el orden de ``FAVORITOS``."""
    fav = [k for k in FAVORITOS if k in cat]
    return [*fav, *[k for k in cat if k not in fav]]


def vecino(clave: str, cat: dict[str, Producto], paso: int) -> str:
    """El producto anterior (``paso=-1``) o siguiente (``+1``) del mismo grupo, en orden circular."""
    grupo = [k for k, p in cat.items() if p.grupo == cat[clave].grupo]
    return grupo[(grupo.index(clave) + paso) % len(grupo)]
```

- [ ] **Step 2: Verificar el catálogo con datos reales**

```bash
uv run python - <<'EOF'
import sys, datetime as dt
sys.path.insert(0, "scripts")
from visor_app import datos, productos as P
d = datos.dias("centro-sur-austral")[dt.date(2019, 5, 30)]
cat = P.catalogo(d)
orden = P.ordenados(cat)
print(len(cat), orden[:11])
assert orden[0] == "rgb:airmass" and "goes:C16" in cat and "idx:vgp_01" in cat
assert not any(k.endswith(":u_lm") for k in cat)
assert P.vecino("goes:C13", cat, +1) == "goes:C14" and P.vecino("goes:C01", cat, -1) == "goes:C16"
assert cat["rgb:airmass"].es_goes and not cat["idx:vgp_01"].es_goes
print(cat["idx:vgp_01"].etiqueta, "|", cat["goes:C13"].etiqueta, "|", cat["goes:dT"].corta)
EOF
```

Esperado: imprime unos 60–80 productos con los 11 favoritos primero, sin `AssertionError`.

- [ ] **Step 3: Lint, formato y tipos**

Run: `uv run ruff check scripts && uv run ruff format scripts && uv run pyright`
Expected: `All checks passed!` y `0 errors`.

- [ ] **Step 4: Commit**

```bash
git add scripts/visor_app/productos.py
git commit -m "Agregar el catálogo único de productos del visor (ERA5, GOES y derivados)"
```

---

### Task 2: Capas — los datos de cada producto a una hora

**Files:**
- Create: `scripts/visor_app/capas.py`

**Interfaces:**
- Consumes: `productos.Producto`, `productos.DIVERGENTES`, `productos.RANGOS`, `productos.RANGO_GOES`;
  `datos.abre`, `datos.imagen_en(d, t) -> (Path, np.datetime64) | None`,
  `datos.anterior(d, t) -> (Path, np.datetime64) | None`, `datos.instante(da) -> pd.Timestamp`;
  `componentes.unidad`; `graficos.Encuadre`; `tema.DIVERGENTE`, `tema.SECUENCIAL`, `tema.VISIBLE`, `tema.IR`,
  `tema.SURFACE`, `tema.COLD`, `tema.INK`, `tema.WARM`.
- Produces:
  - `@dataclass(frozen=True) class Capa(z, lat, lon, titulo, unidad="", escala=None, rango=(0.0, 1.0), centro=False, umbral=None, nota=None)`
    con propiedad `es_rgb -> bool` (`z.ndim == 3`). En RGB, `z` es `uint8` de forma `(nlat, nlon, 3)`.
  - `capa(d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, *, sub: int = 1, nivel: float | None = None) -> Capa | None`
  - `vacia(titulo: str, enc: graficos.Encuadre) -> Capa`
  - `niveles(d: datos.Dia) -> list[float]` (niveles de presión, de mayor a menor)
  - `airmass(ds: xr.Dataset, ti: np.datetime64) -> np.ndarray`
  - `viento_850(d: datos.Dia, t: pd.Timestamp, enc: graficos.Encuadre) -> tuple[list[float | None], list[float | None]] | None`

- [ ] **Step 1: Escribir `capas.py`**

La lógica de ERA5 y GOES es la de `_era5` y `_goes_figura` de `p_mapas.py`, separada del dibujo; el
viento es el cálculo de `_vectores`. Los títulos son cortos porque van sobre cada subgráfico.

```python
"""Datos de un panel a una hora: la matriz (o el RGB) que la grilla de Mapas dibuja por producto.

Separa el cálculo del dibujo: ``capa`` devuelve valores, escala y rango; ``graficos.grilla`` los pinta.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from visor_app import componentes, datos, graficos, productos, tema

# Receta Airmass (EUMETSAT/CIRA): (banda, banda que se resta, valor para 0, valor para 255), gamma 1.
# El azul va de 243,9 a 208,5 K: C08 invertido, los topes y el aire frío salen azules.
AIRMASS = (("C08", "C10", -26.2, 0.6), ("C12", "C13", -43.2, 6.7), ("C08", None, 243.9, 208.5))


@dataclass(frozen=True)
class Capa:
    """Lo que dibuja un panel: valores sobre (lat, lon), título, unidad, escala y rango de color."""

    z: np.ndarray  # 2D con valores, o 3D uint8 (nlat, nlon, 3) si es RGB
    lat: np.ndarray
    lon: np.ndarray
    titulo: str
    unidad: str = ""
    escala: list | str | None = None
    rango: tuple[float, float] = (0.0, 1.0)
    centro: bool = False
    umbral: float | None = None
    nota: str | None = None  # advertencia para el pie de la página

    @property
    def es_rgb(self) -> bool:
        """Si ``z`` es una imagen RGB en vez de un campo de valores."""
        return self.z.ndim == 3


def _rango(z: np.ndarray, centro: bool) -> tuple[float, float]:
    """Rango de color entre los percentiles 1 y 99 de ``z`` (simétrico si ``centro``)."""
    lo, hi = np.nanpercentile(z, [1, 99])
    if centro:
        m = float(max(abs(lo), abs(hi)))
        return -m, m
    return float(lo), float(hi)


def vacia(titulo: str, enc: graficos.Encuadre) -> Capa:
    """Panel sin datos (p. ej. ΔC13 sin imagen anterior): conserva su lugar y su título en la grilla."""
    return Capa(np.full((2, 2), np.nan), np.array([enc.norte, enc.sur]),
                np.array([enc.oeste, enc.este]), titulo)  # fmt: skip


def niveles(d: datos.Dia) -> list[float]:
    """Niveles de presión del día, de superficie hacia arriba (vacío si no hay niveles de presión)."""
    if d.pl is None:
        return []
    return sorted(datos.abre(d.pl)["level"].values.tolist(), reverse=True)


def airmass(ds: xr.Dataset, ti: np.datetime64) -> np.ndarray:
    """Imagen RGB Airmass ``uint8`` (nlat, nlon, 3) de la hora ``ti`` de ``ds``; NaN queda en negro."""
    canales = []
    for a, b, v0, v1 in AIRMASS:
        x = ds[a].sel(time=ti).values.astype(np.float32)
        if b is not None:
            x = x - ds[b].sel(time=ti).values
        canales.append(np.clip((x - v0) / (v1 - v0), 0.0, 1.0))
    rgb = np.nan_to_num(np.stack(canales, axis=-1), nan=0.0)
    return (rgb * 255).round().astype(np.uint8)


def _era5(d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, nivel: float | None) -> Capa:
    """Campo ERA5 de ``prod`` a la hora en punto más cercana a ``t`` (en ``nivel`` si es de presión)."""
    ruta = {"idx": d.idx, "sfc": d.sfc, "pl": d.pl}[prod.fuente]
    assert ruta is not None
    ds = datos.abre(ruta)
    v = prod.variable
    da = ds[v].sel(time=t, method="nearest")
    titulo = f"{prod.corta} · {datos.instante(da['time']):%H:%M}"
    nota = None
    if "level" in da.dims:
        nv = niveles(d)
        nivel = nivel if nivel in nv else (850.0 if 850.0 in nv else nv[0])
        da = da.sel(level=nivel)
        titulo += f" · {nivel:g} hPa"
        nota = "Sobre los Andes los niveles bajos están bajo tierra (valores extrapolados)."
    centro = v in productos.DIVERGENTES
    z = da.values
    umbral = ds[v].attrs.get("umbral_chile")
    return Capa(
        z, ds["latitude"].values, ds["longitude"].values, titulo,
        unidad=componentes.unidad(str(ds[v].attrs.get("units", ""))),
        escala=tema.DIVERGENTE if centro else tema.SECUENCIAL,
        rango=productos.RANGOS.get(v) or _rango(z, centro), centro=centro,
        umbral=None if umbral is None else float(umbral), nota=nota,
    )  # fmt: skip


def _goes(d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, sub: int) -> Capa | None:
    """Producto GOES en la imagen más cercana a ``t``, submuestreado ``sub``; ``None`` si falta imagen."""
    img = datos.imagen_en(d, t)
    if img is None:
        return None
    ruta, ti = img
    ds = datos.abre(ruta)
    lat, lon = ds["latitude"].values[::sub], ds["longitude"].values[::sub]
    hora = pd.Timestamp(ti)
    v = prod.variable
    if v == "airmass":
        return Capa(airmass(ds, ti)[::sub, ::sub], lat, lon, f"{prod.corta} · {hora:%H:%M}")
    if v == "dT":
        prev = datos.anterior(d, ti)
        if prev is None:
            return None
        r0, t0 = prev
        z = ds["C13"].sel(time=ti).values - datos.abre(r0)["C13"].sel(time=t0).values
        minutos = (hora - pd.Timestamp(t0)).total_seconds() / 60
        return Capa(z[::sub, ::sub], lat, lon, f"ΔC13 en {minutos:.0f} min · {hora:%H:%M}",
                    unidad="K", escala=tema.DIVERGENTE, rango=(-15.0, 15.0), centro=True)  # fmt: skip
    if v == "C08-C13":
        z = ds["C08"].sel(time=ti).values - ds["C13"].sel(time=ti).values
        escala = [[0.0, tema.SURFACE], [0.7, tema.COLD], [0.89, tema.INK], [1.0, tema.WARM]]
        return Capa(z[::sub, ::sub], lat, lon, f"C08 − C13 · {hora:%H:%M}", unidad="K",
                    escala=escala, rango=(-40.0, 5.0))  # fmt: skip
    n = int(v[1:])
    return Capa(
        ds[v].sel(time=ti).values[::sub, ::sub], lat, lon, f"{prod.corta} · {hora:%H:%M}",
        unidad=componentes.unidad(str(ds[v].attrs.get("units", ""))),
        escala=tema.VISIBLE if n <= 6 else tema.IR, rango=productos.RANGO_GOES[n],
    )  # fmt: skip


def capa(
    d: datos.Dia, prod: productos.Producto, t: pd.Timestamp, *, sub: int = 1,
    nivel: float | None = None,
) -> Capa | None:  # fmt: skip
    """La capa de ``prod`` a la hora ``t``; ``None`` si GOES no tiene la imagen que hace falta."""
    if prod.es_goes:
        return _goes(d, prod, t, sub)
    return _era5(d, prod, t, nivel)


def viento_850(
    d: datos.Dia, t: pd.Timestamp, enc: graficos.Encuadre
) -> tuple[list[float | None], list[float | None]] | None:
    """Flechas del viento en 850 hPa (una de cada tres celdas) como líneas x/y separadas por ``None``."""
    if d.pl is None:
        return None
    h = datos.abre(d.pl).sel(time=t, method="nearest").sel(level=850, method="nearest")
    h = h.sel(latitude=slice(enc.norte, enc.sur), longitude=slice(enc.oeste, enc.este))
    u, v = h["u"].values[::3, ::3], h["v"].values[::3, ::3]
    LA, LO = np.meshgrid(h["latitude"].values[::3], h["longitude"].values[::3], indexing="ij")
    k = 0.018  # grados por m/s
    xs: list[float | None] = []
    ys: list[float | None] = []
    for x0, y0, du, dv in zip(LO.ravel(), LA.ravel(), u.ravel(), v.ravel(), strict=True):
        x1, y1 = x0 + du * k, y0 + dv * k
        ang = np.arctan2(dv, du)
        ala = 0.25 * np.hypot(du, dv) * k
        xs += [x0, x1, x1 - ala * np.cos(ang - 0.45), None, x1, x1 - ala * np.cos(ang + 0.45), None]
        ys += [y0, y1, y1 - ala * np.sin(ang - 0.45), None, y1, y1 - ala * np.sin(ang + 0.45), None]
    return xs, ys
```

Nota: `capas` importa `graficos` solo por el tipo `Encuadre`; `graficos` **no** debe importar `capas` a nivel
de módulo (Task 3 usa `TYPE_CHECKING`) para evitar el ciclo.

- [ ] **Step 2: Verificar las capas con datos reales**

```bash
uv run python - <<'EOF'
import sys, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, "scripts")
from visor_app import capas, datos, graficos, productos as P
d = datos.dias("centro-sur-austral")[dt.date(2019, 5, 30)]
cat = P.catalogo(d)
t = pd.Timestamp("2019-05-30 21:50")
am = capas.capa(d, cat["rgb:airmass"], t, sub=2)
assert am is not None and am.es_rgb and am.z.dtype == np.uint8 and am.z.shape == (651, 251, 3)
print("airmass medias RGB:", am.z.reshape(-1, 3).mean(axis=0).round(1))
c13 = capas.capa(d, cat["goes:C13"], t, sub=2)
assert c13 is not None and not c13.es_rgb and c13.z.shape == (651, 251)
vgp = capas.capa(d, cat["idx:vgp_01"], t)
assert vgp is not None and vgp.umbral == 0.1 and vgp.z.shape == (105, 41), vgp
pl = next(k for k in cat if k.startswith("pl:"))
c = capas.capa(d, cat[pl], t, nivel=500.0)
assert c is not None and "500 hPa" in c.titulo and c.nota
primera = pd.Timestamp(datos.imagenes(d)[0][0])
assert capas.capa(d, cat["goes:dT"], primera) is None
enc = graficos.Encuadre(-34, -40, -75, -70)
assert capas.vacia("x", enc).z.shape == (2, 2)
assert capas.viento_850(d, t, enc) is not None
print(am.titulo, "|", c13.titulo, "|", vgp.titulo, "|", c.titulo)
EOF
```

Esperado: sin `AssertionError`. Las medias del Airmass deben ser tres números distintos entre ~40 y ~200
(una imagen gris o negra uniforme indica la receta mal aplicada). Si `vgp.umbral` no es 0.1, revisar el
atributo `umbral_chile` en `era5_idx_20190530.nc` y ajustar solo la aserción.

- [ ] **Step 3: Lint, formato y tipos**

Run: `uv run ruff check scripts && uv run ruff format scripts && uv run pyright`
Expected: limpio.

- [ ] **Step 4: Commit**

```bash
git add scripts/visor_app/capas.py
git commit -m "Separar el cálculo de cada producto del dibujo y agregar el RGB Airmass"
```

---

### Task 3: `graficos.grilla` — subgráficos con zoom sincronizado

**Files:**
- Modify: `scripts/visor_app/graficos.py` (agregar tras `mapa`, antes de `# --- Sondeo`)

**Interfaces:**
- Consumes: `capas.Capa` (solo para tipos, bajo `TYPE_CHECKING`), `Encuadre`, `Punto`, `tema`.
- Produces:
  - `disposicion(n: int) -> tuple[int, int]`
  - `z_fondo(c: Capa) -> np.ndarray` (la matriz tal como entra a la traza: el RGB se voltea a latitud creciente)
  - `grilla(capas: list[Capa], contornos: list[Capa | None], enc: Encuadre, costa: tuple[list, list], *, eventos: pd.DataFrame | None = None, punto: Punto | None = None, clic: tuple[np.ndarray, np.ndarray] | None = None, viento: tuple[list, list] | None = None) -> tuple[go.Figure, list[int]]`
    — devuelve la figura y el índice de la traza de fondo de cada panel (para animar).

- [ ] **Step 1: Agregar el import para tipos**

Al inicio de `graficos.py`, junto a los imports:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # capas importa graficos (Encuadre): solo se usa para anotar
    from visor_app.capas import Capa
```

- [ ] **Step 2: Agregar `disposicion`, `z_fondo` y `grilla`**

Claves del diseño:
- `make_subplots(shared_xaxes="all", shared_yaxes="all")` hace que los ejes `x2…`, `y2…` igualen
  (`matches`) a `x` e `y`: el zoom en un panel mueve todos.
- La proporción (`scaleanchor`) va **solo** en `yaxis` → `x`; los demás la heredan por `matches`. Poner
  `scaleanchor` en ejes que también tienen `matches` produce conflictos de restricciones en plotly.
- El RGB va como `go.Image`, que dibuja la fila 0 en `y0` y avanza `dy`. Con el eje y creciente
  (rango fijo de sur a norte) la imagen se voltea a latitud creciente y `dy` queda positivo.
- Cada barra de color se ubica a la derecha del dominio de su subgráfico.

```python
# --- Grilla de Mapas -----------------------------------------------------------------------------
def disposicion(n: int) -> tuple[int, int]:
    """Filas y columnas de la grilla para ``n`` paneles: 1×1, 1×2, 2×2 (3–4) o 2×3 (5–6)."""
    if n <= 2:
        return 1, max(n, 1)
    if n <= 4:
        return 2, 2
    return 2, 3


def z_fondo(c: "Capa") -> np.ndarray:
    """La matriz de ``c`` como entra a su traza: el RGB pasa a latitud creciente para ``go.Image``."""
    if c.es_rgb and c.lat[0] > c.lat[-1]:
        return c.z[::-1]
    return c.z


def _fondo(c: "Capa", barra: dict) -> go.Heatmap | go.Image:
    """Traza de fondo de un panel: imagen RGB o mapa de calor con su barra de color."""
    if c.es_rgb:
        lat = c.lat[::-1] if c.lat[0] > c.lat[-1] else c.lat
        return go.Image(
            z=z_fondo(c), x0=float(c.lon[0]), dx=float(c.lon[1] - c.lon[0]), y0=float(lat[0]),
            dy=float(lat[1] - lat[0]), hovertemplate="%{y:.2f}°, %{x:.2f}°<extra></extra>",
        )  # fmt: skip
    return go.Heatmap(
        z=c.z, x=c.lon, y=c.lat, colorscale=c.escala, zmin=c.rango[0], zmax=c.rango[1],
        zmid=0 if c.centro else None, colorbar=barra,
        hovertemplate="%{y:.2f}°, %{x:.2f}°<br><b>%{z:.3g}</b> " + c.unidad + "<extra></extra>",
    )  # fmt: skip


def _umbral(c: "Capa", ancho: float) -> go.Contour:
    """Línea del umbral chileno de ``c`` en rojo."""
    return go.Contour(
        z=c.z, x=c.lon, y=c.lat, showscale=False, hoverinfo="skip",
        contours={"start": c.umbral, "end": c.umbral, "size": 1, "coloring": "none"},
        line={"color": tema.SEVERE, "width": ancho},
    )  # fmt: skip


def grilla(
    capas: list["Capa"], contornos: list["Capa | None"], enc: Encuadre, costa: tuple[list, list],
    *, eventos: pd.DataFrame | None = None, punto: Punto | None = None,
    clic: tuple[np.ndarray, np.ndarray] | None = None, viento: tuple[list, list] | None = None,
) -> tuple[go.Figure, list[int]]:  # fmt: skip
    """Paneles en una figura con los ejes compartidos: el zoom y el desplazamiento van juntos.

    ``contornos[i]`` es un campo ERA5 que se dibuja como isolíneas sobre el panel ``i`` (o ``None``).
    ``clic`` es la grilla (lat, lon) de marcadores invisibles que hace clicable cada panel. Devuelve la
    figura y el índice de la traza de fondo de cada panel, para animarla con ``go.Frame``.
    """
    filas, cols = disposicion(len(capas))
    fig = make_subplots(
        rows=filas, cols=cols, shared_xaxes="all", shared_yaxes="all",
        horizontal_spacing=0.09 if cols > 1 else 0.02, vertical_spacing=0.08,
        subplot_titles=[c.titulo for c in capas],
    )  # fmt: skip
    fig.update_layout(template="cuaderno")
    fondos: list[int] = []
    for i, (c, cont) in enumerate(zip(capas, contornos, strict=True)):
        r, k = i // cols + 1, i % cols + 1
        sp = fig.get_subplot(r, k)
        xd, yd = sp.xaxis.domain, sp.yaxis.domain
        barra = {
            "title": {"text": c.unidad, "side": "right"}, "thickness": 10, "outlinewidth": 0,
            "x": xd[1] + 0.004, "xanchor": "left", "y": (yd[0] + yd[1]) / 2, "len": (yd[1] - yd[0]) * 0.9,
        }  # fmt: skip
        fondos.append(len(fig.data))
        fig.add_trace(_fondo(c, barra), row=r, col=k)
        if c.umbral is not None and not c.es_rgb:
            fig.add_trace(_umbral(c, 1.6), row=r, col=k)
        if cont is not None:
            fig.add_trace(
                go.Contour(
                    z=cont.z, x=cont.lon, y=cont.lat, showscale=False, hoverinfo="skip", ncontours=8,
                    contours={"coloring": "lines", "showlabels": True,
                              "labelfont": {"size": 10, "color": tema.INK_2}},
                    colorscale=[[0, tema.INK_2], [1, tema.INK_2]], line={"width": 0.8},
                ),
                row=r, col=k,
            )  # fmt: skip
            if cont.umbral is not None:
                fig.add_trace(_umbral(cont, 2.0), row=r, col=k)
        xs, ys = costa
        fig.add_trace(
            go.Scatter(x=xs, y=ys, mode="lines", line={"color": tema.INK, "width": 0.9},
                       hoverinfo="skip"),
            row=r, col=k,
        )  # fmt: skip
        if viento is not None:
            fig.add_trace(
                go.Scatter(x=viento[0], y=viento[1], mode="lines", hoverinfo="skip",
                           line={"color": tema.INK_2, "width": 1}),
                row=r, col=k,
            )  # fmt: skip
        if clic is not None:
            LA, LO = np.meshgrid(clic[0], clic[1], indexing="ij")
            fig.add_trace(
                go.Scatter(
                    x=LO.ravel(), y=LA.ravel(), mode="markers", hoverinfo="skip",
                    marker={"size": 9, "color": "rgba(0,0,0,0)"},
                    selected={"marker": {"opacity": 0}}, unselected={"marker": {"opacity": 0}},
                ),
                row=r, col=k,
            )  # fmt: skip
        if eventos is not None and len(eventos):
            fig.add_trace(
                go.Scatter(
                    x=eventos["lon"], y=eventos["lat"], mode="markers", text=eventos["texto"],
                    hoverinfo="text",
                    marker={"symbol": "triangle-up", "size": 11, "color": tema.SEVERE,
                            "line": {"color": tema.SURFACE, "width": 1.2}},
                    unselected={"marker": {"opacity": 1}},
                ),
                row=r, col=k,
            )  # fmt: skip
        if punto is not None:
            fig.add_trace(
                go.Scatter(
                    x=[punto.lon], y=[punto.lat], mode="markers", hoverinfo="text",
                    text=[f"<b>{punto.nombre}</b><br>{punto.lat:.2f}°, {punto.lon:.2f}°"],
                    marker={"symbol": "circle-open", "size": 20, "color": tema.ACCENT,
                            "line": {"width": 2.5}},
                    unselected={"marker": {"opacity": 1}},
                ),
                row=r, col=k,
            )  # fmt: skip
    for i, a in enumerate(fig.layout.annotations):  # títulos alineados a la izquierda del panel
        a.update(x=fig.get_subplot(i // cols + 1, i % cols + 1).xaxis.domain[0], xanchor="left",
                 font={"family": tema.SANS, "size": 13, "color": tema.INK})  # fmt: skip
    fig.update_xaxes(range=[enc.oeste, enc.este], showgrid=False, ticksuffix="°", title=None)
    fig.update_yaxes(range=[enc.sur, enc.norte], showgrid=False, ticksuffix="°", title=None)
    fig.update_layout(
        yaxis={"scaleanchor": "x", "scaleratio": enc.aspecto},
        height=640 if filas == 1 else 470 * filas, showlegend=False, dragmode="pan",
        clickmode="event+select", uirevision="grilla", margin={"t": 56, "r": 48},
    )  # fmt: skip
    return _estilo(fig), fondos
```

- [ ] **Step 3: Verificar la estructura de la figura y dejar un HTML para mirarla**

```bash
uv run python - <<'EOF'
import sys, datetime as dt
import pandas as pd
sys.path.insert(0, "scripts")
from visor_app import capas, datos, graficos, productos as P
assert [graficos.disposicion(n) for n in range(1, 7)] == [(1, 1), (1, 2), (2, 2), (2, 2), (2, 3), (2, 3)]
d = datos.dias("centro-sur-austral")[dt.date(2019, 5, 30)]
cat = P.catalogo(d)
reg = datos.region("centro-sur-austral")
t = pd.Timestamp("2019-05-30 21:50")
enc = graficos.encuadre_eventos(datos.eventos(d.fecha), reg)
cs = [capas.capa(d, cat[k], t, sub=2) for k in ("rgb:airmass", "goes:C13", "idx:vgp_01")]
vgp = capas.capa(d, cat["idx:vgp_01"], t)
ref = datos.era5_ref(d)
fig, fondos = graficos.grilla(
    cs, [vgp, None, None], enc, datos.costa(reg), eventos=datos.eventos(d.fecha),
    clic=(ref["latitude"].values, ref["longitude"].values),
)
L = fig.layout
assert L.xaxis2.matches == "x" and L.yaxis3.matches == "y" and L.yaxis.scaleanchor == "x"
assert [type(fig.data[i]).__name__ for i in fondos] == ["Image", "Heatmap", "Heatmap"]
assert fig.data[fondos[0]].dy > 0
fig.write_html("/tmp/grilla_prueba.html", include_plotlyjs="cdn")
print("ok", len(fig.data), "trazas; abrir /tmp/grilla_prueba.html")
EOF
```

Esperado: `ok N trazas`. Abrir `/tmp/grilla_prueba.html` en el navegador y comprobar: 2×2 con el cuarto
hueco vacío; Airmass con el norte arriba (la costa de Chile coincide con la del C13); contornos de VGP
y la línea roja de 0,1 sobre el Airmass; al hacer zoom en un panel, los otros dos lo siguen. **Si el RGB
sale invertido o desplazado, corregir solo `_fondo`/`z_fondo` antes de seguir.**

- [ ] **Step 4: Lint, formato y tipos**

Run: `uv run ruff check scripts && uv run ruff format scripts && uv run pyright`
Expected: limpio. Si pyright se queja de `sp.xaxis.domain` (los stubs de plotly no tipan `get_subplot`),
anotar esa línea con `# pyright: ignore[reportAttributeAccessIssue]`, como ya se hace con `add_hline`.

- [ ] **Step 5: Commit**

```bash
git add scripts/visor_app/graficos.py
git commit -m "Agregar la grilla de mapas con ejes compartidos para sincronizar el zoom"
```

---

### Task 4: Estado de los paneles y recorrido guiado

**Files:**
- Modify: `scripts/visor_app/estado.py` (agregar `Panel` y su API; cambiar el final de `aplica_paso`)
- Modify: `scripts/visor_app/textos.py:134-184` (`Paso` y `RECORRIDOS`) y `AYUDA` (agregar `"airmass"`)

**Interfaces:**
- Produces (en `estado`):
  - `MAX_PANELES = 6`
  - `@dataclass(frozen=True) class Panel(id: int, clave: str, nivel: float | None = None, contorno: str | None = None)`
  - `paneles() -> list[Panel] | None` (`None` = nunca se fijaron en esta sesión)
  - `fija_paneles(ps: list[Panel]) -> None`
  - `nuevo_panel(clave: str) -> Panel`
  - `agrega_panel(clave: str) -> None`, `quita_panel(id_: int) -> None`,
    `cambia_panel(id_: int, **cambios: object) -> None`
- Produces (en `textos`): `Paso.paneles: tuple[str, ...]`; `AYUDA["airmass"]`.

- [ ] **Step 1: Agregar la API de paneles a `estado.py`**

Agregar `import dataclasses` arriba y, después de `elige_punto`, este bloque. La lista no es la clave de
ningún widget, así que Streamlit no la borra al cambiar de página: no necesita `recuerda`/`guarda`.

```python
# --- Paneles de la página Mapas ------------------------------------------------------------------
MAX_PANELES = 6


@dataclass(frozen=True)
class Panel:
    """Un panel de la grilla de Mapas: producto del catálogo y sus opciones."""

    id: int  # estable mientras el panel existe: nombra las claves de sus widgets
    clave: str  # clave de ``productos.catalogo``
    nivel: float | None = None  # hPa, solo productos de niveles de presión
    contorno: str | None = None  # clave ERA5 dibujada como isolíneas (solo paneles GOES)


def paneles() -> list[Panel] | None:
    """Los paneles de la grilla, o ``None`` si todavía no se fijaron en esta sesión."""
    ps = st.session_state.get("paneles")
    return None if ps is None else list(ps)


def fija_paneles(ps: list[Panel]) -> None:
    """Reemplaza los paneles de la grilla."""
    st.session_state["paneles"] = list(ps)


def nuevo_panel(clave: str) -> Panel:
    """Un panel con ``clave`` y un id que no se repite en la sesión."""
    n = st.session_state.get("_sig_panel", 0)
    st.session_state["_sig_panel"] = n + 1
    return Panel(n, clave)


def agrega_panel(clave: str) -> None:
    """Callback: agrega un panel con ``clave`` al final (si no se llegó al tope)."""
    ps = paneles() or []
    if len(ps) < MAX_PANELES:
        fija_paneles([*ps, nuevo_panel(clave)])


def quita_panel(id_: int) -> None:
    """Callback: quita el panel ``id_``."""
    fija_paneles([p for p in paneles() or [] if p.id != id_])


def cambia_panel(id_: int, **cambios: object) -> None:
    """Callback: cambia campos del panel ``id_`` (``clave``, ``nivel`` o ``contorno``)."""
    fija_paneles([dataclasses.replace(p, **cambios) if p.id == id_ else p for p in paneles() or []])
```

- [ ] **Step 2: El recorrido fija paneles**

En `estado.aplica_paso`, reemplazar:

```python
    if p.era5:
        fija("era5_var", p.era5)
    if p.goes:
        fija("goes_prod", p.goes)
```

por:

```python
    if p.paneles:
        fija_paneles([nuevo_panel(c) for c in p.paneles])
```

y en su docstring cambiar «las capas de la página Mapas» por «los paneles de la página Mapas».

- [ ] **Step 3: `Paso.paneles` y los pasos del recorrido en `textos.py`**

En `class Paso`, reemplazar los campos

```python
    era5: str | None = None  # variable de la página Mapas
    goes: str | None = None  # producto GOES de la página Mapas
```

por

```python
    paneles: tuple[str, ...] = ()  # claves de productos.catalogo para la grilla de Mapas
```

y en `RECORRIDOS` cambiar los tres pasos de Mapas (los textos no cambian):

- `evento="Ángeles", era5="cizalle_01", goes="C13",` → `evento="Ángeles", paneles=("idx:cizalle_01", "goes:C13"),`
- `evento="Quilelto", era5="vgp_01", goes="C13",` → `evento="Quilelto", paneles=("idx:vgp_01", "goes:C13"),`
- `evento="Ángeles", era5="srh_01", goes="dT",` → `evento="Ángeles", paneles=("idx:srh_01", "goes:dT"),`

El texto del paso de las 21:50 dice «A la derecha, el enfriamiento del tope»: sigue siendo cierto, porque
con dos paneles el segundo queda a la derecha.

- [ ] **Step 4: Ayuda del Airmass en `AYUDA`**

Agregar después de la entrada `"C08-C13"`:

```python
    "airmass": (
        "**RGB Airmass**: rojo = C08 − C10, verde = C12 − C13, azul = C08 invertido. Solo usa "
        "infrarrojo, así que sirve de día y de noche. Rojizo: aire seco bajado de la estratósfera "
        "(intrusión seca, cerca del chorro). Verde oliva: masa de aire cálida y húmeda. Azul y "
        "violeta: aire frío polar. Blanco: topes altos y fríos. Sirve para ubicar la nube coma y el "
        "borde de la intrusión seca, donde suele organizarse la convección."
    ),
```

- [ ] **Step 5: Verificar que nada más usa los campos viejos**

Run: `grep -rn "era5_var\|goes_prod\|\.era5\b\|\.goes\b" scripts/visor_app/estado.py scripts/visor_app/textos.py scripts/visor.py`
Expected: sin resultados (las referencias que quedan en `p_mapas.py` se van en la Task 5).

- [ ] **Step 6: Lint, formato y tipos**

Run: `uv run ruff check scripts && uv run ruff format scripts && uv run pyright`
Expected: limpio.

- [ ] **Step 7: Commit**

```bash
git add scripts/visor_app/estado.py scripts/visor_app/textos.py
git commit -m "Guardar los paneles de Mapas en el estado y llevar el recorrido a paneles"
```

---

### Task 5: Reescribir la página Mapas

**Files:**
- Rewrite: `scripts/visor_app/p_mapas.py`

**Interfaces:**
- Consumes: todo lo anterior: `productos.catalogo/ordenados/vecino/FAVORITOS/Producto`,
  `capas.capa/vacia/niveles/viento_850/Capa`, `graficos.grilla/disposicion/z_fondo/encuadre_eventos/Encuadre`,
  `estado.paneles/fija_paneles/nuevo_panel/agrega_panel/quita_panel/cambia_panel/MAX_PANELES/Panel`,
  `datos.costa/era5_ref/imagenes`, `textos.AYUDA/NOTA_AUSTRAL`.
- Produces: `pagina() -> None` (lo usa `visor.py`, sin cambios).

- [ ] **Step 1: Escribir el nuevo `p_mapas.py`**

Reemplaza el archivo completo. La barra superior es Encuadre · Agregar panel · Viento · Animar · Detalle.
Debajo van los controles de cada panel, en filas y columnas que siguen la grilla (control `n` arriba
del panel `n`), y después la figura. Cada control: selector (favoritos con ★) · ◀ · ▶ · opciones (nivel o
contorno, si aplica) · ×.

```python
"""Página «Mapas»: una grilla de 1 a 6 paneles (ERA5, bandas GOES o RGB) con el zoom sincronizado."""

import dataclasses

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from visor_app import capas, datos, estado, graficos, productos, tema, textos

PASO_ANIMACION = 3  # se dibuja uno de cada 3 píxeles GOES al animar
MAX_ANIMADOS = 3  # paneles GOES que se animan a la vez


def _al_clic() -> None:
    """Callback de la grilla: el punto clicado en cualquier panel pasa a ser el punto elegido."""
    puntos = st.session_state["grilla"].selection.points
    if puntos:
        la, lo = float(puntos[0]["y"]), float(puntos[0]["x"])
        estado.elige_punto(estado.Punto(la, lo, f"{la:.2f}°, {lo:.2f}°"))


def _al_cambiar(id_: int, campo: str, clave_widget: str) -> None:
    """Callback de los widgets de un panel: copia su valor al panel (``"—"`` significa ninguno)."""
    v = st.session_state[clave_widget]
    estado.cambia_panel(id_, **{campo: None if v == "—" else v})


def _al_agregar(clave_widget: str) -> None:
    """Callback de «Agregar panel»: agrega el producto elegido y deja el widget en blanco."""
    clave = st.session_state[clave_widget]
    if clave:
        estado.agrega_panel(clave)
    st.session_state[clave_widget] = None


def _agregar(cat: dict[str, productos.Producto], n: int) -> None:
    """Popover para agregar un panel: botonera de favoritos y la lista completa."""
    lleno = n >= estado.MAX_PANELES
    with st.popover("Agregar panel", icon=":material/add:", disabled=lleno, width="stretch",
                    help=f"Hasta {estado.MAX_PANELES} paneles." if lleno else None):  # fmt: skip
        st.pills(
            "Favoritos", [k for k in productos.FAVORITOS if k in cat], key="agrega_fav",
            format_func=lambda k: cat[k].corta, on_change=_al_agregar, args=("agrega_fav",),
        )  # fmt: skip
        st.selectbox(
            "Otro producto", productos.ordenados(cat), index=None, key="agrega_otro",
            placeholder="Escribe para buscar…", format_func=lambda k: cat[k].etiqueta,
            on_change=_al_agregar, args=("agrega_otro",),
        )  # fmt: skip


def _controles(p: estado.Panel, n: int, cat: dict[str, productos.Producto], d: datos.Dia) -> None:
    """Fila de controles del panel ``n``: producto, ◀ ▶, opciones y quitar."""
    prod = cat[p.clave]
    k_clave = f"p{p.id}_clave"
    st.session_state[k_clave] = p.clave  # el panel es la fuente de verdad; el widget lo refleja
    c1, c2, c3, c4, c5 = st.columns([8, 1, 1, 1, 1], gap="small", vertical_alignment="bottom")
    c1.selectbox(
        f"Panel {n}", productos.ordenados(cat), key=k_clave,
        format_func=lambda k: ("★ " if k in productos.FAVORITOS else "") + cat[k].etiqueta,
        on_change=_al_cambiar, args=(p.id, "clave", k_clave),
    )  # fmt: skip
    for col, paso, icono, ayuda in ((c2, -1, ":material/chevron_left:", "Anterior"),
                                    (c3, +1, ":material/chevron_right:", "Siguiente")):  # fmt: skip
        col.button(
            "", icon=icono, key=f"p{p.id}_{paso}", help=f"{ayuda} en «{prod.grupo}»",
            on_click=estado.cambia_panel, args=(p.id,),
            kwargs={"clave": productos.vecino(p.clave, cat, paso)},
        )  # fmt: skip
    indices = [k for k in cat if k.startswith("idx:")]
    if prod.fuente == "pl" or (prod.es_goes and indices):
        with c4.popover("", icon=":material/tune:", help="Nivel o contornos ERA5"):
            if prod.fuente == "pl":
                nv = capas.niveles(d)
                k_nivel = f"p{p.id}_nivel"
                st.session_state[k_nivel] = p.nivel if p.nivel in nv else (850.0 if 850.0 in nv else nv[0])
                st.select_slider("Nivel (hPa)", options=nv, key=k_nivel, on_change=_al_cambiar,
                                 args=(p.id, "nivel", k_nivel))  # fmt: skip
            else:
                k_cont = f"p{p.id}_cont"
                st.session_state[k_cont] = p.contorno or "—"
                st.selectbox(
                    "Contornos ERA5", ["—", *indices], key=k_cont,
                    format_func=lambda k: k if k == "—" else cat[k].corta,
                    on_change=_al_cambiar, args=(p.id, "contorno", k_cont),
                    help="Isolíneas de un índice sobre la imagen; el umbral chileno en rojo.",
                )  # fmt: skip
    c5.button("", icon=":material/close:", key=f"p{p.id}_x", help="Quitar el panel",
              on_click=estado.quita_panel, args=(p.id,))  # fmt: skip


def _capa_panel(
    p: estado.Panel, n: int, cat: dict[str, productos.Producto], d: datos.Dia, t: pd.Timestamp,
    enc: graficos.Encuadre, sub: int,
) -> capas.Capa:  # fmt: skip
    """La capa del panel ``n`` con su número en el título (vacía si falta la imagen anterior)."""
    prod = cat[p.clave]
    c = capas.capa(d, prod, t, sub=sub, nivel=p.nivel)
    if c is None:
        return capas.vacia(f"{n} · {prod.corta} · sin imagen anterior", enc)
    return dataclasses.replace(c, titulo=f"{n} · {c.titulo}")


def _animar(
    fig: go.Figure, fondos: list[int], animados: list[int], visibles: list[estado.Panel],
    cat: dict[str, productos.Producto], d: datos.Dia, t: pd.Timestamp, enc: graficos.Encuadre,
) -> int:  # fmt: skip
    """Agrega a ``fig`` un cuadro por imagen GOES en ±1 h para los paneles ``animados``.

    Devuelve cuántos cuadros quedaron (0 o 1 = no se anima).
    """
    cerca = [ti for ti, _ in datos.imagenes(d) if abs(pd.Timestamp(ti) - t) <= pd.Timedelta("1h")]
    titulos = [a.to_plotly_json() for a in fig.layout.annotations]
    cuadros, etiquetas = [], []
    for ti in cerca:
        cs = {i: capas.capa(d, cat[visibles[i].clave], pd.Timestamp(ti), sub=PASO_ANIMACION)
              for i in animados}  # fmt: skip
        if any(c is None for c in cs.values()):
            continue
        anots = [dict(a) for a in titulos]
        datos_cuadro = []
        for i, c in cs.items():
            assert c is not None
            anots[i]["text"] = f"{i + 1} · {c.titulo}"
            z = graficos.z_fondo(c)
            datos_cuadro.append(go.Image(z=z) if c.es_rgb else go.Heatmap(z=z))
        cuadros.append(go.Frame(data=datos_cuadro, traces=[fondos[i] for i in cs],
                                name=str(len(cuadros)), layout={"annotations": anots}))  # fmt: skip
        etiquetas.append(pd.Timestamp(ti).strftime("%H:%M"))
    if len(cuadros) < 2:
        return len(cuadros)
    fig.frames = cuadros
    boton = {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True,
             "transition": {"duration": 0}}  # fmt: skip
    fig.update_layout(
        updatemenus=[{
            "type": "buttons", "direction": "left", "x": 0, "y": -0.04, "xanchor": "left",
            "yanchor": "top", "showactive": False, "bgcolor": tema.SURFACE_2,
            "bordercolor": tema.LINE, "font": {"family": tema.SANS, "size": 12},
            "buttons": [
                {"label": "Reproducir", "method": "animate", "args": [None, boton]},
                {"label": "Pausa", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0}, "mode": "immediate"}]},
            ],
        }],
        sliders=[{
            "x": 0.32, "len": 0.68, "y": -0.02, "currentvalue": {"visible": False},
            "bordercolor": tema.LINE, "tickcolor": tema.LINE, "font": {"family": tema.MONO, "size": 10},
            "steps": [{"label": e, "method": "animate",
                       "args": [[str(i)], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}]}
                      for i, e in enumerate(etiquetas)],
        }],
        margin={"b": 70},
    )  # fmt: skip
    return len(cuadros)


def pagina() -> None:
    """Dibuja la página."""
    ctx = estado.contexto()
    t = estado.t_actual()
    st.title("Mapas")
    if t is None:
        st.info("Este día no tiene datos con hora.")
        return
    t = pd.Timestamp(t)
    cat = productos.catalogo(ctx.dia)
    if not cat:
        st.info("Este día no tiene ERA5 ni GOES. Corre los scripts de descarga (ver AGENTS.md).")
        return
    if estado.paneles() is None:  # primera visita: un panel RGB, o el primer índice si no hay GOES
        inicial = "rgb:airmass" if "rgb:airmass" in cat else productos.ordenados(cat)[0]
        estado.fija_paneles([estado.nuevo_panel(inicial)])
    ps = estado.paneles() or []

    for clave, defecto in (("encuadre", "Zona de eventos"), ("viento", False), ("sub", 2),
                           ("animar", False)):  # fmt: skip
        estado.recuerda(clave)
        st.session_state.setdefault(clave, defecto)
    c1, c2, c3, c4, c5 = st.columns([2, 1.2, 1, 1, 1.3], vertical_alignment="bottom")
    vista = c1.segmented_control("Encuadre", ["Zona de eventos", "Región completa"], key="encuadre")
    with c2:
        _agregar(cat, len(ps))
    c3.toggle("Viento 850 hPa", key="viento", disabled=ctx.dia.pl is None,
              help="Flechas del viento en 850 hPa sobre todos los paneles (requiere niveles de presión).")  # fmt: skip
    c4.toggle("Animar GOES ±1 h", key="animar", disabled=not ctx.dia.goes,
              help=f"Loop de los paneles GOES (hasta {MAX_ANIMADOS}) de una hora antes a una hora después.")  # fmt: skip
    c5.select_slider("Detalle GOES", options=[1, 2, 3, 4], key="sub",
                     format_func=lambda s: {1: "máximo", 2: "alto", 3: "medio", 4: "bajo"}[s])  # fmt: skip
    for clave in ("encuadre", "viento", "sub", "animar"):
        estado.guarda(clave)
    if vista == "Región completa" or ctx.eventos.empty:
        enc = graficos.Encuadre(ctx.reg.norte, ctx.reg.sur, ctx.reg.oeste, ctx.reg.este)
    else:
        enc = graficos.encuadre_eventos(ctx.eventos, ctx.reg)

    visibles = [p for p in ps if p.clave in cat]
    faltan = [p for p in ps if p.clave not in cat]
    if not visibles:
        st.info("No hay paneles. Agrega uno con «Agregar panel»: el RGB Airmass es un buen comienzo.")
        return
    filas, cols = graficos.disposicion(len(visibles))
    for f in range(filas):
        columnas = st.columns(cols, gap="medium")
        for j, p in enumerate(visibles[f * cols : (f + 1) * cols]):
            with columnas[j]:
                _controles(p, f * cols + j + 1, cat, ctx.dia)

    animar = bool(st.session_state.get("animar"))
    goes_idx = [i for i, p in enumerate(visibles) if cat[p.clave].es_goes]
    animados = goes_idx[:MAX_ANIMADOS] if animar else []
    sub = int(st.session_state.get("sub", 2))
    lista = [
        _capa_panel(p, i + 1, cat, ctx.dia, t, enc, PASO_ANIMACION if i in animados else sub)
        for i, p in enumerate(visibles)
    ]
    contornos = [
        capas.capa(ctx.dia, cat[p.contorno], t) if p.contorno in cat and cat[p.clave].es_goes else None
        for p in visibles
    ]
    ref = datos.era5_ref(ctx.dia)
    fig, fondos = graficos.grilla(
        lista, contornos, enc, datos.costa(ctx.reg), eventos=ctx.eventos, punto=estado.punto(),
        clic=None if ref is None else (ref["latitude"].values, ref["longitude"].values),
        viento=capas.viento_850(ctx.dia, t, enc) if st.session_state.get("viento") else None,
    )  # fmt: skip
    n_cuadros = _animar(fig, fondos, animados, visibles, cat, ctx.dia, t, enc) if animados else 0
    st.plotly_chart(
        fig, width="stretch", theme=None, key="grilla", on_select=_al_clic,
        selection_mode="points", config={"scrollZoom": True},
    )  # fmt: skip

    notas = ["Rueda o botones del gráfico para acercar; todos los paneles se mueven juntos."]
    if ref is not None:
        notas.append("Clic en cualquier panel para elegir un punto (sondeo y series).")
    if any(c.umbral is not None for c in [*lista, *[c for c in contornos if c]]):
        notas.append("Línea roja: umbral chileno.")
    if goes_idx:
        notas.append("GOES: hora de inicio del barrido, sin corrección de paralaje (topes desplazados "
                     "10–20 km hacia el sur-suroeste).")  # fmt: skip
    notas += sorted({c.nota for c in lista if c.nota})
    if animar and animados:
        notas.append(
            f"Animación: {n_cuadros} imágenes cada 10 min, un píxel de cada {PASO_ANIMACION}."
            if n_cuadros >= 2 else "No hay suficientes imágenes alrededor de esta hora para animar."
        )  # fmt: skip
        if len(goes_idx) > MAX_ANIMADOS:
            notas.append(f"Se animan los primeros {MAX_ANIMADOS} paneles GOES.")
    if faltan:
        notas.append("Sin datos este día: " + ", ".join(p.clave for p in faltan) + ".")
    st.caption(" ".join(notas))

    vistos = dict.fromkeys(
        [cat[p.clave].variable for p in visibles] + [cat[p.contorno].variable for p in visibles
                                                     if p.contorno in cat]
    )  # fmt: skip
    ayudas = [textos.AYUDA[v] for v in vistos if v in textos.AYUDA]
    if ayudas:
        with st.expander("Qué estás viendo", expanded=estado.paso_actual() is not None):
            for a in ayudas:
                st.markdown(a)
            st.caption(textos.NOTA_AUSTRAL)
```

Notas para quien implemente:
- `st.button("", icon=...)`: Streamlit 1.64 acepta etiqueta vacía con icono. Si da advertencia de
  accesibilidad, usar la etiqueta `" "` y `label_visibility` no aplica a botones.
- Escribir en `st.session_state[k_clave]` antes de crear el widget sin pasar `index`/`value` es lo que
  permite que ◀ ▶ y el recorrido cambien el selector; **no** pasar `index=` a esos selectbox (Streamlit
  avisa si el valor llega por las dos vías).

- [ ] **Step 2: Lint, formato y tipos**

Run: `uv run ruff check scripts && uv run ruff format scripts && uv run pyright`
Expected: limpio.

- [ ] **Step 3: Prueba de humo con AppTest (página Mapas, sin navegador)**

```bash
uv run python - <<'EOF'
import sys
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(f"{__import__('os').getcwd()}/scripts/visor.py", default_timeout=240)
at.run()
at.session_state["ir_a"] = "mapas"
at.run()
assert not at.exception, [e.value for e in at.exception]
assert [t.value for t in at.title] == ["Mapas"]
ps = at.session_state["paneles"]
assert [p.clave for p in ps] == ["rgb:airmass"], ps
assert at.selectbox(key=f"p{ps[0].id}_clave").value == "rgb:airmass"
# ▶ en el panel 1: pasa al siguiente derivado GOES
at.button(key=f"p{ps[0].id}_1").click().run()
assert not at.exception, [e.value for e in at.exception]
print("tras ▶:", at.session_state["paneles"][0].clave)
# agregar dos paneles y elegir contorno en el GOES
from visor_app import estado
for k in ("idx:vgp_01", "goes:C13"):
    at.session_state["agrega_otro"] = k
    at.selectbox(key="agrega_otro").set_value(k).run()
assert not at.exception, [e.value for e in at.exception]
print("paneles:", [p.clave for p in at.session_state["paneles"]])
assert len(at.session_state["paneles"]) == 3
# activar animación con 2 paneles GOES
at.toggle(key="animar").set_value(True).run()
assert not at.exception, [e.value for e in at.exception]
# ir a Sondeo y volver: los paneles siguen
at.session_state["ir_a"] = "sondeo"; at.run()
at.session_state["ir_a"] = "mapas"; at.run()
assert len(at.session_state["paneles"]) == 3 and not at.exception
# quitar todos
for p in list(at.session_state["paneles"]):
    at.button(key=f"p{p.id}_x").click().run()
assert not at.exception and at.session_state["paneles"] == []
print("ok")
EOF
```

Esperado: `tras ▶: goes:dT` (el siguiente del grupo «GOES derivados»), `paneles:` con 3 claves y `ok`.
Si AppTest no deja escribir `agrega_otro` antes de `set_value`, quitar esa línea: basta con `set_value`.

- [ ] **Step 4: Revisión de los casos borde (Review Focus)**

Con el mismo esquema de AppTest, comprobar:
1. `ΔC13` en la primera hora del día (`at.session_state["t_idx"] = 0`): sin excepción; el título del
   panel dice «sin imagen anterior».
2. Recorrido guiado: `at.button` «Empezar recorrido» y luego «Siguiente» hasta el paso 2 → los paneles
   quedan `["idx:cizalle_01", "goes:C13"]` y la página es Mapas.

```bash
uv run python - <<'EOF'
import os
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(f"{os.getcwd()}/scripts/visor.py", default_timeout=240)
at.run()
at.session_state["ir_a"] = "mapas"; at.run()
p = at.session_state["paneles"][0]
at.selectbox(key=f"p{p.id}_clave").set_value("goes:dT").run()
at.session_state["t_idx"] = 0; at.run()
assert not at.exception, [e.value for e in at.exception]
empezar = next(b for b in at.button if b.label == "Empezar recorrido")
empezar.click().run()
siguiente = next(b for b in at.button if b.label == "Siguiente")
siguiente.click().run()
assert not at.exception, [e.value for e in at.exception]
print([q.clave for q in at.session_state["paneles"]], [t.value for t in at.title])
EOF
```

Esperado: `['idx:cizalle_01', 'goes:C13'] ['Mapas']`.

- [ ] **Step 5: Commit**

```bash
git add scripts/visor_app/p_mapas.py
git commit -m "Reemplazar el par ERA5 | GOES de Mapas por una grilla de paneles con zoom sincronizado"
```

---

### Task 6: Documentación y revisión visual

**Files:**
- Modify: `AGENTS.md` (párrafo **Visor**)

- [ ] **Step 1: Actualizar el párrafo del visor en `AGENTS.md`**

Después de «…estado compartido está en `visor_app/estado.py` (`recuerda`/`guarda` copian los widgets de
cada página bajo `_<clave>`).», agregar:

```markdown
La página Mapas es una grilla de 1 a 6 paneles en una sola figura plotly con ejes compartidos (el zoom va
sincronizado). Cada panel muestra un producto de `visor_app/productos.py` (claves `idx:`, `sfc:`, `pl:`,
`goes:`, `rgb:`), calculado por `visor_app/capas.py` (incluye el RGB Airmass); la lista de paneles vive en
`st.session_state["paneles"]` (`estado.Panel`), no en widgets, y el recorrido guiado la fija con `Paso.paneles`.
```

- [ ] **Step 2: Verificación final**

Run: `uv run ruff check scripts && uv run ruff format --check scripts && uv run pyright`
Expected: limpio.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "Documentar la grilla de mapas del visor"
```

- [ ] **Step 4: Revisión visual de Pablo**

Pedir a Pablo que corra `uv run streamlit run scripts/visor.py`, abra Mapas y revise: el Airmass inicial
(colores plausibles, norte arriba, alineado con la costa), agregar hasta 6 paneles (la disposición cambia
1 → 1×2 → 2×2 → 2×3), zoom con la rueda en un panel y que los demás lo sigan, ◀ ▶, contornos de VGP sobre
el C13, animación con 2 paneles GOES y el clic que elige punto desde un panel GOES. Anotar lo que haya que
ajustar (alturas, espaciado de barras de color, ancho de los controles con 3 columnas) como cambios aparte.
