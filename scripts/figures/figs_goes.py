#!/usr/bin/env python3
"""Figura 3: GOES-16 ABI banda 13 sobre Chile centro-sur durante el brote del 30 de mayo de 2019.

Lee imágenes consecutivas de ``ABI-L2-CMIPF`` (disco completo, 2 km, cada 10 min) desde
``data/goes/*.nc``, recorta Chile centro-sur con la proyección geoestacionaria del ABI (la directa,
``fwd``, está aquí; la inversa es ``common.latlon``) y dibuja la temperatura de brillo de la primera y la última imagen, más su tendencia en diez
minutos. Produce ``figs/fig3_goes_20190530.png``. Uso: ``uv run python scripts/figures/figs_goes.py``.
"""

import glob
import re
import sys
import warnings
from pathlib import Path

import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import median_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

warnings.filterwarnings("ignore")
matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
OUT, DATA = ROOT / "figs", ROOT / "data"
ACC, SEV, COLD, WARM, MUT = "#0E6A63", "#D2492A", "#4C7FB8", "#C98A3C", "#64757B"
INK, LINE = "#0C1518", "#C9D3D6"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.edgecolor": LINE,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUT,
        "ytick.color": MUT,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
    }
)

LAT0, LAT1, LON0, LON1 = -44.0, -32.0, -78.0, -68.0
REQ, RPOL, HSAT, LON_0 = 6378137.0, 6356752.31414, 42164160.0, -75.0
E2 = 1 - (RPOL**2 / REQ**2)


def fwd(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convierte latitud/longitud (grados) en ángulos de barrido x, y del ABI (radianes)."""
    lat, lon = np.radians(lat), np.radians(lon)
    latc = np.arctan((RPOL**2 / REQ**2) * np.tan(lat))
    rc = RPOL / np.sqrt(1 - E2 * np.cos(latc) ** 2)
    sx = HSAT - rc * np.cos(latc) * np.cos(lon - np.radians(LON_0))
    sy = -rc * np.cos(latc) * np.sin(lon - np.radians(LON_0))
    sz = rc * np.sin(latc)
    return np.arcsin(-sy / np.sqrt(sx**2 + sy**2 + sz**2)), np.arctan(sz / sx)


def read(f: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Lee el archivo GOES ``f`` recortado al recuadro ``LAT0..LAT1`` × ``LON0..LON1``.

    Devuelve la temperatura de brillo (K, NaN bajo 150 K), la latitud y la longitud de cada píxel,
    y el instante ``t`` del archivo (segundos desde el 1-ene-2000 12 UTC).
    """
    with h5py.File(f, "r") as h:
        x, y = common.axis(h, "x"), common.axis(h, "y")
        xa, ya = fwd(np.array([LAT0, LAT1, LAT0, LAT1]), np.array([LON0, LON0, LON1, LON1]))
        i0, i1 = np.searchsorted(x, [xa.min(), xa.max()])
        j = np.argsort(y)
        ys = y[j]
        k0, k1 = np.searchsorted(ys, [ya.min(), ya.max()])
        j0, j1 = len(y) - k1 - 1, len(y) - k0 + 1
        i0, i1, j0, j1 = max(i0 - 4, 0), min(i1 + 4, len(x)), max(j0 - 4, 0), min(j1 + 4, len(y))
        cmi = common.dataset(h, "CMI")
        bt = cmi[j0:j1, i0:i1] * common.num(cmi, "scale_factor") + common.num(cmi, "add_offset")
        bt[bt < 150] = np.nan
        lat, lon = common.latlon(x[i0:i1], y[j0:j1], common.dataset(h, "goes_imager_projection"))
        t = common.dataset(h, "t")[()]
    return bt, lat, lon, t


fs = sorted(glob.glob(str(DATA / "goes" / "*.nc")))


def stamp(f: str) -> str:
    """Extrae del nombre del archivo GOES la hora de inicio del barrido, como "HH:MM UTC"."""
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", f)
    assert m, f"nombre de archivo GOES inesperado: {f}"
    return f"{m.group(3)}:{m.group(4)} UTC"


data = [read(f) for f in fs]
print("recorte:", data[0][0].shape, "| BT min:", np.nanmin(data[-1][0]))

# escala IR: gris para topes cálidos, color para los muy fríos
cols = [
    (0.00, "#3B2C22"),
    (0.28, "#8C8175"),
    (0.46, "#E8E6E1"),
    (0.52, "#FFFFFF"),
    (0.60, "#4C7FB8"),
    (0.70, "#2E9E8F"),
    (0.80, "#E3C34A"),
    (0.90, "#D2492A"),
    (1.00, "#6B1B2E"),
]
cmap = LinearSegmentedColormap.from_list("ir", [(1 - p, c) for p, c in cols][::-1])
VMIN, VMAX = 190, 300

TOR = [
    (-37.463, -72.330, "Los Ángeles  EF2"),
    (-36.726, -71.810, "Coihueco  EF2"),
    (-37.106, -72.119, "San Miguel de Itata"),
    (-36.496, -71.943, "Quilelto"),
    (-37.939, -72.498, "Collipulli"),
]

fig = plt.figure(figsize=(11.6, 6.2))
gs = fig.add_gridspec(
    1, 3, width_ratios=[1, 1, 1.06], wspace=0.08, left=0.045, right=0.985, top=0.795, bottom=0.09
)
axes = [fig.add_subplot(gs[0, i]) for i in range(3)]
for ax, (bt, lat, lon, _t), f in zip(axes[:2], [data[0], data[-1]], [fs[0], fs[-1]], strict=True):
    m = ax.pcolormesh(
        lon, lat, bt, cmap=cmap, vmin=VMIN, vmax=VMAX, shading="auto", rasterized=True
    )
    ax.contour(
        lon, lat, bt, levels=[210, 220], colors=["white", "#00000055"], linewidths=[0.8, 0.5]
    )
    ax.text(
        0.03,
        0.97,
        stamp(f),
        transform=ax.transAxes,
        fontsize=10.5,
        fontweight="bold",
        va="top",
        color="white",
        bbox=dict(fc="#0C1518AA", ec="none", pad=2.5),
    )
    for la, lo, _nm in TOR:
        ax.plot(lo, la, marker="v", ms=7, mfc="none", mec="white", mew=1.6, zorder=5)
        ax.plot(lo, la, marker="v", ms=7, mfc="none", mec=SEV, mew=0.9, zorder=6)
axes[0].set_ylabel("latitud")
for ax in axes:
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_aspect(1.25)
    ax.set_xticks([-76, -74, -72, -70])
    ax.set_xticklabels(["76°W", "74°W", "72°W", "70°W"])
    ax.set_yticks(np.arange(-43, -31, 3))
    ax.set_xlabel("longitud")
axes[1].set_yticklabels([])
axes[2].set_yticklabels([])
axes[0].set_yticklabels([f"{abs(v)}°S" for v in np.arange(-43, -31, 3)])
axes[0].annotate(
    "Los Ángeles\ntornado EF2 · 21:57 UTC",
    xy=(-72.33, -37.46),
    xytext=(-77.8, -34.4),
    fontsize=8.4,
    color="white",
    fontweight="bold",
    bbox=dict(fc=SEV, ec="none", pad=2.5),
    arrowprops=dict(arrowstyle="-", color=SEV, lw=1.1, shrinkA=2, shrinkB=7),
)

# tendencia dBT/dt
bt0, bt1 = data[-2][0], data[-1][0]
d = median_filter(np.nan_to_num(bt1 - bt0), size=3)
d[np.isnan(bt1) | np.isnan(bt0)] = np.nan
mm = axes[2].pcolormesh(
    data[-1][2], data[-1][1], d, cmap="RdBu", vmin=-12, vmax=12, shading="auto", rasterized=True
)
axes[2].text(
    0.03,
    0.97,
    "cambio 21:40 → 21:50",
    transform=axes[2].transAxes,
    fontsize=10.5,
    fontweight="bold",
    va="top",
    color=INK,
    bbox=dict(fc="#FFFFFFCC", ec="none", pad=2.5),
)
for la, lo, _nm in TOR:
    axes[2].plot(lo, la, marker="v", ms=7, mfc="none", mec="k", mew=0.9, zorder=6)

cax = fig.add_axes((0.045, 0.855, 0.38, 0.021))
cb = fig.colorbar(m, cax=cax, orientation="horizontal")
cb.set_label("temperatura de brillo, banda 13 (K)", fontsize=8.4)
cb.ax.xaxis.set_label_position("top")
cb.ax.xaxis.set_ticks_position("bottom")
cb.ax.tick_params(labelsize=8)
cax2 = fig.add_axes((0.72, 0.855, 0.265, 0.021))
cb2 = fig.colorbar(mm, cax=cax2, orientation="horizontal")
cb2.set_label("ΔT en 10 min (K) · azul = se enfría", fontsize=8.4)
cb2.ax.xaxis.set_label_position("top")
cb2.ax.xaxis.set_ticks_position("bottom")
cb2.ax.tick_params(labelsize=8)
fig.text(
    0.045,
    0.975,
    "GOES-16 ABI · banda 13 (10,3 µm) · 30 de mayo de 2019",
    fontsize=13,
    fontweight="bold",
    va="top",
)
fig.text(
    0.045,
    0.945,
    "Disco completo, 2 km, una imagen cada 10 min · s3://noaa-goes16/ABI-L2-CMIPF/2019/150/  ▾ = tornados del brote",
    fontsize=8.4,
    color=MUT,
    va="top",
)
fig.savefig(f"{OUT}/fig3_goes_20190530.png", dpi=175, bbox_inches="tight")
print("fig3_goes_20190530.png | dBT/dt min =", np.nanmin(d).round(1), "K/10min")
