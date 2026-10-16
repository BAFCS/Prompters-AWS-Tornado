"""Métricas de clasificación del v2 a partir de la validación LOEO fuera de partición.

Reproduce ``loeo.run_loeo`` con la tabla, las particiones y las columnas guardadas del modelo y
calcula F1, precisión, recall, ROC/PR-AUC, Brier, MCC e intervalos bootstrap por evento.
Uso: ``uv run python scripts/app/oof_metrics.py``
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

sys.path[:0] = ["scripts", "scripts/model", "scripts/model/sm_job", "scripts/app"]
import loeo  # noqa: E402
import train_hybrid  # noqa: E402, F401  (aplica el parche de árboles mínimos a loeo.fit_xgb)


def oof(model_dir: str, config: str) -> tuple[pd.DataFrame, dict]:
    root = Path(model_dir)
    table = pd.read_parquet(root / f"work/channels/{config}/train/part-0.parquet")
    fj = json.loads((root / "folds.json").read_text())
    folds = loeo.folds_from_json(fj)
    feats = json.loads((root / config / "feature_columns.json").read_text())["required"]
    res = loeo.run_loeo(table, feats, folds, int(fj.get("seed", 0)))
    mj = res.to_metrics_json(config)
    rows = [
        (o.held, o.dev, yt, pt)
        for o in res.outcomes
        if not o.skipped
        for yt, pt in zip(o.y_test, o.p_test, strict=False)
    ]
    d = pd.DataFrame(rows, columns=["held", "dev", "y", "p"])
    return d[~d["dev"]], mj


def report(name: str, d: pd.DataFrame, mj: dict) -> None:
    y, p = d["y"].to_numpy().astype(int), d["p"].to_numpy()
    print(
        f"\n== {name}: {len(d)} filas, {y.sum()} positivas, {len(y) - y.sum()} no etiquetadas (prevalencia {y.mean():.3f})"
    )
    print(f"   reproduce CSI LOEO {mj['selection']['csi']:.3f}")
    print(
        f"   ROC-AUC {roc_auc_score(y, p):.3f} | PR-AUC {average_precision_score(y, p):.3f} (azar {y.mean():.3f}) | Brier {brier_score_loss(y, p):.3f}"
    )
    pr, rc, th = precision_recall_curve(y, p)
    f1s = 2 * pr * rc / (pr + rc + 1e-12)
    k = int(np.nanargmax(f1s[:-1]))
    for t, lab in ((0.5, "umbral 0,50"), (float(th[k]), f"umbral F1-óptimo {th[k]:.2f}")):
        q = (p >= t).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, q, labels=[0, 1]).ravel()
        print(
            f"   [{lab}] F1 {f1_score(y, q):.3f} | Precisión {precision_score(y, q, zero_division=0):.3f} | Recall {recall_score(y, q):.3f} | "
            f"Accuracy {accuracy_score(y, q):.3f} | Bal.Acc {balanced_accuracy_score(y, q):.3f} | MCC {matthews_corrcoef(y, q):.3f} | TP {tp} FP {fp} FN {fn} TN {tn}"
        )
    rng = np.random.default_rng(0)
    g = d["held"].unique()
    f1b, apb = [], []
    for _ in range(1000):
        b = pd.concat([d[d["held"] == x] for x in rng.choice(g, len(g))])
        if b["y"].sum() == 0:
            continue
        f1b.append(f1_score(b["y"], (b["p"] >= 0.5).astype(int)))
        apb.append(average_precision_score(b["y"], b["p"]))
    print(
        f"   IC95% (bootstrap por evento): F1@0,5 [{np.percentile(f1b, 2.5):.2f}, {np.percentile(f1b, 97.5):.2f}] | PR-AUC [{np.percentile(apb, 2.5):.2f}, {np.percentile(apb, 97.5):.2f}]"
    )


def main() -> None:
    """Imprime las métricas de physical, baseline_era5 y el modelo retenido."""
    for name, md, cfg in [
        ("v2 physical (completo)", "data/model/v2/hibrido", "physical"),
        ("v2 baseline_era5 (completo)", "data/model/v2/hibrido", "baseline_era5"),
        ("v2 physical (sin 2019-05-30/31)", "data/model/v2/hibrido_holdout_20190530", "physical"),
    ]:
        d, mj = oof(md, cfg)
        report(name, d, mj)


if __name__ == "__main__":
    main()
