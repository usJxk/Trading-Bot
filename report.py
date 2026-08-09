"""
report.py
Exporta los resultados de un backtest a CSV, Excel, JSON o PDF.
No importa Tkinter -- recibe datos ya calculados (trades + stats) y una ruta
de archivo, y escribe el archivo.
"""

import json

import pandas as pd


def _trades_dataframe(trades: list) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    for col in ("signal_time", "entry_time", "exit_time"):
        if col in df.columns:
            df[col] = df[col].astype(str)
    return df


def export_csv(trades: list, path: str):
    _trades_dataframe(trades).to_csv(path, index=False)
    return path


def export_excel(trades: list, stats: dict, path: str):
    df_trades = _trades_dataframe(trades)
    df_stats = pd.DataFrame([
        {"metrica": k, "valor": v} for k, v in stats.items()
        if not isinstance(v, dict)
    ])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_trades.to_excel(writer, sheet_name="Operaciones", index=False)
        df_stats.to_excel(writer, sheet_name="Metricas", index=False)

        for key in ("profit_per_month_r", "operaciones_por_mes", "operaciones_por_dia_semana"):
            if isinstance(stats.get(key), dict) and stats[key]:
                pd.DataFrame(list(stats[key].items()), columns=["periodo", "valor"]).to_excel(
                    writer, sheet_name=key[:31], index=False
                )
    return path


def export_json(trades: list, stats: dict, config: dict, path: str):
    payload = {
        "config": config,
        "stats": stats,
        "trades": json.loads(_trades_dataframe(trades).to_json(orient="records")),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return path


def export_pdf(trades: list, stats: dict, config: dict, path: str, chart_figures: list | None = None):
    """
    Genera un PDF con el resumen del backtest y (opcionalmente) las figuras
    de matplotlib ya generadas por charts.py, una por pagina.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    import io

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    # --- Pagina 1: resumen ---
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, height - 2 * cm, "Reporte de Backtest")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 2.7 * cm,
                 f"Simbolo: {config.get('symbol', '-')}   Timeframe: {config.get('timeframe', '-')}   "
                 f"Velas: {config.get('num_candles', '-')}")

    y = height - 3.6 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Metricas principales")
    y -= 0.6 * cm
    c.setFont("Helvetica", 9)

    simple_items = [(k, v) for k, v in stats.items() if not isinstance(v, dict)]
    for k, v in simple_items:
        if y < 2 * cm:
            c.showPage()
            y = height - 2 * cm
            c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y, f"{k}: {v}")
        y -= 0.45 * cm

    # --- Paginas siguientes: graficos ---
    if chart_figures:
        for fig in chart_figures:
            c.showPage()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            from reportlab.lib.utils import ImageReader
            img = ImageReader(buf)
            img_w, img_h = img.getSize()
            scale = min((width - 2 * cm) / img_w, (height - 3 * cm) / img_h)
            c.drawImage(img, 2 * cm, height - 2 * cm - img_h * scale, width=img_w * scale, height=img_h * scale)

    c.save()
    return path
