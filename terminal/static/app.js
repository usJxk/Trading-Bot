import {CandleChart, equityChart} from "./chart.js";

const $ = (id) => document.getElementById(id);
const token = document.querySelector("meta[name=terminal-token]").content;
const price = new Intl.NumberFormat("es", {maximumFractionDigits: 6});
const quotePrice = new Intl.NumberFormat("es", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const round = new Intl.NumberFormat("es", {maximumFractionDigits: 2});
const date = new Intl.DateTimeFormat("es", {dateStyle: "medium", timeStyle: "short", timeZone: "UTC"});
const titles = {market: "Mercado", backtest: "Backtesting", journal: "Diario"};
const examples = ["AAPL", "MSFT", "BTC-USD", "EURUSD"];
const directions = {
  ALCISTA: "Alcista", BAJISTA: "Bajista", RANGO: "Rango",
  "NEUTRAL / RANGO": "Neutral", INDEFINIDO: "Indefinida",
};
const sourceNames = {demo: "Serie de ejemplo", yahoo: "Yahoo Finance"};
const chart = new CandleChart($("price-chart"), $("candle-detail"), range => {
  $("chart-prev").disabled = !range?.older;
  $("chart-next").disabled = $("chart-latest").disabled = !range?.newer;
});
const browserPrefs = "mesa.settings.v1";
const runningJob = "mesa.backtest.v1";
function readSettings() {
  try { return JSON.parse(localStorage.getItem(browserPrefs)) || {}; }
  catch { return {}; }
}
function remember(update) {
  try { localStorage.setItem(browserPrefs, JSON.stringify({...readSettings(), ...update})); }
  catch { /* Storage may be disabled in the browser. */ }
}
function jobInTab(id) {
  try {
    if (id === undefined) return sessionStorage.getItem(runningJob);
    if (id) sessionStorage.setItem(runningJob, id);
    else sessionStorage.removeItem(runningJob);
  } catch { /* The job remains available until the server restarts. */ }
}
const state = {
  view: "market", interval: "1h", market: null, watch: [], journal: [], result: null,
  analysisRequest: null, history: [], closeId: null, jobId: null, polling: false, toast: 0,
};
const marketError = $("market-error");
const backtestError = $("backtest-error");
const backtestForm = $("backtest-form");

function showError(node, message = "") {
  node.textContent = message;
  node.hidden = !message;
}

function notify(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(state.toast);
  state.toast = setTimeout(() => { toast.hidden = true; }, 4300);
}

async function api(path, {method = "GET", data, signal, blob = false} = {}) {
  const headers = {"X-Terminal-Token": token};
  if (data !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api/" + path, {method, headers, signal,
    body: data === undefined ? undefined : JSON.stringify(data)});
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    throw Object.assign(new Error(details.error || "No se pudo completar la solicitud."), {
      status: response.status,
    });
  }
  return blob ? response.blob() : response.json();
}

function format(value, formatter = price) {
  return value == null ? "—" : formatter.format(value);
}

function signed(value, suffix = "") {
  return value == null ? "—" : (value > 0 ? "+" : "") + round.format(value) + suffix;
}

function datetime(value) {
  const stamp = new Date(value);
  return value && !Number.isNaN(stamp.getTime()) ? date.format(stamp) : "—";
}

function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = content;
  if (className) element.className = className;
  return element;
}

function button(label, action, className) {
  const item = node("button", label, className);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

function tableRow(values) {
  const row = node("tr");
  for (const value of values) {
    const cell = node("td");
    if (value instanceof Node) cell.append(value);
    else cell.textContent = value ?? "—";
    row.append(cell);
  }
  return row;
}

function emptyRow(table, columns, message) {
  const row = node("tr");
  const cell = node("td", message, "empty");
  cell.colSpan = columns;
  table.replaceChildren(row);
  row.append(cell);
}

function renderWatch() {
  const saved = state.watch.length > 0;
  const items = saved ? state.watch : examples.map(symbol => ({symbol, timeframe: "1h"}));
  $("watch-caption").hidden = saved;
  $("watch-list").replaceChildren(...items.map(({symbol, timeframe}) => {
    const row = node("div", undefined, "watch-row");
    const select = button("", () => {
      $("symbol").value = symbol;
      state.interval = timeframe;
      setView("market");
      loadMarket();
    }, "watch-symbol");
    select.classList.toggle("active", symbol === state.market?.symbol && timeframe === state.market.interval);
    select.append(node("strong", symbol), node("small", timeframe));
    row.append(select);
    if (saved) {
      const remove = button("×", async () => {
        try {
          state.watch = (await api("watch/" + encodeURIComponent(symbol), {method: "DELETE"})).items;
          renderWatch();
          $("watch-add").focus();
          notify(symbol + " eliminado del seguimiento.");
        } catch (error) { notify(error.message); }
      }, "watch-remove icon-button");
      remove.setAttribute("aria-label", "Quitar " + symbol + " del seguimiento");
      row.append(remove);
    }
    return row;
  }));
}

function marketStatus(message) {
  $("chart-empty").textContent = message;
  $("chart-empty").hidden = !message;
}

function renderMarket(data) {
  const selected = data?.symbol || $("symbol").value.trim().toUpperCase();
  $("instrument").textContent = selected || "Sin símbolo";
  $("ticker-chip").textContent = selected.charAt(0) || "—";
  $("source-tag").textContent = (data?.source || $("source").value) === "demo" ? "Ejemplo" : "Histórico";
  $("quote").textContent = format(data?.close, Math.abs(data?.close) >= 10 ? quotePrice : price);
  $("watch-add").disabled = $("use-chart").disabled = !data;
  $("chart-interval").textContent = data?.interval || state.interval;
  const change = $("change");
  change.textContent = data?.change == null ? "" : signed(data.change, " %");
  change.className = data?.change > 0 ? "positive" : data?.change < 0 ? "negative" : "";
  $("bias").textContent = directions[data?.bias] || "—";
  $("bias").className = data?.bias === "ALCISTA" ? "positive" : data?.bias === "BAJISTA" ? "negative" : "";
  $("score").textContent = signed(data?.score);
  const reasons = data?.reasons?.length ? data.reasons : [
    data ? "La estrategia quedó sin señales destacadas." : "Carga un símbolo para ver las señales.",
  ];
  $("reasons").replaceChildren(...reasons.map(reason => node("li", reason)));
  $("stat-source").textContent = sourceNames[data?.source || $("source").value];
  $("stat-ticker").textContent = data?.ticker || "—";
  $("stat-volume").textContent = format(data?.volume);
  $("stat-trend").textContent = directions[data?.trend] || data?.trend || "—";
  $("market-date").textContent = data ? datetime(data.candles.at(-1)[0]) + " UTC" : "";
  chart.update(data);
  renderWatch();
}

async function loadMarket() {
  state.analysisRequest?.abort();
  const controller = new AbortController();
  state.analysisRequest = controller;
  const symbol = $("symbol").value.trim().toUpperCase();
  $("symbol").value = symbol;
  for (const item of $("intervals").querySelectorAll("button")) {
    item.setAttribute("aria-pressed", String(item.dataset.interval === state.interval));
  }
  if (!state.market) renderMarket(null);
  showError(marketError);
  $("market-feedback").hidden = false;
  const status = $("market-loading");
  status.hidden = false;
  status.textContent = "Cargando " + (symbol || "símbolo") + " · " + state.interval + "…";
  if (!state.market) marketStatus("Cargando velas…");
  $("price-chart").setAttribute("aria-busy", "true");
  try {
    const query = new URLSearchParams({symbol, interval: state.interval, source: $("source").value});
    const data = await api("analysis?" + query, {signal: controller.signal});
    if (controller.signal.aborted) return;
    state.market = data;
    renderMarket(data);
    remember({symbol: data.symbol, interval: data.interval});
    marketStatus("");
  } catch (error) {
    if (controller.signal.aborted) return;
    if (!state.market) marketStatus("Sin datos para este gráfico");
    showError(marketError, error.message + (state.market ? " Sigue visible el gráfico anterior." : ""));
  } finally {
    if (!controller.signal.aborted) {
      $("price-chart").setAttribute("aria-busy", "false");
      status.hidden = true;
      $("market-feedback").hidden = marketError.hidden;
    }
  }
}

function setView(view) {
  const previous = state.view;
  state.view = view;
  if (previous !== view) $("toast").hidden = true;
  for (const key of Object.keys(titles)) $(key).hidden = key !== view;
  $("view-title").textContent = titles[view];
  for (const item of document.querySelectorAll("[data-view]")) {
    if (item.dataset.view === view) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  $("market-source").hidden = view !== "market";
  if (view === "backtest") loadHistory();
  if (view === "journal") api("journal").then(data => {
    state.journal = data.items;
    renderJournal();
  }).catch(error => notify(error.message));
}

function renderResult(result) {
  state.result = result;
  const config = result?.config;
  const stats = result?.stats;
  if (config) {
    const dates = config.start ? " · " + datetime(config.start) + " a " + datetime(config.end) + " UTC" : "";
    $("result-caption").textContent = [config.symbol, config.timeframe, config.num_candles + " velas",
      sourceNames[config.source] || "Registro anterior"].join(" · ") + dates;
  } else $("result-caption").textContent = "Elige una configuración y ejecuta la simulación.";
  const metrics = stats ? [
    ["Resultado neto", signed(stats.net_profit_r, " R")],
    ["Caída máxima", format(stats.max_drawdown_r, round) + " R"],
    ["Operaciones", format(stats.operaciones)],
    ["Aciertos", format(stats.winrate_pct, round) + " %"],
  ] : [];
  $("result-stats").replaceChildren(...metrics.map(([label, value]) => {
    const group = node("div");
    group.append(node("dt", label), node("dd", value));
    return group;
  }));
  $("equity-chart").hidden = !result?.curve;
  if (result?.curve) equityChart($("equity-chart"), result.curve);
  const note = $("result-note");
  note.hidden = !config;
  note.textContent = config?.source
    ? "Coste por operación: " + format(config.cost, round) + " R. El resultado corresponde a esta muestra histórica."
    : "Este registro de la versión anterior solo contiene el resumen.";
  $("export-buttons").hidden = !config;
  document.querySelector('[data-export="csv"]').hidden = !result?.trades;
  $("result-trades").hidden = !result?.trades;
  if (!result?.trades?.length) {
    emptyRow($("result-rows"), 5, "La estrategia no abrió operaciones con esta configuración.");
    return;
  }
  $("result-rows").replaceChildren(...result.trades.map(trade => tableRow([
    datetime(trade.entry_time), trade.side === "COMPRA" ? "Compra" : "Venta",
    format(trade.entry_price), format(trade.exit_price), signed(trade.r_multiple, " R"),
  ])));
}

function renderHistory() {
  const body = $("history");
  if (!state.history.length) {
    emptyRow(body, 6, "Todavía no hay simulaciones guardadas.");
    return;
  }
  body.replaceChildren(...state.history.map(item => {
    const actions = node("span");
    actions.append(
      button("Abrir", async () => {
        try {
          renderResult(await api("backtests/" + item.id));
          $("result-heading").scrollIntoView({block: "nearest"});
        } catch (error) { notify(error.message); }
      }),
      button("Eliminar", async () => {
        if (!window.confirm("¿Eliminar esta simulación del historial?")) return;
        try {
          state.history = (await api("backtests/" + item.id, {method: "DELETE"})).items;
          if (state.result?.id === item.id) renderResult(null);
          renderHistory();
          notify("Simulación eliminada.");
        } catch (error) { notify(error.message); }
      }),
    );
    actions.className = "actions";
    const row = tableRow([datetime(item.fecha), item.symbol, item.timeframe,
      item.num_candles, signed(item.beneficio_r, " R"), actions]);
    row.lastElementChild.className = "actions";
    return row;
  }));
}

async function loadHistory() {
  try {
    state.history = (await api("backtests")).items;
    renderHistory();
  } catch (error) { notify(error.message); }
}

function renderJournal() {
  const filter = $("journal-filter").value;
  const items = state.journal.filter(item => !filter || item.status === filter);
  if (!items.length) {
    emptyRow($("journal-rows"), 7, "No hay operaciones en esta vista.");
    return;
  }
  $("journal-rows").replaceChildren(...items.map(item => {
    const pnl = item.close_price == null || !item.entry_price ? null
      : (item.close_price - item.entry_price) / item.entry_price * (item.side === "COMPRA" ? 100 : -100);
    const action = item.status === "ABIERTA" ? button("Cerrar", () => {
      state.closeId = item.id;
      const form = $("close-form");
      form.reset();
      $("close-context").textContent = item.symbol + " · Entrada " + format(item.entry_price);
      showError(form.querySelector(".error"));
      $("close-dialog").showModal();
    }) : "Cerrada";
    const details = node("div");
    const plan = [
      ["Stop", item.stop_loss], ["Objetivo", item.take_profit], ["Cantidad", item.size],
    ].filter(([, value]) => value != null).map(([label, value]) => label + " " + format(value));
    if (plan.length) details.append(node("p", plan.join(" · "), "trade-plan"));
    details.append(node("span", item.notes || (plan.length ? "" : "—")));
    const row = tableRow([item.symbol, item.side === "COMPRA" ? "Compra" : "Venta", format(item.entry_price),
      format(item.close_price), signed(pnl, " %"), details, action]);
    row.children[4].className = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "";
    row.children[5].className = "note";
    return row;
  }));
}

function formData(form, numeric) {
  const fields = Object.fromEntries(new FormData(form));
  for (const key of numeric) fields[key] = fields[key] === "" ? null : Number(fields[key]);
  return fields;
}

async function submitJournal(form, path, numeric, message) {
  const errorNode = form.querySelector(".error");
  const submit = form.querySelector('[type="submit"]');
  showError(errorNode);
  submit.disabled = true;
  try {
    state.journal = (await api(path, {method: "POST", data: formData(form, numeric)})).items;
    form.closest("dialog").close();
    renderJournal();
    notify(message);
  } catch (error) { showError(errorNode, error.message); }
  finally { submit.disabled = false; }
}

document.querySelectorAll("[data-view]").forEach(item => item.addEventListener("click", () => setView(item.dataset.view)));
$("search").addEventListener("submit", event => { event.preventDefault(); loadMarket(); });
$("intervals").addEventListener("click", event => {
  if (!event.target.dataset.interval) return;
  state.interval = event.target.dataset.interval;
  loadMarket();
});
$("zones").addEventListener("change", event => {
  chart.showZones = event.target.checked;
  remember({zones: chart.showZones});
  chart.schedule();
});
$("chart-depth").addEventListener("change", event => {
  chart.depth = event.target.value;
  remember({depth: chart.depth});
  chart.schedule();
});
$("chart-prev").addEventListener("click", () => chart.page(1));
$("chart-next").addEventListener("click", () => chart.page(-1));
$("chart-latest").addEventListener("click", () => chart.setOffset(0));
$("use-chart").addEventListener("click", () => {
  if (!state.market) return;
  const {symbol, interval, source} = state.market;
  backtestForm.elements.symbol.value = symbol;
  backtestForm.elements.interval.value = interval;
  backtestForm.elements.source.value = source;
  setView("backtest");
  backtestForm.elements.limit.focus();
});
$("source").addEventListener("change", () => {
  if (state.view === "market") loadMarket();
});
$("watch-add").addEventListener("click", async event => {
  const control = event.currentTarget;
  if (!state.market) return;
  const {symbol, interval} = state.market;
  control.disabled = true;
  try {
    state.watch = (await api("watch", {method: "POST", data: {symbol, interval}})).items;
    renderWatch();
    notify(symbol + " guardado en seguimiento.");
  } catch (error) { notify(error.message); }
  finally { control.disabled = !state.market; }
});

const startSimulation = backtestForm.querySelector('[type="submit"]');
const cancelSimulation = $("cancel-backtest");
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function progress(status, value = 0, total = 0) {
  const labels = {
    loading: "Preparando las velas…", running: "Velas procesadas " + value + " de " + total,
    cancelling: "Cancelando…", saving: "Guardando la simulación…", retry: "Volviendo a conectar…",
  };
  $("backtest-progress").hidden = !status;
  $("backtest-status").textContent = labels[status] || "";
  const bar = $("backtest-bar");
  if (status === "running" && total > 0) bar.value = Math.floor(value / total * 100);
  else bar.removeAttribute("value");
  cancelSimulation.hidden = !state.jobId || status === "saving";
  cancelSimulation.disabled = status === "cancelling";
  startSimulation.disabled = !!status;
}

async function monitorJob(id) {
  if (state.polling) return;
  state.polling = true;
  progress("loading");
  let attempts = 0;
  try {
    while (state.jobId === id) {
      let data;
      try {
        data = await api("backtest-jobs/" + id);
        attempts = 0;
      } catch (error) {
        if (error.status || ++attempts > 3) throw error;
        progress("retry");
        await pause(900);
        continue;
      }
      if (data.status === "done") {
        renderResult(await api("backtests/" + data.run_id));
        await loadHistory();
        notify("Simulación guardada.");
        break;
      }
      if (data.status === "cancelled") { notify("Simulación cancelada."); break; }
      if (data.status === "error") throw new Error(data.error);
      progress(data.status, data.value, data.total);
      await pause(document.hidden ? 1100 : 220);
    }
  } catch (error) {
    showError(backtestError, error.message);
    loadHistory();
  } finally {
    state.jobId = null;
    jobInTab(null);
    state.polling = false;
    progress(null);
  }
}

backtestForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (startSimulation.disabled || state.jobId) return;
  const data = formData(backtestForm, ["limit", "sl", "tp", "score", "cost"]);
  showError(backtestError);
  progress("loading");
  try {
    const {id} = await api("backtest-jobs", {method: "POST", data});
    state.jobId = id;
    jobInTab(id);
    monitorJob(id);
  } catch (error) {
    showError(backtestError, error.message);
    progress(null);
  }
});

cancelSimulation.addEventListener("click", async () => {
  if (!state.jobId) return;
  cancelSimulation.disabled = true;
  try {
    await api("backtest-jobs/" + state.jobId, {method: "DELETE"});
  } catch (error) {
    if (error.status !== 409) showError(backtestError, error.message);
  }
});

document.querySelectorAll("[data-export]").forEach(control => control.addEventListener("click", async () => {
  const id = state.result?.id;
  const fmt = control.dataset.export;
  if (!id) return;
  try {
    const file = await api("backtests/" + id + "/export/" + fmt, {blob: true});
    const url = URL.createObjectURL(file);
    const link = node("a");
    link.href = url;
    link.download = "backtest-" + id + "." + fmt;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (error) { notify(error.message); }
}));

$("journal-filter").addEventListener("change", renderJournal);
$("trade-add").addEventListener("click", () => {
  const form = $("trade-form");
  form.reset();
  form.elements.symbol.value = state.market?.symbol || $("symbol").value;
  showError(form.querySelector(".error"));
  $("trade-dialog").showModal();
});
document.querySelectorAll("[data-dialog-close]").forEach(item =>
  item.addEventListener("click", () => item.closest("dialog").close()));
$("trade-form").addEventListener("submit", event => {
  event.preventDefault();
  submitJournal(event.currentTarget, "journal", ["entry", "stop", "target", "size"], "Operación guardada.");
});
$("close-form").addEventListener("submit", event => {
  event.preventDefault();
  submitJournal(event.currentTarget, "journal/" + state.closeId + "/close", ["close"], "Operación cerrada.");
});

new ResizeObserver(() => equityChart($("equity-chart"), state.result?.curve)).observe($("equity-chart"));
const savedPrefs = readSettings();
if (["auto", "near", "wide"].includes(savedPrefs.depth)) $("chart-depth").value = chart.depth = savedPrefs.depth;
if (typeof savedPrefs.zones === "boolean") $("zones").checked = chart.showZones = savedPrefs.zones;
if (typeof savedPrefs.symbol === "string" && savedPrefs.symbol.length <= 24) $("symbol").value = savedPrefs.symbol;
const intervals = Array.from($("intervals").querySelectorAll("button"), item => item.dataset.interval);
if (intervals.includes(savedPrefs.interval)) state.interval = savedPrefs.interval;
state.jobId = jobInTab();
if (state.jobId && /^[0-9a-f]{32}$/.test(state.jobId)) {
  setView("backtest");
  monitorJob(state.jobId);
} else state.jobId = null;
api("watch").then(data => { state.watch = data.items; renderWatch(); }).catch(error => notify(error.message));
loadMarket();
