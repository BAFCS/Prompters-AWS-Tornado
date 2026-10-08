#!/usr/bin/env python3
"""Figuras 1 y 2: el catálogo de tornados y trombas marinas de Chile.

Lee la base de Bastías-Curivil et al. (figshare, doi:10.6084/m9.figshare.25119566) y produce:

- ``figs/fig1_catalog_map.png``: mapa de los 102 eventos con histograma por latitud.
- ``figs/fig2_catalog_panels.png``: estacionalidad, hora del día, sesgo de reporte e intensidad EF.

Entradas: ``data/tornados_chile.xlsx`` (hoja ``Final_Table``) y ``data/coast.zip`` (shapefile de
costa, p. ej. Natural Earth 10m). Uso: ``uv run python scripts/figures/figs_catalog.py``.
"""

import datetime
import re
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.patches import Rectangle

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
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.titlesize": 10.5,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
    }
)

df = pd.read_excel(DATA / "tornados_chile.xlsx", sheet_name="Final_Table")
d = pd.to_datetime(df["Date (Gregorian Calendar)"], errors="coerce")
df["_y"], df["_m"] = d.dt.year, d.dt.month
lat = pd.to_numeric(df["Latitude"], errors="coerce")
lon = pd.to_numeric(df["Longitude"], errors="coerce")


# Banderas 0/1 de tipo de evento (Waterspout trae algún NaN, que cuenta como 0).
T, W = (df[c].fillna(0).astype(int) for c in ("Tornado", "Waterspout"))
ef = df["Max. EF Rating"].astype(str).str.extract(r"(\d)")[0].astype(float)


def decimal_hours(col: str) -> np.ndarray:
    """Devuelve la columna horaria ``col`` como horas decimales (NaN si no se puede leer).

    Acepta objetos ``datetime.time`` y textos como "14:30" o "14h".
    """
    h = []
    for v in df[col]:
        if isinstance(v, datetime.time):
            h.append(v.hour + v.minute / 60.0)
            continue
        m = re.search(r"(\d{1,2})[:h]\s*(\d{2})?", str(v))
        h.append(int(m.group(1)) + (int(m.group(2)) / 60.0 if m.group(2) else 0) if m else np.nan)
    return np.array(h, dtype=float)


hl = decimal_hours("Hour (local)")


def tag(ax: Axes, txt: str, sub: str = "") -> None:
    """Pone el título ``txt`` alineado a la izquierda de ``ax`` y, si hay, el subtítulo ``sub``."""
    ax.set_title(txt, loc="left", fontsize=10.5, fontweight="bold", color=INK, pad=16)
    if sub:
        ax.text(
            0.0, 1.012, sub, transform=ax.transAxes, fontsize=8.3, color=MUT, ha="left", va="bottom"
        )


# ─────────── FIGURA A · mapa ───────────

coast = gpd.read_file(f"zip://{DATA / 'coast.zip'}")
fig, (axm, axl) = plt.subplots(
    1, 2, figsize=(9.2, 8.8), width_ratios=[2.25, 1], gridspec_kw=dict(wspace=0.05)
)
fig.subplots_adjust(top=0.845)
coast.plot(ax=axm, color=LINE, linewidth=0.9, zorder=1)
axm.set_facecolor("#FBFCFC")
is_t, is_w = (T > 0) & (W == 0), (W > 0) & (T == 0)
both = (T > 0) & (W > 0)
sz = np.where(np.isnan(ef), 26, 26 + 30 * np.nan_to_num(ef))
for mask, color, alpha, z, name in (
    (is_w, COLD, 0.85, 4, "Tromba marina"),
    (both, WARM, 0.9, 5, "Ambos"),
    (is_t, SEV, 0.85, 6, "Tornado"),
):
    axm.scatter(
        lon[mask],
        lat[mask],
        s=sz[mask],
        c=color,
        alpha=alpha,
        ec="white",
        lw=0.6,
        zorder=z,
        label=f"{name} ({mask.sum()})",
    )
unclassified = (T == 0) & (W == 0)
if unclassified.sum():
    axm.scatter(
        lon[unclassified],
        lat[unclassified],
        s=sz[unclassified],
        c="none",
        ec=MUT,
        lw=0.9,
        zorder=3,
        label=f"Sin clasificar ({unclassified.sum()})",
    )
axm.axhline(-42.4, color=ACC, ls="--", lw=1.4, zorder=7)
axm.text(
    -79.5,
    -43.5,
    "evento más austral: 42,4°S",
    color=ACC,
    fontsize=8.5,
    ha="left",
    fontweight="bold",
)
axm.add_patch(Rectangle((-80, -56), 14, 13.6, fc=ACC, alpha=0.07, ec="none", zorder=2))
axm.text(-79.5, -50.2, "más de 1.000 km\nsin ningún registro", color=ACC, fontsize=8.5, va="bottom")
axm.set_xlim(-80, -66)
axm.set_ylim(-56, -17)
axm.set_aspect(1.45)
axm.set_xlabel("longitud")
axm.set_ylabel("latitud")
axm.set_xticks([-78, -74, -70])
axm.set_xticklabels(["78°W", "74°W", "70°W"])
axm.set_yticks(np.arange(-55, -16, 5))
axm.set_yticklabels([f"{abs(v)}°S" for v in np.arange(-55, -16, 5)])
axm.legend(loc="upper left", frameon=False, fontsize=8.5, handletextpad=0.4, borderpad=0.2)
for y, n in [
    (-33.4, "Santiago"),
    (-36.8, "Concepción"),
    (-38.7, "Temuco"),
    (-41.5, "Puerto Montt"),
    (-53.2, "Punta Arenas"),
]:
    axm.plot([-70.8], [y], marker="s", ms=2.6, color=MUT, zorder=8)
    axm.text(-70.2, y, n, fontsize=7.4, color=MUT, va="center")
tag(axm, "A · Dónde están los 102 eventos", "tamaño $\\propto$ intensidad EF")

h, edges = np.histogram(lat.dropna(), bins=np.arange(-56, -16, 2))
ctr = (edges[:-1] + edges[1:]) / 2
axl.barh(ctr, h, height=1.7, color=ACC, alpha=0.85)
axl.set_ylim(-56, -17)
axl.set_yticks([])
axl.set_xlabel("eventos")
axl.axhline(-42.4, color=ACC, ls="--", lw=1.4)
axl.spines["left"].set_visible(False)
tag(axl, "B · Por latitud", "89 % entre 34° y 42°S")
fig.text(
    0.062,
    0.985,
    "Tornados y trombas marinas en Chile, 1554–2025",
    ha="left",
    va="top",
    fontsize=13.5,
    fontweight="bold",
    color=INK,
)
fig.text(
    0.062,
    0.958,
    "Base de datos de Bastías-Curivil, Rondanelli, Vicencio et al. (figshare, CC BY 4.0) · n = 102",
    ha="left",
    va="top",
    fontsize=8.6,
    color=MUT,
)
fig.savefig(f"{OUT}/fig1_catalog_map.png", dpi=185, bbox_inches="tight")
plt.close(fig)
print("fig1_catalog_map.png")

# ─────────── FIGURA B · 2x2 ───────────
fig, axs = plt.subplots(2, 2, figsize=(9.2, 6.4))
fig.subplots_adjust(hspace=0.52, wspace=0.24)
(a1, a2), (a3, a4) = axs

mn = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
mc = df["_m"].value_counts().reindex(range(1, 13), fill_value=0)
cols = [SEV if m in (5, 6) else (ACC if m in (3, 4, 7, 8) else MUT) for m in range(1, 13)]
a1.bar(range(1, 13), mc.values, color=cols, alpha=0.9)
a1.set_xticks(range(1, 13))
a1.set_xticklabels(mn)
a1.set_ylabel("eventos")
for m in (5, 6):
    a1.text(m, mc[m] + 1, str(mc[m]), ha="center", fontsize=8.5, fontweight="bold", color=SEV)
tag(a1, "C · Estacionalidad")
a1.set_title(
    "junio (36) supera a mayo (24) · invierno 55 %, otoño 31 %",
    loc="left",
    fontsize=8.3,
    color=MUT,
    fontweight="normal",
    pad=3,
)

hh = hl[~np.isnan(hl)]
a2.hist(hh, bins=np.arange(-0.5, 24.5, 1), color=ACC, alpha=0.85)
a2.axvspan(13, 20, color=SEV, alpha=0.10)
a2.set_ylim(0, a2.get_ylim()[1] * 1.18)
a2.text(
    16.5,
    a2.get_ylim()[1] * 0.93,
    "tarde local",
    ha="center",
    fontsize=8.3,
    color=SEV,
    fontweight="bold",
)
a2.set_xlabel("hora local")
a2.set_ylabel("eventos")
a2.set_xticks(range(0, 25, 4))
tag(a2, "D · Hora del día")
a2.set_title(
    f"{len(hh)} eventos con hora conocida · mediana {np.median(hh):.0f}:00",
    loc="left",
    fontsize=8.3,
    color=MUT,
    fontweight="normal",
    pad=3,
)

per = [
    ("1554–1999", ((df["_y"] >= 1500) & (df["_y"] <= 1999)).sum(), 446),
    ("2000–2014", ((df["_y"] >= 2000) & (df["_y"] <= 2014)).sum(), 15),
    ("2015–2025", ((df["_y"] >= 2015) & (df["_y"] <= 2025)).sum(), 11),
]
yy = np.arange(3)
a3.barh(yy, [p[1] for p in per], color=[MUT, COLD, SEV], alpha=0.9, height=0.62)
a3.set_yticks(yy)
a3.set_yticklabels([f"{p[0]}\n{p[2]} años" for p in per], fontsize=8)
a3.invert_yaxis()
a3.set_xlabel("eventos")
for i, p in enumerate(per):
    a3.text(
        p[1] + 1.5,
        i,
        f"{p[1] / 102 * 100:.1f} %",
        va="center",
        fontsize=8.5,
        fontweight="bold",
        color=[MUT, COLD, SEV][i],
    )
a3.spines["left"].set_visible(False)
tag(a3, "E · El sesgo de reporte")
a3.set_title(
    "dos tercios del catálogo cabe en once años",
    loc="left",
    fontsize=8.3,
    color=MUT,
    fontweight="normal",
    pad=3,
)

ec = pd.Series(ef).value_counts().reindex([0, 1, 2, 3, 4, 5], fill_value=0)
a4.bar(range(6), ec.values, color=[ACC, ACC, SEV, SEV, LINE, LINE], alpha=0.9)
a4.set_xticks(range(6))
a4.set_xticklabels([f"EF{i}" for i in range(6)])
a4.set_ylabel("eventos")
for i, v in enumerate(ec.values):
    if v:
        a4.text(i, v + 1, str(int(v)), ha="center", fontsize=8.5, color=MUT)
a4.text(
    4.5, ec.max() * 0.55, "ninguno\nregistrado", ha="center", fontsize=8, color=MUT, style="italic"
)
tag(a4, "F · Intensidad", "94 de 102 eventos clasificados")
fig.savefig(f"{OUT}/fig2_catalog_panels.png", dpi=185, bbox_inches="tight")
plt.close(fig)
print("fig2_catalog_panels.png")
print("mediana hora local:", np.median(hh), "| p25-p75:", np.percentile(hh, [25, 75]))
