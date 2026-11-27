"""
data_feed.py
Descarga datos OHLCV via yfinance y traduce alias comunes (XAUUSD, US100, NQ...)
a los tickers reales que usa Yahoo Finance.

Puedes escribir CUALQUIER simbolo en la app: si esta en el diccionario de abajo
se traduce automaticamente; si no esta, se usa tal cual como ticker de Yahoo
Finance (por ejemplo MSFT, TSLA, BTC-USD, ^GSPC, etc.).
"""

import yfinance as yf
import pandas as pd
import numpy as np

# Alias -> ticker real de Yahoo Finance
SYMBOL_ALIASES = {
    "XAUUSD": "GC=F",      # Oro (futuro). Alternativa spot: "XAUUSD=X" (menos fiable en yfinance)
    "XAGUSD": "SI=F",      # Plata
    "US100": "^NDX",       # Nasdaq 100 (indice). Para el futuro CFD-like: "NQ=F"
    "NQ": "NQ=F",          # Futuro Nasdaq
    "US30": "YM=F",        # Futuro Dow Jones
    "US500": "^GSPC",      # S&P 500
    "SPX": "^GSPC",
    "GER40": "^GDAXI",
    "UK100": "^FTSE",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "WTI": "CL=F",
    "US OIL": "CL=F",
}

# Intervalos permitidos en la app -> (interval de yfinance, periodo de descarga)
TIMEFRAMES = {
    "1m": ("1m", "7d"),
    "2m": ("2m", "60d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h": ("1h", "730d"),
    "4h": ("1h", "730d"),   # se resamplea a partir de 1h, yfinance no tiene 4h nativo
    "1d": ("1d", "5y"),
    "1wk": ("1wk", "10y"),
}


def resolve_symbol(user_symbol: str) -> str:
    """Traduce un alias a su ticker real de Yahoo Finance (o lo deja igual)."""
    key = user_symbol.strip().upper()
    return SYMBOL_ALIASES.get(key, user_symbol.strip())


def fetch_ohlcv(user_symbol: str, timeframe: str = "1h") -> pd.DataFrame:
    """
    Descarga velas OHLCV para el simbolo/timeframe pedido.
    Lanza ValueError si el timeframe no es valido o no llegaron datos.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe no soportado: {timeframe}")

    interval, period = TIMEFRAMES[timeframe]
    ticker = resolve_symbol(user_symbol)

    raw = yf.download(
        tickers=ticker,
        interval=interval,
        period=period,
        progress=False,
        auto_adjust=True,
        multi_level_index=False,
        timeout=10,
        threads=False,
    )

    if raw is None or raw.empty:
        raise ValueError(
            f"No se pudieron descargar datos para '{user_symbol}' (ticker resuelto: '{ticker}'). "
            "Revisa que el simbolo exista en Yahoo Finance o prueba escribiendo el ticker exacto."
        )

    raw = raw.rename(columns=str.title)
    raw = raw[["Open", "High", "Low", "Close", "Volume"]]
    raw = raw.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    raw = raw.loc[~raw.index.duplicated(keep="last")]
    raw = raw.loc[
        (raw["Low"] <= raw[["Open", "Close"]].min(axis=1))
        & (raw["High"] >= raw[["Open", "Close"]].max(axis=1))
        & (raw["Volume"] >= 0)
    ]

    if timeframe == "4h":
        raw = raw.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

    if raw.empty:
        raise ValueError("El proveedor no devolvió velas válidas.")
    return raw


def last_price(user_symbol: str) -> float:
    """Ultimo precio de cierre disponible para el simbolo."""
    df = fetch_ohlcv(user_symbol, "15m")
    return float(df["Close"].iloc[-1])
