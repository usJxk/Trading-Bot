"""
optimizer.py
Corre automaticamente muchas configuraciones de backtest (distintos min_score,
distintos toggles de componentes ICT/SMC, distintos SL/TP) y devuelve una
tabla ordenada por Profit Factor, tal como se pidio.

No modifica backtester.py ni strategy.py: solo arma combinaciones de
parametros y llama a backtester.run_backtest() para cada una.
"""

import itertools

import backtester
import statistics_module


DEFAULT_GRID = {
    "min_score": [3, 4, 5, 6],
    "toggle_order_blocks": [True, False],
    "toggle_fvg": [True, False],
    "toggle_footprint": [True, False],
    "toggle_liquidity_sweep": [True, False],
    "toggle_premium_discount": [True, False],
    "toggle_choch": [True, False],
    "toggle_bos": [True, False],
    "toggle_trend": [True, False],
}


def _build_configs(grid: dict, base_kwargs: dict) -> list:
    """Convierte el grid (listas de valores por parametro) en una lista de configs concretas."""
    keys = list(grid.keys())
    values_product = itertools.product(*[grid[k] for k in keys])

    configs = []
    for combo in values_product:
        combo_dict = dict(zip(keys, combo))
        strategy_kwargs = {
            "use_order_blocks": combo_dict.pop("toggle_order_blocks", True),
            "use_fvg": combo_dict.pop("toggle_fvg", True),
            "use_footprint": combo_dict.pop("toggle_footprint", True),
            "use_liquidity_sweep": combo_dict.pop("toggle_liquidity_sweep", True),
            "use_premium_discount": combo_dict.pop("toggle_premium_discount", True),
            "use_choch": combo_dict.pop("toggle_choch", True),
            "use_bos": combo_dict.pop("toggle_bos", True),
            "use_trend": combo_dict.pop("toggle_trend", True),
        }
        cfg = {**base_kwargs, **combo_dict, "strategy_kwargs": strategy_kwargs}
        configs.append(cfg)
    return configs


def _label_config(cfg: dict) -> str:
    parts = [f"score>={cfg.get('min_score', '-')}"]
    sk = cfg.get("strategy_kwargs", {})
    off = [k.replace("use_", "") for k, v in sk.items() if not v]
    if off:
        parts.append("sin " + "+".join(off))
    return " | ".join(parts)


def run_optimization(df, grid: dict | None = None, base_kwargs: dict | None = None,
                      min_candles: int = 30, progress_callback=None, max_combinations: int = 500) -> list:
    """
    Ejecuta backtester.run_backtest() para cada combinacion del grid.
    grid: dict con listas de valores (ver DEFAULT_GRID). None = usa el default.
    base_kwargs: parametros fijos para todas las corridas (ej. sl_atr, tp_atr).
    progress_callback: callback(indice_actual, total_configs).
    max_combinations: limite de seguridad para no generar grids gigantes por error.

    ADVERTENCIA: el DEFAULT_GRID completo son 4 * 2^8 = 1024 combinaciones. Con
    backtest O(n^2), esto puede tardar mucho en historiales largos. Para el uso
    normal es preferible run_optimization_presets() (mucho mas rapido).

    Devuelve una lista de dicts ordenada por Profit Factor descendente:
    [{"label": ..., "config": ..., "stats": ...}, ...]
    """
    grid = grid or DEFAULT_GRID
    base_kwargs = base_kwargs or {"sl_atr": 1.0, "tp_atr": 2.0}

    configs = _build_configs(grid, base_kwargs)
    if len(configs) > max_combinations:
        configs = configs[:max_combinations]

    results = []
    for idx, cfg in enumerate(configs):
        if progress_callback is not None:
            progress_callback(idx, len(configs))

        res = backtester.run_backtest(df, min_candles=min_candles, **cfg)
        stats = statistics_module.compute_full_stats(res["trades"], res["equity_curve_r"])

        results.append({
            "label": _label_config(cfg),
            "config": cfg,
            "stats": stats,
        })

    if progress_callback is not None:
        progress_callback(len(configs), len(configs))

    def sort_key(r):
        pf = r["stats"]["profit_factor"]
        return pf if pf != float("inf") else 1e9

    results.sort(key=sort_key, reverse=True)
    return results


def run_optimization_presets(df, min_scores=(3, 4, 5, 6), base_kwargs: dict | None = None,
                              min_candles: int = 30, progress_callback=None) -> list:
    """
    Version rapida y practica del optimizador: para cada min_score, compara
    "Base" (todo activo) contra apagar UN componente ICT/SMC a la vez (igual
    al ejemplo de la tabla que pediste: Base / Score>=4 / Score>=5 / ...).
    Son min_scores * 9 combinaciones en vez de min_scores * 256 -> mucho mas
    rapido y mucho mas facil de leer.
    """
    base_kwargs = base_kwargs or {"sl_atr": 1.0, "tp_atr": 2.0}
    toggles = ["use_order_blocks", "use_fvg", "use_footprint", "use_liquidity_sweep",
               "use_premium_discount", "use_choch", "use_bos", "use_trend"]

    presets = [("Base", {})]
    for t in toggles:
        presets.append((f"sin {t.replace('use_', '')}", {t: False}))

    combos = []
    for score in min_scores:
        for label, off in presets:
            sk = {k: True for k in toggles}
            sk.update(off)
            combos.append((f"{label} (score>={score})", {**base_kwargs, "min_score": score, "strategy_kwargs": sk}))

    results = []
    for idx, (label, cfg) in enumerate(combos):
        if progress_callback is not None:
            progress_callback(idx, len(combos))
        res = backtester.run_backtest(df, min_candles=min_candles, **cfg)
        stats = statistics_module.compute_full_stats(res["trades"], res["equity_curve_r"])
        results.append({"label": label, "config": cfg, "stats": stats})

    if progress_callback is not None:
        progress_callback(len(combos), len(combos))

    def sort_key(r):
        pf = r["stats"]["profit_factor"]
        return pf if pf != float("inf") else 1e9

    results.sort(key=sort_key, reverse=True)
    return results
