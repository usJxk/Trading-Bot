"""
backtest_window.py
Ventana independiente (Toplevel) de Backtesting / Optimizacion / Historial.
Se abre desde app.py con un boton, sin tocar el flujo de analisis normal.

Toda la logica pesada vive en backtester.py / optimizer.py / statistics_module.py
/ charts.py / report.py / storage.py -- este archivo SOLO arma la interfaz y
corre esos modulos en hilos (threading) para no congelar la ventana, tal como
pediste ("igual que el resto del proyecto").
"""

import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import backtester
import optimizer
import statistics_module
import charts
import report
import storage
import data_feed

BG = "#0f1117"
PANEL = "#161923"
TEXT = "#e6e8ef"
MUTED = "#8a8fa3"
GREEN = "#22c55e"
RED = "#ef4444"
ACCENT = "#3b82f6"

def _all_timeframes() -> dict:
    return data_feed.TIMEFRAMES


def _fetch_ohlcv_any_timeframe(symbol, timeframe, num_candles):
    raw = data_feed.fetch_ohlcv(symbol, timeframe)
    return raw.tail(num_candles) if num_candles else raw


class BacktestWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Backtesting - Bot ICT / SMC / FVG")
        self.geometry("1300x850")
        self.configure(bg=BG)
        self.minsize(1100, 700)

        self.current_df = None
        self.current_result = None
        self.current_money = None
        self.current_stats = None
        self.current_chart_figures = []

        notebook_style = ttk.Style(self)
        try:
            notebook_style.theme_use("clam")
        except tk.TclError:
            pass

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.tab_backtest = tk.Frame(self.notebook, bg=BG)
        self.tab_optimizer = tk.Frame(self.notebook, bg=BG)
        self.tab_history = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.tab_backtest, text="Backtest")
        self.notebook.add(self.tab_optimizer, text="Optimizacion")
        self.notebook.add(self.tab_history, text="Historial")

        self._build_backtest_tab()
        self._build_optimizer_tab()
        self._build_history_tab()
        self._load_history_into_ui()

    # =========================================================== Backtest ==

    def _build_backtest_tab(self):
        tab = self.tab_backtest

        config = tk.Frame(tab, bg=PANEL, padx=12, pady=12)
        config.pack(side="top", fill="x")

        def labeled_entry(parent, label, default, width=10):
            f = tk.Frame(parent, bg=PANEL)
            f.pack(side="left", padx=8)
            tk.Label(f, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            e = tk.Entry(f, width=width)
            e.insert(0, str(default))
            e.pack()
            return e

        self.bt_symbol = labeled_entry(config, "Simbolo", "XAUUSD")
        f_tf = tk.Frame(config, bg=PANEL)
        f_tf.pack(side="left", padx=8)
        tk.Label(f_tf, text="Temporalidad", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self.bt_timeframe = ttk.Combobox(f_tf, width=6, state="readonly", values=list(_all_timeframes().keys()))
        self.bt_timeframe.set("1h")
        self.bt_timeframe.pack()

        self.bt_candles = labeled_entry(config, "Velas", "1000")
        self.bt_capital = labeled_entry(config, "Capital inicial", "1000")
        self.bt_risk = labeled_entry(config, "Riesgo % / op.", "1.0")
        self.bt_commission = labeled_entry(config, "Comision (R)", "0.0", width=6)
        self.bt_spread = labeled_entry(config, "Spread (R)", "0.0", width=6)
        self.bt_slippage = labeled_entry(config, "Slippage (R)", "0.0", width=6)
        self.bt_sl_atr = labeled_entry(config, "SL (ATR)", "1.0", width=6)
        self.bt_tp_atr = labeled_entry(config, "TP (ATR)", "2.0", width=6)
        self.bt_min_score = labeled_entry(config, "Score min.", "4", width=6)

        run_btn = tk.Button(config, text="Correr Backtest", command=self._run_backtest_clicked,
                             bg=ACCENT, fg="white", relief="flat", padx=14)
        run_btn.pack(side="left", padx=12, pady=(14, 0))

        # --- progreso ---
        progress_frame = tk.Frame(tab, bg=BG, padx=12)
        progress_frame.pack(side="top", fill="x", pady=(8, 0))
        self.bt_progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.bt_progress.pack(fill="x", side="left", expand=True)
        self.bt_progress_label = tk.Label(progress_frame, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), width=40)
        self.bt_progress_label.pack(side="left", padx=8)

        # --- resultados: notebook interno (metricas / graficos) ---
        results_area = tk.Frame(tab, bg=BG)
        results_area.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(results_area, bg=PANEL, width=380)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        tk.Label(left, text="METRICAS", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.bt_stats_text = tk.Text(left, bg=PANEL, fg=TEXT, relief="flat", font=("Consolas", 9), borderwidth=0)
        self.bt_stats_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.bt_stats_text.configure(state="disabled")

        export_frame = tk.Frame(left, bg=PANEL)
        export_frame.pack(fill="x", padx=10, pady=(0, 10))
        for label, fmt in [("CSV", "csv"), ("Excel", "xlsx"), ("JSON", "json"), ("PDF", "pdf")]:
            tk.Button(export_frame, text=label, command=lambda f=fmt: self._export(f),
                      bg="#22293b", fg=TEXT, relief="flat").pack(side="left", expand=True, fill="x", padx=2)

        right = tk.Frame(results_area, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self.charts_notebook = ttk.Notebook(right)
        self.charts_notebook.pack(fill="both", expand=True)
        self.chart_tabs = {}
        for name in ["Equity", "Drawdown", "Mensual", "Distribucion", "vs Buy&Hold", "Heatmap"]:
            frame = tk.Frame(self.charts_notebook, bg=BG)
            self.charts_notebook.add(frame, text=name)
            self.chart_tabs[name] = frame

    def _run_backtest_clicked(self):
        try:
            symbol = self.bt_symbol.get().strip().upper()
            timeframe = self.bt_timeframe.get()
            num_candles = int(self.bt_candles.get())
            capital = float(self.bt_capital.get())
            risk_pct = float(self.bt_risk.get())
            commission = float(self.bt_commission.get())
            spread = float(self.bt_spread.get())
            slippage = float(self.bt_slippage.get())
            sl_atr = float(self.bt_sl_atr.get())
            tp_atr = float(self.bt_tp_atr.get())
            min_score = int(self.bt_min_score.get())
        except ValueError:
            messagebox.showerror("Error", "Revisa que los campos numericos sean validos.")
            return

        if not symbol:
            messagebox.showwarning("Falta simbolo", "Escribe un simbolo.")
            return

        self.bt_progress["value"] = 0
        self.bt_progress_label.configure(text="Descargando datos...")
        threading.Thread(
            target=self._run_backtest_thread,
            args=(symbol, timeframe, num_candles, capital, risk_pct, commission, spread, slippage, sl_atr, tp_atr, min_score),
            daemon=True,
        ).start()

    def _run_backtest_thread(self, symbol, timeframe, num_candles, capital, risk_pct,
                              commission, spread, slippage, sl_atr, tp_atr, min_score):
        t0 = time.time()
        try:
            df = _fetch_ohlcv_any_timeframe(symbol, timeframe, num_candles)
        except Exception as exc:
            self.after(0, self._on_error, str(exc))
            return

        def progress_cb(i, n):
            elapsed = time.time() - t0
            pct = (i / n * 100) if n else 0
            remaining = (elapsed / i * (n - i)) if i > 0 else 0
            self.after(0, lambda: self._update_progress(pct, i, n, elapsed, remaining))

        try:
            result = backtester.run_backtest(df, sl_atr=sl_atr, tp_atr=tp_atr, min_score=min_score,
                                              progress_callback=progress_cb)
            money = backtester.apply_money_simulation(result["trades"], capital_inicial=capital,
                                                        riesgo_pct=risk_pct, commission_r=commission,
                                                        spread_r=spread, slippage_r=slippage)
            bh = backtester.buy_and_hold_curve(df, capital_inicial=capital, start_index=30)
            stats = statistics_module.compute_full_stats(
                result["trades"], result["equity_curve_r"],
                equity_curve_money=money["equity_curve_money"], capital_inicial=capital,
            )
        except Exception as exc:
            self.after(0, self._on_error, str(exc))
            return

        self.after(0, lambda: self._on_backtest_done(symbol, timeframe, num_candles, capital, risk_pct,
                                                       df, result, money, bh, stats))

    def _update_progress(self, pct, i, n, elapsed, remaining):
        self.bt_progress["value"] = pct
        self.bt_progress_label.configure(
            text=f"Procesando... {i}/{n} velas | transcurrido {elapsed:.0f}s | restante ~{remaining:.0f}s"
        )

    def _on_error(self, message):
        self.bt_progress_label.configure(text="Error.")
        messagebox.showerror("Error", message)

    def _on_backtest_done(self, symbol, timeframe, num_candles, capital, risk_pct, df, result, money, bh, stats):
        self.current_df = df
        self.current_result = result
        self.current_money = money
        self.current_stats = stats
        self.current_config = {"symbol": symbol, "timeframe": timeframe, "num_candles": num_candles,
                                "capital_inicial": capital, "riesgo_pct": risk_pct}

        self.bt_progress["value"] = 100
        self.bt_progress_label.configure(text=f"Listo. {stats['operaciones']} operaciones.")

        self._render_stats(stats)
        self._render_charts(result, money, bh, stats)

        try:
            storage.save_backtest_run(
                symbol, timeframe, num_candles, capital, risk_pct, stats,
                json.dumps({"stats": stats, "config": self.current_config}, default=str),
            )
            self._load_history_into_ui()
        except Exception:
            pass  # el historial es un extra; si falla el guardado no debe romper la corrida

    def _render_stats(self, stats):
        self.bt_stats_text.configure(state="normal")
        self.bt_stats_text.delete("1.0", "end")
        labels = [
            ("Operaciones", "operaciones"), ("Ganadas", "ganadas"), ("Perdidas", "perdidas"),
            ("Break Even", "break_even"), ("Winrate %", "winrate_pct"), ("Profit Factor", "profit_factor"),
            ("Expectancy (R)", "expectancy_r"), ("Net Profit (R)", "net_profit_r"),
            ("Net Profit ($)", "net_profit_money"), ("Beneficio %", "beneficio_pct"),
            ("Max Drawdown (R)", "max_drawdown_r"), ("Max Drawdown ($)", "max_drawdown_money"),
            ("Max Drawdown %", "max_drawdown_pct"), ("Average Win (R)", "average_win_r"),
            ("Average Loss (R)", "average_loss_r"), ("RR promedio", "rr_promedio"),
            ("Sharpe Ratio", "sharpe_ratio"), ("Sortino Ratio", "sortino_ratio"),
            ("Calmar Ratio", "calmar_ratio"), ("Recovery Factor", "recovery_factor"),
            ("Mayor ganadora (R)", "mayor_ganadora_r"), ("Mayor perdedora (R)", "mayor_perdedora_r"),
            ("Racha ganadora max.", "longest_winning_streak"), ("Racha perdedora max.", "longest_losing_streak"),
            ("Tiempo prom. x trade (h)", "tiempo_promedio_por_trade_horas"),
        ]
        for label, key in labels:
            val = stats.get(key)
            self.bt_stats_text.insert("end", f"{label:<26}: {val}\n")

        if stats.get("profit_per_month_r"):
            self.bt_stats_text.insert("end", "\nBeneficio por mes (R):\n")
            for k, v in stats["profit_per_month_r"].items():
                self.bt_stats_text.insert("end", f"  {k}: {v}\n")
        self.bt_stats_text.configure(state="disabled")

    def _render_charts(self, result, money, bh, stats):
        for fig in self.current_chart_figures:
            pass  # las figuras viejas se recolectan solas al perder referencia
        self.current_chart_figures = []

        figs = {
            "Equity": charts.equity_curve_figure(money["equity_curve_money"], label="Capital ($)"),
            "Drawdown": charts.drawdown_figure(money["equity_curve_money"]),
            "Mensual": charts.monthly_profit_bar_figure(stats["profit_per_month_r"]),
            "Distribucion": charts.distribution_histogram_figure(result["trades"]),
            "vs Buy&Hold": charts.equity_vs_buyhold_figure(money["equity_curve_money"], bh),
            "Heatmap": charts.monthly_heatmap_figure(stats["profit_per_month_r"]),
        }

        for name, fig in figs.items():
            for child in self.chart_tabs[name].winfo_children():
                child.destroy()
            canvas = FigureCanvasTkAgg(fig, master=self.chart_tabs[name])
            canvas.get_tk_widget().pack(fill="both", expand=True)
            canvas.draw()
            self.current_chart_figures.append(fig)

    def _export(self, fmt):
        if not self.current_result:
            messagebox.showwarning("Sin datos", "Corre un backtest primero.")
            return

        ext_map = {"csv": ".csv", "xlsx": ".xlsx", "json": ".json", "pdf": ".pdf"}
        path = filedialog.asksaveasfilename(defaultextension=ext_map[fmt],
                                             initialfile=f"backtest_{self.current_config['symbol']}")
        if not path:
            return

        try:
            trades = self.current_money["trades"]
            if fmt == "csv":
                report.export_csv(trades, path)
            elif fmt == "xlsx":
                report.export_excel(trades, self.current_stats, path)
            elif fmt == "json":
                report.export_json(trades, self.current_stats, self.current_config, path)
            elif fmt == "pdf":
                report.export_pdf(trades, self.current_stats, self.current_config, path,
                                   chart_figures=self.current_chart_figures)
            messagebox.showinfo("Exportado", f"Guardado en {path}")
        except Exception as exc:
            messagebox.showerror("Error al exportar", str(exc))

    # ========================================================= Optimizacion ==

    def _build_optimizer_tab(self):
        tab = self.tab_optimizer

        config = tk.Frame(tab, bg=PANEL, padx=12, pady=12)
        config.pack(side="top", fill="x")

        def labeled_entry(parent, label, default, width=10):
            f = tk.Frame(parent, bg=PANEL)
            f.pack(side="left", padx=8)
            tk.Label(f, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            e = tk.Entry(f, width=width)
            e.insert(0, str(default))
            e.pack()
            return e

        self.opt_symbol = labeled_entry(config, "Simbolo", "XAUUSD")
        f_tf = tk.Frame(config, bg=PANEL)
        f_tf.pack(side="left", padx=8)
        tk.Label(f_tf, text="Temporalidad", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self.opt_timeframe = ttk.Combobox(f_tf, width=6, state="readonly", values=list(_all_timeframes().keys()))
        self.opt_timeframe.set("1h")
        self.opt_timeframe.pack()

        self.opt_candles = labeled_entry(config, "Velas", "1000")
        self.opt_scores = labeled_entry(config, "Scores a probar", "3,4,5,6", width=14)

        tk.Button(config, text="Optimizar (por componente)", command=self._run_optimizer_clicked,
                  bg=ACCENT, fg="white", relief="flat", padx=12).pack(side="left", padx=12, pady=(14, 0))

        tk.Label(tab, text="Compara, para cada score minimo, apagar un componente ICT/SMC a la vez "
                            "(mucho mas rapido que probar las 256 combinaciones posibles).",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=900, justify="left").pack(
            anchor="w", padx=14, pady=(4, 0))

        progress_frame = tk.Frame(tab, bg=BG, padx=12)
        progress_frame.pack(side="top", fill="x", pady=(8, 0))
        self.opt_progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.opt_progress.pack(fill="x", side="left", expand=True)
        self.opt_progress_label = tk.Label(progress_frame, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), width=30)
        self.opt_progress_label.pack(side="left", padx=8)

        table_frame = tk.Frame(tab, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=12, pady=12)

        cols = ("label", "wr", "pf", "beneficio", "dd", "trades")
        self.opt_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        headers = {"label": "Configuracion", "wr": "WR", "pf": "PF", "beneficio": "Beneficio (R)",
                   "dd": "Max DD (R)", "trades": "Operaciones"}
        widths = {"label": 320, "wr": 70, "pf": 70, "beneficio": 110, "dd": 100, "trades": 90}
        for c in cols:
            self.opt_tree.heading(c, text=headers[c])
            self.opt_tree.column(c, width=widths[c])
        self.opt_tree.pack(fill="both", expand=True)

    def _run_optimizer_clicked(self):
        symbol = self.opt_symbol.get().strip().upper()
        timeframe = self.opt_timeframe.get()
        try:
            num_candles = int(self.opt_candles.get())
            scores = tuple(int(s.strip()) for s in self.opt_scores.get().split(",") if s.strip())
        except ValueError:
            messagebox.showerror("Error", "Revisa 'Velas' y 'Scores a probar' (ej: 3,4,5,6).")
            return

        if not symbol or not scores:
            messagebox.showwarning("Faltan datos", "Escribe simbolo y al menos un score.")
            return

        self.opt_progress["value"] = 0
        self.opt_progress_label.configure(text="Descargando datos...")
        threading.Thread(target=self._run_optimizer_thread, args=(symbol, timeframe, num_candles, scores),
                          daemon=True).start()

    def _run_optimizer_thread(self, symbol, timeframe, num_candles, scores):
        try:
            df = _fetch_ohlcv_any_timeframe(symbol, timeframe, num_candles)
        except Exception as exc:
            self.after(0, messagebox.showerror, "Error", str(exc))
            return

        def progress_cb(i, n):
            pct = (i / n * 100) if n else 0
            self.after(0, lambda: self._update_opt_progress(pct, i, n))

        try:
            ranking = optimizer.run_optimization_presets(df, min_scores=scores, progress_callback=progress_cb)
        except Exception as exc:
            self.after(0, messagebox.showerror, "Error", str(exc))
            return

        self.after(0, lambda: self._on_optimizer_done(ranking))

    def _update_opt_progress(self, pct, i, n):
        self.opt_progress["value"] = pct
        self.opt_progress_label.configure(text=f"{i}/{n} configuraciones")

    def _on_optimizer_done(self, ranking):
        for item in self.opt_tree.get_children():
            self.opt_tree.delete(item)
        for r in ranking:
            s = r["stats"]
            self.opt_tree.insert("", "end", values=(
                r["label"], f"{s['winrate_pct']}%", s["profit_factor"],
                s["net_profit_r"], s["max_drawdown_r"], s["operaciones"],
            ))
        self.opt_progress_label.configure(text=f"Listo. {len(ranking)} configuraciones probadas.")

    # ============================================================ Historial ==

    def _build_history_tab(self):
        tab = self.tab_history

        top = tk.Frame(tab, bg=BG, padx=12, pady=12)
        top.pack(fill="x")
        tk.Button(top, text="Refrescar", command=self._load_history_into_ui,
                  bg="#22293b", fg=TEXT, relief="flat").pack(side="left")
        tk.Button(top, text="Eliminar seleccionado", command=self._delete_selected_history,
                  bg="#22293b", fg=TEXT, relief="flat").pack(side="left", padx=6)

        cols = ("fecha", "symbol", "timeframe", "candles", "pf", "wr", "beneficio", "dd")
        self.hist_tree = ttk.Treeview(tab, columns=cols, show="headings")
        headers = {"fecha": "Fecha", "symbol": "Simbolo", "timeframe": "TF", "candles": "Velas",
                   "pf": "PF", "wr": "WR", "beneficio": "Beneficio %", "dd": "Max DD (R)"}
        widths = {"fecha": 160, "symbol": 90, "timeframe": 60, "candles": 70,
                  "pf": 60, "wr": 60, "beneficio": 100, "dd": 100}
        for c in cols:
            self.hist_tree.heading(c, text=headers[c])
            self.hist_tree.column(c, width=widths[c])
        self.hist_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.hist_tree.bind("<Double-1>", self._on_history_double_click)

        tk.Label(tab, text="Doble clic en una fila para ver el detalle guardado (sin volver a ejecutar el backtest).",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(0, 8))

    def _load_history_into_ui(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        for h in storage.get_backtest_history():
            self.hist_tree.insert("", "end", iid=str(h["id"]), values=(
                h["fecha"][:19].replace("T", " "), h["symbol"], h["timeframe"], h["num_candles"],
                h["profit_factor"], h["winrate_pct"],
                h["beneficio_pct"] if h["beneficio_pct"] is not None else "—", h["max_drawdown_r"],
            ))

    def _delete_selected_history(self):
        sel = self.hist_tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Confirmar", "Eliminar este backtest del historial?"):
            storage.delete_backtest_run(int(sel[0]))
            self._load_history_into_ui()

    def _on_history_double_click(self, event):
        sel = self.hist_tree.selection()
        if not sel:
            return
        record = storage.get_backtest_by_id(int(sel[0]))
        if not record:
            return

        detail = tk.Toplevel(self)
        detail.title(f"Backtest #{record['id']} - {record['symbol']} ({record['timeframe']})")
        detail.geometry("500x600")
        detail.configure(bg=BG)

        text = tk.Text(detail, bg=PANEL, fg=TEXT, font=("Consolas", 9))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        stats = record["result"].get("stats", {})
        for k, v in stats.items():
            if isinstance(v, dict):
                continue
            text.insert("end", f"{k}: {v}\n")
        text.configure(state="disabled")
