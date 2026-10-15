"""Reductor: PCA de los embeddings a 8-16 componentes (lógica pura, solo NumPy).

No importa ``common`` ni bibliotecas de E/S, para usarse igual en la Validación_LOEO local y dentro
del contenedor de SageMaker. La PCA se calcula con la SVD de la matriz centrada de las filas válidas
(sin NaN) y el signo de cada componente se fija para que su valor de mayor magnitud sea positivo:
así el ajuste es determinista. ``save``/``load`` usan ``.npz`` en ``float64`` (ida y vuelta exacta).

- ``fit`` excluye las filas con NaN o infinitos y falla si quedan menos filas válidas que
  componentes (Req. 5.7, 5.8).
- ``transform`` conserva el número y el orden de filas y deja NaN en las filas inválidas; falla si
  la dimensión difiere de la del ajuste (Req. 5.3, 5.7, 5.8).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

MIN_COMPONENTS = 8
MAX_COMPONENTS = 16
DEFAULT_COMPONENTS = 8


def _matrix(emb: np.ndarray) -> np.ndarray:
    """``emb`` como matriz ``float64`` de dos dimensiones."""
    x = np.asarray(emb, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError(f"se esperaba una matriz (filas × dimensión); se recibió forma {x.shape}")
    return x


class Reducer:
    """PCA ajustada con NumPy, con ``n_components`` entre 8 y 16 (Req. 5.1, 5.6)."""

    def __init__(self, n_components: int, model_id: str) -> None:
        """Reductor sin ajustar de ``n_components`` componentes para el modelo ``model_id``."""
        ok = isinstance(n_components, int | np.integer) and not isinstance(n_components, bool)
        if not ok or not MIN_COMPONENTS <= int(n_components) <= MAX_COMPONENTS:
            raise ValueError(
                f"n_components={n_components!r} fuera del rango permitido "
                f"[{MIN_COMPONENTS}, {MAX_COMPONENTS}] (enteros)"
            )
        self.n_components = int(n_components)
        self.model_id = model_id
        self.mean: np.ndarray | None = None
        self.components: np.ndarray | None = None
        self.explained_variance_ratio: np.ndarray | None = None
        self.input_dim: int | None = None

    def fit(self, emb: np.ndarray) -> Reducer:
        """Ajusta la PCA con las filas de ``emb`` sin NaN ni infinitos y devuelve ``self``."""
        x = _matrix(emb)
        valid = np.isfinite(x).all(axis=1)
        n_valid = int(valid.sum())
        if n_valid < self.n_components:
            raise ValueError(
                f"se esperaban al menos {self.n_components} filas con embedding válido; "
                f"se recibieron {n_valid}"
            )
        if x.shape[1] < self.n_components:
            raise ValueError(
                f"se esperaba una dimensión de al menos {self.n_components}; "
                f"se recibió {x.shape[1]}"
            )
        xv = x[valid]
        mean = xv.mean(axis=0)
        _, s, vt = np.linalg.svd(xv - mean, full_matrices=False)
        comps = vt[: self.n_components].copy()
        rows = np.arange(comps.shape[0])
        signs = np.sign(comps[rows, np.abs(comps).argmax(axis=1)])
        signs[signs == 0] = 1.0
        comps *= signs[:, None]
        var = s**2
        total = float(var.sum())
        ratio = var[: self.n_components] / total if total > 0 else np.zeros(self.n_components)
        self.mean = mean
        self.components = comps
        self.explained_variance_ratio = np.clip(ratio, 0.0, 1.0)
        self.input_dim = int(x.shape[1])
        return self

    def _fitted(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
        """``(mean, components, ratio, input_dim)``; falla si el Reductor no está ajustado."""
        if (
            self.mean is None
            or self.components is None
            or self.explained_variance_ratio is None
            or self.input_dim is None
        ):
            raise RuntimeError("el Reductor no está ajustado: llama a fit primero")
        return self.mean, self.components, self.explained_variance_ratio, self.input_dim

    def transform(self, emb: np.ndarray) -> np.ndarray:
        """Proyección ``N × n_components`` en el orden de entrada; NaN en las filas inválidas."""
        mean, comps, _, dim = self._fitted()
        x = _matrix(emb)
        if x.shape[1] != dim:
            raise ValueError(f"dimensión esperada {dim}; se recibió {x.shape[1]}")
        out = np.full((x.shape[0], self.n_components), np.nan)
        valid = np.isfinite(x).all(axis=1)
        out[valid] = (x[valid] - mean) @ comps.T
        return out

    def explained_variance(self) -> tuple[list[float], list[float]]:
        """Fracción de varianza explicada por componente y acumulada (Req. 5.4)."""
        _, _, ratio, _ = self._fitted()
        cumulative = np.minimum(np.cumsum(ratio), 1.0)
        return [float(v) for v in ratio], [float(v) for v in cumulative]

    def save(self, path: Path) -> None:
        """Guarda el Reductor ajustado en ``path`` (``.npz``) vía ``.tmp`` + ``os.replace``."""
        mean, comps, ratio, dim = self._fitted()
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("wb") as f:
            np.savez(
                f,
                mean=mean,
                components=comps,
                explained_variance_ratio=ratio,
                n_components=np.int64(self.n_components),
                model_id=np.str_(self.model_id),
                input_dim=np.int64(dim),
            )
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> Reducer:
        """Carga un Reductor guardado con ``save``."""
        with np.load(path, allow_pickle=False) as z:
            r = cls(int(z["n_components"]), str(z["model_id"]))
            r.mean = np.asarray(z["mean"], dtype=np.float64)
            r.components = np.asarray(z["components"], dtype=np.float64)
            r.explained_variance_ratio = np.asarray(z["explained_variance_ratio"], dtype=np.float64)
            r.input_dim = int(z["input_dim"])
        return r
