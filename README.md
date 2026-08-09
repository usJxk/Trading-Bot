# Bot de Analisis ICT / SMC / FVG (solo señales)

App de escritorio en Python que analiza cualquier simbolo (XAUUSD, EURUSD,
AAPL, NQ, US100, etc.) usando conceptos de **ICT** y **Smart Money Concepts
(SMC)**: estructura de mercado (BOS/CHoCH), **Fair Value Gaps (FVG)**, Order
Blocks, barridas de liquidez, zonas premium/discount, y una **aproximacion**
de footprint (presion compradora/vendedora por volumen).

Te da un veredicto **ALCISTA / BAJISTA / NEUTRAL** con las razones detras,
y un diario de operaciones donde tu registras manualmente tus compras y
ventas. **El bot no ejecuta ordenes reales** — eso fue una decision explicita
para que tengas control total del dinero; solo te da el analisis y tu
registras lo que hiciste.

Todo se guarda en una base de datos local (`trading_bot.db`, se crea sola en
la misma carpeta). Si cierras la app y la abres de nuevo, recupera tu
watchlist, tus operaciones abiertas/cerradas y el ultimo analisis de cada
simbolo.

## Instalacion

Necesitas Python 3.10 o superior instalado.

```bash
cd trading_bot
pip install -r requirements.txt
```

En Windows, si `tkinter` no viene incluido con tu instalacion de Python,
reinstala Python marcando la opcion "tcl/tk and IDLE" en el instalador
oficial de python.org. En Linux (Debian/Ubuntu): `sudo apt install python3-tk`.
En macOS con python.org, tkinter ya viene incluido.

## Ejecutar

```bash
python app.py
```

## Como se usa

1. Escribe un simbolo en el campo "Simbolo" (por ejemplo `XAUUSD`, `AAPL`,
   `NQ`, `US100`, `EURUSD`, o cualquier ticker valido de Yahoo Finance como
   `MSFT` o `BTC-USD`).
2. Elige la temporalidad (15m, 30m, 1h, 4h, 1d).
3. Click en **Analizar** (o **+ Agregar a watchlist** para guardarlo y
   analizarlo de una vez).
4. A la derecha aparece el veredicto (ALCISTA/BAJISTA/NEUTRAL) con la lista
   de razones. En el centro, el grafico de velas con las zonas de FVG y
   Order Blocks resaltadas.
5. Cuando decidas operar, usa **Registrar COMPRA** / **Registrar VENTA** en
   el diario de operaciones para dejar constancia de tu entrada, SL, TP y
   notas. Doble clic sobre una operacion abierta para cerrarla.
6. Activa "Auto-refrescar cada 5 min" si quieres que vuelva a analizar el
   simbolo activo automaticamente.

## Simbolos: alias soportados

El campo "Simbolo" acepta alias comunes que se traducen automaticamente al
ticker real de Yahoo Finance (ver `data_feed.py` -> `SYMBOL_ALIASES` para
editar o agregar mas):

| Escribes  | Se traduce a |
|-----------|--------------|
| XAUUSD    | GC=F (futuro de oro) |
| US100     | ^NDX (indice Nasdaq 100) |
| NQ        | NQ=F (futuro Nasdaq) |
| US30      | YM=F (futuro Dow Jones) |
| US500 / SPX | ^GSPC (S&P 500) |
| EURUSD, GBPUSD, USDJPY... | EURUSD=X, GBPUSD=X, USDJPY=X... |
| BTCUSD    | BTC-USD |
| AAPL, MSFT, TSLA... | se usan tal cual (son tickers de acciones normales) |

Si escribes un simbolo que no esta en la lista, se manda tal cual a Yahoo
Finance — funciona con cualquier ticker que exista ahi.

## Limitaciones importantes (leelas antes de operar con dinero real)

- **Este bot NO es un footprint institucional real.** Un footprint de
  verdad usa datos tick-by-tick de volumen por nivel de precio y bid/ask,
  que Yahoo Finance (fuente gratuita) no ofrece. Lo que este bot calcula es
  una *aproximacion* de presion compradora/vendedora basada en volumen total
  de la vela y en donde cerro el precio dentro de su rango. Es una heuristica
  razonable, no un footprint de verdad. Si necesitas footprint real, hace
  falta contratar datos de un proveedor especializado (Bookmap, Sierra Chart
  + feed de nivel 2, etc.) — puedo ayudarte a integrar eso despues si
  consigues el feed.
- El analisis de ICT/SMC (estructura, FVG, Order Blocks, barridas de
  liquidez) es una **implementacion algoritmica de conceptos discrecionales**.
  Los traders profesionales de ICT/SMC usan bastante criterio humano y
  contexto (noticias, sesiones, correlaciones); este bot es una guia, no una
  certeza. Ninguna estrategia tecnica garantiza ganancias.
- El bot **no ejecuta ordenes reales** ni se conecta a ningun broker. Todo lo
  que ves en el diario de operaciones lo escribes tu mismo — es un registro,
  no una ejecucion automatica.
- Los datos de Yahoo Finance pueden tener pequenos retrasos y, para
  intervalos cortos (15m/30m), un historico limitado (60 dias).
- Prueba siempre primero en una cuenta demo antes de usar dinero real.

## Backtesting

`backtester.py` es un modulo nuevo e independiente — no toca `strategy.py`,
`app.py`, `data_feed.py` ni `storage.py`. Recorre el historico **vela por
vela** llamando a `strategy.analyze()` solo con las velas ya "pasadas" en ese
punto (nunca ve el futuro), simula la entrada en la apertura de la siguiente
vela con SL/TP en multiplos de ATR, y calcula metricas estandar.

Los resultados se expresan en **multiplos de R** (R = lo que arriesgaste en
esa operacion), no en % de una cuenta — no inventamos un balance ni un
tamano de posicion que no existen en el proyecto.

### Uso rapido por linea de comandos

```bash
python backtester.py XAUUSD --timeframe 1h --sl-atr 1.0 --tp-atr 2.0 --min-score 4
python backtester.py AAPL --timeframe 1d --require-fvg --plot
```

Esto imprime un reporte como:

```
Operaciones:      135
Ganadas:          43
Perdidas:         92
Winrate:          31.85%
Profit Factor:    0.93
Beneficio total:  -6.0 R
Max Drawdown:     28.0 R
Expectancy:       -0.044 R por operacion
```

### Uso desde Python (para comparar configuraciones)

```python
import data_feed, backtester

df = data_feed.fetch_ohlcv("XAUUSD", "1h")

configs = [
    {"min_score": 3, "sl_atr": 1.0, "tp_atr": 2.0},
    {"min_score": 4, "sl_atr": 1.0, "tp_atr": 2.0, "require_fvg": True},
    {"min_score": 4, "sl_atr": 1.5, "tp_atr": 3.0, "require_ob": True},
]
ranking = backtester.compare_configs(df, configs)
for r in ranking:
    print(r["config"], "->", r["stats"])
```

### Filtros disponibles (aprovechan `result["details"]` de tu estrategia)

- `min_score`: puntaje minimo (valor absoluto) del veredicto de `strategy.analyze()`.
- `require_fvg`: exige un FVG sin mitigar a favor de la direccion de la senal.
- `require_ob`: exige un Order Block activo a favor de la direccion.
- `ignore_range`: ignora veredictos "NEUTRAL / RANGO" (activado por defecto).
- `side_filter`: prueba solo "ALCISTA" o solo "BAJISTA".
- `sl_atr` / `tp_atr`: distancia de SL/TP en multiplos de ATR(14).

### Limitaciones del backtester (leelas antes de confiar en los numeros)

- No modela spread, comisiones ni slippage — en la vida real esos costos
  bajan el resultado, sobre todo con muchas operaciones pequeñas.
- No modela tamano de posicion ni balance de cuenta: todo esta en R, tu
  decides despues cuanto vale una R en tu cuenta real (ej. 1% de riesgo).
- Es O(n^2) porque `strategy.analyze()` recalcula todo el historico visible
  en cada paso — para historiales muy largos puede tardar; usa `step` para
  acelerar (analiza 1 de cada N velas) si hace falta.
- Un buen resultado en backtest **no garantiza** resultados futuros —
  sobre todo si terminas ajustando filtros hasta que "cuadren" con el
  pasado (overfitting). Prueba siempre en datos que no usaste para ajustar
  la estrategia (out-of-sample) antes de confiar en un resultado.

## Plataforma de Backtesting profesional (interfaz grafica)

Desde la ventana principal, el boton **📊 Backtest** abre una ventana nueva
e independiente con 3 pestañas. El analisis normal (la ventana de siempre)
sigue funcionando exactamente igual — esto es un modo adicional, no un
reemplazo. (El `backtester.py` por linea de comandos de la seccion anterior
sigue funcionando igual tambien.)

### Pestaña "Backtest"

Configuras simbolo, temporalidad (1m, 2m, 15m, 30m, 1h, 4h, 1d, 1wk — las que
soporta Yahoo Finance), cantidad de velas, capital inicial, riesgo % por
operacion, comision/spread/slippage (en multiplos de R), y SL/TP en ATR.
Mientras corre, ves una barra de progreso con velas procesadas, tiempo
transcurrido y tiempo restante estimado (corre en un hilo aparte, no congela
la ventana). Al terminar, panel con todas las metricas (operaciones, winrate,
profit factor, expectancy, net profit, drawdown, Sharpe, Sortino, Calmar,
recovery factor, rachas, estacionalidad, etc.) y 6 graficos: Equity Curve,
Drawdown, Beneficio mensual, Distribucion de resultados, Equity vs Buy&Hold,
y Heatmap mensual. Botones para exportar a CSV, Excel, JSON y PDF (el PDF
incluye todos los graficos).

### Pestaña "Optimizacion"

Prueba automaticamente, para cada score minimo que elijas, que pasa si
apagas un componente ICT/SMC a la vez (Order Blocks, FVG, Footprint,
Liquidity Sweep, Premium/Discount, CHoCH, BOS, Trend), y muestra una tabla
ordenada por Profit Factor — igual al ejemplo que diste (Base / Score>=4 /
Score>=5...). Es la version rapida y practica; si quieres probar TODAS las
256 combinaciones posibles por score (2^8), esa funcion tambien existe
(`optimizer.run_optimization()`) pero cuidado: puede tardar mucho en
historiales largos, por eso no es la que usa la interfaz por defecto.

### Pestaña "Historial"

Cada backtest que corres se guarda solo en SQLite (tabla nueva
`backtest_history`, no toca las tablas existentes). Doble clic en cualquier
fila para ver el detalle guardado sin volver a ejecutarlo.

### Que se toco y que no, para integrar esto

- **`strategy.py`**: se agregaron parametros opcionales `use_trend`,
  `use_bos`, `use_choch`, `use_fvg`, `use_order_blocks`,
  `use_liquidity_sweep`, `use_premium_discount`, `use_footprint` a
  `analyze()`, todos `True` por defecto. Una llamada `analyze(df)` sin
  argumentos se comporta exactamente igual que antes (verificado). Este fue
  el unico cambio a la logica existente, y era necesario para que el
  optimizador pueda apagar componentes uno a la vez.
- **`backtester.py`**: se agrego `progress_callback` y `strategy_kwargs` a
  `run_backtest()` (ambos opcionales, no cambian el comportamiento si no se
  usan), y dos funciones nuevas (`apply_money_simulation`,
  `buy_and_hold_curve`). No se toco la logica de entradas/salidas existente.
- **`app.py`**: se agrego un import y un boton "📊 Backtest" que abre la
  ventana nueva. Nada mas.
- **`storage.py`**: se agrego una tabla nueva (`backtest_history`) y sus
  funciones. Las tablas y funciones existentes no se tocaron.
- **Archivos 100% nuevos**: `backtest_window.py` (la interfaz de las 3
  pestañas), `optimizer.py`, `statistics_module.py` (llamado asi y no
  `statistics.py` para no chocar con el modulo estandar de Python del mismo
  nombre), `charts.py`, `report.py`.

### Rendimiento

`strategy.analyze()` recalcula todo el historico visible en cada paso del
backtest (es O(n^2)). Con 1000-2000 velas tarda pocos segundos; con 10 000-
20 000 velas puede tardar varios minutos — la barra de progreso te muestra el
tiempo restante estimado en tiempo real para que sepas que esperar.

## Estructura del proyecto

```
trading_bot/
├── app.py                  # Interfaz grafica principal (Tkinter) - punto de entrada
├── backtest_window.py       # Ventana de Backtesting/Optimizacion/Historial (nuevo)
├── strategy.py               # Motor de analisis ICT/SMC/FVG/footprint aproximado
├── backtester.py               # Backtesting walk-forward sobre strategy.py
├── optimizer.py                  # Grid search / optimizacion por componente (nuevo)
├── statistics_module.py            # Metricas avanzadas: Sharpe, Sortino, Calmar... (nuevo)
├── charts.py                         # Graficos matplotlib (nuevo)
├── report.py                           # Exportacion CSV/Excel/JSON/PDF (nuevo)
├── data_feed.py                          # Descarga de datos (yfinance) + alias de simbolos
├── storage.py                              # Persistencia SQLite (watchlist, trades, historial...)
├── requirements.txt
└── trading_bot.db                            # Se crea automaticamente al primer uso
```

## Ideas para extender esto despues

- Conectar a un broker real (MetaTrader5, Interactive Brokers) para pasar de
  "solo senales" a ejecucion automatica, si en algun momento lo quieres.
- Anadir alertas por Telegram/Discord cuando cambie el sesgo de un simbolo.
- Anadir mas timeframes o confluencia multi-timeframe (ej. sesgo en 4h +
  entrada en 15m).
- Footprint real si consigues un feed de datos de nivel 2 / tick data.
