"""Local browser interface for analysis, paper journal and historical simulation."""

import csv
from contextlib import closing
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
import json
import math
from numbers import Integral, Real
from secrets import compare_digest, token_hex
from threading import Lock

from .jobs import Simulations

from flask import Flask, Response, abort, render_template, request
from werkzeug.exceptions import HTTPException

import backtester
import data_feed
import statistics_module
import storage
import strategy
from . import market


def json_values(value):
    if isinstance(value, dict):
        return {key: json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_values(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return value


def parameters(data):
    source = data.get("source", "demo")
    interval = data.get("interval", "1h")
    if source not in ("demo", "yahoo") or interval not in market.INTERVALS:
        raise ValueError("Selecciona una fuente y un intervalo válidos.")
    return market.symbol_key(data.get("symbol")), interval, source


def object_body():
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError("El contenido debe ser un objeto JSON.")
    return data


def number(data, key, label, low, high, *, integer=False, optional=False):
    value = data.get(key)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise ValueError(f"{label}: escribe un número válido.")
    if not low <= value <= high:
        raise ValueError(f"{label}: usa un valor entre {low:g} y {high:g}.")
    return value


def simulation_parameters(data):
    params = parameters(data)
    values = {
        "limit": number(data, "limit", "Velas", 60, 600, integer=True),
        "sl": number(data, "sl", "Stop", .1, 10),
        "tp": number(data, "tp", "Objetivo", .1, 20),
        "score": number(data, "score", "Puntuación", 1, 10, integer=True),
        "cost": number(data, "cost", "Coste por operación", 0, 2),
    }
    return params, values


def simulation(cache, params, values, progress=None):
    symbol, interval, source = params
    limit, sl, tp, score, cost = (values[key] for key in ("limit", "sl", "tp", "score", "cost"))
    frame = cache.get(params, limit)
    if len(frame) < 60:
        raise ValueError("Se necesitan al menos 60 velas cerradas para simular.")
    result = backtester.run_backtest(frame, sl_atr=sl, tp_atr=tp, min_score=score,
                                    progress_callback=progress)
    trades = []
    curve = [0.0]
    for trade in result["trades"]:
        net = trade["r_multiple"] - cost
        trades.append({**trade, "gross_r": trade["r_multiple"], "r_multiple": net,
                       "outcome": "WIN" if net > 1e-9 else "LOSS" if net < -1e-9 else "BREAK_EVEN"})
        curve.append(curve[-1] + net)
    stats = statistics_module.compute_full_stats(trades, curve)
    config = {"symbol": symbol, "timeframe": interval, "source": source,
              "num_candles": len(frame), "limit": limit, "sl": sl, "tp": tp, "score": score,
              "cost": cost, "start": frame.index[0], "end": frame.index[-1],
              "sample_sha256": sha256(frame.to_csv(float_format="%.12g", lineterminator="\n").encode()).hexdigest()}
    payload = json_values({"config": config, "stats": stats, "curve": curve, "trades": trades})
    return payload


def save_simulation(payload):
    config = payload["config"]
    run_id = storage.save_backtest_run(
        config["symbol"], config["timeframe"], config["num_candles"],
        None, None, payload["stats"], json.dumps(payload, allow_nan=False)
    )
    return {**payload, "id": run_id}


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def create_app():
    app = Flask(__name__)
    app.config.update(TRUSTED_HOSTS=["127.0.0.1", "localhost"], MAX_CONTENT_LENGTH=12 * 1024)
    storage.init_db()
    token = token_hex(32)
    simulation_lock = Lock()
    cache = market.CandleCache()
    jobs = Simulations(simulation_lock, app.logger)

    @app.before_request
    def protect_api():
        if request.path.startswith("/api/"):
            supplied = request.headers.get("X-Terminal-Token", "")
            if not compare_digest(supplied.encode("utf-8"), token.encode("ascii")):
                abort(403, "Abre la interfaz desde este equipo.")
            if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                abort(403, "Abre la interfaz desde este equipo.")

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path == "/" or request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return {"error": str(error)}, 400

    @app.errorhandler(market.MarketUnavailable)
    def unavailable(error):
        return {"error": str(error)}, 502

    @app.errorhandler(HTTPException)
    def http_error(error):
        return {"error": error.description}, error.code

    @app.errorhandler(500)
    def server_error(_error):
        return {"error": "No se pudo completar la operación. Revisa el registro de la aplicación."}, 500

    @app.get("/")
    def index():
        return render_template("index.html", token=token)

    @app.get("/api/analysis")
    def analysis():
        params = parameters(request.args)
        symbol, interval, source = params
        frame = cache.get(params, 600)
        if len(frame) < 30:
            raise ValueError("El proveedor devolvió menos de 30 velas cerradas.")
        result = strategy.analyze(frame.tail(420))
        details = result["details"]
        recent = frame.tail(400)
        zones = [
            {"start": zone["timestamp"], "low": zone["zone_low"], "high": zone["zone_high"],
             "bias": zone["direction"], "kind": kind}
            for kind, items in (("FVG", details["fvgs"]), ("OB", details["order_blocks"]))
            for zone in items[-8:] if not zone.get("mitigated", False)
        ]
        previous, last = frame["Close"].iloc[-2:]
        return json_values({
            "symbol": symbol, "interval": interval, "source": source,
            "ticker": data_feed.resolve_symbol(symbol), "candles": market.candles(recent),
            "bias": result["bias"], "score": result["score"], "reasons": result["reasons"],
            "trend": details["structure"]["trend"], "zones": zones, "close": last,
            "change": (last - previous) / abs(previous) * 100 if previous else None,
            "volume": frame["Volume"].iloc[-1],
        })

    @app.get("/api/watch")
    def watchlist():
        return {"items": storage.get_watchlist()}

    @app.post("/api/watch")
    def save_watch():
        symbol, interval, _ = parameters(object_body())
        storage.add_symbol(symbol, interval)
        return {"items": storage.get_watchlist()}, 201

    @app.delete("/api/watch/<symbol>")
    def remove_watch(symbol):
        storage.remove_symbol(market.symbol_key(symbol))
        return {"items": storage.get_watchlist()}

    @app.get("/api/journal")
    def journal():
        return json_values({"items": storage.get_trades()})

    @app.post("/api/journal")
    def add_trade():
        data = object_body()
        symbol = market.symbol_key(data.get("symbol"))
        side, notes = data.get("side"), data.get("notes", "")
        if side not in ("COMPRA", "VENTA") or not isinstance(notes, str) or len(notes) > 1000:
            raise ValueError("Selecciona un lado y limita la nota a 1.000 caracteres.")
        entry = number(data, "entry", "Entrada", 1e-10, 1e12)
        stop = number(data, "stop", "Stop", 1e-10, 1e12, optional=True)
        target = number(data, "target", "Objetivo", 1e-10, 1e12, optional=True)
        size = number(data, "size", "Cantidad", 1e-10, 1e12, optional=True)
        if ((stop is not None and (stop >= entry if side == "COMPRA" else stop <= entry))
                or (target is not None and (target <= entry if side == "COMPRA" else target >= entry))):
            raise ValueError("Revisa que el stop y el objetivo estén del lado correcto de la entrada.")
        storage.log_trade(symbol, side, entry, stop, target, size, notes.strip())
        return journal(), 201

    @app.post("/api/journal/<int:trade_id>/close")
    def close_trade(trade_id):
        close = number(object_body(), "close", "Precio de cierre", 1e-10, 1e12)
        if not storage.close_trade(trade_id, close):
            abort(409, "La operación ya está cerrada o no existe.")
        return journal()

    @app.post("/api/backtests")
    def run_backtest():
        params, values = simulation_parameters(object_body())
        if not simulation_lock.acquire(blocking=False):
            abort(429, "Hay una simulación en curso.")
        try:
            return save_simulation(simulation(cache, params, values)), 201
        finally:
            simulation_lock.release()

    @app.post("/api/backtest-jobs")
    def start_job():
        params, values = simulation_parameters(object_body())

        def compute(progress):
            return simulation(cache, params, values, progress)

        job_id = jobs.start(compute, save_simulation)
        if job_id is None:
            abort(409, "Ya hay una simulación en curso.")
        return {"id": job_id}, 202

    @app.get("/api/backtest-jobs/<job_id>")
    def job_status(job_id):
        status = jobs.status(job_id)
        if status is None:
            abort(404, "La sesión de esta simulación ya no está disponible. Revisa el historial.")
        return status

    @app.delete("/api/backtest-jobs/<job_id>")
    def cancel_job(job_id):
        if not jobs.cancel(job_id):
            abort(409, "La simulación ya terminó o está guardando el resultado.")
        return {"status": "cancelling"}, 202

    @app.get("/api/backtests")
    def history():
        with closing(storage.get_connection()) as conn:
            rows = conn.execute(
                """SELECT id, fecha, symbol, timeframe, num_candles, beneficio_r
                   FROM backtest_history ORDER BY id DESC LIMIT 100"""
            ).fetchall()
        return json_values({"items": [dict(row) for row in rows]})

    def saved(run_id):
        row = storage.get_backtest_by_id(run_id)
        if row is None:
            abort(404, "No existe esa simulación.")
        return json_values({**row["result"], "id": run_id})

    @app.get("/api/backtests/<int:run_id>")
    def backtest_info(run_id):
        return saved(run_id)

    @app.delete("/api/backtests/<int:run_id>")
    def remove_backtest(run_id):
        storage.delete_backtest_run(run_id)
        return history()

    @app.get("/api/backtests/<int:run_id>/export/<fmt>")
    def export(run_id, fmt):
        payload = saved(run_id)
        if fmt == "json":
            output = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
            mime = "application/json"
        elif fmt == "csv" and "trades" in payload:
            table = StringIO()
            fields = ("entry_time", "exit_time", "side", "entry_price", "exit_price",
                      "sl", "tp", "gross_r", "r_multiple", "outcome", "score")
            writer = csv.writer(table)
            writer.writerow(fields)
            writer.writerows([csv_cell(trade.get(field)) for field in fields] for trade in payload["trades"])
            output, mime = table.getvalue(), "text/csv"
        else:
            abort(404, "Ese formato de exportación no está disponible para esta simulación.")
        return Response(output, mimetype=mime,
                        headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.{fmt}"'})

    return app
