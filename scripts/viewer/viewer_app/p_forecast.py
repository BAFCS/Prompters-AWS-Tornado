"""Página «Mapa del modelo»: predicción del XGBoost híbrido (ERA5 + imágenes GOES) sobre Chile.

Muestra el sitio que genera la rama ``merge/datos-modelo`` (``scripts/app/infer_grid.py`` +
``scripts/app/prototype.py``), publicado en el mismo CloudFront bajo ``/resultados/sitio/``. El
modelo es el XGBoost híbrido de ``scripts/model`` (config ``embeddings``: índices ERA5, variables
GOES y embeddings Bedrock Titan de la imagen), entrenado con etiquetas reales del catálogo. La URL se
puede cambiar con la variable de entorno ``FORECAST_SITE_URL`` (por ejemplo para pruebas locales).
"""

import os

import streamlit as st

from viewer_app import theme

DEFAULT_URL = "https://d1m48zea07nk1y.cloudfront.net/resultados/sitio/index.html"


def site_url() -> str:
    """URL del sitio de predicciones (``FORECAST_SITE_URL`` o la publicada en CloudFront)."""
    return os.environ.get("FORECAST_SITE_URL", DEFAULT_URL)


def page() -> None:
    """Dibuja la página con el mapa embebido y el contexto del modelo."""
    st.title("Mapa del modelo")
    st.markdown(
        "Índice de favorabilidad del **XGBoost híbrido** (índices ERA5 + variables GOES + embedding "
        "de la imagen GOES con Bedrock Titan) por celda y hora (en hora de Chile), con los tornados del "
        "catálogo marcados en su hora. Elige el día y mueve la hora."
    )
    st.caption(
        "Índice relativo: no es una probabilidad calibrada ni un pronóstico oficial. "
        "El 30 y 31 de mayo de 2019 se predicen **fuera de muestra** (el modelo no vio esos días); "
        "los demás días los vio en el entrenamiento. Validación dejando un evento afuera: "
        "CSI 0,345 (híbrido) frente a 0,294 (solo variables físicas) y 0,274 (solo ERA5)."
    )
    url = site_url()
    # El mapa toma los colores del tema activo del visor (claro u oscuro).
    sep = "&" if "?" in url else "?"
    themed = f"{url}{sep}theme={'dark' if theme.is_dark() else 'light'}"
    st.iframe(themed, height=760)
    st.link_button("Abrir el mapa en pantalla completa", themed, icon=":material/open_in_new:")
