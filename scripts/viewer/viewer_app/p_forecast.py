"""Página «Mapa del modelo»: predicción del XGBoost v2 ``physical`` (ERA5 + GOES) sobre Chile.

Muestra el sitio que genera la rama ``merge/datos-modelo`` (``scripts/app/infer_grid.py`` +
``scripts/app/prototype.py``), publicado en el mismo CloudFront bajo ``/resultados/sitio/``. El
modelo es el XGBoost v2 de ``scripts/model`` (config ``physical``: índices ERA5 y variables físicas
GOES C08/C13), entrenado con etiquetas reales del catálogo; sus métricas van en la tarjeta de
:mod:`viewer_app.model_metrics`. La URL se puede cambiar con la variable de entorno
``FORECAST_SITE_URL`` (por ejemplo para pruebas locales).
"""

import os

import streamlit as st

from viewer_app import model_metrics, theme

DEFAULT_URL = "https://d1m48zea07nk1y.cloudfront.net/resultados/sitio/index.html"


def site_url() -> str:
    """URL del sitio de predicciones (``FORECAST_SITE_URL`` o la publicada en CloudFront)."""
    return os.environ.get("FORECAST_SITE_URL", DEFAULT_URL)


def page() -> None:
    """Dibuja la página con el mapa embebido y el contexto del modelo."""
    st.title("Mapa del modelo")
    st.markdown(
        "Índice de favorabilidad del **XGBoost v2 «physical»** (índices ERA5 + variables físicas "
        "GOES C08/C13) por celda y hora (en hora de Chile), con los tornados del catálogo marcados "
        "en su hora. Elige el día y mueve la hora."
    )
    st.caption(
        "Índice relativo: no es una probabilidad calibrada ni un pronóstico oficial. "
        "Modelo v2: GOES de una sola fuente (bucket del equipo) para días con y sin tornado. "
        "El 30 y 31 de mayo de 2019 se predicen **fuera de muestra** (el modelo no vio esos días); "
        "los demás días los vio en el entrenamiento. Las métricas de validación dejando un evento "
        "afuera están en la tarjeta de abajo; con pocos eventos (37) las diferencias pequeñas "
        "entre modelos están dentro del ruido."
    )
    model_metrics.stamp("forecast")
    url = site_url()
    # El mapa toma los colores del tema activo del visor (claro u oscuro).
    sep = "&" if "?" in url else "?"
    themed = f"{url}{sep}theme={'dark' if theme.is_dark() else 'light'}"
    st.iframe(themed, height=760)
    st.caption("La escala del mapa (lineal o relativa al máximo del día) se elige dentro del mapa.")
    st.link_button("Abrir el mapa en pantalla completa", themed, icon=":material/open_in_new:")
