"""
app.py
Punto de entrada de la aplicacion de escritorio (Tkinter).

Que hace esta app:
- Puedes agregar cualquier simbolo (XAUUSD, AAPL, NQ, US100, EURUSD, o cualquier
  ticker valido de Yahoo Finance) a tu watchlist.
- Analiza cada simbolo con ICT/SMC (estructura, BOS/CHoCH, FVG, Order Blocks,
  barridas de liquidez, premium/discount) + una aproximacion de footprint.
- Muestra un veredicto grande: ALCISTA / BAJISTA / NEUTRAL, con las razones.
- Dibuja un grafico de velas con las FVG y Order Blocks marcados.
- Tiene un diario de operaciones manual (tu registras tus compras/ventas;
  el bot NO ejecuta ordenes reales - eso fue lo que pediste).
- Todo se guarda en SQLite (trading_bot.db). Si cierras la app y la vuelves
  a abrir, recupera tu watchlist, tus operaciones y el ultimo analisis de
  cada simbolo: no "se olvida" de nada.

Ejecutar con:  python app.py
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

import storage
import data_feed
import strategy
from backtest_window import BacktestWindow

BG = "#0f1117"
PANEL = "#161923"
TEXT = "#e6e8ef"
MUTED = "#8a8fa3"
GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#eab308"
ACCENT = "#3b82f6"


class TradingBotApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bot de Analisis ICT / SMC / FVG - Solo Senales")
        self.geometry("1280x800")
        self.configure(bg=BG)
        self.minsize(1100, 700)

        storage.init_db()

        self.current_symbol = None
        self.current_timeframe = tk.StringVar(value="1h")
        self.current_df = None
        self.current_result = None
        self.auto_refresh_on = tk.BooleanVar(value=False)
        self._auto_job = None

        self._build_style()
        self._build_layout()
        self._load_watchlist_into_ui()
        self._restore_last_state()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI --

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                         foreground=TEXT, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background="#1f2330", foreground=TEXT,
                         relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT)

    def _build_layout(self):
        top = tk.Frame(self, bg=BG, pady=10, padx=10)
        top.pack(side="top", fill="x")

        tk.Label(top, text="Simbolo:", bg=BG, fg=TEXT, font=("Segoe UI", 11)).pack(side="left")
        self.symbol_entry = tk.Entry(top, width=14, font=("Segoe UI", 11))
        self.symbol_entry.pack(side="left", padx=(6, 12))
        self.symbol_entry.insert(0, "XAUUSD")

        tk.Label(top, text="Temporalidad:", bg=BG, fg=TEXT, font=("Segoe UI", 11)).pack(side="left")
        tf_combo = ttk.Combobox(top, textvariable=self.current_timeframe, width=6,
                                 values=list(data_feed.TIMEFRAMES.keys()), state="readonly")
        tf_combo.pack(side="left", padx=(6, 12))

        tk.Button(top, text="+ Agregar a watchlist", command=self._add_symbol,
                  bg=ACCENT, fg="white", relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(top, text="Analizar", command=self._analyze_current, bg="#22293b",
                  fg=TEXT, relief="flat", padx=10).pack(side="left", padx=4)

        tk.Button(top, text="📊 Backtest", command=self._open_backtest_window, bg="#7c3aed",
                  fg="white", relief="flat", padx=10).pack(side="left", padx=4)

        self.auto_chk = tk.Checkbutton(top, text="Auto-refrescar cada 5 min", variable=self.auto_refresh_on,
                                        command=self._toggle_auto_refresh, bg=BG, fg=TEXT,
                                        selectcolor=PANEL, activebackground=BG)
        self.auto_chk.pack(side="left", padx=12)

        self.status_label = tk.Label(top, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.status_label.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 10))

        # --- Columna izquierda: watchlist + diario de operaciones ---
        left = tk.Frame(body, bg=BG, width=340)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        tk.Label(left, text="WATCHLIST", bg=BG, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.watchlist_tree = ttk.Treeview(left, columns=("bias",), show="tree headings", height=8)
        self.watchlist_tree.heading("#0", text="Simbolo")
        self.watchlist_tree.heading("bias", text="Sesgo")
        self.watchlist_tree.column("#0", width=140)
        self.watchlist_tree.column("bias", width=140)
        self.watchlist_tree.pack(fill="x", pady=(4, 4))
        self.watchlist_tree.bind("<Double-1>", self._on_watchlist_double_click)

        tk.Button(left, text="Quitar seleccionado", command=self._remove_selected_symbol,
                  bg="#22293b", fg=TEXT, relief="flat").pack(fill="x", pady=(0, 14))

        tk.Label(left, text="DIARIO DE OPERACIONES (manual)", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        trade_btns = tk.Frame(left, bg=BG)
        trade_btns.pack(fill="x", pady=4)
        tk.Button(trade_btns, text="Registrar COMPRA", command=lambda: self._open_trade_dialog("COMPRA"),
                  bg=GREEN, fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(trade_btns, text="Registrar VENTA", command=lambda: self._open_trade_dialog("VENTA"),
                  bg=RED, fg="white", relief="flat").pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.trades_tree = ttk.Treeview(
            left, columns=("side", "entry", "sl", "tp", "status"), show="headings", height=10
        )
        for col, label, w in [("side", "Lado", 55), ("entry", "Entrada", 70),
                               ("sl", "SL", 60), ("tp", "TP", 60), ("status", "Estado", 60)]:
            self.trades_tree.heading(col, text=label)
            self.trades_tree.column(col, width=w)
        self.trades_tree.pack(fill="both", expand=True, pady=(4, 4))
        self.trades_tree.bind("<Double-1>", self._on_trade_double_click)

        tk.Label(left, text="(doble clic en una operacion abierta para cerrarla)",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        # --- Columna central: grafico ---
        center = tk.Frame(body, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.fig = Figure(figsize=(6, 5), dpi=100, facecolor=BG)
        self.ax = self.fig.add_subplot(111, facecolor=BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=center)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # --- Columna derecha: veredicto ---
        right = tk.Frame(body, bg=PANEL, width=320)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text="VEREDICTO", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(14, 4))
        self.bias_label = tk.Label(right, text="--", bg=PANEL, fg=TEXT, font=("Segoe UI", 26, "bold"))
        self.bias_label.pack(anchor="w", padx=14)

        self.score_label = tk.Label(right, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 10))
        self.score_label.pack(anchor="w", padx=14, pady=(0, 10))

        tk.Label(right, text="RAZONES", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=14)

        self.reasons_text = tk.Text(right, bg=PANEL, fg=TEXT, wrap="word", relief="flat",
                                     font=("Segoe UI", 10), height=22, borderwidth=0)
        self.reasons_text.pack(fill="both", expand=True, padx=14, pady=(4, 14))
        self.reasons_text.configure(state="disabled")

    # -------------------------------------------------------------- acciones --

    def _set_status(self, msg: str):
        self.status_label.configure(text=msg)
        self.update_idletasks()

    def _add_symbol(self):
        symbol = self.symbol_entry.get().strip().upper()
        if not symbol:
            return
        storage.add_symbol(symbol, self.current_timeframe.get())
        self._load_watchlist_into_ui()
        self._analyze_current()

    def _remove_selected_symbol(self):
        sel = self.watchlist_tree.selection()
        if not sel:
            return
        symbol = self.watchlist_tree.item(sel[0], "text")
        if messagebox.askyesno("Confirmar", f"Quitar {symbol} de la watchlist?"):
            storage.remove_symbol(symbol)
            self._load_watchlist_into_ui()

    def _load_watchlist_into_ui(self):
        for item in self.watchlist_tree.get_children():
            self.watchlist_tree.delete(item)
        analyses = storage.get_all_analyses()
        for row in storage.get_watchlist():
            sym = row["symbol"]
            bias = analyses.get(sym, {}).get("bias", "sin analizar")
            self.watchlist_tree.insert("", "end", text=sym, values=(bias,))

    def _on_watchlist_double_click(self, event):
        sel = self.watchlist_tree.selection()
        if not sel:
            return
        symbol = self.watchlist_tree.item(sel[0], "text")
        self.symbol_entry.delete(0, "end")
        self.symbol_entry.insert(0, symbol)
        self._analyze_current()

    def _analyze_current(self):
        symbol = self.symbol_entry.get().strip().upper()
        timeframe = self.current_timeframe.get()
        if not symbol:
            return
        self._set_status(f"Descargando datos de {symbol} ({timeframe})...")
        threading.Thread(target=self._analyze_thread, args=(symbol, timeframe), daemon=True).start()

    def _analyze_thread(self, symbol, timeframe):
        try:
            df = data_feed.fetch_ohlcv(symbol, timeframe)
            result = strategy.analyze(df)
        except Exception as exc:
            self.after(0, lambda: self._on_analyze_error(str(exc)))
            return
        self.after(0, lambda: self._on_analyze_success(symbol, timeframe, df, result))

    def _on_analyze_error(self, message):
        self._set_status("Error al analizar.")
        messagebox.showerror("Error", message)

    def _on_analyze_success(self, symbol, timeframe, df, result):
        self.current_symbol = symbol
        self.current_df = df
        self.current_result = result

        storage.save_analysis(symbol, timeframe, result["bias"], result["score"],
                               result["reasons"], result["details"].get("last_close", 0.0))

        self._render_bias(result)
        self._render_chart(df, result)
        self._load_watchlist_into_ui()
        self._set_status(f"Ultima actualizacion: {datetime.now().strftime('%H:%M:%S')}")

    def _render_bias(self, result):
        bias = result["bias"]
        color = GREEN if bias == "ALCISTA" else RED if bias == "BAJISTA" else YELLOW
        self.bias_label.configure(text=bias, fg=color)
        self.score_label.configure(text=f"Puntaje interno: {result['score']}")

        self.reasons_text.configure(state="normal")
        self.reasons_text.delete("1.0", "end")
        for r in result["reasons"]:
            self.reasons_text.insert("end", f"\u2022 {r}\n\n")
        self.reasons_text.configure(state="disabled")

    def _render_chart(self, df, result):
        self.ax.clear()
        plot_df = df.iloc[-80:]
        xs = range(len(plot_df))

        for x, (_, row) in zip(xs, plot_df.iterrows()):
            color = GREEN if row["Close"] >= row["Open"] else RED
            self.ax.plot([x, x], [row["Low"], row["High"]], color=color, linewidth=1)
            self.ax.add_patch(Rectangle(
                (x - 0.3, min(row["Open"], row["Close"])), 0.6,
                max(abs(row["Close"] - row["Open"]), 1e-9),
                color=color,
            ))

        offset = len(df) - len(plot_df)
        for fvg in result["details"].get("fvgs", []):
            if fvg["mitigated"] or fvg["index"] < offset:
                continue
            x = fvg["index"] - offset
            color = "#16a34a55" if fvg["direction"] == "ALCISTA" else "#dc262655"
            self.ax.axhspan(fvg["zone_low"], fvg["zone_high"], xmin=max(x - 3, 0) / len(plot_df),
                             xmax=1.0, color=color, linewidth=0)

        for ob in result["details"].get("order_blocks", []):
            if ob["index"] < offset:
                continue
            x = ob["index"] - offset
            color = "#3b82f655" if ob["direction"] == "ALCISTA" else "#f9731655"
            self.ax.axhspan(ob["zone_low"], ob["zone_high"], xmin=max(x - 1, 0) / len(plot_df),
                             xmax=1.0, color=color, linewidth=0)

        self.ax.set_title(f"{self.current_symbol} - {self.current_timeframe.get()}", color=TEXT)
        self.ax.tick_params(colors=MUTED)
        for spine in self.ax.spines.values():
            spine.set_color("#2a2f3d")
        self.canvas.draw()

    # ------------------------------------------------------------ backtest --

    def _open_backtest_window(self):
        """Abre la ventana de Backtesting (nueva, independiente). No toca el
        flujo de analisis normal de esta ventana en absoluto."""
        if getattr(self, "_backtest_win", None) is not None and self._backtest_win.winfo_exists():
            self._backtest_win.lift()
            self._backtest_win.focus_force()
            return
        self._backtest_win = BacktestWindow(self)

    # ------------------------------------------------------- auto refresh --

    def _toggle_auto_refresh(self):
        storage.set_setting("auto_refresh", "1" if self.auto_refresh_on.get() else "0")
        if self.auto_refresh_on.get():
            self._schedule_auto_refresh()
        elif self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None

    def _schedule_auto_refresh(self):
        self._analyze_current()
        self._auto_job = self.after(5 * 60 * 1000, self._schedule_auto_refresh)

    # ------------------------------------------------------------ trades --

    def _open_trade_dialog(self, side):
        symbol = self.symbol_entry.get().strip().upper()
        if not symbol:
            messagebox.showwarning("Falta simbolo", "Escribe un simbolo primero.")
            return

        entry = simpledialog.askfloat("Precio de entrada", f"Precio de entrada para {side} en {symbol}:")
        if entry is None:
            return
        sl = simpledialog.askfloat("Stop Loss", "Stop Loss (opcional, cancelar para omitir):")
        tp = simpledialog.askfloat("Take Profit", "Take Profit (opcional, cancelar para omitir):")
        size = simpledialog.askfloat("Tamano", "Tamano / lotaje (opcional):")
        notes = simpledialog.askstring("Notas", "Notas de la operacion (opcional):") or ""

        storage.log_trade(symbol, side, entry, stop_loss=sl, take_profit=tp, size=size, notes=notes)
        self._load_trades_into_ui()

    def _load_trades_into_ui(self):
        for item in self.trades_tree.get_children():
            self.trades_tree.delete(item)
        for t in storage.get_trades():
            self.trades_tree.insert("", "end", iid=str(t["id"]),
                                     values=(t["side"], t["entry_price"], t["stop_loss"] or "-",
                                             t["take_profit"] or "-", t["status"]))

    def _on_trade_double_click(self, event):
        sel = self.trades_tree.selection()
        if not sel:
            return
        trade_id = int(sel[0])
        trades = {t["id"]: t for t in storage.get_trades()}
        trade = trades.get(trade_id)
        if not trade or trade["status"] == "CERRADA":
            return
        close_price = simpledialog.askfloat("Cerrar operacion", f"Precio de cierre para la operacion #{trade_id}:")
        if close_price is None:
            return
        storage.close_trade(trade_id, close_price)
        self._load_trades_into_ui()

    # -------------------------------------------------------------- estado --

    def _restore_last_state(self):
        """Al abrir la app, recupera lo que estaba pasando la ultima vez."""
        self._load_trades_into_ui()
        auto = storage.get_setting("auto_refresh", "0") == "1"
        self.auto_refresh_on.set(auto)

        last_symbol = storage.get_setting("last_symbol")
        last_tf = storage.get_setting("last_timeframe")
        if last_symbol:
            self.symbol_entry.delete(0, "end")
            self.symbol_entry.insert(0, last_symbol)
        if last_tf:
            self.current_timeframe.set(last_tf)

        watchlist = storage.get_watchlist()
        if watchlist:
            self._set_status(f"Sesion restaurada: {len(watchlist)} simbolo(s) en watchlist.")
        if auto:
            self._schedule_auto_refresh()

    def _on_close(self):
        storage.set_setting("last_symbol", self.symbol_entry.get().strip().upper())
        storage.set_setting("last_timeframe", self.current_timeframe.get())
        self.destroy()


if __name__ == "__main__":
    app = TradingBotApp()
    app.mainloop()
