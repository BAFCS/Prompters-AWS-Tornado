## Resumen

<!-- Qué cambia y por qué, en dos o tres frases. -->

## Cambios

<!-- Lista breve por área: scripts de datos, visor, figuras, documentación... -->

-

## Cómo probarlo

<!-- Comandos y datos necesarios (qué región/día descargar, qué página abrir). -->

```bash
uv sync
uv run ruff check scripts && uv run ruff format --check scripts && uv run pyright
uv run python -m unittest discover -s tests -v
```

## Lista de verificación

- [ ] `ruff check`, `ruff format --check` y `pyright` pasan limpios
- [ ] Las pruebas de `tests/` pasan
- [ ] Si cambia una figura, se regeneró y se comparó con la anterior
- [ ] Si cambia `docs/mesociclones_chile.md`, se actualizó `scripts/viewer_app/texts.py`
- [ ] Si cambia un color del tema, se cambió en `.streamlit/config.toml` y en `viewer_app/theme.py`
- [ ] Los signos y umbrales respetan el hemisferio sur (SRH negativa, *left-mover*, umbrales chilenos)
- [ ] `AGENTS.md` y `README.md` siguen al día
- [ ] No se versionan datos (`data/`, `*.nc`, `*.xlsx`, ...)

## Notas

<!-- Decisiones abiertas, dependencias con otras PR, capturas del visor si cambia la interfaz. -->
