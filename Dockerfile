# Imagen del visor Streamlit. Lleva también los scripts de datos, así que la misma imagen sirve para
# descargar y procesar en la máquina: los datos van en un volumen montado en /app/data.
FROM ghcr.io/astral-sh/uv:0.9.5-python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY .streamlit .streamlit
COPY scripts scripts
COPY figs figs

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "scripts/viewer/viewer.py", "--server.address=0.0.0.0"]
