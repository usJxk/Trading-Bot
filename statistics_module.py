"""
statistics.py
Metricas avanzadas de un backtest, a partir de la lista de trades y la curva
de equity que devuelve backtester.run_backtest() (y opcionalmente
backtester.apply_money_simulation()).

Modulo de puro calculo: no importa Tkinter, no importa strategy.py. Recibe
datos y devuelve un diccionario con todas las metricas.
"""

import math
from collections import defaultdict

import numpy as np


def compute_full_stats(
    trades: list,
    equity_curve_r: list,
    equity_curve_money: list | None = None,
    capital_inicial: float | None = None,
    periods_per_year: int = 252,
) -> dict:
    """
    trades: lista de dicts como los que produce backtester.run_backtest()
            (con opcionalmente 'pnl_money' si se le aplico apply_money_simulation).
    equity_curve_r: curva acumulada en R (siempre disponible).
    equity_curve_money / capital_inicial: opcionales, si se corrio la
            simulacion en dinero. Si no se pasan, las metricas en dinero
            quedan en None y solo se calculan en R.
    """
    n = len(trades)
    out = {
        "operaciones": n, "ganadas": 0, "perdidas": 0, "break_even": 0,
        "winrate_pct": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0,
        "net_profit_r": 0.0, "net_profit_money": None, "beneficio_pct": None,
        "max_drawdown_r": 0.0, "max_drawdown_money": None, "max_drawdown_pct": None,
        "average_win_r": 0.0, "average_loss_r": 0.0, "rr_promedio": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
        "recovery_factor": 0.0,
        "profit_per_month_r": {}, "profit_per_year_r": {},
        "longest_winning_streak": 0, "longest_losing_streak": 0,
        "operaciones_por_mes": {}, "operaciones_por_dia_semana": {},
        "tiempo_promedio_por_trade_horas": 0.0,
        "mayor_ganadora_r": 0.0, "mayor_perdedora_r": 0.0,
    }
    if n == 0:
        return out

    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    be = [t for t in trades if t["outcome"] == "BREAK_EVEN"]

    out["ganadas"] = len(wins)
    out["perdidas"] = len(losses)
    out["break_even"] = len(be)
    out["winrate_pct"] = round(len(wins) / n * 100, 2)

    gross_profit = sum(t["r_multiple"] for t in wins)
    gross_loss = abs(sum(t["r_multiple"] for t in losses))
    out["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    total_r = sum(t["r_multiple"] for t in trades)
    out["net_profit_r"] = round(total_r, 2)
    out["expectancy_r"] = round(total_r / n, 3)

    out["average_win_r"] = round(np.mean([t["r_multiple"] for t in wins]), 3) if wins else 0.0
    out["average_loss_r"] = round(np.mean([t["r_multiple"] for t in losses]), 3) if losses else 0.0
    out["rr_promedio"] = round(abs(out["average_win_r"] / out["average_loss_r"]), 2) if out["average_loss_r"] else 0.0

    out["mayor_ganadora_r"] = round(max((t["r_multiple"] for t in wins), default=0.0), 2)
    out["mayor_perdedora_r"] = round(min((t["r_multiple"] for t in losses), default=0.0), 2)

    # --- Drawdown (en R) ---
    peak = equity_curve_r[0]
    max_dd_r = 0.0
    for v in equity_curve_r:
        peak = max(peak, v)
        max_dd_r = max(max_dd_r, peak - v)
    out["max_drawdown_r"] = round(max_dd_r, 2)
    out["recovery_factor"] = round(total_r / max_dd_r, 2) if max_dd_r > 0 else 0.0
    out["calmar_ratio"] = round((total_r / n * periods_per_year) / max_dd_r, 2) if max_dd_r > 0 else 0.0

    # --- Sharpe / Sortino (sobre los retornos por operacion, en R) ---
    r_returns = np.array([t["r_multiple"] for t in trades], dtype=float)
    if len(r_returns) > 1 and r_returns.std(ddof=1) > 0:
        out["sharpe_ratio"] = round(float(r_returns.mean() / r_returns.std(ddof=1)) * math.sqrt(len(r_returns)), 2)
    downside = r_returns[r_returns < 0]
    if len(downside) > 1 and downside.std(ddof=1) > 0:
        out["sortino_ratio"] = round(float(r_returns.mean() / downside.std(ddof=1)) * math.sqrt(len(r_returns)), 2)

    # --- Rachas ---
    cur_w = cur_l = max_w = max_l = 0
    for t in trades:
        if t["outcome"] == "WIN":
            cur_w += 1
            cur_l = 0
        elif t["outcome"] == "LOSS":
            cur_l += 1
            cur_w = 0
        else:
            cur_w = cur_l = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)
    out["longest_winning_streak"] = max_w
    out["longest_losing_streak"] = max_l

    # --- Estacionalidad (por mes / dia de la semana) ---
    profit_month = defaultdict(float)
    profit_year = defaultdict(float)
    count_month = defaultdict(int)
    count_weekday = defaultdict(int)
    dias = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    holding_hours = []

    for t in trades:
        entry_t = t["entry_time"]
        key_month = f"{entry_t.year}-{entry_t.month:02d}"
        profit_month[key_month] += t["r_multiple"]
        profit_year[str(entry_t.year)] += t["r_multiple"]
        count_month[key_month] += 1
        count_weekday[dias[entry_t.weekday()]] += 1

        exit_t = t["exit_time"]
        holding_hours.append((exit_t - entry_t).total_seconds() / 3600.0)

    out["profit_per_month_r"] = {k: round(v, 2) for k, v in sorted(profit_month.items())}
    out["profit_per_year_r"] = {k: round(v, 2) for k, v in sorted(profit_year.items())}
    out["operaciones_por_mes"] = dict(sorted(count_month.items()))
    out["operaciones_por_dia_semana"] = {d: count_weekday.get(d, 0) for d in dias}
    out["tiempo_promedio_por_trade_horas"] = round(float(np.mean(holding_hours)), 2) if holding_hours else 0.0

    # --- Metricas en dinero (si aplica) ---
    if equity_curve_money and capital_inicial:
        out["net_profit_money"] = round(equity_curve_money[-1] - capital_inicial, 2)
        out["beneficio_pct"] = round((equity_curve_money[-1] - capital_inicial) / capital_inicial * 100, 2)

        peak_m = equity_curve_money[0]
        max_dd_m = max_dd_pct = 0.0
        for v in equity_curve_money:
            peak_m = max(peak_m, v)
            max_dd_m = max(max_dd_m, peak_m - v)
            if peak_m > 0:
                max_dd_pct = max(max_dd_pct, (peak_m - v) / peak_m)
        out["max_drawdown_money"] = round(max_dd_m, 2)
        out["max_drawdown_pct"] = round(max_dd_pct * 100, 2)

    return out
