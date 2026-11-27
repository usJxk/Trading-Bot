const palette = {
  up: "#7ed7c5", down: "#eea79c", grid: "#34424d", text: "#a3b0bd",
  bright: "#eef1f0", accent: "#efd195", label: "#384956",
};
const prices = [2, 4, 6].map(digits => new Intl.NumberFormat("es", {
  minimumFractionDigits: digits, maximumFractionDigits: digits,
}));
const formatPrice = value => prices[Math.abs(value) >= 10 ? 0 : Math.abs(value) >= .01 ? 1 : 2].format(value);
const formatTime = new Intl.DateTimeFormat("es", {
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
});
const shortDate = new Intl.DateTimeFormat("es", {month: "short", day: "numeric", timeZone: "UTC"});

function canvasSurface(node) {
  const {width, height} = node.getBoundingClientRect();
  if (width <= 0 || height <= 0) return null;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.max(1, Math.round(width * ratio));
  const pixelHeight = Math.max(1, Math.round(height * ratio));
  if (node.width !== pixelWidth) node.width = pixelWidth;
  if (node.height !== pixelHeight) node.height = pixelHeight;
  const ctx = node.getContext("2d");
  ctx.setTransform(node.width / width, 0, 0, node.height / height, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.font = "11px monospace";
  ctx.lineWidth = 1;
  return {ctx, width, height};
}

function grid(ctx, left, right, top, bottom, high, low, lines = 5) {
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  for (let i = 0; i <= lines; i++) {
    const y = top + (bottom - top) * i / lines;
    ctx.strokeStyle = palette.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.fillText(formatPrice(high - (high - low) * i / lines), right + 7, y);
  }
}

export class CandleChart {
  constructor(node, detail, onRange) {
    this.node = node;
    this.detail = detail;
    this.onRange = onRange;
    this.data = null;
    this.hover = null;
    this.depth = "auto";
    this.offset = 0;
    this.frame = 0;
    this.showZones = true;
    new ResizeObserver(() => this.schedule()).observe(node);
    window.addEventListener("resize", () => this.schedule());
    node.addEventListener("pointerdown", event => {
      if (!this.plot || event.button !== 0) return;
      this.drag = {id: event.pointerId, from: event.clientX, offset: this.offset};
      node.setPointerCapture(event.pointerId);
    });
    node.addEventListener("pointermove", event => {
      if (!this.plot || !this.data) return;
      const {left, right, count} = this.plot;
      if (this.drag?.id === event.pointerId && (this.drag.moved || Math.abs(event.clientX - this.drag.from) > 5)) {
        this.drag.moved = true;
        this.offset = this.drag.offset + Math.round((event.clientX - this.drag.from) * count / (right - left));
        this.setHover(null);
        return;
      }
      const cursor = event.clientX - node.getBoundingClientRect().left;
      this.setHover(Math.min(count - 1, Math.max(0, Math.floor((cursor - left) / (right - left) * count))));
    });
    for (const event of ["pointerup", "lostpointercapture", "pointercancel"]) {
      node.addEventListener(event, () => { this.drag = null; });
    }
    node.addEventListener("pointerleave", () => this.setHover(null));
    node.addEventListener("blur", () => this.setHover(null));
    node.addEventListener("keydown", event => {
      if (!this.plot) return;
      if (["PageUp", "PageDown", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        if (event.key === "PageUp" || event.key === "PageDown") this.page(event.key === "PageUp" ? 1 : -1);
        else this.setOffset(event.key === "Home" ? this.plot.total : 0);
      } else if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
        event.preventDefault();
        const {count} = this.plot;
        this.setHover(Math.min(count - 1, Math.max(0,
          (this.hover ?? count - 1) + (event.key === "ArrowLeft" ? -1 : 1))));
      }
    });
  }

  schedule() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
    });
  }

  setHover(index) {
    this.hover = index;
    this.schedule();
  }

  setOffset(offset) {
    this.offset = offset;
    this.setHover(null);
  }

  page(direction) {
    if (this.plot) this.setOffset(this.offset + direction * Math.max(1, Math.floor(this.plot.count * .8)));
  }

  update(data) {
    const changed = !data || ["symbol", "interval", "source"].some(key => data[key] !== this.data?.[key]);
    if (data) {
      const visibleEnd = !changed && this.offset ? this.times.at(-1 - this.offset) : null;
      this.times = data.candles.map(candle => Date.parse(candle[0]));
      this.zones = data.zones.map(zone => ({...zone, time: Date.parse(zone.start)}));
      if (visibleEnd !== null) {
        const index = this.times.findIndex(time => time >= visibleEnd);
        this.offset = index < 0 ? 0 : this.times.length - 1 - index;
      }
    }
    this.data = data;
    if (changed) this.setOffset(0);
    else this.setHover(null);
  }

  draw() {
    const surface = canvasSurface(this.node);
    if (!surface) return;
    if (!this.data?.candles.length) {
      this.plot = null;
      this.detail.textContent = "Apertura, máximo, mínimo y cierre";
      this.onRange(null);
      return;
    }

    const {ctx, width, height} = surface;
    const left = 12, right = width - 74, top = 14, bottom = height - 60;
    const pixels = {near: 12, auto: 7, wide: 4}[this.depth];
    const total = this.data.candles.length;
    const count = Math.min(total, Math.max(10, Math.floor((right - left) / pixels)));
    this.offset = Math.min(total - count, Math.max(0, this.offset));
    const end = total - this.offset;
    const start = end - count;
    const data = this.data.candles.slice(start, end);
    this.hover = this.hover == null ? null : Math.min(this.hover, count - 1);
    this.plot = {left, right, count, total};
    this.onRange({older: start > 0, newer: this.offset > 0});
    const max = Math.max(...data.map(candle => candle[2]));
    const min = Math.min(...data.map(candle => candle[3]));
    const margin = (max - min || Math.abs(max) || 1) * .06;
    const hi = max + margin, lo = min - margin;
    const maxVolume = Math.max(...data.map(candle => candle[5]), 1);
    const spacing = (right - left) / count;
    const thickness = Math.max(1, spacing * .66);
    const x = i => left + (i + .5) * spacing;
    const y = price => top + (hi - price) * (bottom - top) / (hi - lo);

    grid(ctx, left, right, top, bottom, hi, lo);
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, right - left, bottom - top);
    ctx.clip();
    if (this.showZones) {
      const timestamps = this.times.slice(start, end);
      for (const zone of this.zones) {
        const first = timestamps.findIndex(time => time >= zone.time);
        if (first < 0 || zone.low > hi || zone.high < lo) continue;
        const zx = zone.time < timestamps[0] ? left : x(first);
        const color = zone.bias === "ALCISTA" ? palette.up : palette.down;
        const zy = y(zone.high);
        ctx.fillStyle = color + (zone.kind === "FVG" ? "24" : "15");
        ctx.fillRect(zx, zy, right - zx, Math.max(2, y(zone.low) - zy));
        ctx.strokeStyle = color + "73";
        ctx.setLineDash(zone.kind === "OB" ? [3, 3] : []);
        ctx.beginPath();
        ctx.moveTo(zx, zy);
        ctx.lineTo(right, zy);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    data.forEach(([, open, high, low, close], i) => {
      const color = open <= close ? palette.up : palette.down;
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.moveTo(x(i), y(high));
      ctx.lineTo(x(i), y(low));
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.fillRect(x(i) - thickness / 2, Math.min(y(open), y(close)), thickness,
                   Math.max(1, Math.abs(y(open) - y(close))));

    });
    ctx.restore();
    // Draw volume outside the clipping region used for price, below the last grid line.
    data.forEach(([, open, , , close, volume], i) => {
      const volumeHeight = volume / maxVolume * 30;
      ctx.fillStyle = (open <= close ? palette.up : palette.down) + "55";
      ctx.fillRect(x(i) - thickness / 2, height - 25 - volumeHeight, thickness, volumeHeight);
    });

    ctx.textAlign = "center";
    ctx.fillStyle = palette.text;
    const labels = width < 450 ? 2 : width < 600 ? 3 : 5;
    const timeLabel = ["1d", "1wk", "4h"].includes(this.data.interval) ? shortDate : formatTime;
    let previousLabelEnd = -Infinity;
    for (let i = 0; i < labels; i++) {
      const index = Math.round((count - 1) * (.12 + .76 * i / (labels - 1)));
      const label = timeLabel.format(new Date(data[index][0]));
      const half = ctx.measureText(label).width / 2;
      const labelX = Math.max(half + 4, Math.min(width - half - 4, x(index)));
      if (labelX - half < previousLabelEnd + 6) continue;
      ctx.fillText(label, labelX, height - 10);
      previousLabelEnd = labelX + half;
    }

    const candle = data[this.hover ?? count - 1];
    const position = this.hover == null ? null : x(this.hover);
    const cy = y(candle[4]);
    ctx.strokeStyle = this.hover == null ? palette.accent + "95" : palette.bright + "88";
    ctx.setLineDash([4, 5]);
    ctx.beginPath();
    ctx.moveTo(left, cy);
    ctx.lineTo(right, cy);
    if (position !== null) {
      ctx.moveTo(position, top);
      ctx.lineTo(position, height - 25);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    const label = formatPrice(candle[4]);
    ctx.textAlign = "left";
    ctx.fillStyle = this.hover == null ? palette.accent : palette.label;
    ctx.fillRect(right + 3, cy - 9, Math.min(70, ctx.measureText(label).width + 10), 18);
    ctx.fillStyle = this.hover == null ? "#23201a" : palette.bright;
    ctx.fillText(label, right + 8, cy);
    const [stamp, open, high, low, close] = candle;
    this.detail.textContent = [
      formatTime.format(new Date(stamp)), "A " + formatPrice(open), "Máx " + formatPrice(high),
      "Mín " + formatPrice(low), "C " + formatPrice(close),
    ].join("  /  ");
  }
}

export function equityChart(node, values) {
  const surface = canvasSurface(node);
  if (!surface || !values?.length) return;
  const {ctx, width, height} = surface;
  const left = 7, right = width - 58, top = 12, bottom = height - 20;
  const max = Math.max(0, ...values), min = Math.min(0, ...values);
  const margin = (max - min || 1) * .1;
  const high = max + margin, low = min - margin;
  const y = value => top + (high - value) * (bottom - top) / (high - low);
  const x = index => left + (right - left) * index / Math.max(1, values.length - 1);
  grid(ctx, left, right, top, bottom, high, low, 4);
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
  if (values.length === 1) ctx.lineTo(right, y(values[0]));
  ctx.stroke();
}
