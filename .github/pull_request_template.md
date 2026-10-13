## Resumen

<!-- Qué cambia y por qué, en dos o tres frases. -->

## Cambios

<!-- Lista breve por área: datos, modelos, visor, figuras, documentación... -->

-

## Cómo probarlo

<!-- Comandos y datos necesarios (qué región y días descargar, qué script correr). -->

```bash
uv sync
make check
```

## Lista de verificación

- [ ] `make check` pasa (ruff, formato, pyright y pruebas)
- [ ] La lógica nueva (un índice, una etiqueta, un recorte) tiene su prueba en `tests/`
- [ ] Los signos y umbrales respetan el hemisferio sur (SRH negativa, *left-mover*, umbrales chilenos)
- [ ] No se versionan datos ni credenciales (`data/`, `*.nc`, `*.xlsx`, `.env`, ...)
- [ ] `AGENTS.md`, `README.md` y `docs/` siguen al día
- [ ] Si toca el visor: textos alineados con `docs/` y colores cambiados en `.streamlit/config.toml` y `viewer_app/theme.py`

## Notas

<!-- Decisiones tomadas, dependencias con otras PR, capturas si cambia una figura o el visor. -->
