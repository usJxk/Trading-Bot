"""
storage.py
Persistencia local en SQLite. Guarda todo lo que el bot necesita recordar
entre encendidos: la watchlist, el diario de operaciones manuales, el ultimo
analisis por simbolo y configuraciones generales. Al reiniciar la app se
recarga todo desde aqui, por lo que el bot "no se queda tonto": sabe que
simbolos estabas siguiendo, que operaciones tienes abiertas y cual fue el
ultimo sesgo detectado en cada uno.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_bot.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            timeframe TEXT NOT NULL DEFAULT '1h',
            added_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,              -- 'COMPRA' o 'VENTA'
            entry_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            size REAL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'ABIERTA',  -- 'ABIERTA' o 'CERRADA'
            close_price REAL,
            opened_at TEXT NOT NULL,
            closed_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS last_analysis (
            symbol TEXT PRIMARY KEY,
            timeframe TEXT,
            bias TEXT,
            score INTEGER,
            reasons_json TEXT,
            last_close REAL,
            updated_at TEXT NOT NULL
        )
    """)

    # Tabla nueva (aditiva): historial de backtests, para la pestana "Historial".
    cur.execute("""
        CREATE TABLE IF NOT EXISTS backtest_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            num_candles INTEGER,
            capital_inicial REAL,
            riesgo_pct REAL,
            profit_factor REAL,
            winrate_pct REAL,
            beneficio_r REAL,
            beneficio_pct REAL,
            max_drawdown_r REAL,
            expectancy_r REAL,
            result_json TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------- Watchlist --------------------------------

def add_symbol(symbol: str, timeframe: str = "1h"):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO watchlist (symbol, timeframe, added_at) VALUES (?, ?, ?)",
        (symbol.upper(), timeframe, _now()),
    )
    conn.commit()
    conn.close()


def remove_symbol(symbol: str):
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
    conn.commit()
    conn.close()


def get_watchlist() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --------------------------------- Trades ----------------------------------

def log_trade(symbol, side, entry_price, stop_loss=None, take_profit=None, size=None, notes=""):
    conn = get_connection()
    conn.execute(
        """INSERT INTO trades (symbol, side, entry_price, stop_loss, take_profit, size, notes, status, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'ABIERTA', ?)""",
        (symbol.upper(), side, entry_price, stop_loss, take_profit, size, notes, _now()),
    )
    conn.commit()
    conn.close()


def close_trade(trade_id: int, close_price: float):
    conn = get_connection()
    conn.execute(
        "UPDATE trades SET status = 'CERRADA', close_price = ?, closed_at = ? WHERE id = ?",
        (close_price, _now(), trade_id),
    )
    conn.commit()
    conn.close()


def get_trades(status: str | None = None) -> list:
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM trades WHERE status = ? ORDER BY opened_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades ORDER BY opened_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------- Ultimo analisis ------------------------------

def save_analysis(symbol: str, timeframe: str, bias: str, score: int, reasons: list, last_close: float):
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO last_analysis (symbol, timeframe, bias, score, reasons_json, last_close, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (symbol.upper(), timeframe, bias, score, json.dumps(reasons, ensure_ascii=False), last_close, _now()),
    )
    conn.commit()
    conn.close()


def get_analysis(symbol: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM last_analysis WHERE symbol = ?", (symbol.upper(),)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["reasons"] = json.loads(d.pop("reasons_json"))
    return d


def get_all_analyses() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM last_analysis").fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d.pop("reasons_json"))
        out[d["symbol"]] = d
    return out


# --------------------------------- Settings ---------------------------------

def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_setting(key: str, default=None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


# ---------------------------- Historial de backtests ----------------------------
# (Tabla y funciones nuevas -- aditivas, no afectan nada de lo anterior.)

def save_backtest_run(symbol, timeframe, num_candles, capital_inicial, riesgo_pct,
                       stats: dict, full_result_json: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO backtest_history
           (fecha, symbol, timeframe, num_candles, capital_inicial, riesgo_pct,
            profit_factor, winrate_pct, beneficio_r, beneficio_pct, max_drawdown_r,
            expectancy_r, result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            _now(), symbol.upper(), timeframe, num_candles, capital_inicial, riesgo_pct,
            stats.get("profit_factor"), stats.get("winrate_pct"), stats.get("net_profit_r"),
            stats.get("beneficio_pct"), stats.get("max_drawdown_r"), stats.get("expectancy_r"),
            full_result_json,
        ),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def get_backtest_history() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM backtest_history ORDER BY fecha DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backtest_by_id(run_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM backtest_history WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d["result_json"])
    return d


def delete_backtest_run(run_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM backtest_history WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()

