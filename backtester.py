"""
backtester.py
Backtesting "walk-forward" para strategy.py, SIN modificar strategy.py,
app.py, data_feed.py ni storage.py.

Idea central (igual a la que te describieron): en cada paso i, el motor solo
le pasa a strategy.analyze() las velas [0..i] -> el algoritmo nunca puede ver
el futuro. Si la senal pasa los filtros, se simula una entrada en la apertura
de la siguiente vela, con SL/TP en multiplos de ATR, y se recorre vela a vela
hasta que toque SL, TP, o se acabe el historico disponible.

Los resultados se expresan en multiplos de R (R = distancia entre entrada y
SL, o sea "lo que arriesgaste"). Es el estandar real de backtesting: no
inventa un tamano de posicion ni un balance de cuenta que no tenemos.

Uso basico:

    import data_feed, backtester

    df = data_feed.fetch_ohlcv("XAUUSD", "1h")
    resultado = backtester.run_backtest(df, sl_atr=1.0, tp_atr=2.0, min_score=4)
    backtester.print_report(resultado)

Comparar configuraciones (ej. distintos min_score o distintos filtros):

    configs = [
        {"min_score": 3, "sl_atr": 1.0, "tp_atr": 2.0},
        {"min_score": 4, "sl_atr": 1.0, "tp_atr": 2.0, "require_fvg": True},
        {"min_score": 4, "sl_atr": 1.5, "tp_atr": 3.0, "require_ob": True},
    ]
    ranking = backtester.compare_configs(df, configs)
    for r in ranking:
        print(r["config"], "->", r["stats"])

ADVERTENCIA DE RENDIMIENTO: strategy.analyze() recalcula estructura, FVGs,
order blocks, etc. sobre TODO el historico visible en cada paso, asi que el
backtest completo es O(n^2). Para 1000-3000 velas tarda pocos segundos; para
historiales muy largos (ej. 15m durante 60 dias -> miles de velas) puede
tardar mas. Usa el parametro `step` para saltar velas y acelerar si hace falta.
"""

import pandas as pd
import numpy as np


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = (df["High"] - df["Low"])
    return tr.rolling(period).mean()


def _passes_filters(result, side_filter, min_score, require_ob, require_fvg, ignore_range):
    bias = result["bias"]

    if bias not in ("ALCISTA", "BAJISTA"):
        return False, None
    if ignore_range and bias == "NEUTRAL / RANGO":
        return False, None
    if side_filter and bias != side_filter:
        return False, None
    if abs(result["score"]) < min_score:
        return False, None

    if require_ob:
        obs = result["details"].get("order_blocks", [])
        if not any(ob["direction"] == bias for ob in obs):
            return False, None

    if require_fvg:
        fvgs = result["details"].get("fvgs", [])
        if not any(f["direction"] == bias and not f["mitigated"] for f in fvgs):
            return False, None

    side = "COMPRA" if bias == "ALCISTA" else "VENTA"
    return True, side


def run_backtest(
    df: pd.DataFrame,
    min_candles: int = 30,
    sl_atr: float = 1.0,
    tp_atr: float = 2.0,
    min_score: int = 3,
    require_ob: bool = False,
    require_fvg: bool = False,
    ignore_range: bool = True,
    side_filter: str | None = None,
    max_bars_in_trade: int = 200,
    step: int = 1,
    strategy_kwargs: dict | None = None,
    progress_callback=None,
) -> dict:
    """
    Corre el backtest completo sobre df (OHLCV, index ascendente por tiempo).

    Parametros clave:
    - sl_atr / tp_atr: distancia de SL/TP en multiplos del ATR(14) al momento
      de la senal (SL 1.0 = un ATR de distancia; TP 2.0 = dos ATR -> ratio 1:2).
    - min_score: puntaje minimo (valor absoluto) que debe tener el veredicto
      de strategy.analyze() para considerar la senal.
    - require_ob / require_fvg: exige que ademas del bias haya un Order Block
      o un FVG sin mitigar a favor de la direccion.
    - ignore_range: si True, ignora los veredictos "NEUTRAL / RANGO".
    - side_filter: "ALCISTA" o "BAJISTA" para probar solo un lado; None = ambos.
    - max_bars_in_trade: limite de velas que se espera a que toque SL/TP antes
      de forzar el cierre al precio de esa ultima vela.
    - step: analiza 1 de cada `step` velas (para acelerar backtests largos).
    - strategy_kwargs: dict opcional con los toggles use_trend/use_bos/use_choch/
      use_fvg/use_order_blocks/use_liquidity_sweep/use_premium_discount/
      use_footprint de strategy.analyze(), para que optimizer.py pueda probar
      que tanto aporta cada concepto. None = comportamiento normal (todo activo).
    - progress_callback: funcion opcional callback(indice_actual, total_velas)
      que se llama en cada paso, para poder actualizar una barra de progreso
      desde la UI sin bloquear el hilo principal.

    No permite operaciones solapadas: mientras hay una posicion abierta no se
    evaluan nuevas senales (igual que "cierra y despues buscas la siguiente").
    """
    import strategy  # import local para evitar dependencia circular en algunos entornos

    if min_candles < 30 or step < 1 or max_bars_in_trade < 1:
        raise ValueError("Se requieren al menos 30 velas iniciales y pasos positivos.")
    if not all(np.isfinite(value) and value > 0 for value in (sl_atr, tp_atr)):
        raise ValueError("Las distancias de salida deben ser positivas y finitas.")

    strategy_kwargs = strategy_kwargs or {}
    atr_series = _atr(df)
    n = len(df)
    trades = []
    equity_r = [0.0]
    i = min_candles

    while i < n - 1:
        if progress_callback is not None:
            progress_callback(i, n)

        window = df.iloc[:i + 1]
        result = strategy.analyze(window, **strategy_kwargs)
        ok, side = _passes_filters(result, side_filter, min_score, require_ob, require_fvg, ignore_range)

        if not ok:
            i += step
            continue

        atr_val = atr_series.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            i += step
            continue

        entry_index = i + 1
        if entry_index >= n:
            break
        entry_price = float(df["Open"].iloc[entry_index])

        if side == "COMPRA":
            sl = entry_price - sl_atr * atr_val
            tp = entry_price + tp_atr * atr_val
        else:
            sl = entry_price + sl_atr * atr_val
            tp = entry_price - tp_atr * atr_val

        risk = abs(entry_price - sl)
        if risk <= 0:
            i += step
            continue

        outcome = exit_price = exit_index = None

        for j in range(entry_index, min(entry_index + max_bars_in_trade, n)):
            bar = df.iloc[j]
            hit_sl = (bar["Low"] <= sl) if side == "COMPRA" else (bar["High"] >= sl)
            hit_tp = (bar["High"] >= tp) if side == "COMPRA" else (bar["Low"] <= tp)

            opening = float(bar["Open"])
            gap_stop = opening <= sl if side == "COMPRA" else opening >= sl
            gap_target = opening >= tp if side == "COMPRA" else opening <= tp
            if gap_stop:
                outcome, exit_price, exit_index = "LOSS", opening, j
                break
            if gap_target:
                outcome, exit_price, exit_index = "WIN", tp, j
                break
            if hit_sl:
                # si ambos se tocan en la misma vela, se asume el peor caso (SL primero)
                outcome, exit_price, exit_index = "LOSS", sl, j
                break
            if hit_tp:
                outcome, exit_price, exit_index = "WIN", tp, j
                break

        if outcome is None:
            exit_index = min(entry_index + max_bars_in_trade, n) - 1
            exit_price = float(df["Close"].iloc[exit_index])
            pnl_r_preview = (exit_price - entry_price) / risk if side == "COMPRA" else (entry_price - exit_price) / risk
            if abs(pnl_r_preview) < 0.1:
                outcome = "BREAK_EVEN"
            else:
                outcome = "WIN" if pnl_r_preview > 0 else "LOSS"

        r_multiple = (exit_price - entry_price) / risk if side == "COMPRA" else (entry_price - exit_price) / risk

        trades.append({
            "signal_time": df.index[i],
            "entry_time": df.index[entry_index],
            "exit_time": df.index[exit_index],
            "side": side,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "exit_price": exit_price,
            "outcome": outcome,
            "r_multiple": r_multiple,
            "score": result["score"],
            "bias": result["bias"],
        })
        equity_r.append(equity_r[-1] + r_multiple)

        i = exit_index + 1  # no se solapan operaciones

    if progress_callback is not None:
        progress_callback(n, n)

    return {"trades": trades, "equity_curve_r": equity_r, "stats": _compute_stats(trades, equity_r)}


# ---------------------------------------------------------------------------
# Conversion a dinero real (capital, riesgo %, comision, spread, slippage)
# ---------------------------------------------------------------------------

def apply_money_simulation(
    trades: list,
    capital_inicial: float = 1000.0,
    riesgo_pct: float = 1.0,
    commission_r: float = 0.0,
    spread_r: float = 0.0,
    slippage_r: float = 0.0,
) -> dict:
    """
    Convierte una lista de trades (en multiplos de R, tal como la devuelve
    run_backtest) a dinero real, SIN volver a correr el backtest ni tocar
    strategy.py/backtester.py run_backtest(). Es una capa aparte, aditiva.

    - capital_inicial: capital con el que arranca la simulacion (USD).
    - riesgo_pct: % del capital ACTUAL que se arriesga en cada operacion
      (interes compuesto: el riesgo en dinero crece o baja con el capital).
    - commission_r / spread_r / slippage_r: costos por operacion expresados
      en multiplos de R (ej. 0.05 = medio del 10% de tu riesgo se lo come el
      costo). Si no sabes cuanto poner, usa 0 y ajusta despues.

    Devuelve trades con "pnl_money" y "capital_after" agregados, mas la curva
    de equity en dinero y en % sobre el capital inicial.
    """
    capital = capital_inicial
    equity_money = [capital]
    trades_money = []

    for t in trades:
        riesgo_dinero = capital * (riesgo_pct / 100.0)
        costo_r = commission_r + spread_r + slippage_r
        r_neto = t["r_multiple"] - costo_r

        pnl_money = max(-capital, riesgo_dinero * r_neto)
        capital += pnl_money

        t2 = dict(t)
        t2["pnl_money"] = round(pnl_money, 2)
        t2["capital_after"] = round(capital, 2)
        t2["riesgo_dinero"] = round(riesgo_dinero, 2)
        trades_money.append(t2)
        equity_money.append(capital)

    return {
        "trades": trades_money,
        "equity_curve_money": equity_money,
        "capital_inicial": capital_inicial,
        "capital_final": round(capital, 2),
        "beneficio_pct": round((capital - capital_inicial) / capital_inicial * 100, 2) if capital_inicial else 0.0,
        "net_profit_money": round(capital - capital_inicial, 2),
    }


def buy_and_hold_curve(df: pd.DataFrame, capital_inicial: float = 1000.0, start_index: int = 0) -> list:
    """Curva de 'comprar y mantener' desde start_index, para comparar contra la equity del backtest."""
    closes = df["Close"].iloc[start_index:]
    if len(closes) == 0:
        return [capital_inicial]
    first = float(closes.iloc[0])
    units = capital_inicial / first
    return [float(c) * units for c in closes]


def _compute_stats(trades: list, equity_r: list) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "operaciones": 0, "ganadas": 0, "perdidas": 0, "winrate_pct": 0.0,
            "profit_factor": 0.0, "beneficio_total_r": 0.0, "max_drawdown_r": 0.0,
            "expectancy_r": 0.0,
        }

    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]

    gross_profit = sum(t["r_multiple"] for t in wins)
    gross_loss = abs(sum(t["r_multiple"] for t in losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    total_r = sum(t["r_multiple"] for t in trades)

    peak = equity_r[0]
    max_dd = 0.0
    for v in equity_r:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    return {
        "operaciones": n,
        "ganadas": len(wins),
        "perdidas": len(losses),
        "winrate_pct": round(len(wins) / n * 100, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
        "beneficio_total_r": round(total_r, 2),
        "max_drawdown_r": round(max_dd, 2),
        "expectancy_r": round(total_r / n, 3),
    }


def print_report(result: dict, titulo: str = "REPORTE DE BACKTEST"):
    s = result["stats"]
    print("=" * 42)
    print(titulo)
    print("=" * 42)
    print(f"Operaciones:      {s['operaciones']}")
    print(f"Ganadas:          {s['ganadas']}")
    print(f"Perdidas:         {s['perdidas']}")
    print(f"Winrate:          {s['winrate_pct']}%")
    print(f"Profit Factor:    {s['profit_factor']}")
    print(f"Beneficio total:  {s['beneficio_total_r']} R")
    print(f"Max Drawdown:     {s['max_drawdown_r']} R")
    print(f"Expectancy:       {s['expectancy_r']} R por operacion")
    print("=" * 42)
    print("Nota: 'R' = multiplo del riesgo arriesgado en cada operacion (no es % de cuenta).")


def compare_configs(df: pd.DataFrame, configs: list, min_candles: int = 30) -> list:
    """
    Corre run_backtest() para cada dict de kwargs en `configs` y devuelve la
    lista de resultados ordenada por profit factor descendente. Cada item
    trae {"config": {...}, "trades": [...], "equity_curve_r": [...], "stats": {...}}.
    """
    results = []
    for cfg in configs:
        res = run_backtest(df, min_candles=min_candles, **cfg)
        results.append({"config": cfg, **res})

    def sort_key(r):
        pf = r["stats"]["profit_factor"]
        return pf if pf != float("inf") else 1e9

    results.sort(key=sort_key, reverse=True)
    return results


def plot_equity_curve(result: dict, save_path: str | None = None):
    """Grafica la curva de equity (en R) del backtest. Requiere matplotlib."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(result["equity_curve_r"], color="#3b82f6", linewidth=1.5)
    ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--")
    ax.set_title("Curva de equity (en multiplos de R)")
    ax.set_xlabel("Numero de operacion")
    ax.set_ylabel("R acumulado")
    ax.grid(alpha=0.2)

    if save_path:
        fig.savefig(save_path, dpi=120, bbox_inches="tight")
        print(f"Grafico guardado en {save_path}")
    else:
        plt.show()


if __name__ == "__main__":
    import argparse
    import data_feed

    parser = argparse.ArgumentParser(description="Backtest de strategy.py sobre un simbolo/timeframe.")
    parser.add_argument("symbol", help="Simbolo, ej: XAUUSD, AAPL, EURUSD, NQ, US100")
    parser.add_argument("--timeframe", default="1h", choices=list(data_feed.TIMEFRAMES.keys()))
    parser.add_argument("--sl-atr", type=float, default=1.0)
    parser.add_argument("--tp-atr", type=float, default=2.0)
    parser.add_argument("--min-score", type=int, default=3)
    parser.add_argument("--require-ob", action="store_true")
    parser.add_argument("--require-fvg", action="store_true")
    parser.add_argument("--plot", action="store_true", help="Guarda equity_curve.png")
    args = parser.parse_args()

    print(f"Descargando {args.symbol} ({args.timeframe})...")
    data = data_feed.fetch_ohlcv(args.symbol, args.timeframe)
    print(f"{len(data)} velas descargadas. Corriendo backtest...")

    out = run_backtest(
        data,
        sl_atr=args.sl_atr,
        tp_atr=args.tp_atr,
        min_score=args.min_score,
        require_ob=args.require_ob,
        require_fvg=args.require_fvg,
    )
    print_report(out, titulo=f"BACKTEST {args.symbol} ({args.timeframe})")

    if args.plot:
        plot_equity_curve(out, save_path="equity_curve.png")
