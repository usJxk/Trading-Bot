"""
charts.py
Genera figuras de matplotlib a partir de los resultados de un backtest.
No importa Tkinter -- devuelve objetos Figure que la UI puede embeber
(FigureCanvasTkAgg) o report.py puede guardar como imagen para el PDF.
"""

from collections import defaultdict

import numpy as np
from matplotlib.figure import Figure

BG = "#0f1117"
GRID = "#2a2f3d"
TEXT = "#e6e8ef"
GREEN = "#22c55e"
RED = "#ef4444"
BLUE = "#3b82f6"
YELLOW = "#eab308"


def _new_fig(figsize=(8, 4)):
    fig = Figure(figsize=figsize, dpi=100, facecolor=BG)
    ax = fig.add_subplot(111, facecolor=BG)
    ax.tick_params(colors=TEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(alpha=0.15, color=GRID)
    return fig, ax


def equity_curve_figure(equity_curve, label="Equity (R)", title="Curva de equity"):
    fig, ax = _new_fig()
    ax.plot(equity_curve, color=BLUE, linewidth=1.5)
    ax.axhline(equity_curve[0], color="#888888", linewidth=0.8, linestyle="--")
    ax.fill_between(range(len(equity_curve)), equity_curve, equity_curve[0],
                     where=[v >= equity_curve[0] for v in equity_curve],
                     color=GREEN, alpha=0.08, interpolate=True)
    ax.fill_between(range(len(equity_curve)), equity_curve, equity_curve[0],
                     where=[v < equity_curve[0] for v in equity_curve],
                     color=RED, alpha=0.08, interpolate=True)
    ax.set_title(title, color=TEXT, fontsize=10)
    ax.set_xlabel("Operacion #", color=TEXT, fontsize=8)
    ax.set_ylabel(label, color=TEXT, fontsize=8)
    fig.tight_layout()
    return fig


def drawdown_figure(equity_curve, title="Drawdown"):
    peak = equity_curve[0]
    dd = []
    for v in equity_curve:
        peak = max(peak, v)
        dd.append(v - peak)  # <= 0

    fig, ax = _new_fig()
    ax.fill_between(range(len(dd)), dd, 0, color=RED, alpha=0.35)
    ax.plot(dd, color=RED, linewidth=1)
    ax.set_title(title, color=TEXT, fontsize=10)
    ax.set_xlabel("Operacion #", color=TEXT, fontsize=8)
    ax.set_ylabel("Drawdown", color=TEXT, fontsize=8)
    fig.tight_layout()
    return fig


def monthly_profit_bar_figure(profit_per_month: dict, title="Beneficio mensual"):
    fig, ax = _new_fig()
    if not profit_per_month:
        ax.set_title("Sin datos suficientes", color=TEXT, fontsize=10)
        return fig
    months = list(profit_per_month.keys())
    values = list(profit_per_month.values())
    colors = [GREEN if v >= 0 else RED for v in values]
    ax.bar(months, values, color=colors)
    ax.set_title(title, color=TEXT, fontsize=10)
    ax.tick_params(axis="x", rotation=60, labelsize=7)
    ax.set_ylabel("R", color=TEXT, fontsize=8)
    fig.tight_layout()
    return fig


def distribution_histogram_figure(trades: list, title="Distribucion de resultados (R por operacion)"):
    fig, ax = _new_fig()
    values = [t["r_multiple"] for t in trades]
    if not values:
        ax.set_title("Sin operaciones", color=TEXT, fontsize=10)
        return fig
    colors_bins = GREEN
    ax.hist(values, bins=min(30, max(5, len(values) // 3)), color=BLUE, alpha=0.75, edgecolor=GRID)
    ax.axvline(0, color="#888888", linewidth=0.8, linestyle="--")
    ax.set_title(title, color=TEXT, fontsize=10)
    ax.set_xlabel("R multiple", color=TEXT, fontsize=8)
    ax.set_ylabel("Frecuencia", color=TEXT, fontsize=8)
    fig.tight_layout()
    return fig


def equity_vs_buyhold_figure(equity_curve, buyhold_curve, title="Equity vs Buy & Hold"):
    fig, ax = _new_fig()
    # normaliza ambas curvas a % de cambio desde el inicio para que sean comparables
    eq0 = equity_curve[0] if equity_curve[0] != 0 else 1
    bh0 = buyhold_curve[0] if buyhold_curve[0] != 0 else 1
    eq_pct = [(v / eq0 - 1) * 100 for v in equity_curve]
    bh_pct = [(v / bh0 - 1) * 100 for v in buyhold_curve]

    n = min(len(eq_pct), len(bh_pct))
    ax.plot(eq_pct[:n], color=BLUE, linewidth=1.5, label="Estrategia")
    ax.plot(bh_pct[:n], color=YELLOW, linewidth=1.2, label="Buy & Hold", alpha=0.8)
    ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--")
    ax.legend(facecolor=BG, edgecolor=GRID, labelcolor=TEXT, fontsize=8)
    ax.set_title(title, color=TEXT, fontsize=10)
    ax.set_ylabel("% de cambio", color=TEXT, fontsize=8)
    fig.tight_layout()
    return fig


def monthly_heatmap_figure(profit_per_month: dict, title="Heatmap mensual (R)"):
    """Heatmap simple: filas = anio, columnas = mes 1-12."""
    fig, ax = _new_fig(figsize=(8, 3))
    if not profit_per_month:
        ax.set_title("Sin datos suficientes", color=TEXT, fontsize=10)
        return fig

    by_year = defaultdict(lambda: [np.nan] * 12)
    for key, val in profit_per_month.items():
        year, month = key.split("-")
        by_year[year][int(month) - 1] = val

    years = sorted(by_year.keys())
    matrix = np.array([by_year[y] for y in years])

    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto",
                    vmin=-np.nanmax(np.abs(matrix)) if np.any(~np.isnan(matrix)) else -1,
                    vmax=np.nanmax(np.abs(matrix)) if np.any(~np.isnan(matrix)) else 1)
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(years, color=TEXT, fontsize=8)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
                        color=TEXT, fontsize=7)
    for i in range(len(years)):
        for j in range(12):
            if not np.isnan(matrix[i, j]):
                ax.text(j, i, f"{matrix[i, j]:.1f}", ha="center", va="center", color="black", fontsize=6)
    ax.set_title(title, color=TEXT, fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    return fig
