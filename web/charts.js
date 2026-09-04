// Zero-dependency canvas charts with US-EPA AQI colouring. Charts redraw on resize.

const registry = new Map();
const PAD = { l: 34, r: 8, t: 10, b: 20 };
const GRID = "#1e293b";
const AXIS = "#64748b";
const PM10_COLOR = "#38bdf8";

export function drawLine(canvas, data, labelFn) {
  registry.set(canvas, { kind: "line", data, labelFn });
  render(canvas);
}

export function drawBars(canvas, data, labelFn) {
  registry.set(canvas, { kind: "bars", data, labelFn });
  render(canvas);
}

function colorForPm25(v) {
  const t = [
    [9.0, "#00e400"], [35.4, "#ffff00"], [55.4, "#ff7e00"],
    [125.4, "#ff0000"], [225.4, "#8f3f97"],
  ];
  for (const [hi, c] of t) if (v <= hi) return c;
  return "#7e0023";
}

function setup(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function empty(ctx, w, h) {
  ctx.fillStyle = AXIS;
  ctx.font = "13px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("No data yet", w / 2, h / 2);
}

function render(canvas) {
  const item = registry.get(canvas);
  if (!item) return;
  const { ctx, w, h } = setup(canvas);
  const data = item.data || [];
  if (!data.length) return empty(ctx, w, h);

  const maxV = Math.max(20, ...data.map((d) => Math.max(d.pm25 || 0, d.pm10 || 0))) * 1.1;
  const top = PAD.t, bottom = h - PAD.b;
  const y = (v) => bottom - (v / maxV) * (bottom - top);
  const n = data.length;
  const x = (i) =>
    PAD.l + (n === 1 ? (w - PAD.l - PAD.r) / 2 : (i / (n - 1)) * (w - PAD.l - PAD.r));

  // grid + y labels
  ctx.lineWidth = 1;
  ctx.font = "10px system-ui, sans-serif";
  for (let i = 0; i <= 3; i++) {
    const val = (maxV / 3) * i;
    const yy = y(val);
    ctx.strokeStyle = GRID;
    ctx.beginPath();
    ctx.moveTo(PAD.l, yy);
    ctx.lineTo(w - PAD.r, yy);
    ctx.stroke();
    ctx.fillStyle = AXIS;
    ctx.textAlign = "right";
    ctx.fillText(Math.round(val), PAD.l - 4, yy + 3);
  }

  if (item.kind === "line") {
    const accent = colorForPm25(Math.max(...data.map((d) => d.pm25 || 0)));
    // area fill under PM2.5
    ctx.beginPath();
    data.forEach((d, i) => (i ? ctx.lineTo(x(i), y(d.pm25 || 0)) : ctx.moveTo(x(i), y(d.pm25 || 0))));
    ctx.lineTo(x(n - 1), bottom);
    ctx.lineTo(x(0), bottom);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, top, 0, bottom);
    grad.addColorStop(0, accent + "66");
    grad.addColorStop(1, accent + "00");
    ctx.fillStyle = grad;
    ctx.fill();
    // PM2.5 line
    ctx.beginPath();
    data.forEach((d, i) => (i ? ctx.lineTo(x(i), y(d.pm25 || 0)) : ctx.moveTo(x(i), y(d.pm25 || 0))));
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.stroke();
    // PM10 dashed line
    ctx.beginPath();
    data.forEach((d, i) => (i ? ctx.lineTo(x(i), y(d.pm10 || 0)) : ctx.moveTo(x(i), y(d.pm10 || 0))));
    ctx.strokeStyle = PM10_COLOR;
    ctx.lineWidth = 1.25;
    ctx.setLineDash([4, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
  } else {
    const bw = Math.max(2, ((w - PAD.l - PAD.r) / n) * 0.6);
    data.forEach((d, i) => {
      const yy = y(d.pm25 || 0);
      ctx.fillStyle = colorForPm25(d.pm25 || 0);
      ctx.fillRect(x(i) - bw / 2, yy, bw, bottom - yy);
    });
    ctx.fillStyle = PM10_COLOR;
    data.forEach((d, i) => {
      ctx.beginPath();
      ctx.arc(x(i), y(d.pm10 || 0), 1.8, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  // x labels (up to 4 ticks)
  ctx.fillStyle = AXIS;
  ctx.textAlign = "center";
  const ticks = Math.min(4, n);
  for (let i = 0; i < ticks; i++) {
    const idx = Math.round((n - 1) * (i / Math.max(1, ticks - 1)));
    ctx.fillText(item.labelFn(data[idx].t), x(idx), h - 6);
  }
}

let raf = null;
window.addEventListener("resize", () => {
  if (raf) cancelAnimationFrame(raf);
  raf = requestAnimationFrame(() => registry.forEach((_, c) => render(c)));
});
