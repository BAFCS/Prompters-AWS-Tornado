---
name: viewer
description: Levanta el visor Streamlit del repo (scripts/viewer/viewer.py) y lo revisa en el navegador con Playwright MCP, en modo claro y oscuro. Úsala para ver, probar o capturar el visor, o para confirmar en la app real un cambio en scripts/viewer/viewer.py o scripts/viewer/viewer_app/ (no basta con las pruebas de tests/). No la uses para los scripts de figuras ni de datos.
---

# Revisar el visor en el navegador

Las pruebas de `tests/` (AppTest) no ejecutan el JavaScript ni el CSS del tema, así que lo visual
(vigía del modo, plotly, columnas que se apilan) solo se ve en un navegador real.

## 1. Arrancar

```bash
PUERTO=$(python3 -c 'import socket; s = socket.socket(); s.bind(("", 0)); print(s.getsockname()[1])')
uv run streamlit run scripts/viewer/viewer.py --server.headless true --server.port "$PUERTO" \
  > "${TMPDIR:-/tmp}/visor-$PUERTO.log" 2>&1 &
```

Lánzalo en segundo plano con un puerto libre (otra sesión o worktree puede tener ya un visor en
8501 u otro puerto fijo, y lo estarías probando a él) y espera a que responda antes de abrirlo:
`curl -sf http://localhost:$PUERTO/_stcore/health` devuelve `ok`.

## 2. Recorrer

Páginas (barra de navegación superior): `/` Problema y `/datos` (se ven aunque no haya datos), `/caso`
(Caso de estudio) y `/mapas`. Las demás necesitan datos en `data/crops/<region>/`; si no hay,
muestran un aviso de "sin datos", que es el comportamiento esperado.

Con Playwright MCP (Chromium):
- Navega a cada página y espera a que desaparezca el indicador "Running…" de Streamlit antes de
  capturar. Plotly tarda un poco más que el resto.
- Revisa la consola (`browser_console_messages`): no debe haber errores de JavaScript.
- Captura a 1440×900 y a tablet (1024×768 con la barra lateral abierta): las columnas de
  `theme.columns` deben apilarse sin desbordar.

## 3. Modo claro y oscuro

Alterna con el botón "Cambiar a modo oscuro / claro" de la barra lateral (`theme.mode_button`); el
vigía marca `<html data-theme>` y redibuja plotly sin recargar. Comprueba, en cada modo, que
`document.documentElement.dataset.theme` pasó de `light` a `dark` (o al revés), que las figuras plotly cambiaron de fondo y que el
texto sigue legible. Ojo: `browser_emulate_media` cambia `prefers-color-scheme`, que no es lo mismo
que el botón; prueba los dos caminos si tocaste `theme.py`.

## 4. Cerrar

Cierra el navegador y detén solo tu servidor (`kill` del PID que lanzaste, nunca por nombre: puede
haber otros visores corriendo). Las capturas quedan en `.playwright-mcp/`, que está en `.gitignore`;
no las copies a `figs/`.

Informa qué páginas y modos revisaste, con las capturas relevantes y cualquier error de consola.
