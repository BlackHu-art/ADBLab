const root = document.documentElement;
if (!root.dataset.theme) {
  root.dataset.theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

const packageInput = document.getElementById("packageInput");
const activityInput = document.getElementById("activityInput");
const statusText = document.getElementById("statusText");
const actionButtons = Array.from(document.querySelectorAll("[data-action]"));
const tabs = Array.from(document.querySelectorAll(".tab-button"));
const panels = Array.from(document.querySelectorAll(".tab-panel"));
const deviceTable = document.getElementById("deviceTable");
const summaryList = document.getElementById("summaryList");
const eventList = document.getElementById("eventList");
const metricDetailList = document.getElementById("metricDetailList");
const reportSummary = document.getElementById("reportSummary");
const runStateValue = document.getElementById("runStateValue");
const packageValue = document.getElementById("packageValue");
const sampleCountValue = document.getElementById("sampleCountValue");
const reportStatusValue = document.getElementById("reportStatusValue");
const inspectorTabs = Array.from(document.querySelectorAll(".inspector-tab"));
const inspectorBodies = Array.from(document.querySelectorAll(".inspector-body"));
const inspectorToggle = document.getElementById("inspectorToggle");
const workspacePanel = document.querySelector(".workspace-panel");
const shell = document.querySelector(".dashboard-shell");
const sideToggle = document.getElementById("sideToggle");
const chartCanvases = Array.from(document.querySelectorAll(".metric-chart"));
let sharedHover = null;

let state = {
  state: "",
  currentPackage: "",
  packageName: "",
  activity: "",
  controls: {},
  theme: "",
  palette: {},
  points: [],
  events: [],
  report: "",
  reportSummary: {},
  deviceInfo: [],
  metricSummaries: [],
  metricDetails: [],
  axisPolicy: {}
};
let bridge = null;

function cssColor(name, fallback) {
  const value = getComputedStyle(root).getPropertyValue(name).trim();
  return value || fallback;
}

function parseHexColor(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const match = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!match) return null;
  const hex = match[1].length === 3
    ? match[1].split("").map(char => char + char).join("")
    : match[1];
  return {
    r: parseInt(hex.slice(0, 2), 16),
    g: parseInt(hex.slice(2, 4), 16),
    b: parseInt(hex.slice(4, 6), 16)
  };
}

function rgbaFromHex(value, alpha) {
  const rgb = parseHexColor(value);
  return rgb ? `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})` : value;
}

function isDarkColor(value) {
  const rgb = parseHexColor(value);
  if (!rgb) return root.dataset.theme !== "light";
  const luminance = (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
  return luminance < 0.52;
}

function applyTheme(payload = {}) {
  const palette = payload.palette || {};
  const font = payload.font || {};
  const themeName = String(payload.theme || "").toLowerCase();
  if (themeName.includes("dark")) {
    root.dataset.theme = "dark";
  } else if (themeName.includes("light")) {
    root.dataset.theme = "light";
  } else if (palette.background || palette.bg) {
    root.dataset.theme = isDarkColor(palette.background || palette.bg) ? "dark" : "light";
  }

  const variableMap = {
    background: "--bg",
    bg: "--bg",
    surface: "--surface",
    panel: "--surface",
    surfaceSoft: "--surface-soft",
    field: "--field",
    input: "--field",
    button: "--button",
    buttonHover: "--button-hover",
    disabledBackground: "--disabled-bg",
    disabledText: "--disabled-text",
    border: "--border",
    borderStrong: "--border-strong",
    text: "--text",
    title: "--title",
    muted: "--muted",
    subtle: "--subtle",
    accent: "--accent",
    accentContrast: "--accent-contrast",
    warning: "--warn",
    warn: "--warn",
    danger: "--danger",
    error: "--danger",
    info: "--info",
    success: "--success"
  };
  for (const [key, variable] of Object.entries(variableMap)) {
    if (palette[key]) {
      root.style.setProperty(variable, palette[key]);
    }
  }

  if (palette.accent && !palette.selection) {
    root.style.setProperty("--selection", rgbaFromHex(palette.accent, 0.16));
  }
  if (palette.border && !palette.grid) {
    root.style.setProperty("--grid", rgbaFromHex(palette.border, 0.36));
    root.style.setProperty("--grid-soft", rgbaFromHex(palette.border, 0.16));
  }
  if (palette.surfaceSoft || palette.field || palette.surface) {
    root.style.setProperty("--scrollbar-track", palette.surfaceSoft || palette.field || palette.surface);
  }
  if (palette.borderStrong || palette.border || palette.muted) {
    root.style.setProperty("--scrollbar-thumb", palette.borderStrong || palette.border || palette.muted);
  }
  if (palette.buttonHover || palette.accent) {
    root.style.setProperty("--scrollbar-thumb-hover", palette.buttonHover || palette.accent);
  }
  if (palette.surface) {
    root.style.setProperty("--chart-bg", palette.surface);
  }
  if (palette.border) {
    root.style.setProperty("--chart-grid", rgbaFromHex(palette.border, root.dataset.theme === "light" ? 0.28 : 0.38));
  }
  if (palette.text) {
    root.style.setProperty("--chart-axis", rgbaFromHex(palette.text, root.dataset.theme === "light" ? 0.78 : 0.84));
    root.style.setProperty("--chart-crosshair", rgbaFromHex(palette.text, root.dataset.theme === "light" ? 0.72 : 0.88));
    root.style.setProperty("--chart-tooltip-text", palette.text);
  }
  if (palette.background) {
    root.style.setProperty("--chart-tooltip", rgbaFromHex(palette.background, 0.94));
  }
  if (palette.accent) {
    root.style.setProperty("--fps-color", palette.accent);
  }
  if (palette.warning || palette.warn) {
    const warning = palette.warning || palette.warn;
    root.style.setProperty("--jank-color", warning);
    root.style.setProperty("--cpu-bg-color", warning);
    root.style.setProperty("--cpu-user-color", warning);
    root.style.setProperty("--memory-native-color", warning);
    root.style.setProperty("--memory-swap-color", warning);
  }
  if (palette.danger || palette.error) {
    const danger = palette.danger || palette.error;
    root.style.setProperty("--cpu-fg-color", danger);
    root.style.setProperty("--cpu-app-color", danger);
  }
  if (palette.info) {
    root.style.setProperty("--stutter-color", palette.info);
    root.style.setProperty("--cpu-system-color", palette.info);
    root.style.setProperty("--memory-java-color", palette.info);
  }
  if (palette.success) {
    root.style.setProperty("--memory-pss-color", palette.success);
  }
  if (palette.accent) {
    root.style.setProperty("--memory-graphics-color", palette.accent);
  }

  if (font.family) {
    root.style.setProperty("--font-family", `"${String(font.family).replace(/"/g, '\\"')}", "Segoe UI", Arial, sans-serif`);
  }
  if (Number.isFinite(Number(font.uiSize))) {
    const size = Math.max(8, Math.min(24, Number(font.uiSize)));
    root.style.setProperty("--font-size", `${size}px`);
    root.style.setProperty("--label-size", `${Math.max(8, size - 1)}px`);
    root.style.setProperty("--header-size", `${size}px`);
  }
  if (Number.isFinite(Number(font.labelSize))) {
    const size = Math.max(8, Math.min(22, Number(font.labelSize)));
    root.style.setProperty("--label-size", `${size}px`);
  }
  if (Number.isFinite(Number(font.headerSize))) {
    const size = Math.max(8, Math.min(24, Number(font.headerSize)));
    root.style.setProperty("--header-size", `${size}px`);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderControls() {
  const collecting = String(state.state || "").toLowerCase().startsWith("collecting");
  statusText.textContent = collecting ? String(state.state).replace(/^Collecting\s*/i, "") || "00:00" : "00:00";
  if (document.activeElement !== packageInput) {
    packageInput.value = state.packageName || "";
  }
  if (document.activeElement !== activityInput) {
    activityInput.value = state.activity || "";
  }
  const controls = state.controls || {};
  for (const button of actionButtons) {
    const action = button.dataset.action;
    let enabled = true;
    if (action === "currentPackage") enabled = controls.current !== false;
    if (action === "quickCheck") enabled = controls.quick !== false;
    if (action === "startMonitor") enabled = controls.start !== false;
    if (action === "stopMonitor") enabled = controls.stop === true;
    if (action === "mark") enabled = controls.mark === true;
    if (action === "openReport") enabled = controls.openReport === true;
    if (action === "exportReport") enabled = controls.export === true;
    if (action === "openPerfetto") enabled = true;
    if (action === "refreshDeviceInfo") enabled = true;
    button.disabled = !enabled;
  }
}

function renderDeviceTable() {
  const rows = Array.isArray(state.deviceInfo) ? state.deviceInfo : [];
  deviceTable.innerHTML = rows.map(row => `
    <div class="info-row">
      <div class="info-key">${escapeHtml(row.info)}</div>
      <div class="info-value">${escapeHtml(row.value || "unavailable")}</div>
    </div>
  `).join("");
}

function formatMetricValue(value, digits = 1, unit = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  const rendered = formatNumber(number, digits);
  return `${rendered}${unit ? ` ${unit}` : ""}`;
}

function statusTone(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("collecting") || text.includes("monitor") || text.includes("running")) return "running";
  if (text.includes("analyzing") || text.includes("quick")) return "analyzing";
  if (text.includes("warn")) return "warn";
  if (text.includes("fail") || text.includes("error") || text.includes("offline")) return "bad";
  if (text.includes("ready") || text.includes("pass") || text.includes("online")) return "good";
  return "idle";
}

function renderTopStatus() {
  const points = Array.isArray(state.points) ? state.points : [];
  const report = state.reportSummary || {};
  const runState = state.state || "Idle";
  runStateValue.textContent = runState;
  runStateValue.dataset.tone = statusTone(runState);
  packageValue.textContent = state.packageName || state.currentPackage || "--";
  sampleCountValue.textContent = String(points.length);
  reportStatusValue.textContent = report.status || "--";
  reportStatusValue.dataset.tone = statusTone(report.status || "");
}

function renderLiveSummary() {
  const summaries = Array.isArray(state.metricSummaries) ? state.metricSummaries : [];
  if (!summaryList) return;
  if (!summaries.length) {
    summaryList.innerHTML = '<div class="empty-text">Waiting for samples</div>';
    return;
  }
  summaryList.innerHTML = summaries.map(item => `
    <div class="summary-row">
      <div class="summary-name" title="${escapeHtml(item.label)}">
        <span class="summary-dot" style="background:${escapeHtml(item.color || "var(--accent)")};"></span>
        <span>${escapeHtml(item.label)}</span>
      </div>
      <div class="summary-cell"><span>now</span><strong>${escapeHtml(formatMetricValue(item.now, item.digits, item.unit))}</strong></div>
      <div class="summary-cell"><span>avg</span><strong>${escapeHtml(formatMetricValue(item.avg, item.digits, item.unit))}</strong></div>
      <div class="summary-cell"><span>max</span><strong>${escapeHtml(formatMetricValue(item.max, item.digits, item.unit))}</strong></div>
    </div>
  `).join("");
}

function renderInspector() {
  renderEvents();
  renderMetricDetails();
  renderReportSummary();
}

function renderEvents() {
  if (!eventList) return;
  const events = Array.isArray(state.events) ? state.events.slice(-160) : [];
  if (!events.length) {
    eventList.innerHTML = '<div class="empty-text">No events yet</div>';
    return;
  }
  eventList.innerHTML = events.map(entry => {
    const text = String(entry || "");
    const match = text.match(/^(\d{2}:\d{2}:\d{2})\s+(.*)$/);
    const time = match ? match[1] : "";
    const message = match ? match[2] : text;
    return `
      <div class="event-row">
        <div class="event-time">${escapeHtml(time)}</div>
        <div class="event-text" title="${escapeHtml(message)}">${escapeHtml(message)}</div>
      </div>
    `;
  }).join("");
}

function renderMetricDetails() {
  if (!metricDetailList) return;
  const groups = Array.isArray(state.metricDetails) ? state.metricDetails : [];
  if (!groups.length) {
    metricDetailList.innerHTML = '<div class="empty-text">Waiting for metric details</div>';
    return;
  }
  metricDetailList.innerHTML = groups.map(group => `
    <section class="metric-detail-group">
      <div class="metric-detail-title">${escapeHtml(group.group || "Metrics")}</div>
      ${(Array.isArray(group.items) ? group.items : []).map(item => {
        const value = String(item.value ?? "--");
        const unit = item.unit && value !== "--" ? ` ${item.unit}` : "";
        return `
          <div class="metric-detail-row">
            <span title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
            <strong title="${escapeHtml(value)}${escapeHtml(unit)}">${escapeHtml(value)}${escapeHtml(unit)}</strong>
          </div>
        `;
      }).join("")}
    </section>
  `).join("");
}

function renderReportSummary() {
  if (!reportSummary) return;
  const report = state.reportSummary || {};
  const metrics = Array.isArray(report.metrics) ? report.metrics : [];
  const findings = Array.isArray(report.findings) ? report.findings : [];
  const rawReport = String(state.report || "").trim();
  if (!report.title && !metrics.length && !findings.length && !rawReport) {
    reportSummary.innerHTML = '<div class="empty-text">No report yet</div>';
    return;
  }
  reportSummary.innerHTML = `
    <div class="report-title">
      <span>${escapeHtml(report.title || "Report")}</span>
      <span class="report-status">${escapeHtml(report.status || "--")}</span>
    </div>
    <div class="report-metrics">
      ${metrics.map(item => `
        <div class="report-metric">
          <span>${escapeHtml(item.label)}</span>
          <strong title="${escapeHtml(item.value ?? "--")}">${escapeHtml(item.value ?? "--")}</strong>
        </div>
      `).join("")}
    </div>
    ${findings.map(item => `<div class="report-finding">${escapeHtml(item)}</div>`).join("")}
    ${rawReport ? `<pre class="report-raw">${escapeHtml(rawReport)}</pre>` : ""}
  `;
}

function numericValue(point, key) {
  const value = point && point[key];
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

function formatNumber(value, digits = 0) {
  if (!Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 1000) return `${Math.round(value).toLocaleString()}`;
  if (Math.abs(value) >= 100) return `${Math.round(value)}`;
  return value.toFixed(digits);
}

function formatTimeLabel(timestamp) {
  if (!Number.isFinite(timestamp)) return "";
  const date = new Date(timestamp);
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleTimeString([], { hour12: false, minute: "2-digit", second: "2-digit" });
  }
  return `${Math.round(timestamp / 1000)}s`;
}

function roundUpTick(value) {
  if (!Number.isFinite(value) || value <= 0) return 10;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function chartDefinitions() {
  return {
    fpsChart: {
      axisKey: "fpsChart",
      yLabel: "FPS",
      minMax: 60,
      unit: "",
      series: [
        { key: "fps", label: "FPS", color: cssColor("--fps-color", "#a855f7"), digits: 0 },
        { key: "jank", label: "Jank", color: cssColor("--jank-color", "#f59e0b"), digits: 0, unit: "%" },
        { key: "stutter_rate", label: "Stutter", color: cssColor("--stutter-color", "#38bdf8"), digits: 1, unit: "%" },
        { key: "frame_time_p95", label: "P95", color: cssColor("--frame-time-color", "#9aa4b4"), digits: 1, unit: " ms" }
      ]
    },
    cpuChart: {
      axisKey: "cpuChart",
      yLabel: "CPU %",
      minMax: 100,
      unit: "%",
      series: [
        { key: "cpu_app", label: "App", color: cssColor("--cpu-app-color", "#ff6b6b"), digits: 1, unit: "%" },
        { key: "cpu_user", label: "User", color: cssColor("--cpu-user-color", "#f59e0b"), digits: 1, unit: "%" },
        { key: "cpu_system", label: "System", color: cssColor("--cpu-system-color", "#38bdf8"), digits: 1, unit: "%" }
      ]
    },
    memoryChart: {
      axisKey: "memoryChart",
      yLabel: "Memory",
      minMax: 256,
      unit: " MB",
      series: [
        { key: "memory_pss", label: "PSS", color: cssColor("--memory-pss-color", "#3fb950"), digits: 1, unit: " MB" },
        { key: "memory_java", label: "Java Heap", color: cssColor("--memory-java-color", "#58a6ff"), digits: 1, unit: " MB" },
        { key: "memory_native", label: "Native", color: cssColor("--memory-native-color", "#f59e0b"), digits: 1, unit: " MB" },
        { key: "memory_graphics", label: "Graphics", color: cssColor("--memory-graphics-color", "#4cc38a"), digits: 1, unit: " MB" },
        { key: "memory_swap", label: "Swap", color: cssColor("--memory-swap-color", "#f59e0b"), digits: 1, unit: " MB" }
      ]
    }
  };
}

function pointsForSeries(points, series) {
  return series.map(item => {
    let lastValue = null;
    return {
      ...item,
      values: points.map(point => {
        const value = numericValue(point, item.key);
        if (value !== null) {
          lastValue = value;
        }
        return lastValue;
      })
    };
  });
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}

function chartPlot(width, height, fontSize) {
  const plot = {
    left: Math.max(58, fontSize * 4.8),
    top: height < 100 ? 10 : 16,
    right: Math.max(96, width - 18),
    bottom: Math.max(44, height - (height < 100 ? 24 : 34))
  };
  plot.width = Math.max(1, plot.right - plot.left);
  plot.height = Math.max(1, plot.bottom - plot.top);
  return plot;
}

function hoverRatioForCanvas(canvas, x) {
  const rect = canvas.getBoundingClientRect();
  const fontSize = Math.max(10, parseInt(cssColor("--font-size", "12px"), 10) || 12);
  const plot = chartPlot(rect.width, rect.height, fontSize);
  return Math.max(0, Math.min(1, (x - plot.left) / plot.width));
}

function pointPosition(plot, point, index, count, minTime, timeSpan, yMax, value) {
  const timestamp = numericValue(point, "_ts");
  const ratio = timestamp === null ? index / Math.max(1, count - 1) : (timestamp - minTime) / timeSpan;
  const x = plot.left + Math.max(0, Math.min(1, ratio)) * plot.width;
  const y = plot.bottom - Math.max(0, Math.min(1, value / yMax)) * plot.height;
  return { x, y };
}

function drawTimelineMarkers(ctx, plot, minTime, timeSpan, fontSize, showLabels = false) {
  const markers = Array.isArray(state.markers) ? state.markers : [];
  if (!markers.length) return;
  const markerColor = cssColor("--warn", "#f59e0b");
  ctx.save();
  ctx.strokeStyle = markerColor;
  ctx.fillStyle = markerColor;
  ctx.lineWidth = 1;
  ctx.font = `${Math.max(9, fontSize - 1)}px ${cssColor("--font-family", "Segoe UI")}`;
  ctx.textBaseline = "top";
  for (const marker of markers.slice(-12)) {
    const timestamp = Number(marker.timestamp_ms);
    if (!Number.isFinite(timestamp)) continue;
    const ratio = (timestamp - minTime) / timeSpan;
    if (ratio < 0 || ratio > 1) continue;
    const x = plot.left + ratio * plot.width;
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    if (showLabels && plot.height >= 84) {
      const label = fitText(ctx, marker.label || "Mark", 84);
      ctx.fillText(label, Math.min(x + 4, plot.right - 86), plot.top + 3);
    }
  }
  ctx.restore();
}

function yAxisMax(definition, numeric) {
  const policies = state.axisPolicy || {};
  const policy = policies[definition.axisKey] || {};
  const floorMax = Number.isFinite(Number(policy.max)) ? Number(policy.max) : (definition.minMax || 10);
  const dataMax = Math.max(...numeric, 0);
  if (policy.padded === false) {
    return stableAxisMax(definition.axisKey, floorMax, dataMax);
  }
  return roundUpTick(Math.max(floorMax, dataMax) * 1.08);
}

function stableAxisMax(axisKey, floorMax, dataMax) {
  if (!Number.isFinite(dataMax) || dataMax <= floorMax) {
    return floorMax;
  }
  if (axisKey === "fpsChart") {
    const stops = [60, 90, 120, 144, 165, 240];
    return stops.find(stop => dataMax <= stop) || roundUpTick(dataMax);
  }
  return roundUpTick(dataMax);
}

function drawLegendSample(ctx, x, y, series) {
  ctx.strokeStyle = series.color;
  ctx.lineWidth = 2.4;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x - 5, y);
  ctx.lineTo(x + 8, y);
  ctx.stroke();
}

function fitText(ctx, text, maxWidth) {
  const value = String(text);
  if (ctx.measureText(value).width <= maxWidth) return value;
  let shortened = value;
  while (shortened.length > 1 && ctx.measureText(`${shortened}...`).width > maxWidth) {
    shortened = shortened.slice(0, -1);
  }
  return `${shortened}...`;
}

function drawSeries(ctx, plot, points, series, minTime, timeSpan, yMax) {
  ctx.strokeStyle = series.color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  let hasLine = false;
  for (let index = 0; index < points.length; index += 1) {
    const value = series.values[index];
    if (value === null) {
      hasLine = false;
      continue;
    }
    const point = pointPosition(plot, points[index], index, points.length, minTime, timeSpan, yMax, value);
    if (!hasLine) {
      ctx.moveTo(point.x, point.y);
      hasLine = true;
    } else {
      ctx.lineTo(point.x, point.y);
    }
  }
  ctx.stroke();
}

function drawLegend(ctx, plot, seriesList, fontSize) {
  const axis = cssColor("--chart-axis", "rgba(255,255,255,0.82)");
  ctx.font = `${fontSize}px ${cssColor("--font-family", "Segoe UI")}`;
  ctx.textBaseline = "middle";
  const available = Math.max(70, plot.width - 16);
  const maxWidth = Math.min(available, Math.max(78, ...seriesList.map(series => ctx.measureText(series.label).width + 20)));
  const left = Math.max(plot.left + 8, plot.right - maxWidth - 8);
  let y = plot.top + 10;
  for (const series of seriesList) {
    drawLegendSample(ctx, left + 5, y, series);
    ctx.fillStyle = axis;
    ctx.textAlign = "left";
    ctx.fillText(fitText(ctx, series.label, maxWidth - 20), left + 16, y);
    y += fontSize + 5;
  }
}

function roundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawCrosshair(ctx, canvas, plot, points, seriesList, minTime, timeSpan, yMax, fontSize) {
  if (!sharedHover || !sharedHover.inside || !points.length) return;
  const xRatio = Math.max(0, Math.min(1, sharedHover.xRatio));
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < points.length; index += 1) {
    const timestamp = numericValue(points[index], "_ts");
    const ratio = timestamp === null ? index / Math.max(1, points.length - 1) : (timestamp - minTime) / timeSpan;
    const distance = Math.abs(ratio - xRatio);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  }

  const timestamp = numericValue(points[nearestIndex], "_ts");
  const sampleTime = timestamp === null ? minTime + xRatio * timeSpan : timestamp;
  const x = pointPosition(plot, points[nearestIndex], nearestIndex, points.length, minTime, timeSpan, yMax, 0).x;

  ctx.save();
  ctx.strokeStyle = cssColor("--chart-crosshair", "rgba(255,255,255,0.86)");
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, plot.top);
  ctx.lineTo(x, plot.bottom);
  ctx.stroke();
  ctx.setLineDash([]);

  if (canvas.id !== sharedHover.sourceId) {
    ctx.restore();
    return;
  }

  const rows = [{ label: formatTimeLabel(sampleTime), color: cssColor("--chart-tooltip-text", "#fff"), value: "" }];
  for (const series of seriesList) {
    const value = series.values[nearestIndex];
    if (value === null) continue;
    const unit = series.unit ?? "";
    rows.push({
      label: series.label,
      color: series.color,
      value: `${formatNumber(value, series.digits ?? 1)}${unit}`
    });
  }
  if (rows.length <= 1) {
    ctx.restore();
    return;
  }

  ctx.font = `${fontSize}px ${cssColor("--font-family", "Segoe UI")}`;
  const labelWidth = Math.max(...rows.map(row => ctx.measureText(row.label).width));
  const valueWidth = Math.max(...rows.map(row => ctx.measureText(row.value).width));
  const boxWidth = Math.min(plot.width - 16, Math.max(150, labelWidth + valueWidth + 34));
  const rowHeight = fontSize + 6;
  const boxHeight = rows.length * rowHeight + 12;
  let boxX = x + 12;
  if (boxX + boxWidth > plot.right - 4) boxX = x - boxWidth - 12;
  boxX = Math.max(plot.left + 4, Math.min(plot.right - boxWidth - 4, boxX));
  const boxY = Math.max(plot.top + 4, Math.min(plot.bottom - boxHeight - 4, sharedHover.y - boxHeight / 2));

  ctx.fillStyle = cssColor("--chart-tooltip", "rgba(17,20,26,0.94)");
  ctx.strokeStyle = cssColor("--border", "rgba(255,255,255,0.2)");
  ctx.lineWidth = 1;
  roundRect(ctx, boxX, boxY, boxWidth, boxHeight, 6);
  ctx.fill();
  ctx.stroke();

  ctx.textBaseline = "middle";
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    const y = boxY + 10 + rowHeight * index + rowHeight / 2;
    ctx.fillStyle = index === 0 ? cssColor("--chart-tooltip-text", "#fff") : row.color;
    ctx.textAlign = "left";
    ctx.fillText(fitText(ctx, row.label, boxWidth - valueWidth - 28), boxX + 10, y);
    if (row.value) {
      ctx.textAlign = "right";
      ctx.fillStyle = cssColor("--chart-tooltip-text", "#fff");
      ctx.fillText(row.value, boxX + boxWidth - 10, y);
    }
  }
  ctx.restore();
}

function renderMetricChart(canvas, definition) {
  if (!canvas || !definition) return;
  const { ctx, width, height } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  const bg = cssColor("--chart-bg", "#141720");
  const grid = cssColor("--chart-grid", "rgba(255,255,255,0.18)");
  const axis = cssColor("--chart-axis", "rgba(255,255,255,0.82)");
  const fontSize = Math.max(10, parseInt(cssColor("--font-size", "12px"), 10) || 12);
  const fontFamily = cssColor("--font-family", "Segoe UI");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const plot = chartPlot(width, height, fontSize);

  const points = Array.isArray(state.points) ? state.points : [];
  const seriesList = pointsForSeries(points, definition.series);
  const numeric = seriesList.flatMap(series => series.values.filter(value => value !== null));
  const yMax = yAxisMax(definition, numeric);
  const times = points.map(point => numericValue(point, "_ts")).filter(value => value !== null);
  const minTime = times.length ? Math.min(...times) : 0;
  const maxTime = times.length ? Math.max(...times) : Math.max(points.length - 1, 1) * 1000;
  const timeSpan = Math.max(1, maxTime - minTime);

  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = axis;
  ctx.font = `${fontSize}px ${fontFamily}`;
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (let tick = 0; tick <= 4; tick += 1) {
    const ratio = tick / 4;
    const y = plot.bottom - ratio * plot.height;
    const value = yMax * ratio;
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.fillText(formatNumber(value), plot.left - 8, y);
  }

  ctx.strokeStyle = axis;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.bottom);
  ctx.lineTo(plot.right, plot.bottom);
  ctx.stroke();

  ctx.save();
  ctx.translate(17, plot.top + plot.height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = axis;
  ctx.fillText(definition.yLabel, 0, 0);
  ctx.restore();

  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const labelTicks = [0, 0.5, 1];
  for (const ratio of labelTicks) {
    const x = plot.left + ratio * plot.width;
    ctx.strokeStyle = grid;
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    const labelTime = minTime + ratio * timeSpan;
    ctx.fillStyle = axis;
    ctx.fillText(formatTimeLabel(labelTime), x, plot.bottom + 8);
  }

  for (const series of seriesList) {
    drawSeries(ctx, plot, points, series, minTime, timeSpan, yMax);
  }
  drawTimelineMarkers(ctx, plot, minTime, timeSpan, fontSize, definition.axisKey === "fpsChart");
  if (height >= 92) {
    drawLegend(ctx, plot, seriesList, fontSize);
  }
  drawCrosshair(ctx, canvas, plot, points, seriesList, minTime, timeSpan, yMax, fontSize);

  if (!numeric.length) {
    ctx.fillStyle = cssColor("--muted", "#9aa4b4");
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`Waiting for ${definition.yLabel} samples`, plot.left + plot.width / 2, plot.top + plot.height / 2);
  }
}

function renderCharts() {
  const definitions = chartDefinitions();
  for (const canvas of chartCanvases) {
    renderMetricChart(canvas, definitions[canvas.id]);
  }
}

function renderTabs(activeTab) {
  for (const tab of tabs) {
    tab.classList.toggle("active", tab.dataset.tab === activeTab);
  }
  for (const panel of panels) {
    panel.classList.toggle("active", panel.id === `${activeTab}Panel`);
  }
}

function renderInspectorTab(activeTab) {
  const tabName = ["events", "metrics", "report"].includes(activeTab) ? activeTab : "events";
  for (const tab of inspectorTabs) {
    tab.classList.toggle("active", tab.dataset.inspectorTab === tabName);
  }
  for (const panel of inspectorBodies) {
    panel.classList.toggle("active", panel.id === `${tabName}Inspector`);
  }
  if (workspacePanel) {
    workspacePanel.classList.remove("inspector-mode-events", "inspector-mode-metrics", "inspector-mode-report");
    workspacePanel.classList.add(`inspector-mode-${tabName}`);
  }
  requestAnimationFrame(renderCharts);
}

function toggleInspector() {
  if (!workspacePanel || !inspectorToggle) return;
  const collapsed = !workspacePanel.classList.contains("inspector-collapsed");
  workspacePanel.classList.toggle("inspector-collapsed", collapsed);
  inspectorToggle.textContent = collapsed ? "Expand" : "Collapse";
  inspectorToggle.setAttribute("aria-pressed", collapsed ? "true" : "false");
  requestAnimationFrame(renderCharts);
}

function toggleSidePanel() {
  if (!shell || !sideToggle) return;
  const collapsed = !shell.classList.contains("side-collapsed");
  shell.classList.toggle("side-collapsed", collapsed);
  sideToggle.textContent = collapsed ? "\u203a" : "\u2039";
  sideToggle.setAttribute("aria-pressed", collapsed ? "true" : "false");
  requestAnimationFrame(renderCharts);
}

function requestAction(action, payload = {}) {
  if (!bridge || !bridge.requestAction) return;
  bridge.requestAction(action, JSON.stringify(payload));
}

function commitTargetInput(action, input) {
  requestAction(action, { value: input.value.trim() });
}

function buildPreviewPayload() {
  const now = Date.now();
  return {
    state: "Preview",
    currentPackage: "com.example.shopping",
    packageName: "com.example.shopping",
    activity: "com.example.shopping/.MainActivity",
    controls: { current: true, quick: true, start: true, stop: false, openReport: true, export: true },
    theme: root.dataset.theme === "light" ? "Light" : "Dark",
    palette: {},
    font: { family: "Segoe UI", uiSize: 12 },
    events: [
      "14:31:10 Preview data loaded",
      "14:31:20 Target package set to com.example.shopping",
      "14:32:04 Monitor started",
      "14:33:11 Mark 1: Scroll list",
      "14:34:25 Monitor report ready"
    ],
    report: "Preview Monitor: WARN",
    reportSummary: {
      title: "Preview Monitor",
      status: "warn",
      metrics: [
        { label: "FPS", value: "56.8" },
        { label: "Jank", value: "8.30%" },
        { label: "Stutter", value: "1.60%" },
        { label: "P95", value: "24.6 ms" },
        { label: "CPU", value: "26.0%" },
        { label: "PSS", value: "345 MB" }
      ],
      findings: ["Jank rose during the scroll segment."]
    },
    points: [
      { _ts: now - 5000, fps: 58, jank: 2, stutter: 0, stutter_rate: 0, frame_time_p95: 18.4, cpu_app: 21, cpu_user: 16, cpu_system: 5, cpu_fg: 21, cpu_bg: 0, memory_pss: 326, memory_java: 148, memory_native: 92, memory_graphics: 42, memory_swap: 3 },
      { _ts: now - 4000, fps: 60, jank: 1, stutter: 0, stutter_rate: 0, frame_time_p95: 16.8, cpu_app: 24, cpu_user: 18, cpu_system: 6, cpu_fg: 24, cpu_bg: 0, memory_pss: 332, memory_java: 151, memory_native: 94, memory_graphics: 43, memory_swap: 3 },
      { _ts: now - 3000, fps: 55, jank: 5, stutter: 1, stutter_rate: 1.7, frame_time_p95: 27.4, cpu_app: 37, cpu_user: 28, cpu_system: 9, cpu_fg: 37, cpu_bg: 0, memory_pss: 337, memory_java: 153, memory_native: 95, memory_graphics: 45, memory_swap: 4 },
      { _ts: now - 2000, fps: 59, jank: 3, stutter: 0, stutter_rate: 0, frame_time_p95: 21.1, cpu_app: 29, cpu_user: 22, cpu_system: 7, cpu_fg: 29, cpu_bg: 0, memory_pss: 339, memory_java: 154, memory_native: 96, memory_graphics: 45, memory_swap: 4 },
      { _ts: now - 1000, fps: 57, jank: 4, stutter: 0, stutter_rate: 0, frame_time_p95: 24.6, cpu_app: 31, cpu_user: 24, cpu_system: 7, cpu_fg: 31, cpu_bg: 0, memory_pss: 342, memory_java: 157, memory_native: 97, memory_graphics: 46, memory_swap: 4 },
      { _ts: now, fps: 60, jank: 1, stutter: 0, stutter_rate: 0, frame_time_p95: 17.2, cpu_app: 26, cpu_user: 20, cpu_system: 6, cpu_fg: 26, cpu_bg: 0, memory_pss: 345, memory_java: 158, memory_native: 98, memory_graphics: 47, memory_swap: 5 }
    ],
    markers: [
      { timestamp_ms: now - 3600, label: "Open page" },
      { timestamp_ms: now - 2100, label: "Scroll list" },
      { timestamp_ms: now - 900, label: "Start video" }
    ],
    metricSummaries: [
      { metric: "fps", label: "FPS", unit: "", digits: 1, color: "#4cc38a", now: 60, avg: 58.2, max: 60, count: 6 },
      { metric: "jank", label: "Jank", unit: "%", digits: 1, color: "#f59e0b", now: 1, avg: 2.8, max: 5, count: 6 },
      { metric: "stutter_rate", label: "Stutter", unit: "%", digits: 1, color: "#38bdf8", now: 0, avg: 0.3, max: 1.7, count: 6 },
      { metric: "frame_time_p95", label: "P95", unit: "ms", digits: 1, color: "#9aa4b4", now: 17.2, avg: 20.9, max: 27.4, count: 6 },
      { metric: "cpu_app", label: "CPU", unit: "%", digits: 1, color: "#ff6b6b", now: 26, avg: 28.2, max: 37, count: 6 },
      { metric: "cpu_user", label: "User", unit: "%", digits: 1, color: "#f59e0b", now: 20, avg: 21.3, max: 28, count: 6 },
      { metric: "cpu_system", label: "System", unit: "%", digits: 1, color: "#38bdf8", now: 6, avg: 6.7, max: 9, count: 6 },
      { metric: "memory_pss", label: "PSS", unit: "MB", digits: 1, color: "#3fb950", now: 345, avg: 336.8, max: 345, count: 6 },
      { metric: "memory_java", label: "Java", unit: "MB", digits: 1, color: "#58a6ff", now: 158, avg: 153.8, max: 158, count: 6 },
      { metric: "memory_native", label: "Native", unit: "MB", digits: 1, color: "#f59e0b", now: 98, avg: 95.3, max: 98, count: 6 },
      { metric: "memory_graphics", label: "Graphics", unit: "MB", digits: 1, color: "#4cc38a", now: 47, avg: 44.7, max: 47, count: 6 },
      { metric: "memory_swap", label: "Swap", unit: "MB", digits: 1, color: "#f59e0b", now: 5, avg: 3.8, max: 5, count: 6 }
    ],
    metricDetails: [
      { group: "Frame", items: [
        { label: "FPS", value: "60.0", unit: "" },
        { label: "Jank", value: "1.0", unit: "%" },
        { label: "Stutter", value: "0.0", unit: "%" },
        { label: "P95", value: "17.2", unit: "ms" }
      ] },
      { group: "CPU", items: [
        { label: "App", value: "26.0", unit: "%" },
        { label: "User", value: "20.0", unit: "%" },
        { label: "System", value: "6.0", unit: "%" },
        { label: "Threads", value: "42", unit: "" }
      ] },
      { group: "Memory", items: [
        { label: "PSS", value: "345.0", unit: "MB" },
        { label: "Java", value: "158.0", unit: "MB" },
        { label: "Native", value: "98.0", unit: "MB" },
        { label: "Graphics", value: "47.0", unit: "MB" },
        { label: "Swap", value: "5.0", unit: "MB" }
      ] },
      { group: "Objects", items: [
        { label: "Activities", value: "1", unit: "" },
        { label: "Views", value: "98", unit: "" }
      ] }
    ],
    axisPolicy: {
      fpsChart: { min: 0, max: 60, padded: false },
      cpuChart: { min: 0, max: 100, padded: false },
      memoryChart: { min: 0, max: 256, padded: true }
    },
    deviceInfo: [
      { info: "Device Name", value: "Pixel Preview" },
      { info: "Device Type", value: "Pixel 8 Pro" },
      { info: "OS", value: "Android 15" },
      { info: "CPU Type", value: "Tensor" },
      { info: "CPU Info", value: "Google Tensor G3" },
      { info: "CPU Arch", value: "arm64-v8a" },
      { info: "CPU CoreNum", value: "9" },
      { info: "CPU Freq", value: "little: 300-1704 MHz\nmiddle: 300-2367 MHz\nbig: 300-2914 MHz" },
      { info: "GPU Type", value: "ARM Mali-G715" },
      { info: "OpenGL", value: "OpenGL ES 3.2\nBuild preview" },
      { info: "GPU Freq", value: "unavailable" },
      { info: "Ram Size", value: "12.0 GB" },
      { info: "Swap", value: "2048 MB" },
      { info: "Root", value: "No" },
      { info: "SerialNum", value: "emulator-5554" }
    ]
  };
}

window.renderPerformanceTimeline = function(payload) {
  applyTheme(payload || {});
  state = payload || state;
  renderTopStatus();
  renderControls();
  renderLiveSummary();
  renderDeviceTable();
  renderInspector();
  renderCharts();
};

packageInput.addEventListener("change", () => commitTargetInput("setPackage", packageInput));
activityInput.addEventListener("change", () => commitTargetInput("setActivity", activityInput));
packageInput.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    commitTargetInput("setPackage", packageInput);
    packageInput.blur();
  }
});
activityInput.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    commitTargetInput("setActivity", activityInput);
    activityInput.blur();
  }
});

for (const canvas of chartCanvases) {
  canvas.addEventListener("mousemove", event => {
    const rect = canvas.getBoundingClientRect();
    sharedHover = {
      inside: true,
      sourceId: canvas.id,
      xRatio: hoverRatioForCanvas(canvas, event.clientX - rect.left),
      y: event.clientY - rect.top
    };
    renderCharts();
  });
  canvas.addEventListener("mouseleave", () => {
    sharedHover = null;
    renderCharts();
  });
}

document.addEventListener("click", event => {
  if (event.target.closest("#sideToggle")) {
    toggleSidePanel();
    return;
  }
  if (event.target.closest("#inspectorToggle")) {
    toggleInspector();
    return;
  }
  const inspectorTab = event.target.closest("[data-inspector-tab]");
  if (inspectorTab) {
    renderInspectorTab(inspectorTab.dataset.inspectorTab || "events");
    return;
  }
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    renderTabs(tab.dataset.tab || "setting");
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  requestAction(button.dataset.action, {});
});

function connectQtBridge() {
  if (!window.qt || !window.qt.webChannelTransport) {
    window.renderPerformanceTimeline(buildPreviewPayload());
    return;
  }
  const script = document.createElement("script");
  script.src = "qrc:///qtwebchannel/qwebchannel.js";
  script.onload = () => {
    if (!window.QWebChannel) {
      window.renderPerformanceTimeline(buildPreviewPayload());
      return;
    }
    new QWebChannel(qt.webChannelTransport, channel => {
      bridge = channel.objects.performanceBridge;
    });
  };
  script.onerror = () => window.renderPerformanceTimeline(buildPreviewPayload());
  document.head.appendChild(script);
}

renderTabs("setting");
renderInspectorTab("events");
connectQtBridge();
window.addEventListener("resize", renderCharts);

window.__performanceDashboard = {
  applyTheme,
  buildPreviewPayload,
  renderInspector,
  renderLiveSummary,
  renderMetricChart,
  renderCharts,
  stableAxisMax,
  yAxisMax,
  toggleSidePanel
};
