"""Métricas del modelo v2 ``physical`` y la tarjeta («stamp») que las muestra en el visor.

Fuente: ``.agents/tasks/hibrido/v2_metricas_clasificacion.txt`` (validación dejando un evento afuera,
LOEO, de la rama ``merge/datos-modelo``; 1181 filas, 37 positivas, prevalencia 0,031). Las cifras
van redondeadas como se presentan al usuario. Es la única fuente de las cifras para la portada
«Problema» y las páginas «Mapa del modelo» y «Predecir»: la interfaz las formatea desde aquí con :func:`fmt`.
"""

import math

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


# Matrices de confusión (etiqueta, TP, FP, FN, TN) de .agents/tasks/hibrido/v2_metricas_clasificacion.txt;
# las métricas macro se calculan desde aquí, no se copian a mano.
CONFUSION: tuple[tuple[str, int, int, int, int], ...] = (
    ("Baseline ERA5 (0,50)", 16, 22, 21, 1122),
    ("Baseline ERA5 (0,24)", 22, 41, 15, 1103),
    ("Physical (0,50)", 17, 18, 20, 1126),
    ("Physical (0,28)", 25, 26, 12, 1118),
    ("Physical holdout (0,50)", 20, 15, 17, 1095),
    ("Physical holdout (0,47)", 22, 15, 15, 1095),
)

MACRO_NOTE = (
    "El macro F1 se infla por la clase 'no tornado' (fácil); "
    "para decidir, mirar F1 clase 1, MCC y PR-AUC."
)


def macro_row(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    """F1 por clase, macro (promedio simple de las dos clases) y MCC de una matriz de confusión."""
    prec = (tp / (tp + fp), tn / (tn + fn))
    rec = (tp / (tp + fn), tn / (tn + fp))
    mcc = (tp * tn - fp * fn) / math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    f1_1 = 2 * tp / (2 * tp + fp + fn)
    f1_0 = 2 * tn / (2 * tn + fp + fn)
    return {
        "f1_1": f1_1,
        "f1_0": f1_0,
        "macro_f1": (f1_1 + f1_0) / 2,
        "macro_precision": sum(prec) / 2,
        "macro_recall": sum(rec) / 2,
        "mcc": mcc,
    }


def macro_table() -> str:
    """Tabla markdown de la comparación macro, una fila por matriz de :data:`CONFUSION`."""
    head = (
        "| Modelo (umbral) | F1 clase 1 | F1 clase 0 | Macro F1 | Macro Precisión | Macro Recall | MCC |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows = [
        f"| {label} | " + " | ".join(fmt(v, 3) for v in macro_row(*cm).values()) + " |"
        for label, *cm in CONFUSION
    ]
    return "\n".join([head, *rows])


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
        with st.expander("Comparación macro"):
            st.markdown(macro_table())
            st.caption(
                "Macro = promedio simple de las dos clases; macro recall = balanced accuracy. "
                + MACRO_NOTE
            )
        st.caption(m["note"])
