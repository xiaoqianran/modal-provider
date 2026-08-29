// modal-gen console — shell, router, api and shared UI primitives.
import { mountConnect, openConnectionSettings } from "./views/view_connect.js";
import { mountCreate } from "./views/view_create.js";
import { mountJobs } from "./views/view_jobs.js";
import { mountArtifacts } from "./views/view_artifacts.js";

const ROUTES = {
  connect: { label: "连接", icon: "plug", render: mountConnect },
  create: { label: "创建", icon: "spark", render: mountCreate },
  jobs: { label: "任务", icon: "list", render: mountJobs },
  artifacts: { label: "产物", icon: "cube", render: mountArtifacts },
};

export const store = {
  mode: "demo",
  connector: null,
  reachable: true,
  snapshot: null,
  counts: { jobs: 0, artifacts: 0 },
  cleanup: null,
};

// ------------------------------------------------------------------ dom
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  plug: '<path d="M9 2v6h6V2M9 22v-6h6v6M12 8v8" />',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2" /><circle cx="12" cy="12" r="3"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />',
  cube: '<path d="M12 2 3 7v10l9 5 9-5V7zM3 7l9 5 9-5M12 12v10" />',
  check: '<path d="M20 6 9 17l-5-5" />',
  alert: '<path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />',
  image: '<rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-5-5L5 21" />',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />',
  close: '<path d="M18 6 6 18M6 6l12 12" />',
  chevron: '<path d="m9 6 6 6-6 6" />',
};

export function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.innerHTML = ICONS[name] || "";
  return svg;
}

// ------------------------------------------------------------------ status
export const JOB_STATUS = {
  accepted: { cls: "info", label: "排队确认" },
  queued: { cls: "info", label: "排队中" },
  running: { cls: "info", label: "运行中" },
  connection_required: { cls: "warn", label: "需重连" },
  cancel_requested: { cls: "neutral", label: "取消中" },
  succeeded: { cls: "ok", label: "成功" },
  failed: { cls: "danger", label: "失败" },
  cancelled: { cls: "neutral", label: "已取消" },
  expired: { cls: "warn", label: "已过期" },
};

export function jobBadge(status) {
  const s = JOB_STATUS[status] || { cls: "neutral", label: status };
  return h("span", { class: `badge badge--${s.cls}` }, h("span", { class: "badge__dot" }), s.label);
}

export function providerBadge(status) {
  const map = {
    available: "ok", healthy: "ok", degraded: "warn",
    unavailable: "warn", disabled: "neutral",
  };
  const cls = map[status] || "neutral";
  const label = { available: "可用", healthy: "健康", degraded: "降级", unavailable: "不可用", disabled: "已停用" }[status] || status;
  return h("span", { class: `badge badge--${cls}` }, h("span", { class: "badge__dot" }), label);
}

export function fmtBytes(n) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

export function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function truncMid(text, head = 10, tail = 8) {
  if (!text) return text;
  if (text.length <= head + tail + 1) return text;
  return `${text.slice(0, head)}…${text.slice(-tail)}`;
}

// ------------------------------------------------------------------ api
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`/ui/api/${path}`, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `HTTP ${resp.status}`);
  }
  return data;
}
export const apiGet = (p) => api("GET", p);
export const apiPost = (p, b) => api("POST", p, b);

// ------------------------------------------------------------------ toast
export function toast(message, kind = "") {
  const host = document.getElementById("toast-host");
  if (!host) return;
  const el = h("div", { class: `toast ${kind ? "toast--" + kind : ""}` }, message);
  host.append(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(6px)"; }, 2600);
  setTimeout(() => el.remove(), 3000);
}

// ------------------------------------------------------------------ drawer/dialog
export function openDrawer(title, bodyNode) {
  const host = document.getElementById("drawer-host");
  const previousFocus = document.activeElement;
  const scrim = h("div", { class: "drawer-scrim" });
  const panel = h("div", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": title });
  const close = () => {
    scrim.classList.remove("scrim--on");
    panel.classList.remove("drawer--open");
    host.classList.remove("host--on");
    setTimeout(() => {
      host.replaceChildren();
      if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
    }, 200);
  };
  panel.append(
    h("div", { class: "drawer__head" },
      h("h3", { class: "drawer__title" }, title),
      h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "关闭", onclick: close }, icon("close", 16))),
    h("div", { class: "drawer__body" }, bodyNode)
  );
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = Array.from(panel.querySelectorAll("input,button,select,textarea,summary,[tabindex]:not([tabindex='-1'])"))
      .filter((node) => !node.disabled && node.offsetParent !== null);
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  scrim.addEventListener("click", close);
  host.className = "drawer-host host--on";
  host.replaceChildren(scrim, panel);
  requestAnimationFrame(() => {
    scrim.classList.add("scrim--on");
    panel.classList.add("drawer--open");
    setTimeout(() => {
      const first = panel.querySelector(".drawer__body input,.drawer__body select,.drawer__body textarea,.drawer__body button")
        || panel.querySelector("button,input,select,textarea,summary,[tabindex]:not([tabindex='-1'])");
      first?.focus();
    }, 80);
  });
  return close;
}


export function stateEmpty(title, desc, { iconName = "file" } = {}) {
  return h("div", { class: "empty" },
    h("div", { class: "empty__icon" }, icon(iconName, 38)),
    h("div", { class: "empty__title" }, title),
    desc ? h("div", { class: "empty__desc" }, desc) : null
  );
}

export function openDialog({ title, body, confirm = "确认", danger = false, onConfirm }) {
  const host = document.getElementById("dialog-host");
  const scrim = h("div", { class: "dialog-scrim" });
  const dialog = h("div", { class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title });
  const close = () => { scrim.classList.remove("scrim--on"); dialog.classList.remove("dialog--open"); host.classList.remove("host--on"); setTimeout(() => host.replaceChildren(), 200); };
  const ok = h("button", {
    class: `btn ${danger ? "btn--danger" : "btn--primary"}`, onclick: () => { close(); onConfirm && onConfirm(); },
  }, confirm);
  dialog.append(
    h("div", { class: "dialog__head" }, h("h3", { class: "dialog__title" }, title)),
    h("div", { class: "dialog__body" }, body),
    h("div", { class: "dialog__foot" }, h("button", { class: "btn btn--ghost", onclick: close }, "取消"), ok)
  );
  scrim.addEventListener("click", close);
  host.className = "dialog-host host--on";
  host.replaceChildren(scrim, dialog);
  requestAnimationFrame(() => { scrim.classList.add("scrim--on"); dialog.classList.add("dialog--open"); });
}

// ------------------------------------------------------------------ hash chip
export function hashChip(hash, { copyable = true } = {}) {
  if (!hash) return h("span", { class: "muted" }, "—");
  const val = h("span", { class: "hash__val" }, truncMid(hash, 12, 10));
  const wrap = h("span", { class: "hash", title: hash }, val);
  if (copyable) {
    const btn = h("button", { class: "hash__copy", title: "复制", onclick: () => { navigator.clipboard.writeText(hash); toast("已复制"); } }, "复制");
    wrap.append(btn);
  }
  return wrap;
}

// ------------------------------------------------------------------ bootstrap + router
async function refreshCounts() {
  try {
    const j = await apiGet("jobs?status=all&page_size=1");
    const a = await apiGet("artifacts");
    store.counts.jobs = j.total || 0;
    store.counts.artifacts = Array.isArray(a.artifacts) ? a.artifacts.length : 0;
  } catch { /* counts optional */ }
  drawNav();
}

function drawNav() {
  const nav = document.getElementById("nav");
  const keys = Object.keys(ROUTES);
  nav.replaceChildren(
    ...keys.map((key) => {
      const r = ROUTES[key];
      const count = key === "jobs" ? store.counts.jobs : key === "artifacts" ? store.counts.artifacts : null;
      const item = h("button", {
        class: "topnav__item", dataset: { route: key },
        onclick: () => { location.hash = `#/${key}`; },
      },
        h("span", { class: "topnav__icon" }, icon(r.icon, 14)),
        h("span", {}, r.label),
        count ? h("span", { class: "topnav__count" }, String(count)) : null
      );
      const active = (location.hash || "#/connect").slice(2) === key;
      if (active) item.setAttribute("aria-current", "true");
      return item;
    })
  );
}

function route() {
  const key = (location.hash || "#/connect").slice(2);
  const entry = ROUTES[key] || ROUTES.connect;
  if (store.cleanup) { try { store.cleanup(); } catch {} store.cleanup = null; }
  drawNav();
  const screen = document.getElementById("screen");
  screen.replaceChildren();
  entry.render(screen);
}

function paintConnector() {
  const status = document.getElementById("connector-status");
  const state = document.getElementById("conn-state");
  const id = document.getElementById("conn-id");
  const badge = document.getElementById("mode-badge");
  badge.hidden = store.mode !== "demo";
  if (!store.reachable) {
    status.dataset.state = "bad";
    state.textContent = "Connector 离线";
    id.textContent = "unreachable";
    return;
  }
  status.dataset.state = "ok";
  state.textContent = "Connector 在线";
  const cid = store.connector?.id || "unified-connector";
  const ver = store.connector?.version || "0.1.0";
  id.textContent = `${cid} · v${ver}`;
}

async function bootstrap() {
  try {
    const data = await apiGet("bootstrap");
    store.mode = data.mode;
    store.connector = data.connector;
    store.reachable = data.reachable !== false;
  } catch {
    store.reachable = false;
  }
  paintConnector();
  document.getElementById("open-settings").onclick = () => openConnectionSettings();
  // render the shell immediately; nav counts are decorative and must never
  // block the first paint of a screen.
  refreshCounts();
  window.addEventListener("hashchange", route);
  route();
}

bootstrap();
