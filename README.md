# Mesa para Trading-Bot

Un espacio local para explorar velas, ver qué detecta la estrategia ICT/SMC y simular cómo se habría comportado en el histórico. Abre con una serie sintética para poder probarlo sin conexión. Las operaciones del diario se anotan a mano y son de práctica.

## Arrancar

Necesitas Python 3.10 o posterior. Probado con Python 3.13 en Fedora.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m terminal
```

En Windows, activa el entorno desde PowerShell con `.\.venv\Scripts\Activate.ps1`, o usa `.\.venv\Scripts\python.exe` directamente.

Abre [127.0.0.1:8765](http://127.0.0.1:8765). Si ese puerto está ocupado, puedes arrancar con `python -m terminal --port 8766`. Pulsa Ctrl+C en la terminal para cerrar el servidor.

## Uso

- **Mercado.** Escribe un símbolo, elige un intervalo y pulsa **Analizar**. Pasa el puntero sobre el gráfico, o enfócalo y usa las flechas, para leer los valores de cada vela. Usa **Zonas** para mostrar u ocultar los FVG y los order blocks. La vista **Automática** ajusta la densidad de las velas al ancho del gráfico. También puedes elegir **Detalle** o **Panorámica**. Arrastra el gráfico, usa los botones de navegación o pulsa Re Pág / Av Pág para recorrer hasta 400 velas. **Últimas** vuelve al final. El botón **+** guarda el símbolo y el intervalo en Seguimiento. **Simular este gráfico** copia la fuente, el símbolo y el intervalo a Backtesting.
- **Datos.** Cambia de **Serie de ejemplo** a **Yahoo Finance** para cargar datos históricos. Si la descarga falla, sigue visible el último gráfico con su fuente y símbolo. Mercado y Backtesting comparten una caché de hasta un minuto (15 segundos para 1m y 2m). El modo de ejemplo genera siempre la misma serie para un símbolo e intervalo en el mismo entorno. El panel indica la fuente, el ticker resuelto y la hora en UTC. Los alias pueden representar instrumentos distintos del nombre escrito. Por ejemplo, `XAUUSD` usa el futuro `GC=F`.
- **Backtesting.** Configura entre 60 y 600 velas, el coste por operación y las distancias de salida. Puedes cambiar de vista mientras se ejecuta, consultar el progreso o cancelar antes de que se guarde. La curva y la tabla muestran el resultado neto en R, medido con respecto a la distancia entre la entrada y el stop inicial. El historial conserva la configuración, el rango de fechas, la huella de la muestra, los resultados y las operaciones. Puedes volver a abrir una simulación o exportarla a CSV y JSON.
- **Diario.** Registra y cierra operaciones de práctica. Puedes filtrar las filas abiertas y cerradas. La variación se calcula a partir de los precios de entrada y cierre según el lado de la operación.

## Qué simula el motor

El motor recibe las velas disponibles hasta la señal y simula la entrada en la apertura de la siguiente. Si una vela abre más allá del stop, la salida se calcula con esa apertura. Si toca stop y objetivo dentro de la misma vela y la apertura no resuelve el orden, se asume que tocó el stop primero. El coste de la interfaz web se descuenta como un valor fijo en R por operación.

La lectura usa reglas aproximadas para estructura, FVG, order blocks y volumen. El volumen por vela solo permite estimar la presión; un footprint requiere datos a nivel de operación. La agrupación de 4h se reconstruye desde velas de 1h. El histórico, los ajustes y los intervalos disponibles dependen del proveedor. Una simulación describe la muestra utilizada y omite la secuencia de precios dentro de cada vela.

## Datos locales y versión de escritorio

El diario, el seguimiento y las simulaciones se guardan en `trading_bot.db` junto al código. Ambas interfaces leen la misma base, incluidas las filas creadas por la versión original. Cierra ambas interfaces antes de copiar esa base para guardarla. Puedes elegir otra ruta mediante la variable `TRADING_BOT_DB`.

El servidor está pensado para usarse en el mismo equipo. Escucha en loopback y exige un token local para las operaciones de la API. La interfaz carga sus recursos desde el propio servidor. Elegir Yahoo Finance activa solicitudes externas para obtener las velas del símbolo.

La interfaz original sigue disponible con `python app.py` si Tkinter está instalado. Desde ella se puede usar el optimizador por componentes y los informes Excel/PDF. También puedes llamar a `python backtester.py --help` para ver las opciones de la CLI original.

## Código

| Ruta | Función |
| --- | --- |
| `terminal/` | Interfaz web local, gráficos, serie de ejemplo y API |
| `data_feed.py` | Datos históricos y alias |
| `strategy.py` | Reglas de análisis |
| `backtester.py`, `statistics_module.py` | Simulación y métricas |
| `storage.py` | Persistencia SQLite |
| `app.py`, `backtest_window.py` | Interfaz original de escritorio |

Licencia [MPL-2.0](LICENSE).
