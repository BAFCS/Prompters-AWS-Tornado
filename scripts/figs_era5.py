#!/usr/bin/env python3
"""Figura 4: el entorno ERA5 del brote tornádico del 30 de mayo de 2019, 21 UTC.

Lee U, V, T y Z en 37 niveles de presión desde ``s3://nsf-ncar-era5/`` (acceso anónimo). Solo baja
el recuadro chileno de una hora, leyendo el HDF5 por rangos de bytes con s3fs + h5py, sin descargar
los archivos globales completos (~1,4 GB cada uno).

Produce ``figs/fig4_era5_20190530.png`` (500 hPa, viento en 850 hPa, cizalle 0-1 y 0-6 km) y guarda
los campos recortados en ``data/era5_cache.npy``. Uso: ``uv run python scripts/figs_era5.py``.
"""

import time
import warnings
from pathlib import Path

import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes

import common

warnings.filterwarnings("ignore")
matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
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

BASE = "nsf-ncar-era5/e5.oper.an.pl/201905/e5.oper.an.pl.128_{}.{}.2019053000_2019053023.nc"
VARS = {
    "z": ("129_z", "ll025sc", "Z"),
    "t": ("130_t", "ll025sc", "T"),
    "u": ("131_u", "ll025uv", "U"),
    "v": ("132_v", "ll025uv", "V"),
}
HOUR = 21


fs = common.s3()
D: dict[str, np.ndarray] = {}
for nm, (code, grid, var) in VARS.items():
    t0 = time.time()
    with fs.open(BASE.format(code, grid), "rb", block_size=8 * 1024 * 1024) as f:
        h = h5py.File(f, "r")
        if "lat" not in D:
            la, lo = common.dataset(h, "latitude")[:], common.dataset(h, "longitude")[:]
            i0, i1 = np.searchsorted(-la, [28, 46])
            j0, j1 = np.searchsorted(lo, [280, 295])
            D["lat"], D["lon"], D["lev"] = la[i0:i1], lo[j0:j1] - 360, common.dataset(h, "level")[:]
        D[nm] = common.dataset(h, var)[HOUR, :, i0:i1, j0:j1].astype("f4")
    print(f"  {nm}: {D[nm].shape} en {time.time() - t0:.0f} s")
lev = D["lev"]
lat, lon = D["lat"], D["lon"]


def L(p: float) -> int:
    """Índice del nivel de presión más cercano a ``p`` hPa."""
    return int(np.argmin(np.abs(lev - p)))


i1000, i900, i850, i500 = L(1000), L(900), L(850), L(500)
gz = D["z"] / common.G


def spd(k: int) -> np.ndarray:
    """Rapidez del viento (m/s) en el nivel de índice ``k``."""
    return np.hypot(D["u"][k], D["v"][k])


def shear(a: int, b: int) -> np.ndarray:
    """Magnitud del cizalle vectorial (m/s) entre los niveles de índice ``a`` y ``b``."""
    return np.hypot(D["u"][a] - D["u"][b], D["v"][a] - D["v"][b])


sh01, sh06 = shear(i900, i1000), shear(i500, i1000)
print(
    f"cizalle 0-1 km: {sh01.min():.1f}-{sh01.max():.1f} m/s"
    f" | 0-6 km: {sh06.min():.1f}-{sh06.max():.1f} m/s"
)

TOR = [
    (-37.463, -72.330),
    (-36.726, -71.810),
    (-37.106, -72.119),
    (-36.496, -71.943),
    (-37.939, -72.498),
]
X, Y = np.meshgrid(lon, lat)
fig, axs = plt.subplots(1, 4, figsize=(13.4, 5.3))
fig.subplots_adjust(left=0.042, right=0.99, top=0.775, bottom=0.10, wspace=0.10)


def base(ax: Axes, ti: str, sub: str) -> None:
    """Aplica a ``ax`` el recuadro, los ejes, el título ``ti``, el subtítulo ``sub`` y los tornados."""
    ax.set_xlim(-80, -66)
    ax.set_ylim(-46, -28)
    ax.set_aspect(1.25)
    ax.set_xticks([-78, -74, -70])
    ax.set_xticklabels(["78°W", "74°W", "70°W"])
    ax.set_yticks(np.arange(-45, -27, 5))
    ax.set_title(ti, loc="left", fontsize=10.2, pad=13)
    ax.text(0, 1.015, sub, transform=ax.transAxes, fontsize=8.2, color=MUT)
    for la, lo_ in TOR:
        ax.plot(lo_, la, marker="v", ms=6, mfc="none", mec=SEV, mew=1.3, zorder=9)


# A · 500 hPa
a = axs[0]
c = a.contourf(
    X, Y, D["t"][i500] - 273.15, levels=np.arange(-30, -13, 1), cmap="YlGnBu_r", extend="both"
)
cs = a.contour(X, Y, gz[i500], levels=np.arange(4800, 6000, 40), colors=INK, linewidths=0.7)
a.clabel(cs, fmt="%d", fontsize=6.5)
base(a, "A · 500 hPa", "temperatura (°C) y altura geopotencial (m)")
plt.colorbar(c, ax=a, orientation="horizontal", pad=0.09, shrink=0.92, aspect=24).ax.tick_params(
    labelsize=7.5
)

# B · 850 hPa viento
b = axs[1]
c = b.contourf(X, Y, spd(i850), levels=np.arange(0, 34, 2), cmap="BuPu", extend="max")
st = 3
b.quiver(
    X[::st, ::st],
    Y[::st, ::st],
    D["u"][i850][::st, ::st],
    D["v"][i850][::st, ::st],
    color=INK,
    scale=430,
    width=0.005,
    alpha=0.75,
)
base(b, "B · 850 hPa", "rapidez del viento (m/s) — el jet del NW")
plt.colorbar(c, ax=b, orientation="horizontal", pad=0.09, shrink=0.92, aspect=24).ax.tick_params(
    labelsize=7.5
)

# C · cizalle 0-1 km
c3 = axs[2]
cc = c3.contourf(X, Y, sh01, levels=np.arange(0, 26, 2), cmap="PuRd", extend="max")
c3.contour(X, Y, sh01, levels=[12], colors=[SEV], linewidths=1.6)
base(c3, "C · Cizalle 0–1 km", "m/s · línea roja = umbral chileno de 12 m/s")
plt.colorbar(cc, ax=c3, orientation="horizontal", pad=0.09, shrink=0.92, aspect=24).ax.tick_params(
    labelsize=7.5
)

# D · cizalle 0-6 km
d = axs[3]
cd = d.contourf(X, Y, sh06, levels=np.arange(0, 46, 3), cmap="PuBuGn", extend="max")
d.contour(X, Y, sh06, levels=[18], colors=[ACC], linewidths=1.6)
base(d, "D · Cizalle 0–6 km", "m/s · línea verde = umbral HSLC de 18 m/s")
plt.colorbar(cd, ax=d, orientation="horizontal", pad=0.09, shrink=0.92, aspect=24).ax.tick_params(
    labelsize=7.5
)
for ax in axs[1:]:
    ax.set_yticklabels([])
axs[0].set_yticklabels([f"{abs(v)}°S" for v in np.arange(-45, -27, 5)])

fig.text(
    0.042,
    0.975,
    "ERA5 · 30 de mayo de 2019, 21:00 UTC · el entorno del brote",
    fontsize=13,
    fontweight="bold",
    va="top",
)
fig.text(
    0.042,
    0.945,
    "0,25°, 37 niveles de presión · leído por rangos de bytes desde s3://nsf-ncar-era5/  ▾ = tornados de ese día",
    fontsize=8.4,
    color=MUT,
    va="top",
)
fig.savefig(f"{OUT}/fig4_era5_20190530.png", dpi=175, bbox_inches="tight")
print("fig4_era5_20190530.png")
np.save(
    DATA / "era5_cache.npy",
    np.array({k: D[k] for k in ("u", "v", "t", "z", "lat", "lon", "lev")}, dtype=object),
    allow_pickle=True,
)
