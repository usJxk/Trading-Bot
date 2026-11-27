"""Historical market data and deterministic examples for the local UI."""

from collections import OrderedDict
import re
from threading import Lock
from time import monotonic

import numpy as np
import pandas as pd

import data_feed

INTERVALS = ("1m", "2m", "15m", "30m", "1h", "4h", "1d", "1wk")
EXAMPLES = {"AAPL": 228.4, "MSFT": 426.2, "BTC-USD": 87200.0, "EURUSD": 1.087}
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def symbol_key(value):
    if not isinstance(value, str):
        raise ValueError("Escribe un símbolo válido.")
    key = value.strip().upper()
    if key not in data_feed.SYMBOL_ALIASES and not re.fullmatch(r"[\^A-Z0-9][A-Z0-9.=\-]{0,23}", key):
        raise ValueError("Escribe un solo símbolo, por ejemplo AAPL o BTC-USD.")
    return key


def example(symbol, interval):
    """A seeded OHLCV series with several market regimes and no network calls."""
    seed = sum((i + 1) * ord(c) for i, c in enumerate(symbol + interval))
    rng = np.random.default_rng(seed)
    length = 600
    t = np.arange(length)
    base = EXAMPLES.get(symbol, 124.0)
    drift = np.interp(t, [0, 140, 230, 360, 449, 535, 569, 599],
                      [-.035, .025, -.025, .05, .015, .05, .035, .122])
    close = base * (1 + drift + np.sin(t / 11) * .009 + np.sin(t / 4.6) * .005
                    + rng.normal(0, .0024, length))
    spread = base * rng.uniform(.001, .005, length)
    opening = np.r_[close[0], close[:-1]] + base * rng.normal(0, .0013, length)
    index = pd.date_range(end="2025-02-21 16:00", periods=length,
                          freq=interval.replace("m", "min") if interval != "1wk" else "W-FRI", tz="UTC")
    return pd.DataFrame({
        "Open": opening,
        "High": np.maximum(opening, close) + spread,
        "Low": np.minimum(opening, close) - spread * rng.uniform(.55, 1.3, length),
        "Close": close,
        "Volume": rng.integers(54000, 460000, length),
    }, index=index)


def load(symbol, interval, source):
    if source == "demo":
        return example(symbol, interval)
    try:
        return data_feed.fetch_ohlcv(symbol, interval)
    except Exception as exc:
        raise MarketUnavailable(
            "Yahoo Finance no devolvió datos. Revisa el símbolo o prueba con la serie de ejemplo."
        ) from exc


class MarketUnavailable(Exception):
    pass


def candles(frame):
    return [
        [stamp.isoformat(), *map(float, values)]
        for stamp, *values in frame[COLUMNS].itertuples(name=None)
    ]


def completed(frame, interval):
    # Weekly dates from Yahoo mark the start of the trading week. A full calendar
    # interval is a conservative cutoff for symbols on different exchanges.
    span = pd.Timedelta(weeks=1) if interval == "1wk" else pd.Timedelta(
        interval.replace("m", "min")
    )
    index = pd.to_datetime(frame.index, utc=True)
    mask = index + span <= pd.Timestamp.now(tz="UTC")
    closed = frame.loc[mask].copy()
    closed.index = index[mask]
    return closed


class CandleCache:
    """Share completed candles between views while bounding provider traffic and memory."""

    def __init__(self, capacity=24, max_age=60):
        self.capacity = capacity
        self.max_age = max_age
        self.entries = OrderedDict()
        self.lock = Lock()
        self.provider = Lock()

    def _get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry and monotonic() < entry[0]:
                self.entries.move_to_end(key)
                return entry[1]
        return None

    def _put(self, key, frame, lifetime):
        with self.lock:
            self.entries[key] = (monotonic() + lifetime, frame)
            self.entries.move_to_end(key)
            if len(self.entries) > self.capacity:
                self.entries.popitem(last=False)

    def get(self, params, limit):
        symbol, interval, source = params
        ticker = data_feed.resolve_symbol(symbol) if source == "yahoo" else symbol
        key = (source, ticker, interval)
        frame = self._get(key)
        if frame is None and source == "demo":
            frame = example(symbol, interval)
            self._put(key, frame, float("inf"))
        if frame is None:
            if not self.provider.acquire(timeout=12):
                raise MarketUnavailable("Yahoo Finance sigue ocupado. Vuelve a intentar en un momento.")
            try:
                frame = self._get(key)
                if frame is None:
                    frame = completed(load(symbol, interval, source), interval).tail(600)
                    # Avoid freezing the previous candle across a short interval boundary.
                    lifetime = min(self.max_age, 15) if interval in ("1m", "2m") else self.max_age
                    self._put(key, frame, lifetime)
            finally:
                self.provider.release()
        return frame.tail(limit)
