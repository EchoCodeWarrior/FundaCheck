const state = {
  data: null,
  page: "dashboard",
  theme: localStorage.getItem("fundacheck-theme") || "light",
  ratioTab: "Overview",
  statementTab: "Income Statement",
  statementQuery: "",
  latestAnswer: null,
  history: JSON.parse(localStorage.getItem("fundacheck-history") || "[]"),
  sidebarCollapsed: localStorage.getItem("fundacheck-sidebar-collapsed") === "true",
};

const $ = (selector, root = document) => root.querySelector(selector);

const ICON_PATHS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  chart: '<path d="M4 19V11M10 19V6M16 19v-9M22 19H2"/><path d="m4 8 5-4 5 3 6-5"/>',
  pie: '<path d="M12 2a10 10 0 1 0 10 10h-10Z"/><path d="M12 2v10h10A10 10 0 0 0 12 2Z"/>',
  file: '<path d="M6 2h8l5 5v15H6z"/><path d="M14 2v6h5M9 13h6M9 17h6"/>',
  message: '<path d="M20 11.5a8 8 0 0 1-8 8H7l-4 3v-7.2a8 8 0 1 1 17-3.8Z"/><path d="M8 11h.01M12 11h.01M16 11h.01"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"/>',
  moon: '<path d="M20.5 15.4A8.5 8.5 0 0 1 8.6 3.5 8.5 8.5 0 1 0 20.5 15.4Z"/>',
  "chevron-left": '<path d="m15 18-6-6 6-6"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 15v5h16v-5"/>',
  spreadsheet: '<path d="M6 2h9l4 4v16H6z"/><path d="M15 2v5h4M9 11h6M9 15h6M9 19h3"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  trend: '<path d="M4 17 10 11l4 3 6-8"/><path d="M15 6h5v5"/>',
  shield: '<path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/>',
  scale: '<path d="M12 4v16M7 4h10M5 8l-3 6a3 3 0 0 0 6 0Zm14 0-3 6a3 3 0 0 0 6 0Z"/><path d="M8 20h8"/>',
  cash: '<rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 9h.01M18 15h.01"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>',
  star: '<path d="m12 3 2.8 5.6 6.2.9-4.5 4.4 1.1 6.1-5.6-2.9-5.6 2.9 1.1-6.1L3 9.5l6.2-.9Z"/>',
  warning: '<path d="m12 3 9 17H3Z"/><path d="M12 9v4M12 17h.01"/>',
  spark: '<path d="m12 3 1.5 6.5L20 11l-6.5 1.5L12 19l-1.5-6.5L4 11l6.5-1.5Z"/><path d="m19 3 .5 2L21 5.5 19.5 6 19 8l-.5-2-1.5-.5 1.5-.5Z"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6H4V5h6"/>',
  users: '<path d="M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20M9.5 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM17 3.7a3.5 3.5 0 0 1 0 6.8M21 20v-1.5a4 4 0 0 0-3-3.9"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
  "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
};

function icon(name, className = "icon") {
  const path = ICON_PATHS[name] || ICON_PATHS.info;
  return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value, digits = 0) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const digits = Math.abs(Number(value)) < 1000 && !Number.isInteger(Number(value)) ? 1 : 0;
  return `₹${number(value, digits)}`;
}

function pct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const raw = Number(value);
  const normalized = Math.abs(raw) <= 2 ? raw * 100 : raw;
  return `${number(normalized, digits)}%`;
}

function ratio(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${number(value, digits)}x`;
}

function metricBy(data, ...names) {
  return data?.metrics?.find((metric) => names.includes(metric.metric)) || null;
}

function metricText(metric, fallback = "—") {
  return metric?.displayLatest || fallback;
}

function metricValue(metric, fallback = "—") {
  if (!metric) return fallback;
  return metricText(metric, fallback);
}

function displaySeriesValue(value, kind = "number") {
  if (kind === "percent") return pct(value);
  if (kind === "money") return money(value);
  return number(value, 1);
}

function showLoading(show, label = "Reading your financials") {
  const loading = $("#loading");
  if (!loading) return;
  loading.hidden = !show;
  const labelNode = $("#loading-label");
  if (labelNode) labelNode.textContent = label;
}

let toastTimer;
function toast(message) {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => node.classList.remove("is-visible"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Something went wrong. Please try again.");
  return payload;
}

function applyTheme() {
  document.body.dataset.theme = state.theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", state.theme === "dark" ? "#0a1610" : "#e9ece8");
}

function recentFiles() {
  try {
    return JSON.parse(localStorage.getItem("fundacheck-recent-files") || "[]");
  } catch {
    return [];
  }
}

function rememberFile(name) {
  const oldFiles = recentFiles().filter((item) => item.name !== name);
  oldFiles.unshift({ name, date: new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) });
  localStorage.setItem("fundacheck-recent-files", JSON.stringify(oldFiles.slice(0, 4)));
}

function datasetDisplay(sourceLabel) {
  const raw = String(sourceLabel || "Uploaded workbook").trim();
  const parts = raw.split(/\s*·\s*/);
  const isDemo = parts.length > 1;
  const fileName = (isDemo ? parts.slice(1).join(" · ") : raw) || "Uploaded workbook";
  const extension = fileName.includes(".") ? fileName.split(".").pop().toUpperCase() : "FILE";
  return {
    label: isDemo ? parts[0] : "Uploaded file",
    fileName,
    extension,
  };
}

function renderSidebar() {
  const dataNode = $("#sidebar-dataset");
  if (!dataNode) return;
  if (!state.data) {
    dataNode.hidden = true;
    dataNode.innerHTML = "";
    return;
  }
  dataNode.hidden = false;
  const source = datasetDisplay(state.data.sourceLabel);
  dataNode.innerHTML = `
    <div class="dataset-label">Data source</div>
    <div class="dataset-file" title="${escapeHTML(source.fileName)}">${icon("spreadsheet")}<span>${escapeHTML(state.data.sourceLabel)}</span></div>
    <div class="data-ready">Data ready</div>
    <div class="sidebar-dataset-actions">
      <button class="primary-button dataset-upload-button" type="button" data-action="open-upload" aria-label="Upload a new file">${icon("upload")}<span>Upload new file</span></button>
      <button class="secondary-button dataset-change-button" type="button" data-action="open-upload" aria-label="Change file">
        Change file
      </button>
    </div>`;
  hydrateIcons(dataNode);
}

function applySidebarState() {
  document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  const toggle = document.querySelector(".sidebar-collapse-toggle");
  if (!toggle) return;
  const label = state.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar";
  toggle.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  toggle.setAttribute("aria-label", label);
  const visibleLabel = toggle.querySelector(".sidebar-collapse-label");
  if (visibleLabel) visibleLabel.textContent = label;
  const srOnly = toggle.querySelector(".sr-only");
  if (srOnly) srOnly.textContent = label;
}

function syncShell() {
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.page === state.page);
  });
  const label = $("#topbar-label");
  if (label) label.textContent = state.data ? `${state.data.company} · ${state.data.latestYear}` : "New analysis";
  applySidebarState();
  renderSidebar();
  hydrateIcons(document);
}

function render() {
  applyTheme();
  const page = $("#page");
  if (!page) return;
  page.innerHTML = state.data ? renderCurrentPage() : renderEmptyState();
  hydrateIcons(page);
  syncShell();
}

function renderEmptyState() {
  const files = recentFiles();
  const rows = files.length
    ? files.map((file) => `
      <div class="recent-row">
        <div class="recent-file-name">${icon("spreadsheet")}<span>${escapeHTML(file.name)}</span></div>
        <span class="file-type">${escapeHTML(file.name.split(".").pop().toUpperCase())}</span>
        <span class="recent-date">${escapeHTML(file.date || "Recently")}</span>
        <button class="more-button" type="button" data-action="toast" data-toast="Choose the file again to run a fresh analysis." aria-label="Recent file options">⋮</button>
      </div>`).join("")
    : `<div class="recent-row"><div class="recent-file-name">${icon("file")}<span>No recent files in this browser yet.</span></div><span class="file-type">—</span><span class="recent-date">Upload to begin</span><button class="more-button" type="button" aria-hidden="true">·</button></div>`;

  return `
    <div class="upload-page">
      <div class="upload-heading">
        <div class="eyebrow">FUNDAMENTAL WORKSPACE · PRIVATE SESSION</div>
        <h1>Start your analysis</h1>
        <p>Upload your financial data to run a clear, sector-aware fundamental analysis.</p>
      </div>
      <div class="card upload-card">
        <div class="drop-zone" id="drop-zone" data-action="open-upload" role="button" tabindex="0" aria-label="Upload an XLSX, XLSM, or CSV file">
          <div class="upload-illustration">${icon("upload")}</div>
          <div class="drop-title">Drop an XLSX, XLSM, or CSV file here</div>
          <div class="drop-helper">Your file is parsed in memory for this session only.</div>
          <button class="primary-button" type="button" data-action="open-upload">${icon("upload")} Upload files</button>
          <div class="upload-divider"><span>or</span></div>
          <button class="browse-link" type="button" data-action="open-upload">Browse from your computer</button>
        </div>
        <button class="demo-link" type="button" data-action="load-demo">${icon("trend")} Use demo data</button>
      </div>
      <div class="card recent-files">
        <div class="card-heading"><h2>Recent files</h2><span class="soft-chip">Browser only</span></div>
        ${rows}
      </div>
    </div>`;
}

function pageHeader(title, subtitle, actions = "", eyebrow = "FUNDAMENTAL ANALYSIS") {
  return `
    <div class="page-heading">
      <div class="page-heading-main">
        <div class="eyebrow">${escapeHTML(eyebrow)}</div>
        <h1>${escapeHTML(title)}</h1>
        <p>${escapeHTML(subtitle)}</p>
      </div>
      <div class="page-heading-actions">${actions}</div>
    </div>`;
}

function headerControls(data, options = {}) {
  const {
    upload = true,
    exportReport = true,
    sector = false,
  } = options;
  const sectors = data.availableSectors || [];
  const sectorControl = sector
    ? `<select class="select-control" data-action="change-sector" aria-label="Choose sector">${sectors.map((item) => `<option value="${escapeHTML(item.key)}" ${item.key === data.sector.key ? "selected" : ""}>${escapeHTML(item.name)}</option>`).join("")}</select>`
    : "";
  return `${sectorControl}
    <span class="control">${icon("file")} ${escapeHTML(data.company)}</span>
    <span class="control">${icon("clock")} ${escapeHTML(data.latestYear || "Latest")}</span>
    ${upload ? `<button class="outline-button" type="button" data-action="open-upload">${icon("upload")} Upload files</button>` : ""}
    ${exportReport ? `<button class="primary-button" type="button" data-action="export-report">${icon("download")} Export</button>` : ""}`;
}

function scoreRing(score) {
  const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
  return `<div class="score-ring" style="--score:${safeScore}"><span class="score-ring-value">${number(safeScore)}</span></div>`;
}

function kpiCard(label, valueHTML, footHTML, iconName, extraClass = "") {
  return `<article class="card kpi-card ${extraClass}">
    <div class="kpi-top"><span class="kpi-label">${label}</span><span class="kpi-icon">${icon(iconName)}</span></div>
    <div class="kpi-value">${valueHTML}</div>
    <div class="kpi-foot">${footHTML}</div>
  </article>`;
}

function scoreKpi(data) {
  const score = data.score.total;
  return `<article class="card kpi-card score-kpi">
    <div class="kpi-top"><span class="kpi-label">Fundamental health</span><span class="kpi-icon">${icon("shield")}</span></div>
    <div class="score-layout">${scoreRing(score)}<div class="score-copy"><div class="kpi-value">${number(score)}<small>/ 100</small></div><div class="kpi-foot"><strong>${escapeHTML(data.score.headline.replace("Fundamentally ", ""))}</strong></div></div></div>
  </article>`;
}

function dashboardKpis(data) {
  const revenueGrowth = metricBy(data, "Sales Growth");
  const roce = data.kpis.roce;
  const debt = data.kpis.debtEquity;
  const cash = data.kpis.cashFlow;
  const revenue = data.kpis.revenue;
  return [
    scoreKpi(data),
    kpiCard("Revenue", `${money(revenue.value)}<small>crore</small>`, `<strong>${metricText(revenueGrowth, "—")}</strong> vs prior year`, "trend"),
    kpiCard("ROCE", `${metricValue(roce)}<small></small>`, `<strong>${roce?.trend > 0 ? "↗ Improving" : "↘ Watch trend"}</strong> · ${escapeHTML(data.latestYear)}`, "target"),
    kpiCard("Debt / Equity", `${metricValue(debt)}<small></small>`, `<strong class="${debt?.lowerIsBetter ? "positive" : ""}">${debt?.lowerIsBetter ? "Lower is better" : "Sector benchmark"}</strong>`, "scale"),
    kpiCard(cash.source === "Free Cash Flow" ? "Free cash flow" : "Operating cash flow", `${money(cash.value)}<small>crore</small>`, `<strong>${cash.value != null ? "Data ready" : "Not in file"}</strong> · ${escapeHTML(data.latestYear)}`, "cash"),
  ].join("");
}

function friendlyMetricName(name) {
  const labels = {
    "Sales Growth": "Sales growth",
    "Net Profit Growth": "Net profit growth",
    "EBITDA Margin": "EBITDA margin",
    "Net Profit Margin": "Net profit margin",
    "Return on Equity (ROE) %": "ROE",
    "Return on Capital Employed (ROCE) %": "ROCE",
    "Return on Assets (ROA) %": "ROA",
    "Debt to Equity Ratio": "Debt / Equity",
    "Interest Coverage Ratio": "Interest coverage",
    "Cash Conversion Cycle": "Cash conversion cycle",
    "CFO / PAT": "CFO / PAT",
    "Fixed Asset Turnover": "Fixed asset turnover",
  };
  return labels[name] || name;
}

function metricFocus(name) {
  if (name.includes("Cash Conversion")) return "working-capital efficiency";
  if (name.includes("Coverage")) return "debt-servicing headroom";
  if (name.includes("Growth")) return "growth quality";
  if (name.includes("Margin")) return "profitability";
  if (name.includes("Capital") || name.includes("Equity") || name.includes("Assets")) return "capital efficiency";
  if (name.includes("Turnover")) return "asset productivity";
  if (name.includes("CFO")) return "cash conversion";
  return "the overall score";
}

function ratioHighlightItems(data, type) {
  const metrics = (data.metrics || []).filter((metric) => metric && metric.latest !== null && metric.latest !== undefined);
  const ordered = [...metrics].sort((a, b) => type === "strength" ? b.score - a.score : a.score - b.score);
  const preferred = ordered.filter((metric) => type === "strength" ? metric.score >= 60 : metric.score < 50);
  const selected = [...preferred, ...ordered.filter((metric) => !preferred.includes(metric))]
    .filter((metric, index, list) => list.indexOf(metric) === index)
    .slice(0, 3);

  return selected.map((metric) => {
    const label = friendlyMetricName(metric.metric);
    const relation = type === "strength"
      ? metric.lowerIsBetter
        ? `Below the ${metric.displayStrongAt} strong-band ceiling`
        : `Above the ${metric.displayStrongAt} strong band`
      : metric.lowerIsBetter
        ? `Above the ${metric.displayWeakAt} weak-band ceiling`
        : `Below the ${metric.displayWeakAt} weak band`;
    const focus = metricFocus(metric.metric);
    const body = type === "strength"
      ? `${relation}, supporting ${focus}.`
      : `${relation}, so ${focus} needs attention.`;
    return {
      title: `${label} ${metric.displayLatest}`,
      body,
    };
  });
}

function ratioHighlightPanel(data, type) {
  const items = ratioHighlightItems(data, type);
  const isStrength = type === "strength";
  const title = isStrength ? "Ratio Strengths" : "Ratio Risks";
  const cardClass = isStrength ? "ratio-panel-strengths" : "ratio-panel-risks";
  const emptyText = isStrength
    ? "Upload a model with scored ratios to surface strengths here."
    : "Upload a model with scored ratios to surface watch items here.";
  return `<article class="ratio-panel ${cardClass}">
    <div class="ratio-panel-heading"><h2>${title}</h2><span class="ratio-count">${items.length}</span></div>
    <div class="ratio-insight-list">${items.length ? items.map((item) => `<article class="ratio-insight-card"><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.body)}</p></article>`).join("") : `<article class="ratio-insight-card ratio-insight-empty"><p>${emptyText}</p></article>`}</div>
  </article>`;
}

function renderRatioHighlights(data) {
  return `<section class="ratio-highlights" aria-label="Ratio strengths and risks">
    ${ratioHighlightPanel(data, "strength")}
    ${ratioHighlightPanel(data, "risk")}
    <button class="ratio-see-all" type="button" data-page="ratios">See all ${icon("arrow")}</button>
  </section>`;
}

function chartValue(value, kind) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return kind === "percent" ? pct(value) : number(value, 0);
}

function lineChart(seriesList, options = {}) {
  const width = 760;
  const height = 260;
  const pad = { left: 46, right: 18, top: 23, bottom: 39 };
  const years = options.years || [];
  const kind = options.kind || "number";
  const allowNegative = options.allowNegative === true;
  const usable = seriesList.map((item) => ({
    ...item,
    values: (item.values || []).map((value) => (value === null || value === undefined ? null : Number(value))),
  }));
  const values = usable.flatMap((item) => item.values.filter((value) => value !== null && !Number.isNaN(value)));
  if (!values.length) return `<div class="dashboard-note">Not enough numeric history to draw this chart.</div>`;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (kind === "percent") {
    min *= 100;
    max *= 100;
  }
  const spread = Math.max(max - min, 1);
  min = allowNegative ? min - spread * 0.12 : Math.max(0, min - spread * 0.12);
  max += spread * 0.12;
  if (kind === "percent" && !allowNegative) min = Math.max(0, min);
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const x = (index) => pad.left + (Math.max(years.length - 1, 1) ? index / Math.max(years.length - 1, 1) : 0.5) * innerWidth;
  const y = (value) => {
    const scaled = kind === "percent" ? value * 100 : value;
    return pad.top + (1 - (scaled - min) / (max - min)) * innerHeight;
  };
  const ticks = Array.from({ length: 4 }, (_, index) => min + ((max - min) * index) / 3).reverse();
  const grid = ticks.map((tick) => {
    const yy = pad.top + ((max - tick) / (max - min)) * innerHeight;
    return `<line class="chart-grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/><text class="chart-axis-value" x="${pad.left - 9}" y="${(yy + 4).toFixed(1)}" text-anchor="end">${number(tick, kind === "percent" ? 0 : 0)}${kind === "percent" ? "%" : ""}</text>`;
  }).join("");
  const xLabels = years.map((year, index) => `<text class="chart-axis-value" x="${x(index).toFixed(1)}" y="${height - 11}" text-anchor="middle">${escapeHTML(year)}</text>`).join("");
  const lines = usable.map((item, seriesIndex) => {
    const points = item.values.map((value, index) => value === null || Number.isNaN(value) ? null : [x(index), y(value)]).filter(Boolean);
    if (!points.length) return "";
    const path = points.map(([px, py], index) => `${index ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
    const area = seriesIndex === 0 && points.length > 1
      ? `<path class="chart-area" d="${path} L ${points[points.length - 1][0].toFixed(1)} ${(height - pad.bottom).toFixed(1)} L ${points[0][0].toFixed(1)} ${(height - pad.bottom).toFixed(1)} Z"/>`
      : "";
    const dots = points.map(([px, py], pointIndex) => {
      const rawValue = item.values.find((value, index) => value !== null && !Number.isNaN(value) && x(index) === px);
      const label = pointIndex === points.length - 1 || years.length <= 5
        ? `<text class="chart-value-label" x="${px.toFixed(1)}" y="${(py - 10).toFixed(1)}" text-anchor="middle">${escapeHTML(chartValue(rawValue, kind))}</text>`
        : "";
      return `<circle class="chart-point ${seriesIndex ? "secondary" : ""}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4"/>${label}`;
    }).join("");
    return `${area}<path class="chart-line ${seriesIndex ? "secondary" : ""}" d="${path}"/>${dots}`;
  }).join("");
  return `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHTML(options.label || "Financial trend chart")}">
    <defs><linearGradient id="chart-area-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#c9903a" stop-opacity="0.3"/><stop offset="100%" stop-color="#c9903a" stop-opacity="0"/></linearGradient></defs>
    ${grid}<line class="chart-axis-line" x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}"/>${lines}${xLabels}</svg>`;
}

function renderChartCard(title, subtitle, chart, legend) {
  return `<article class="card chart-card"><div class="card-heading"><div><h2>${escapeHTML(title)}</h2>${subtitle ? `<p>${escapeHTML(subtitle)}</p>` : ""}</div>${legend || ""}</div><div class="chart-wrap">${chart}</div></article>`;
}

function renderSnapshot(data) {
  const pe = metricBy(data, "PE Ratio", "P/E");
  const marketCap = data.meta?.marketCap;
  const rows = [
    ["Market cap", marketCap != null ? `${money(marketCap)} crore` : "Not in file"],
    ["P/E", metricText(pe, "Not in file")],
    ["EV / EBITDA", "Not in file"],
    ["Price / Book", "Not in file"],
    ["Dividend yield", "Not in file"],
  ];
  return `<article class="card side-snapshot"><div class="card-heading"><div><h2>Valuation snapshot</h2><p>Only fields present in the uploaded model are shown.</p></div></div><div class="snapshot-list">${rows.map(([label, value]) => `<div class="snapshot-row"><span>${label}</span><strong>${escapeHTML(value)}</strong></div>`).join("")}</div></article>`;
}

function listItems(items, type = "positive") {
  if (!items?.length) return `<li><span class="list-icon">${icon("info")}</span><span>No additional notes were produced from the available rows.</span></li>`;
  return items.slice(0, 5).map((item) => `<li><span class="list-icon">${icon(type === "risk" ? "warning" : "check")}</span><span>${escapeHTML(item)}</span></li>`).join("");
}

function renderDashboard(data) {
  const titleActions = headerControls(data, { upload: true, exportReport: true });
  const revenue = data.charts.revenue;
  const note = data.note || {};
  const dataNote = data.rebuiltFromDataSheet ? "Some statement rows were rebuilt from the workbook's raw Data Sheet." : "Figures are sourced from the uploaded workbook; no external market data is being mixed into the score.";
  return `${pageHeader(data.company, `A calm view of ${data.latestYear} performance, quality, and the ratios that move the score.`, titleActions, "FUNDAMENTAL ANALYSIS · DATA READY")}
    <div class="dashboard-kpis">${dashboardKpis(data)}</div>
    ${renderRatioHighlights(data)}
    <div class="dashboard-body-grid">
      ${renderChartCard("Revenue trend", "Reported revenue across the available periods.", lineChart([{ name: "Revenue (₹ crore)", values: revenue.values }], { years: revenue.years, kind: "number", label: "Revenue trend" }), `<div class="chart-legend"><span class="legend-item"><i class="legend-swatch"></i>Revenue (₹ crore)</span></div>`)}
      ${renderSnapshot(data)}
    </div>
    <div class="dashboard-summary-row"><article class="card list-card summary"><h2>${icon("spark")} Analyst summary</h2><div class="summary-quote">${escapeHTML(note.summary || "Upload a workbook to generate a grounded analyst summary.")}<strong>Rule-based and traceable · ${escapeHTML(note.confidence || "medium")} confidence</strong></div></article></div>
    <div class="dashboard-note">${escapeHTML(dataNote)} ${data.dataGaps?.length ? `Missing metrics excluded from score: ${escapeHTML(data.dataGaps.join(", "))}.` : ""}</div>`;
}

function sectionTabs(items, active, action) {
  return `<div class="section-tabs">${items.map((item) => `<button class="section-tab ${item === active ? "is-active" : ""}" type="button" data-action="${action}" data-value="${escapeHTML(item)}">${escapeHTML(item)}</button>`).join("")}</div>`;
}

function insightCard(label, score, status, iconName) {
  return `<article class="card insight-card"><div class="kpi-top"><span class="insight-label">${escapeHTML(label)}</span><span class="kpi-icon">${icon(iconName)}</span></div><div class="insight-value">${number(score)}</div><span class="insight-status">${escapeHTML(status)}</span></article>`;
}

function ratioInsights(data, metricNames = []) {
  const metrics = metricNames.length
    ? metricNames.map((name) => metricBy(data, name)).filter(Boolean)
    : data.metrics || [];
  const ordered = [...metrics].sort((a, b) => b.score - a.score).slice(0, 3);
  const copy = ordered.map((metric) => {
    const improving = metric.trend > 0.05;
    return { title: `${metric.metric} ${improving ? "is improving" : "is being monitored"}`, body: `${metric.displayLatest} · ${metric.score.toFixed(0)}/100 sub-score against the ${escapeHTML(data.sector.name)} rule book.`, icon: improving ? "trend" : "shield" };
  });
  while (copy.length < 3) copy.push({ title: "Transparent scoring", body: "Each available ratio keeps its own value, band, and score so the result can be audited.", icon: "info" });
  return copy;
}

function renderMeaningCard(data, metricNames = []) {
  return `<article class="card meaning-card"><div class="card-heading"><div><h2>What this means</h2><p>Short explanations tied to the scored ratios.</p></div></div>${ratioInsights(data, metricNames).map((item) => `<div class="meaning-item"><div class="meaning-icon">${icon(item.icon)}</div><div><strong>${item.title}</strong><p>${item.body}</p></div></div>`).join("")}</article>`;
}

const DEFAULT_RATIO_ORDER = [
    "Return on Capital Employed (ROCE) %",
    "EBITDA Margin",
    "Net Profit Margin",
    "Debt to Equity Ratio",
    "Interest Coverage Ratio",
    "Cash Conversion Cycle",
];

function renderRatioTable(data, order = DEFAULT_RATIO_ORDER) {
  const rows = order.map((name) => metricBy(data, name)).filter(Boolean);
  return `<article class="card ratio-table-card"><div class="table-toolbar"><h2>Key ratios</h2><span class="benchmark-chip">${icon("target")} Benchmark: ${escapeHTML(data.sector.name)}</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Ratio</th><th>Latest</th><th>3Y average</th><th>Sector strong</th><th>Score</th><th>Read</th></tr></thead><tbody>${rows.length ? rows.map((metric) => `<tr><td class="metric-name">${escapeHTML(metric.metric)}</td><td>${escapeHTML(metric.displayLatest)}</td><td>${metric.average3y != null ? escapeHTML(metric.metric.includes("%") || metric.metric.includes("Margin") ? pct(metric.average3y) : metric.metric.includes("Days") || metric.metric.includes("Cycle") ? `${number(metric.average3y, 0)} days` : ratio(metric.average3y)) : "—"}</td><td>${escapeHTML(metric.displayStrongAt)}</td><td><span class="score-chip">${number(metric.score)}</span></td><td class="${metric.score >= 66 ? "positive" : metric.score < 40 ? "negative" : "warning"}">${escapeHTML(metric.verdict)}</td></tr>`).join("") : `<tr><td colspan="6">No ratio rows are available in this workbook.</td></tr>`}</tbody></table></div></article>`;
}

function ratioSeries(data, name) {
  const row = (data.statements?.["Ratio Analysis"] || []).find((item) => item.name === name);
  return {
    name,
    years: data.years || [],
    values: row?.values || [],
  };
}

function ratioMetricCard(metric) {
  const statusClass = metric.score >= 66 ? "positive" : metric.score < 40 ? "negative" : "warning";
  return `<article class="card ratio-metric-card"><div class="ratio-metric-top"><span class="ratio-metric-label">${escapeHTML(friendlyMetricName(metric.metric))}</span><span class="ratio-metric-verdict ${statusClass}">${escapeHTML(metric.verdict)}</span></div><div class="ratio-metric-value">${escapeHTML(metric.displayLatest || "—")}</div><div class="ratio-metric-score">Score <strong>${number(metric.score)}</strong> / 100 · strong ${escapeHTML(metric.displayStrongAt || "—")}</div></article>`;
}

const RATIO_TAB_SPECS = {
  Profitability: {
    eyebrow: "PROFITABILITY",
    title: "Margins and returns",
    description: "See whether earnings translate into healthy margins and efficient use of capital.",
    metricNames: ["EBITDA Margin", "Net Profit Margin", "Return on Equity (ROE) %", "Return on Capital Employed (ROCE) %"],
    chartTitle: "Profitability trend",
    chartSubtitle: "Margins and returns across the available periods.",
    chartKind: "percent",
    series: ["EBITDA Margin", "Net Profit Margin", "Return on Capital Employed (ROCE) %"],
    allowNegative: false,
  },
  Growth: {
    eyebrow: "GROWTH",
    title: "Growth momentum",
    description: "Compare sales and profit growth over time, including years where momentum moved backwards.",
    metricNames: ["Sales Growth", "Net Profit Growth"],
    chartTitle: "Growth trend",
    chartSubtitle: "Positive and negative changes are shown on the same scale.",
    chartKind: "percent",
    series: ["Sales Growth", "Net Profit Growth"],
    allowNegative: true,
  },
  Leverage: {
    eyebrow: "LEVERAGE",
    title: "Debt and coverage",
    description: "Read the balance-sheet risk through leverage and the company's ability to service interest.",
    metricNames: ["Debt to Equity Ratio", "Interest Coverage Ratio"],
    chartTitle: "Leverage trend",
    chartSubtitle: "Debt-to-equity and interest coverage across the available periods.",
    chartKind: "number",
    series: ["Debt to Equity Ratio", "Interest Coverage Ratio"],
    allowNegative: false,
  },
  "Working capital": {
    eyebrow: "WORKING CAPITAL",
    title: "Cash conversion cycle",
    description: "Understand how quickly cash moves through receivables, inventory, and payables.",
    metricNames: ["Cash Conversion Cycle"],
    chartTitle: "Working-capital trend",
    chartSubtitle: "A negative cash conversion cycle means the business is funded by its operating cycle.",
    chartKind: "number",
    series: ["Cash Conversion Cycle", "Debtor Days", "Inventory Days", "Payable Days"],
    allowNegative: true,
  },
  "Cash flow": {
    eyebrow: "CASH FLOW",
    title: "Cash quality",
    description: "Check whether reported earnings are supported by operating cash generation.",
    metricNames: ["CFO / PAT", "CFO / Sales"],
    chartTitle: "Operating cash flow",
    chartSubtitle: "Reported operating cash flow across the available periods.",
    chartKind: "number",
    series: [],
    allowNegative: true,
  },
};

function renderRatioTabView(data, spec) {
  const metrics = spec.metricNames.map((name) => metricBy(data, name)).filter(Boolean);
  const series = spec.series.length
    ? spec.series.map((name) => ratioSeries(data, name))
    : [{ name: "Operating cash flow", years: data.charts.cashFlow.years, values: data.charts.cashFlow.values }];
  const chart = lineChart(series, {
    years: data.years,
    kind: spec.chartKind,
    allowNegative: spec.allowNegative,
    label: spec.chartTitle,
  });
  const legend = series.map((item, index) => `<span class="legend-item"><i class="legend-swatch ${index ? "secondary" : ""}"></i>${escapeHTML(item.name)}</span>`).join("");
  return `<div class="ratio-tab-summary"><div><span class="mono-label">${escapeHTML(spec.eyebrow)}</span><h2>${escapeHTML(spec.title)}</h2><p>${escapeHTML(spec.description)}</p></div><span class="ratio-tab-count">${metrics.length} tracked ${metrics.length === 1 ? "ratio" : "ratios"}</span></div>
    <div class="ratio-metric-grid">${metrics.length ? metrics.map(ratioMetricCard).join("") : `<article class="card ratio-metric-card ratio-insight-empty"><p class="muted">No scored ratios are available for this view.</p></article>`}</div>
    <div class="ratio-middle-grid"><article class="card chart-card"><div class="card-heading"><div><h2>${escapeHTML(spec.chartTitle)}</h2><p>${escapeHTML(spec.chartSubtitle)}</p></div><div class="chart-legend">${legend}</div></div><div class="chart-wrap">${chart}</div></article>${renderMeaningCard(data, spec.metricNames)}</div>
    ${renderRatioTable(data, spec.metricNames)}`;
}

function renderRatios(data) {
  const pillars = data.score.pillars || {};
  const cards = [
    ["Profitability score", pillars.profitability, "Strong", "trend"],
    ["Growth score", pillars.growth, "Improving", "chart"],
    ["Leverage score", pillars.leverage, "Healthy", "shield"],
    ["Cash flow score", pillars.efficiency, "Stable", "cash"],
  ];
  const roce = data.charts.roce;
  const margin = data.charts.operatingMargin;
  const actions = headerControls(data, { upload: false, exportReport: true, sector: true });
  const tabs = ["Overview", "Profitability", "Growth", "Leverage", "Working capital", "Cash flow"];
  const header = `${pageHeader("Ratio deep dive", "Understand what is driving the company's fundamental health.", actions, `RATIO DEEP DIVE · ${data.latestYear}`)}${sectionTabs(tabs, state.ratioTab, "ratio-tab")}`;
  if (state.ratioTab !== "Overview") return `${header}${renderRatioTabView(data, RATIO_TAB_SPECS[state.ratioTab])}`;
  return `${header}
    <div class="insight-grid">${cards.map(([label, score, status, iconName]) => insightCard(label, score ?? 0, score == null ? "Not available" : status, iconName)).join("")}</div>
    <div class="ratio-middle-grid">
      ${renderChartCard("ROCE and operating margin", "Two separate percentage series on one readable scale.", lineChart([{ name: "ROCE (%)", values: roce.values }, { name: "Operating margin (%)", values: margin.values }], { years: roce.years, kind: "percent", label: "ROCE and operating margin" }), `<div class="chart-legend"><span class="legend-item"><i class="legend-swatch"></i>ROCE</span><span class="legend-item"><i class="legend-swatch secondary"></i>Operating margin</span></div>`)}
      ${renderMeaningCard(data)}
    </div>
    ${renderRatioTable(data)}`;
}

function renderLensStats(data) {
  const roce = metricBy(data, "Return on Capital Employed (ROCE) %");
  const growth = metricBy(data, "Sales Growth");
  return `<article class="card lens-top-strip">
    <div class="lens-stat"><div class="lens-stat-label">Sector position</div><div class="lens-stat-value">Rules</div><div class="lens-stat-note">Compared with ${escapeHTML(data.sector.name)} bands</div></div>
    <div class="lens-stat"><div class="lens-stat-label">Fundamental score</div><div class="lens-stat-value">${number(data.score.total)}</div><div class="lens-stat-note">${escapeHTML(data.score.headline)}</div></div>
    <div class="lens-stat"><div class="lens-stat-label">ROCE</div><div class="lens-stat-value">${escapeHTML(metricText(roce))}</div><div class="lens-stat-note">strong band ${escapeHTML(roce?.displayStrongAt || "—")}</div></div>
    <div class="lens-stat"><div class="lens-stat-label">Revenue growth</div><div class="lens-stat-value">${escapeHTML(metricText(growth))}</div><div class="lens-stat-note">strong band ${escapeHTML(growth?.displayStrongAt || "—")}</div></div>
  </article>`;
}

function renderBenchmarkBars(data) {
  const rows = data.sectorRows || [];
  if (!rows.length) return `<div class="dashboard-note">Not enough matching ratios were found to draw a sector comparison.</div>`;
  return `<div class="bar-list">${rows.map((row) => `<div class="bar-row"><div class="bar-label">${escapeHTML(row.label)}</div><div class="bar-track"><div class="bar" style="width:${Math.round(row.companyScore * 100)}%"></div><div class="bar benchmark" style="width:${Math.round(row.benchmarkScore * 100)}%"></div></div><div class="bar-values"><span>${escapeHTML(row.companyDisplay)}</span><span>${escapeHTML(row.benchmarkDisplay)}</span></div></div>`).join("")}</div>`;
}

function renderPeerTable(data) {
  const rows = data.peerRows || [];
  return `<article class="card peer-table-card"><div class="table-toolbar"><h2>Benchmark set</h2><span class="soft-chip">No external peer feed connected</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Company / reference</th><th>ROCE</th><th>Revenue growth</th><th>Debt / Equity</th><th>Score</th></tr></thead><tbody>${rows.map((row) => `<tr class="${row.kind === "company" ? "highlight" : ""}"><td>${escapeHTML(row.name)}</td><td>${escapeHTML(row.values.ROCE || "—")}</td><td>${escapeHTML(row.values["Revenue growth"] || "—")}</td><td>${escapeHTML(row.values["Debt / Equity"] || "—")}</td><td>${number(row.score)}</td></tr>`).join("")}</tbody></table></div><div class="peer-note">The reference row is the sector rule-book threshold, not a live market peer. Connect a peer-data provider later when you are ready to add external data.</div></article>`;
}

function renderLens(data) {
  const actions = headerControls(data, { upload: false, exportReport: true, sector: true });
  const rows = data.sectorRows || [];
  return `${pageHeader("Sector lens", "See how the company compares with the benchmark rules for its industry.", actions, `SECTOR LENS · ${data.sector.name.toUpperCase()}`)}
    ${renderLensStats(data)}
    <div class="lens-middle-grid">
      <article class="card benchmark-chart-card"><div class="card-heading"><div><h2>Company vs sector benchmark</h2><p>Green is the company; lavender is the strong threshold.</p></div><span class="benchmark-chip">${icon("target")} Benchmark applied</span></div><div class="bar-legend"><span><i></i>Company</span><span><i class="benchmark"></i>Sector strong</span></div>${renderBenchmarkBars(data)}</article>
      <article class="card readout-card"><div class="card-heading"><div><h2>Sector readout</h2><p>${escapeHTML(data.sector.notes)}</p></div></div><ul class="insight-list">${rows.slice(0, 3).map((row) => `<li><span class="list-icon positive">${icon(row.companyScore >= row.benchmarkScore ? "trend" : "warning")}</span><span><strong>${escapeHTML(row.label)}</strong><br>${escapeHTML(row.companyDisplay)} vs ${escapeHTML(row.benchmarkDisplay)} benchmark.</span></li>`).join("") || `<li><span class="list-icon">${icon("info")}</span><span>Choose a sector or upload a richer statement model to compare more ratios.</span></li>`}</ul><div class="readout-score">${icon("check")} ${data.score.total >= 66 ? "Above" : "Within"} sector benchmark bands</div></article>
    </div>
    ${renderPeerTable(data)}`;
}

function statementRowsFor(data, tab) {
  return data.statements?.[tab] || [];
}

function formatStatementCell(name, value, tab) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const lower = name.toLowerCase();
  if (tab === "Common Size" || lower.includes("margin") || lower.includes("growth") || lower.includes("%")) return pct(value);
  if (tab === "Ratio Analysis" || lower.includes("ratio") || lower.includes("coverage") || lower.includes("turnover")) return ratio(value);
  if (lower.includes("days") || lower.includes("cycle")) return `${number(value, 0)} days`;
  return number(value, Math.abs(Number(value)) < 1000 && !Number.isInteger(Number(value)) ? 1 : 0);
}

function renderStatementTable(data) {
  const tab = state.statementTab;
  const query = state.statementQuery.trim().toLowerCase();
  const rows = statementRowsFor(data, tab).filter((row) => !query || row.name.toLowerCase().includes(query));
  const years = data.years || [];
  return `<article class="card statement-table-card"><div class="table-toolbar"><h2>${escapeHTML(tab)}</h2><div class="statement-search">${icon("search")}<input id="statement-search" type="search" value="${escapeHTML(state.statementQuery)}" placeholder="Search metrics" aria-label="Search statement rows" /></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Particulars</th>${years.map((year) => `<th>${escapeHTML(year)}</th>`).join("")}<th>% change</th></tr></thead><tbody>${rows.length ? rows.map((row) => {
    const values = row.values || [];
    const previous = values.length > 1 ? values[values.length - 2] : null;
    const latest = values.length ? values[values.length - 1] : null;
    const change = previous != null && latest != null && Number(previous) !== 0 ? ((Number(latest) - Number(previous)) / Math.abs(Number(previous))) * 100 : null;
    return `<tr class="${row.headline ? "highlight" : ""}"><td class="metric-name">${escapeHTML(row.name)}</td>${values.map((value) => `<td>${escapeHTML(formatStatementCell(row.name, value, tab))}</td>`).join("")}<td class="${change == null ? "muted" : change >= 0 ? "positive" : "negative"}">${change == null ? "—" : `${change >= 0 ? "↑" : "↓"} ${number(Math.abs(change), 1)}%`}</td></tr>`;
  }).join("") : `<tr><td colspan="${years.length + 2}">No rows match this view.</td></tr>`}</tbody></table></div><div class="peer-note">All figures are presented from the uploaded file. Values are not enriched from an external market feed.</div></article>`;
}

function renderStatementNotes(data) {
  const source = data.sourceLabel || "Uploaded workbook";
  return `<article class="card statement-notes"><div class="card-heading"><div><h2>Statement notes</h2><p>Small details that help you trust the table.</p></div></div>
    <div class="note-block"><div class="note-block-icon">${icon("database")}</div><div><strong>Data quality</strong><p>Figures are sourced from the uploaded financial statements and kept in this browser session.</p></div></div>
    <div class="note-block"><div class="note-block-icon">${icon("check")}</div><div><strong>Consistency</strong><p>${data.rebuiltFromDataSheet ? "Raw Data Sheet rows were used to rebuild missing formula outputs." : "The workbook's parsed periods are used consistently across the sections."}</p></div></div>
    <div class="note-block"><div class="note-block-icon">${icon("trend")}</div><div><strong>Analysis ready</strong><p>Use Ratio Analysis and Common Size tabs to move from headline numbers into drivers.</p></div></div>
    <div class="source-box"><span>Data source</span><div class="data-chip">${icon("spreadsheet")} ${escapeHTML(source)}</div></div>
  </article>`;
}

function renderStatements(data) {
  const actions = headerControls(data, { upload: false, exportReport: true });
  const kpis = [
    ["Revenue", data.kpis.revenue, "money", "cash"],
    ["EBITDA", data.kpis.ebitda, "money", "trend"],
    ["Profit after tax", data.kpis.netProfit, "money", "chart"],
    [data.kpis.cashFlow.source === "Free Cash Flow" ? "Free cash flow" : "Operating cash flow", data.kpis.cashFlow, "money", "cash"],
  ];
  const tabs = ["Income Statement", "Balance Sheet", "Cash Flow", "Ratio Analysis", "Common Size"];
  return `${pageHeader("Statements", "Review the numbers behind the analysis.", actions, `STATEMENTS · ${data.latestYear}`)}
    ${sectionTabs(tabs, state.statementTab, "statement-tab")}
    <div class="card metric-strip">${kpis.map(([label, item, kind, iconName]) => `<div class="metric-item"><span class="metric-item-icon">${icon(iconName)}</span><div><div class="metric-item-label">${escapeHTML(label)}</div><div class="metric-item-value">${escapeHTML(kind === "money" ? `${money(item.value)} crore` : number(item.value))}</div></div></div>`).join("")}</div>
    <div class="statement-grid">${renderStatementTable(data)}${renderStatementNotes(data)}</div>`;
}

function defaultAnswer(data) {
  return {
    question: "No question asked yet",
    answer: "Choose a suggested question or type your own. Your answer will be grounded in the uploaded financial data and the selected sector benchmark.",
    grounded: true,
    idle: true,
    ai: data.ai || {},
    sources: [`${data.sector.name} benchmark rules`, data.sourceLabel],
  };
}

function renderAnswer(answer) {
  const result = answer || defaultAnswer(state.data);
  const ai = result.ai || {};
  const providerName = ai.provider === "xai" ? "Grok" : "AI analyst";
  const providerLabel = result.provider === "xai" ? "Grok connected" : result.provider === "groq" ? "Groq connected" : "Analyst connected";
  const statusLabel = result.idle
    ? (ai.configured ? `${providerName} ready` : "Local analysis ready")
    : result.offline && ai.available === false ? "Local analysis · Grok unavailable" : result.offline ? "Local analysis" : providerLabel;
  const errorNote = ai.error ? `<div class="answer-warning">${escapeHTML(providerName)} request failed: ${escapeHTML(ai.error)}. A local answer is shown.</div>` : "";
  return `<article class="card answer-card"><div class="card-heading"><div><h2>Latest answer</h2><p>Only the uploaded model and sector rules are used.</p></div><span class="status-chip">${icon("shield")} Grounded in company data</span></div><div class="answer-inner"><div class="status-chip">${icon("check")} ${statusLabel}</div>${errorNote}<div class="answer-question">${escapeHTML(result.question)}</div><div class="answer-copy">${escapeHTML(result.answer)}</div><div class="answer-sources"><strong class="muted">Sources</strong>${(result.sources || []).map((source) => `<span class="source-pill">${icon("file")} ${escapeHTML(source)}</span>`).join("")}</div></div></article>`;
}

function renderQA(data) {
  const suggestions = [
    "What are the biggest strengths?",
    "Which ratios need attention?",
    "How does the company compare with its sector?",
    "What changed in the latest year?",
  ];
  const actions = headerControls(data, { upload: true, exportReport: false });
  const history = state.history.slice(0, 4);
  const ai = state.latestAnswer?.ai || data.ai || {};
  const providerName = ai.provider === "xai" ? "Grok" : ai.provider || "AI analyst";
  const modelLabel = ai.model ? ` (${ai.model})` : "";
  const aiLabel = ai.available === false
    ? `${providerName} is unavailable right now. A local answer will be shown.`
    : ai.configured
    ? `${providerName}${modelLabel} is ${ai.available === true ? "connected" : "configured"}.`
    : "Grok is not connected. Add XAI_API_KEY to .env and restart Flask.";
  return `${pageHeader("Ask the analyst", "Ask questions about the company using the data you uploaded.", actions, "ASK THE ANALYST · GROUNDED Q&A")}
    <article class="card qa-composer"><label for="ask-input">What would you like to understand?</label><textarea class="question-input" id="ask-input" placeholder="e.g. Why did free cash flow improve in FY24?"></textarea><div class="composer-footer"><div class="grounding-note">${icon("spark")} ${escapeHTML(aiLabel)} Answers are grounded in your uploaded financial data.</div><button class="primary-button" type="button" data-action="ask-question">${icon("arrow")} Ask question</button></div></article>
    <div class="qa-grid"><article class="card suggestions-card"><div class="card-heading"><div><h2>Suggested questions</h2><p>Start with one of these prompts.</p></div></div><div class="suggestion-list">${suggestions.map((question) => `<button class="suggestion-button" type="button" data-action="use-suggestion" data-question="${escapeHTML(question)}">${icon(question.includes("strength") ? "star" : question.includes("ratios") ? "warning" : question.includes("sector") ? "users" : "trend")}<span>${escapeHTML(question)}</span><span class="suggestion-arrow">${icon("arrow")}</span></button>`).join("")}</div></article>${renderAnswer(state.latestAnswer)}</div>
    <article class="card conversation-card"><div class="table-toolbar"><h2>Conversation history</h2><button class="ghost-button" type="button" data-action="clear-history">Clear</button></div>${history.length ? history.map((item) => `<div class="conversation-row">${icon("message")}<span>${escapeHTML(item.question)}</span><span class="conversation-time">${escapeHTML(item.time || "Earlier")}</span></div>`).join("") : `<div class="conversation-row"><span class="muted">Your grounded questions will appear here.</span></div>`}</article>`;
}

function renderCurrentPage() {
  if (state.page === "ratios") return renderRatios(state.data);
  if (state.page === "lens") return renderLens(state.data);
  if (state.page === "statements") return renderStatements(state.data);
  if (state.page === "qa") return renderQA(state.data);
  return renderDashboard(state.data);
}

async function loadAnalysis(formData, label) {
  showLoading(true, label || "Reading your financials");
  try {
    const data = await api("/api/analyze", { method: "POST", body: formData });
    state.data = data;
    state.page = "dashboard";
    state.latestAnswer = null;
    state.statementQuery = "";
    rememberFile(data.sourceLabel);
    document.body.classList.remove("menu-open");
    render();
    toast("Analysis ready — your data stays in this session.");
  } catch (error) {
    toast(error.message);
  } finally {
    showLoading(false);
  }
}

function openFilePicker() {
  $("#file-input")?.click();
}

async function handleSectorChange(select) {
  if (!state.data) return;
  showLoading(true, "Re-scoring against the selected sector");
  try {
    state.data = await api("/api/sector", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ datasetId: state.data.datasetId, sectorKey: select.value }),
    });
    state.latestAnswer = null;
    render();
    toast(`Sector lens updated to ${state.data.sector.name}.`);
  } catch (error) {
    toast(error.message);
    select.value = state.data.sector.key;
  } finally {
    showLoading(false);
  }
}

async function askQuestion(questionOverride = "") {
  if (!state.data) return;
  const input = $("#ask-input");
  const question = (questionOverride || input?.value || "").trim();
  if (!question) {
    toast("Write a question first.");
    input?.focus();
    return;
  }
  showLoading(true, "Reading the scored financials");
  try {
    const answer = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ datasetId: state.data.datasetId, question }),
    });
    state.latestAnswer = answer;
    state.history.unshift({ question, time: "Just now" });
    state.history = state.history.slice(0, 8);
    localStorage.setItem("fundacheck-history", JSON.stringify(state.history));
    state.page = "qa";
    render();
  } catch (error) {
    toast(error.message);
  } finally {
    showLoading(false);
  }
}

function exportReport() {
  if (!state.data?.datasetId) {
    toast("Upload a workbook before exporting a report.");
    return;
  }
  const link = document.createElement("a");
  link.href = `/api/report/${encodeURIComponent(state.data.datasetId)}`;
  link.download = "fundacheck-report.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

document.addEventListener("click", (event) => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) {
    state.page = pageButton.dataset.page;
    document.body.classList.remove("menu-open");
    render();
    return;
  }
  const actionNode = event.target.closest("[data-action]");
  if (!actionNode) return;
  const action = actionNode.dataset.action;
  if (action === "toggle-theme") {
    state.theme = state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("fundacheck-theme", state.theme);
    applyTheme();
    return;
  }
  if (action === "toggle-sidebar") {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    localStorage.setItem("fundacheck-sidebar-collapsed", String(state.sidebarCollapsed));
    applySidebarState();
    return;
  }
  if (action === "open-menu") {
    document.body.classList.add("menu-open");
    return;
  }
  if (action === "close-menu") {
    document.body.classList.remove("menu-open");
    return;
  }
  if (action === "open-upload") {
    openFilePicker();
    return;
  }
  if (action === "load-demo") {
    const form = new FormData();
    form.append("demo", "true");
    loadAnalysis(form, "Loading the demo model");
    return;
  }
  if (action === "export-report") {
    exportReport();
    return;
  }
  if (action === "ratio-tab") {
    state.ratioTab = actionNode.dataset.value;
    render();
    return;
  }
  if (action === "statement-tab") {
    state.statementTab = actionNode.dataset.value;
    state.statementQuery = "";
    render();
    return;
  }
  if (action === "use-suggestion") {
    const question = actionNode.dataset.question || "";
    const input = $("#ask-input");
    if (input) input.value = question;
    askQuestion(question);
    return;
  }
  if (action === "ask-question") {
    askQuestion();
    return;
  }
  if (action === "clear-history") {
    state.history = [];
    state.latestAnswer = null;
    localStorage.removeItem("fundacheck-history");
    render();
    return;
  }
  if (action === "toast") {
    toast(actionNode.dataset.toast || "That control is ready for the next release.");
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches('[data-action="change-sector"]')) handleSectorChange(event.target);
  if (event.target.id === "file-input") {
    const file = event.target.files?.[0];
    if (file) {
      const form = new FormData();
      form.append("file", file);
      loadAnalysis(form, "Parsing your uploaded file");
      event.target.value = "";
    }
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "statement-search") {
    state.statementQuery = event.target.value;
    const caret = event.target.selectionStart;
    render();
    const next = $("#statement-search");
    if (next) {
      next.focus();
      next.setSelectionRange(caret, caret);
    }
  }
});

document.addEventListener("keydown", (event) => {
  const zone = event.target.closest("#drop-zone");
  if (zone && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openFilePicker();
  }
  if (event.target.id === "ask-input" && event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    askQuestion();
  }
});

document.addEventListener("dragover", (event) => {
  const zone = event.target.closest("#drop-zone");
  if (!zone) return;
  event.preventDefault();
  zone.classList.add("is-dragging");
});

document.addEventListener("dragleave", (event) => {
  const zone = event.target.closest("#drop-zone");
  if (zone) zone.classList.remove("is-dragging");
});

document.addEventListener("drop", (event) => {
  const zone = event.target.closest("#drop-zone");
  if (!zone) return;
  event.preventDefault();
  zone.classList.remove("is-dragging");
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  loadAnalysis(form, "Parsing your dropped file");
});

applyTheme();
render();
