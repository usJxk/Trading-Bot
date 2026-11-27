"""
strategy.py
Motor de analisis tecnico: estructura de mercado (ICT/SMC), Fair Value Gaps,
Order Blocks, barridos de liquidez, zonas premium/discount y una
aproximacion de "footprint" (presión compradora/vendedora por vela).

IMPORTANTE sobre el footprint:
Un footprint real necesita datos tick-by-tick de volumen por nivel de precio
(bid/ask). Yahoo Finance (la fuente de datos gratuita que usa este bot) no
entrega eso. Aqui se calcula una APROXIMACION del delta comprador/vendedor
usando el volumen total de la vela y la posicion del cierre dentro del rango
de la vela (si cierra cerca del maximo, se asume mas presión compradora; si
cierra cerca del minimo, mas presión vendedora). Es una heuristica muy usada
en retail, pero no reemplaza un footprint institucional real basado en tick data.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades de estructura (swings, BOS, CHoCH)
# ---------------------------------------------------------------------------

def find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """Marca swing highs / swing lows (fractales de N velas a cada lado)."""
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)

    size = left + right + 1
    if n >= size:
        windows_h = np.lib.stride_tricks.sliding_window_view(highs, size)
        windows_l = np.lib.stride_tricks.sliding_window_view(lows, size)
        # argmax/min keep the first match, as in the original fractal rule.
        swing_high[left:n - right] = (windows_h.argmax(axis=1) == left) & ~np.isnan(windows_h).any(axis=1)
        swing_low[left:n - right] = (windows_l.argmin(axis=1) == left) & ~np.isnan(windows_l).any(axis=1)

    out = df.copy()
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    return out


def market_structure(df: pd.DataFrame) -> dict:
    """
    Determina tendencia (HH/HL alcista, LH/LL bajista), ultimo BOS y si hubo
    un CHoCH (cambio de caracter) reciente.
    """
    swings = find_swings(df)
    highs = swings[swings["swing_high"]]
    lows = swings[swings["swing_low"]]

    if len(highs) < 2 or len(lows) < 2:
        return {
            "trend": "INDEFINIDA",
            "last_bos": None,
            "choch": False,
            "last_swing_high": None,
            "last_swing_low": None,
        }

    last_two_highs = highs["High"].iloc[-2:].values
    last_two_lows = lows["Low"].iloc[-2:].values

    higher_highs = last_two_highs[1] > last_two_highs[0]
    higher_lows = last_two_lows[1] > last_two_lows[0]
    lower_highs = last_two_highs[1] < last_two_highs[0]
    lower_lows = last_two_lows[1] < last_two_lows[0]

    if higher_highs and higher_lows:
        trend = "ALCISTA"
    elif lower_highs and lower_lows:
        trend = "BAJISTA"
    else:
        trend = "RANGO"

    last_swing_high = highs["High"].iloc[-1]
    last_swing_low = lows["Low"].iloc[-1]
    last_close = df["Close"].iloc[-1]

    last_bos = None
    if last_close > last_swing_high:
        last_bos = "ALCISTA"
    elif last_close < last_swing_low:
        last_bos = "BAJISTA"

    # CHoCH simplificado: la tendencia previa (con las 2 anteriores) era
    # contraria al ultimo BOS confirmado.
    choch = False
    if len(highs) >= 3 and len(lows) >= 3 and last_bos is not None:
        prev_higher_highs = highs["High"].iloc[-3] < highs["High"].iloc[-2]
        prev_higher_lows = lows["Low"].iloc[-3] < lows["Low"].iloc[-2]
        prev_trend = "ALCISTA" if (prev_higher_highs and prev_higher_lows) else (
            "BAJISTA" if (not prev_higher_highs and not prev_higher_lows) else "RANGO"
        )
        if prev_trend != "RANGO" and prev_trend != last_bos:
            choch = True

    return {
        "trend": trend,
        "last_bos": last_bos,
        "choch": choch,
        "last_swing_high": float(last_swing_high),
        "last_swing_low": float(last_swing_low),
    }


# ---------------------------------------------------------------------------
# Fair Value Gaps (FVG)
# ---------------------------------------------------------------------------

def find_fvgs(df: pd.DataFrame, max_lookback: int = 60) -> list:
    """
    Detecta Fair Value Gaps de 3 velas (concepto ICT).
    Bullish FVG: low[i] > high[i-2]  -> zona = (high[i-2], low[i])
    Bearish FVG: high[i] < low[i-2]  -> zona = (high[i], low[i-2])
    Marca si ya fueron mitigados (el precio volvio a entrar en la zona).
    """
    fvgs = []
    n = len(df)
    start = max(2, n - max_lookback)

    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    for i in range(start, n):
        high_2, high_i = highs[i - 2], highs[i]
        low_2, low_i = lows[i - 2], lows[i]

        if low_i > high_2:
            zone_low, zone_high = high_2, low_i
            direction = "ALCISTA"
        elif high_i < low_2:
            zone_low, zone_high = high_i, low_2
            direction = "BAJISTA"
        else:
            continue

        mitigated = bool(np.any((lows[i + 1:] <= zone_high) & (highs[i + 1:] >= zone_low)))

        fvgs.append({
            "index": i,
            "timestamp": df.index[i],
            "direction": direction,
            "zone_low": float(zone_low),
            "zone_high": float(zone_high),
            "mitigated": mitigated,
        })

    return fvgs


# ---------------------------------------------------------------------------
# Order Blocks (simplificado)
# ---------------------------------------------------------------------------

def find_order_blocks(df: pd.DataFrame, impulse_pct: float = 0.5, max_lookback: int = 80) -> list:
    """
    Order block alcista: ultima vela bajista antes de un impulso alcista fuerte.
    Order block bajista: ultima vela alcista antes de un impulso bajista fuerte.
    'impulse_pct' es el movimiento minimo (en % del ATR simple) para considerar
    que hubo un impulso.
    """
    n = len(df)
    start = max(3, n - max_lookback)
    ranges = df["High"] - df["Low"]
    average_ranges = ranges.rolling(14).mean().fillna(ranges).to_numpy()
    highs, lows = df["High"].to_numpy(), df["Low"].to_numpy()
    bodies = df["Close"].to_numpy() - df["Open"].to_numpy()

    active = []
    for i in range(start, n - 1):
        move, avg_range = bodies[i + 1], average_ranges[i]
        if avg_range == 0 or np.isnan(avg_range):
            continue
        strength = abs(move) / avg_range
        if not strength >= 1 + impulse_pct:
            continue
        if move > 0 and bodies[i] < 0:
            direction = "ALCISTA"
        elif move < 0 and bodies[i] > 0:
            direction = "BAJISTA"
        else:
            continue
        if np.any((lows[i + 1:] <= highs[i]) & (highs[i + 1:] >= lows[i])):
            continue
        active.append({
            "index": i,
            "timestamp": df.index[i],
            "direction": direction,
            "zone_low": float(lows[i]),
            "zone_high": float(highs[i]),
        })

    return active[-5:]


# ---------------------------------------------------------------------------
# Barrido de liquidez (liquidity sweep)
# ---------------------------------------------------------------------------

def find_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> dict | None:
    """
    Detecta si en las ultimas velas el precio metio mecha mas alla de un swing
    previo y cerro de vuelta adentro (barrida de liquidez / stop hunt).
    """
    swings = find_swings(df)
    recent = swings.iloc[-lookback:]
    prior = swings.iloc[:-lookback] if len(swings) > lookback else swings

    prior_highs = prior[prior["swing_high"]]["High"]
    prior_lows = prior[prior["swing_low"]]["Low"]
    if prior_highs.empty or prior_lows.empty:
        return None

    ref_high = prior_highs.iloc[-1]
    ref_low = prior_lows.iloc[-1]

    last = df.iloc[-1]

    if last["High"] > ref_high and last["Close"] < ref_high:
        return {"type": "BARRIDA_ALCISTA_LIQUIDEZ_COMPRADORA", "signal": "BAJISTA", "level": float(ref_high)}
    if last["Low"] < ref_low and last["Close"] > ref_low:
        return {"type": "BARRIDA_BAJISTA_LIQUIDEZ_VENDEDORA", "signal": "ALCISTA", "level": float(ref_low)}
    return None


# ---------------------------------------------------------------------------
# Premium / Discount (retroceso del rango, concepto ICT/SMC)
# ---------------------------------------------------------------------------

def premium_discount(df: pd.DataFrame, lookback: int = 50) -> dict:
    window = df.iloc[-lookback:]
    hi = window["High"].max()
    lo = window["Low"].min()
    mid = (hi + lo) / 2
    last_close = df["Close"].iloc[-1]
    zone = "PREMIUM" if last_close > mid else "DISCOUNT"
    return {"zone": zone, "range_high": float(hi), "range_low": float(lo), "midpoint": float(mid)}


# ---------------------------------------------------------------------------
# Footprint aproximado (presión compradora / vendedora por volumen)
# ---------------------------------------------------------------------------

def footprint_approx(df: pd.DataFrame, lookback: int = 10) -> dict:
    """
    Aproxima el delta comprador/vendedor de cada vela usando la posicion del
    cierre dentro del rango high-low, ponderado por el volumen de la vela.
    delta_vela = volumen * (2 * (close - low) / (high - low) - 1)
    Rango del factor: -1 (cierre en el minimo) a +1 (cierre en el maximo).
    """
    window = df.iloc[-lookback:].copy()
    rng = (window["High"] - window["Low"]).replace(0, np.nan)
    factor = (2 * (window["Close"] - window["Low"]) / rng) - 1
    factor = factor.fillna(0)
    delta = (window["Volume"] * factor)

    total_delta = float(delta.sum())
    total_volume = float(window["Volume"].sum())
    bias = "ALCISTA" if total_delta > 0 else ("BAJISTA" if total_delta < 0 else "NEUTRAL")

    return {
        "bias": bias,
        "delta_total": total_delta,
        "volumen_total": total_volume,
        "delta_pct": (total_delta / total_volume * 100) if total_volume else 0.0,
    }


# ---------------------------------------------------------------------------
# Combinacion final: genera el sesgo (bias) y las razones
# ---------------------------------------------------------------------------

def analyze(
    df: pd.DataFrame,
    use_trend: bool = True,
    use_bos: bool = True,
    use_choch: bool = True,
    use_fvg: bool = True,
    use_order_blocks: bool = True,
    use_liquidity_sweep: bool = True,
    use_premium_discount: bool = True,
    use_footprint: bool = True,
) -> dict:
    """
    Corre todo el analisis sobre un DataFrame OHLCV (columnas: Open, High, Low,
    Close, Volume; index = timestamps ordenados ascendente) y devuelve un
    veredicto con puntaje, sesgo final y las razones detras de cada punto.

    Los parametros use_* activan o desactivan la CONTRIBUCION AL PUNTAJE de
    cada componente (todos True por defecto, que es el comportamiento
    original e identico al de antes). Se agregaron unicamente para que
    optimizer.py pueda probar que tanto aporta cada concepto ICT/SMC al
    resultado -- una llamada normal `analyze(df)` no cambia en nada.
    """
    if len(df) < 30:
        return {
            "bias": "DATOS_INSUFICIENTES",
            "score": 0,
            "reasons": ["Se necesitan al menos 30 velas para un analisis confiable."],
            "details": {},
        }

    struct = market_structure(df)
    fvgs = find_fvgs(df)
    obs = find_order_blocks(df)
    sweep = find_liquidity_sweep(df)
    pd_zone = premium_discount(df)
    fp = footprint_approx(df)

    last_close = float(df["Close"].iloc[-1])
    active_fvgs = [f for f in fvgs if not f["mitigated"]]

    score = 0
    reasons = []

    if use_trend:
        if struct["trend"] == "ALCISTA":
            score += 2
            reasons.append("Estructura de mercado alcista (máximos y mínimos ascendentes).")
        elif struct["trend"] == "BAJISTA":
            score -= 2
            reasons.append("Estructura de mercado bajista (máximos y mínimos descendentes).")

    if use_bos:
        if struct["last_bos"] == "ALCISTA":
            score += 1
            reasons.append("El cierre superó el último máximo de referencia (BOS).")
        elif struct["last_bos"] == "BAJISTA":
            score -= 1
            reasons.append("El cierre quedó por debajo del último mínimo de referencia (BOS).")

    if use_choch and struct["choch"]:
        if struct["last_bos"] == "ALCISTA":
            score += 1
            reasons.append("Posible cambio de estructura hacia alcista (CHoCH).")
        elif struct["last_bos"] == "BAJISTA":
            score -= 1
            reasons.append("Posible cambio de estructura hacia bajista (CHoCH).")

    if use_fvg:
        nearby_fvgs = [f for f in active_fvgs if f["zone_low"] * 0.99 <= last_close <= f["zone_high"] * 1.01]
        for f in nearby_fvgs[-2:]:
            if f["direction"] == "ALCISTA":
                score += 1
                reasons.append(f"FVG alcista sin mitigar cerca del precio ({f['zone_low']:.4f}-{f['zone_high']:.4f}).")
            else:
                score -= 1
                reasons.append(f"FVG bajista sin mitigar cerca del precio ({f['zone_low']:.4f}-{f['zone_high']:.4f}).")

    if use_order_blocks:
        for ob in obs[-2:]:
            near = ob["zone_low"] * 0.99 <= last_close <= ob["zone_high"] * 1.01
            if near and ob["direction"] == "ALCISTA":
                score += 1
                reasons.append(f"Precio reaccionando en Order Block alcista ({ob['zone_low']:.4f}-{ob['zone_high']:.4f}).")
            elif near and ob["direction"] == "BAJISTA":
                score -= 1
                reasons.append(f"Precio reaccionando en Order Block bajista ({ob['zone_low']:.4f}-{ob['zone_high']:.4f}).")

    if use_liquidity_sweep and sweep:
        if sweep["signal"] == "ALCISTA":
            score += 2
            reasons.append(f"Barrida de liquidez bajista detectada en {sweep['level']:.4f} (posible giro alcista).")
        else:
            score -= 2
            reasons.append(f"Barrida de liquidez alcista detectada en {sweep['level']:.4f} (posible giro bajista).")

    if use_premium_discount:
        if pd_zone["zone"] == "DISCOUNT":
            score += 1
            reasons.append("El cierre está en la mitad inferior del rango reciente (descuento).")
        else:
            score -= 1
            reasons.append("El cierre está en la mitad superior del rango reciente (prima).")

    if use_footprint:
        if fp["bias"] == "ALCISTA":
            score += 1
            reasons.append(f"Footprint aproximado muestra presión compradora (delta +{fp['delta_pct']:.1f}%).")
        elif fp["bias"] == "BAJISTA":
            score -= 1
            reasons.append(f"Footprint aproximado muestra presión vendedora (delta {fp['delta_pct']:.1f}%).")

    if score >= 3:
        bias = "ALCISTA"
    elif score <= -3:
        bias = "BAJISTA"
    else:
        bias = "NEUTRAL / RANGO"

    return {
        "bias": bias,
        "score": score,
        "reasons": reasons,
        "details": {
            "structure": struct,
            "fvgs": fvgs,
            "order_blocks": obs,
            "sweep": sweep,
            "premium_discount": pd_zone,
            "footprint": fp,
            "last_close": last_close,
        },
    }
