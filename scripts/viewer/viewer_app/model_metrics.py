"""Métricas del modelo v2 ``physical`` y la tarjeta («stamp») que las muestra en el visor.

Fuente: ``.agents/tasks/hibrido/v2_metricas_clasificacion.txt`` (validación dejando un evento afuera,
LOEO, de la rama ``merge/datos-modelo``; 1181 filas, 37 positivas, prevalencia 0,031). Las cifras
van redondeadas como se presentan al usuario. Es la única fuente de las cifras para las páginas
«Mapa del modelo» y «Predecir»: la interfaz las formatea desde aquí con :func:`fmt`.
"""

import streamlit as st

V2_PHYSICAL: dict = {
    "model": 'XGBoost v2 "physical" (ERA5 + GOES físicos)',
    "date": "2026-10-15",
    "roc_auc": 0.893,
    "pr_auc": 0.429,
    "pr_auc_ci": (0.32, 0.60),
    "chance": 0.031,
    "brier": 0.024,
    "at_050": {
        "f1": 0.47,
        "f1_ci": (0.34, 0.58),
        "precision": 0.49,
        "recall": 0.46,
        "mcc": 0.46,
        "csi": 0.31,
    },
    "at_028": {"f1": 0.57, "precision": 0.49, "recall": 0.68, "mcc": 0.56},
    "holdout": {"f1": 0.56, "pr_auc": 0.51, "csi": 0.39},
    "baseline_era5": {"roc_auc": 0.816, "f1": 0.43},
    "note": (
        "Puntaje = índice relativo de favorabilidad, no probabilidad calibrada. "
        "Accuracy no se reporta por el desbalance 1:30."
    ),
}


def fmt(x: float, nd: int = 2) -> str:
    """Número con ``nd`` decimales y coma decimal (0.893 → «0,893» con ``nd=3``)."""
    return f"{x:.{nd}f}".replace(".", ",")


def summary_lines() -> list[str]:
    """Líneas de texto del stamp: dos principales y tres de detalle (umbral óptimo, holdout, baseline)."""
    m = V2_PHYSICAL
    a, b, h, base = m["at_050"], m["at_028"], m["holdout"], m["baseline_era5"]
    lo, hi = m["pr_auc_ci"]
    flo, fhi = a["f1_ci"]
    return [
        f"ROC-AUC {fmt(m['roc_auc'], 3)} · PR-AUC {fmt(m['pr_auc'], 3)} "
        f"(IC95 {fmt(lo)}–{fmt(hi)}; azar {fmt(m['chance'], 3)}) · Brier {fmt(m['brier'], 3)}",
        f"Umbral 0,50: F1 {fmt(a['f1'])} (IC95 {fmt(flo)}–{fmt(fhi)}) · "
        f"Precisión {fmt(a['precision'])} · Recall {fmt(a['recall'])} · MCC {fmt(a['mcc'])} · "
        f"CSI {fmt(a['csi'])}",
        f"Umbral 0,28 (F1 óptimo): F1 {fmt(b['f1'])} · Precisión {fmt(b['precision'])} · "
        f"Recall {fmt(b['recall'])} · MCC {fmt(b['mcc'])}",
        f"Holdout sin 30–31/05/2019: F1 {fmt(h['f1'])} · PR-AUC {fmt(h['pr_auc'])} · "
        f"CSI {fmt(h['csi'])}",
        f"Baseline solo ERA5: ROC-AUC {fmt(base['roc_auc'], 3)} · F1 {fmt(base['f1'])}",
    ]


def stamp(key: str) -> None:
    """Tarjeta compacta con las métricas del modelo v2; el detalle va en un desplegable."""
    m = V2_PHYSICAL
    lines = summary_lines()
    with st.container(border=True, key=f"stamp_{key}"):
        st.markdown(f"**Métricas del modelo** · {m['model']} · {m['date']}")
        st.markdown("  \n".join(lines[:2]))
        with st.expander("Más métricas (umbral óptimo, holdout, baseline)"):
            st.markdown("\n".join(f"- {line}" for line in lines[2:]))
        st.caption(m["note"])
