// modal-3D Client — task-oriented single-page UI.
// No framework: small, dependency-free, familiar interactions.

"use strict";

/* ============================================================
   API client
   ============================================================ */

const state = {
  token: localStorage.getItem("m3d.session") || "",
  config: null,
  capabilities: null,
  models: [],
  health: null,
  connected: false,
  jobs: [],
  jobsFilter: "all",
  pollTimer: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (state.token) headers["X-Modal-3D-Session"] = state.token;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, Object.assign({}, options, { headers }));
  return res;
}

async function apiJson(path, options = {}) {
  const res = await api(path, options);
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : text;
    const err = new Error(typeof detail === "string" ? detail : "请求失败");
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ============================================================
   Toast + modal helpers
   ============================================================ */

function toast(message, kind = "info", ms = 4000) {
  const region = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast" + (kind === "error" ? " toast-error" : kind === "success" ? " toast-success" : "");
  el.textContent = message;
  region.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function openDrawer(html) {
  const backdrop = $("#modal-backdrop");
  backdrop.innerHTML = `<div class="drawer" role="dialog" aria-modal="true">${html}</div>`;
  backdrop.hidden = false;
  const drawer = $(".drawer", backdrop);
  $$("[data-close]", drawer).forEach((el) => el.addEventListener("click", closeDrawer));
}

function closeDrawer() {
  const backdrop = $("#modal-backdrop");
  backdrop.hidden = true;
  backdrop.innerHTML = "";
}

// single delegated listener for backdrop clicks and drawer close
$("#modal-backdrop").addEventListener("click", (e) => {
  if (e.target === $("#modal-backdrop")) closeDrawer();
});

/* ============================================================
   Navigation
   ============================================================ */

const SECTIONS = {
  workspace: { title: "工作台", subtitle: "上传图片，选择一个模型生成 GLB 资产" },
  jobs: { title: "任务", subtitle: "查看、筛选并管理所有生成任务" },
  models: { title: "模型", subtitle: "当前可用的 image-to-3D 模型与 profile" },
  connection: { title: "连接", subtitle: "管理 Modal 凭据与 sidecar 健康状态" },
  api: { title: "API 参考", subtitle: "每个可被 curl 调用的接口" },
};

function navigate(section) {
  const meta = SECTIONS[section] || SECTIONS.workspace;
  $("#page-title").textContent = meta.title;
  $("#page-subtitle").textContent = meta.subtitle;
  $$(".nav-item").forEach((n) =>
    n.classList.toggle("is-active", n.dataset.section === section)
  );
  $("#topbar-actions").innerHTML = "";
  renderSection(section);
}

function renderSection(section) {
  const content = $("#content");
  switch (section) {
    case "workspace": renderWorkspace(content); break;
    case "jobs": renderJobs(content); break;
    case "models": renderModels(content); break;
    case "connection": renderConnection(content); break;
    case "api": renderApi(content); break;
    default: renderWorkspace(content);
  }
}

/* ============================================================
   Status → badge mapping (single source of truth)
   ============================================================ */

const STATUS_BADGE = {
  submitting: ["badge-running", "提交中"],
  running: ["badge-running", "运行中"],
  succeeded: ["badge-succeeded", "已完成"],
  failed: ["badge-failed", "失败"],
  cancelled: ["badge-cancelled", "已取消"],
  cancel_requested: ["badge-warn", "取消请求"],
  expired: ["badge-failed", "已过期"],
  connection_required: ["badge-warn", "需重连"],
};

function badgeFor(status) {
  const [cls, label] = STATUS_BADGE[status] || ["badge-neutral", status || "未知"];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch { return iso; }
}

/* ============================================================
   Bootstrap
   ============================================================ */

async function boot() {
  $("#nav").addEventListener("click", (e) => {
    const item = e.target.closest(".nav-item");
    if (item) {
      e.preventDefault();
      navigate(item.dataset.section);
    }
  });

  window.addEventListener("hashchange", () => {
    const section = (location.hash || "#workspace").slice(1);
    navigate(section);
  });

  try {
    state.config = await apiJson("/ui/config");
  } catch (e) {
    toast("无法加载配置: " + e.message, "error");
  }

  const initial = (location.hash || "#workspace").slice(1);
  navigate(SECTIONS[initial] ? initial : "workspace");
  await refreshHealth();
  startPolling();
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(() => {
    refreshHealth();
    if ($("#content").dataset.section === "jobs" || $("#content").dataset.section === "workspace") {
      loadJobs({ silent: true });
    }
  }, 4000);
}

/* ============================================================
   Health / connection
   ============================================================ */

async function refreshHealth() {
  try {
    const health = await apiJson("/health");
    state.health = health;
    state.connected = !!health.modal_connected;
    updateConnPill();
  } catch (e) {
    updateConnPill("error");
  }
}

function updateConnPill(force) {
  const pill = $("#conn-pill");
  const text = $(".conn-pill-text", pill);
  if (force === "error") {
    pill.dataset.state = "error";
    text.textContent = "sidecar 不可达";
    return;
  }
  if (state.config && state.config.demo) {
    pill.dataset.state = "connected";
    text.textContent = "演示模式";
    return;
  }
  if (state.connected) {
    pill.dataset.state = "connected";
    text.textContent = "Modal 已连接";
  } else {
    pill.dataset.state = "disconnected";
    text.textContent = "Modal 未连接";
  }
}

/* ============================================================
   Workspace (primary job: generate an asset)
   ============================================================ */

let selectedFile = null;
let selectedFileUrl = null;

function renderWorkspace(content) {
  content.dataset.section = "workspace";

  const demo = state.config?.demo;
  const requireToken = state.config?.require_token;

  content.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div>
          <h2>生成 3D 资产</h2>
          <p class="card-desc">Primary Job —— 上传一张图，选择模型与 profile，提交生成任务。</p>
        </div>
      </div>

      <div class="steps" id="ws-steps"></div>

      <div class="row-between mt-4 mb-3">
        <span class="text-muted" style="font-size:var(--fs-sm)">步骤 1 · 选择模型</span>
      </div>
      <div class="field">
        <label for="ws-model">模型</label>
        <select class="select" id="ws-model"></select>
      </div>
      <div class="field">
        <label for="ws-profile">Profile（生成质量/参数预设）</label>
        <select class="select" id="ws-profile"></select>
      </div>

      <div class="row-between mt-4 mb-3">
        <span class="text-muted" style="font-size:var(--fs-sm)">步骤 2 · 上传源图</span>
        <span class="text-faint" style="font-size:var(--fs-xs)">PNG / JPEG / WebP</span>
      </div>
      <div class="dropzone" id="ws-dropzone" role="button" tabindex="0" aria-label="上传图片">
        <div class="dz-title">点击选择图片，或拖拽到此处</div>
        <div class="dz-sub">支持 PNG / JPEG / WebP · 最大 20 MiB</div>
        <input type="file" id="ws-file" accept="image/png,image/jpeg,image/webp" hidden />
      </div>
      <img class="preview-thumb hidden" id="ws-preview" alt="预览" />

      <div class="row-between mt-4 mb-3">
        <span class="text-muted" style="font-size:var(--fs-sm)">步骤 3 · 参数</span>
      </div>
      <div class="field">
        <label for="ws-seed">随机种子 (seed)</label>
        <input class="input" id="ws-seed" type="number" value="42" min="0" step="1" />
        <span class="hint">同一 seed 与输入会得到确定性结果；留空则使用 42。</span>
      </div>

      <div class="row mt-4">
        <button class="btn btn-primary" id="ws-submit" disabled>提交生成</button>
        <span class="text-faint" id="ws-submit-hint" style="font-size:var(--fs-xs)"></span>
      </div>
    </div>

    <div class="card" id="ws-recent">
      <div class="card-head">
        <div><h2>最近任务</h2><p class="card-desc">提交后自动出现在这里，并实时刷新状态。</p></div>
        <button class="btn btn-sm btn-ghost" id="ws-goto-jobs">查看全部任务 →</button>
      </div>
      <div id="ws-recent-body"></div>
    </div>
  `;

  // steps hint
  const steps = $("#ws-steps");
  steps.innerHTML = [
    stepHtml(1, "选择模型", "从 /v1/models 读取可用模型", "active"),
    stepHtml(2, "上传源图", "POST /v1/jobs 原样上传", ""),
    stepHtml(3, "提交与轮询", "GET /v1/jobs/{id} 轮询状态", ""),
    stepHtml(4, "下载产物", "GET /v1/jobs/{id}/artifact 下载 GLB", ""),
  ].join("");

  loadModelsIntoSelect();
  bindDropzone();
  bindSeedAndSubmit();

  $("#ws-goto-jobs").addEventListener("click", () => { location.hash = "#jobs"; });
  loadJobs({ silent: true, target: "#ws-recent-body", limit: 5 });
}

function stepHtml(n, title, desc, cls) {
  return `
    <div class="step ${cls}">
      <span class="step-dot"></span>
      <div class="step-body">
        <div class="step-title">${n}. ${escapeHtml(title)}</div>
        <div class="step-desc">${escapeHtml(desc)}</div>
      </div>
    </div>`;
}

async function loadModelsIntoSelect() {
  const select = $("#ws-model");
  if (!select) return;
  select.innerHTML = `<option value="">加载模型中…</option>`;
  try {
    const data = await apiJson("/v1/models");
    state.models = (data.models || []).filter((m) => m.status === "enabled");
    if (!state.models.length) {
      select.innerHTML = `<option value="">无可用模型</option>`;
      return;
    }
    select.innerHTML = state.models
      .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`)
      .join("");
    select.addEventListener("change", () => renderProfilesFor(select.value));
    renderProfilesFor(select.value);
  } catch (e) {
    select.innerHTML = `<option value="">加载失败</option>`;
    toast("加载模型失败: " + e.message, "error");
  }
}

function renderProfilesFor(modelId) {
  const select = $("#ws-profile");
  if (!select) return;
  const model = state.models.find((m) => m.id === modelId);
  const profiles = model?.profiles || [];
  if (!profiles.length) {
    select.innerHTML = `<option value="">无 profile</option>`;
    return;
  }
  select.innerHTML = profiles
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`)
    .join("");
  // default to recommended
  const recommended = profiles.find((p) => p.id === "recommended") || profiles[0];
  if (recommended) select.value = recommended.id;
  updateSubmitEnabled();
}

function bindDropzone() {
  const dz = $("#ws-dropzone");
  const input = $("#ws-file");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("is-dragover"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("is-dragover"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("is-dragover");
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files.length) setFile(input.files[0]);
  });
}

function setFile(file) {
  const valid = ["image/png", "image/jpeg", "image/webp"];
  if (!valid.includes(file.type)) {
    toast("仅支持 PNG / JPEG / WebP", "error");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    toast("图片超过 20 MiB 限制", "error");
    return;
  }
  selectedFile = file;
  if (selectedFileUrl) URL.revokeObjectURL(selectedFileUrl);
  selectedFileUrl = URL.createObjectURL(file);
  $("#ws-dropzone").classList.add("has-file");
  $(".dz-title", $("#ws-dropzone")).textContent = file.name;
  $(".dz-sub", $("#ws-dropzone")).textContent = `${(file.size / 1024).toFixed(1)} KB · ${file.type}`;
  const preview = $("#ws-preview");
  preview.src = selectedFileUrl;
  preview.classList.remove("hidden");
  updateSubmitEnabled();
}

function bindSeedAndSubmit() {
  $("#ws-seed").addEventListener("input", updateSubmitEnabled);
  $("#ws-submit").addEventListener("click", submitJob);
}

function updateSubmitEnabled() {
  const btn = $("#ws-submit");
  if (!btn) return;
  const model = $("#ws-model")?.value;
  const ok = model && selectedFile;
  btn.disabled = !ok;
  const hint = $("#ws-submit-hint");
  if (!ok) {
    hint.textContent = !model ? "请先选择模型" : "请先上传图片";
  } else {
    hint.textContent = "";
  }
}

async function submitJob() {
  const btn = $("#ws-submit");
  const model = $("#ws-model").value;
  const profile = $("#ws-profile").value;
  const seedRaw = $("#ws-seed").value.trim();
  const seed = seedRaw === "" ? 42 : Number(seedRaw);
  if (!model || !selectedFile) return;

  btn.disabled = true;
  btn.textContent = "提交中…";

  const form = new FormData();
  form.append("file", selectedFile);
  form.append("model", model);
  form.append("profile", profile || "recommended");
  form.append("seed", String(seed));

  try {
    const job = await apiJson("/v1/jobs", { method: "POST", body: form });
    toast(`任务已提交: ${job.id}`, "success");
    // reset upload
    selectedFile = null;
    $("#ws-file").value = "";
    $("#ws-dropzone").classList.remove("has-file");
    $(".dz-title", $("#ws-dropzone")).textContent = "点击选择图片，或拖拽到此处";
    $(".dz-sub", $("#ws-dropzone")).textContent = "支持 PNG / JPEG / WebP · 最大 20 MiB";
    $("#ws-preview").classList.add("hidden");
    updateSubmitEnabled();
    await loadJobs({ silent: true, target: "#ws-recent-body", limit: 5 });
  } catch (e) {
    toast("提交失败: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "提交生成";
  }
}

/* ============================================================
   Jobs
   ============================================================ */

async function loadJobs({ silent = false, target = "#jobs-body", limit = null } = {}) {
  const el = $(target);
  if (!el) return;
  try {
    const data = await apiJson("/v1/jobs");
    state.jobs = data.jobs || [];
    renderJobsBody(el, limit);
  } catch (e) {
    if (!silent) el.innerHTML = emptyState("error", "加载失败", e.message);
  }
}

function renderJobs(content) {
  content.dataset.section = "jobs";
  content.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div>
          <h2>生成任务</h2>
          <p class="card-desc">Primary Job —— 监控任务状态，取消或下载产物。</p>
        </div>
        <button class="btn btn-sm btn-ghost" id="jobs-refresh">刷新</button>
      </div>

      <div class="chips mb-4" id="jobs-filters">
        <button class="chip" data-filter="all" aria-pressed="true">全部</button>
        <button class="chip" data-filter="running" aria-pressed="false">运行中</button>
        <button class="chip" data-filter="succeeded" aria-pressed="false">已完成</button>
        <button class="chip" data-filter="failed" aria-pressed="false">失败</button>
        <button class="chip" data-filter="cancelled" aria-pressed="false">已取消</button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务 ID</th>
              <th>模型</th>
              <th>状态</th>
              <th>创建时间</th>
              <th class="num">操作</th>
            </tr>
          </thead>
          <tbody id="jobs-body"><tr><td colspan="5"><div class="state"><span class="spinner"></span><span>加载中…</span></div></td></tr></tbody>
        </table>
      </div>
    </div>
  `;

  $("#jobs-refresh").addEventListener("click", () => loadJobs({ target: "#jobs-body" }));
  $("#jobs-filters").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.jobsFilter = chip.dataset.filter;
    $$(".chip", $("#jobs-filters")).forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    renderJobsBody($("#jobs-body"));
  });

  loadJobs({ target: "#jobs-body" });
}

function renderJobsBody(el, limit = null) {
  let jobs = state.jobs.slice();
  if (state.jobsFilter !== "all") {
    const f = state.jobsFilter;
    jobs = jobs.filter((j) => {
      if (f === "running") return j.status === "running" || j.status === "submitting" || j.status === "connection_required" || j.status === "cancel_requested";
      return j.status === f;
    });
  }
  if (limit != null) jobs = jobs.slice(0, limit);

  if (!jobs.length) {
    el.innerHTML = `<tr><td colspan="5">${emptyState("empty", "暂无任务", "从工作台提交一个生成任务，或在下方用 curl 调用 POST /v1/jobs。")}</td></tr>`;
    return;
  }

  el.innerHTML = jobs.map((j) => `
    <tr>
      <td class="mono truncate" style="max-width:220px" title="${escapeHtml(j.id)}">${escapeHtml(j.id)}</td>
      <td class="mono">${escapeHtml(j.model)}</td>
      <td>${badgeFor(j.status)}</td>
      <td class="muted">${fmtTime(j.created_at)}</td>
      <td class="num">
        <div class="row" style="justify-content:flex-end">
          ${j.status === "succeeded" ? `<button class="btn btn-sm" data-action="download" data-id="${escapeHtml(j.id)}">下载 GLB</button>` : ""}
          ${["running", "submitting", "connection_required", "cancel_requested"].includes(j.status) ? `<button class="btn btn-sm btn-danger" data-action="cancel" data-id="${escapeHtml(j.id)}">取消</button>` : ""}
          <button class="btn btn-sm btn-ghost" data-action="view" data-id="${escapeHtml(j.id)}">详情</button>
        </div>
      </td>
    </tr>
  `).join("");

  el.addEventListener("click", onJobRowAction);
}

function onJobRowAction(e) {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const id = btn.dataset.id;
  const action = btn.dataset.action;
  if (action === "download") downloadArtifact(id);
  else if (action === "cancel") cancelJob(id);
  else if (action === "view") openJobDetail(id);
}

function emptyState(kind, title, desc) {
  const icons = { empty: "○", error: "⚠" };
  return `<div class="state"><div class="state-icon" style="font-size:22px">${icons[kind] || "○"}</div><div class="state-title">${escapeHtml(title)}</div><div class="state-desc">${escapeHtml(desc)}</div></div>`;
}

async function downloadArtifact(id) {
  try {
    const res = await api(`/v1/jobs/${id}/artifact`);
    if (!res.ok) {
      const t = await res.text();
      toast("下载失败: " + (t || res.statusText), "error");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}.glb`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast("下载失败: " + e.message, "error");
  }
}

async function cancelJob(id) {
  if (!confirm(`取消任务 ${id}？`)) return;
  try {
    await apiJson(`/v1/jobs/${id}`, { method: "DELETE" });
    toast("已请求取消", "success");
    await loadJobs({ target: "#jobs-body" });
  } catch (e) {
    toast("取消失败: " + e.message, "error");
  }
}

async function openJobDetail(id) {
  openDrawer(`<div class="drawer-head"><h3>任务详情</h3><button class="btn btn-sm btn-ghost" data-close>关闭</button></div><div id="job-detail-body"><div class="state"><span class="spinner"></span></div></div>`);
  const body = $("#job-detail-body");
  try {
    const job = await apiJson(`/v1/jobs/${id}`);
    body.innerHTML = jobDetailHtml(job);
  } catch (e) {
    body.innerHTML = emptyState("error", "加载失败", e.message);
  }
}

function jobDetailHtml(job) {
  const cond = job.result?.conditioning || null;
  const artifact = job.result?.artifact || null;
  return `
    <div class="row-between mb-3">
      ${badgeFor(job.status)}
      <span class="text-faint" style="font-size:var(--fs-xs)">${escapeHtml(job.id)}</span>
    </div>
    <div class="kv">
      <div class="kv-item"><span class="k">模型</span><span class="v mono">${escapeHtml(job.model)}</span></div>
      <div class="kv-item"><span class="k">Profile</span><span class="v mono">${escapeHtml(job.profile)}</span></div>
      <div class="kv-item"><span class="k">Seed</span><span class="v mono">${escapeHtml(job.seed)}</span></div>
      <div class="kv-item"><span class="k">创建时间</span><span class="v">${fmtTime(job.created_at)}</span></div>
      <div class="kv-item"><span class="k">更新时间</span><span class="v">${fmtTime(job.updated_at)}</span></div>
      ${job.error_code ? `<div class="kv-item"><span class="k">错误码</span><span class="v mono">${escapeHtml(job.error_code)}</span></div>` : ""}
    </div>
    ${cond ? `<div class="mt-4"><div class="text-muted mb-3" style="font-size:var(--fs-sm);font-weight:600">Conditioning（预处理证据）</div><div class="kv">${Object.entries(cond).map(([k, v]) => `<div class="kv-item"><span class="k">${escapeHtml(k)}</span><span class="v mono" style="font-size:var(--fs-xs)">${escapeHtml(v)}</span></div>`).join("")}</div></div>` : ""}
    ${artifact ? `<div class="mt-4"><div class="text-muted mb-3" style="font-size:var(--fs-sm);font-weight:600">产物</div><div class="kv"><div class="kv-item"><span class="k">ID</span><span class="v mono">${escapeHtml(artifact.id)}</span></div><div class="kv-item"><span class="k">SHA256</span><span class="v mono" style="font-size:var(--fs-xs)">${escapeHtml(artifact.sha256)}</span></div><div class="kv-item"><span class="k">字节</span><span class="v">${escapeHtml(artifact.bytes)}</span></div></div><button class="btn btn-primary mt-4" data-dl="${escapeHtml(job.id)}">下载 GLB</button></div>` : ""}
  `;
}

// delegate download from drawer
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-dl]");
  if (btn) {
    const id = btn.dataset.dl;
    closeDrawer();
    downloadArtifact(id);
  }
});

/* ============================================================
   Models
   ============================================================ */

function renderModels(content) {
  content.dataset.section = "models";
  content.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div><h2>可用模型</h2><p class="card-desc">来自 GET /v1/models，字段与 /v1/capabilities 一致。</p></div>
        <button class="btn btn-sm btn-ghost" id="models-refresh">刷新</button>
      </div>
      <div class="grid-cards" id="models-grid"><div class="state"><span class="spinner"></span><span>加载中…</span></div></div>
    </div>
  `;
  $("#models-refresh").addEventListener("click", loadModelsGrid);
  loadModelsGrid();
}

async function loadModelsGrid() {
  const grid = $("#models-grid");
  if (!grid) return;
  try {
    const data = await apiJson("/v1/models");
    state.models = data.models || [];
    if (!state.models.length) {
      grid.innerHTML = emptyState("empty", "暂无模型", "本地 capability 文档未提供任何可用模型。");
      return;
    }
    grid.innerHTML = state.models.map((m) => {
      const profiles = m.profiles || [];
      return `
        <div class="model-card">
          <div class="row-between">
            <span class="model-name">${escapeHtml(m.name || m.id)}</span>
            ${m.status === "enabled" ? '<span class="badge badge-succeeded">enabled</span>' : `<span class="badge badge-neutral">${escapeHtml(m.status)}</span>`}
          </div>
          <span class="model-id">${escapeHtml(m.id)}</span>
          <span class="model-desc">${escapeHtml(m.description || "—")}</span>
          <div class="model-meta">
            <span class="badge badge-neutral">${escapeHtml(m.output || "—")}</span>
            <span class="badge badge-neutral">${profiles.length} profiles</span>
          </div>
        </div>`;
    }).join("");
  } catch (e) {
    grid.innerHTML = emptyState("error", "加载失败", e.message);
  }
}

/* ============================================================
   Connection
   ============================================================ */

function renderConnection(content) {
  content.dataset.section = "connection";
  const demo = state.config?.demo;

  content.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div><h2>连接状态</h2><p class="card-desc">GET /health 与 GET /modal/status。</p></div>
        <span id="conn-badge" class="badge badge-neutral">检测中…</span>
      </div>
      <div class="kv">
        <div class="kv-item"><span class="k">sidecar 状态</span><span class="v" id="conn-health">—</span></div>
        <div class="kv-item"><span class="k">Modal 连接</span><span class="v" id="conn-modal">—</span></div>
        <div class="kv-item"><span class="k">会话令牌要求</span><span class="v" id="conn-token">—</span></div>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h2>Modal 凭据</h2><p class="card-desc">POST /modal/connect —— 用 token_id 与 token_secret 连接你的 Modal 账号。</p></div>
      </div>
      ${demo ? `<div class="alert alert-warn"><span class="alert-title">演示模式</span> 已启用（MODAL_3D_CLIENT_DEMO=1），凭据表单已禁用。</div>` : ""}
      <div class="field">
        <label for="conn-command">直接粘贴整行命令（可自动解析）</label>
        <textarea class="textarea" id="conn-command" rows="2" placeholder='modal token set --token-id ak-xxxx --token-secret as-xxxx' spellcheck="false" ${demo ? "disabled" : ""}></textarea>
        <span class="hint">支持 <code class="mono">modal token set --token-id ... --token-secret ...</code>，粘贴后自动填入下方两个框。</span>
      </div>
      <div class="field">
        <label for="conn-token-id">Token ID</label>
        <input class="input" id="conn-token-id" autocomplete="off" ${demo ? "disabled" : ""} />
      </div>
      <div class="field">
        <label for="conn-token-secret">Token Secret</label>
        <input class="input" id="conn-token-secret" type="password" autocomplete="off" ${demo ? "disabled" : ""} />
      </div>
      <div class="row">
        <button class="btn btn-primary" id="conn-connect" ${demo ? "disabled" : ""}>连接</button>
        <button class="btn btn-danger" id="conn-disconnect" ${demo ? "disabled" : ""}>断开连接</button>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <div><h2>本地会话令牌</h2><p class="card-desc">当设置了 MODAL_3D_CLIENT_TOKEN 时，所有 API 请求需携带 X-Modal-3D-Session 头。</p></div>
      </div>
      <div class="field">
        <label for="conn-session">会话令牌（保存在浏览器 localStorage）</label>
        <input class="input" id="conn-session" type="password" placeholder="未设置则无需填写" value="${escapeHtml(state.token)}" />
        <span class="hint">${state.config?.require_token ? "服务端已启用会话校验，请填写正确的令牌。" : "服务端未启用会话校验，此令牌可选。"}</span>
      </div>
      <button class="btn" id="conn-save-session">保存令牌</button>
    </div>
  `;

  $("#conn-connect").addEventListener("click", connectModal);
  $("#conn-disconnect").addEventListener("click", disconnectModal);
  $("#conn-command").addEventListener("input", parseTokenCommand);
  $("#conn-save-session").addEventListener("click", () => {
    state.token = $("#conn-session").value.trim();
    if (state.token) localStorage.setItem("m3d.session", state.token);
    else localStorage.removeItem("m3d.session");
    toast("会话令牌已保存", "success");
  });

  renderConnStatus();
}

function renderConnStatus() {
  const badge = $("#conn-badge");
  const health = $("#conn-health");
  const modal = $("#conn-modal");
  const token = $("#conn-token");
  if (!badge) return;
  if (state.config?.demo) {
    badge.className = "badge badge-succeeded";
    badge.textContent = "演示模式";
    health.textContent = "ok（演示）";
    modal.textContent = "演示模式（未连接真实 Modal）";
  } else if (state.health == null) {
    badge.className = "badge badge-neutral";
    badge.textContent = "不可达";
    health.textContent = "无法连接 sidecar";
    modal.textContent = "—";
  } else {
    badge.className = "badge " + (state.connected ? "badge-succeeded" : "badge-warn");
    badge.textContent = state.connected ? "已连接" : "未连接";
    health.textContent = state.health.ok ? "ok" : "异常";
    modal.textContent = state.health.modal_connected ? "已连接" : "未连接";
  }
  token.textContent = state.config?.require_token ? "需要 X-Modal-3D-Session" : "无需令牌";
}

function parseTokenCommand() {
  const raw = $("#conn-command").value;
  const match = /--token-id\s+(\S+)/.exec(raw);
  const secretMatch = /--token-secret\s+(\S+)/.exec(raw);
  let changed = false;
  if (match) {
    const id = match[1].replace(/["']/g, "");
    if (id && id !== $("#conn-token-id").value) {
      $("#conn-token-id").value = id;
      changed = true;
    }
  }
  if (secretMatch) {
    const secret = secretMatch[1].replace(/["']/g, "");
    if (secret && secret !== $("#conn-token-secret").value) {
      $("#conn-token-secret").value = secret;
      changed = true;
    }
  }
  if (changed) {
    $("#conn-command").classList.add("is-parsed");
    toast("已从命令中解析出 Token ID / Secret，请确认后点击「连接」", "success");
  }
}

async function connectModal() {
  const tokenId = $("#conn-token-id").value.trim();
  const tokenSecret = $("#conn-token-secret").value.trim();
  if (!tokenId || !tokenSecret) { toast("请填写 Token ID 与 Secret", "error"); return; }
  try {
    await apiJson("/modal/connect", { method: "POST", body: { token_id: tokenId, token_secret: tokenSecret } });
    toast("Modal 连接成功", "success");
    await refreshHealth();
    renderConnStatus();
  } catch (e) {
    toast("连接失败: " + e.message, "error");
  }
}

async function disconnectModal() {
  try {
    await apiJson("/modal/connect", { method: "DELETE" });
    toast("已断开 Modal 连接", "success");
    await refreshHealth();
    renderConnStatus();
  } catch (e) {
    toast("断开失败: " + e.message, "error");
  }
}

/* ============================================================
   API reference
   ============================================================ */

const API_ENDPOINTS = [
  { method: "GET", path: "/health", summary: "sidecar 存活与 Modal 连接状态", detail: "返回 { ok, modal_connected }。无需凭据。", curl: "curl http://127.0.0.1:3213/health" },
  { method: "GET", path: "/modal/status", summary: "Modal 连接状态", detail: "返回 { connected }。", curl: "curl http://127.0.0.1:3213/modal/status" },
  { method: "POST", path: "/modal/connect", summary: "连接 Modal 账号", detail: "JSON body: { token_id, token_secret }。成功后 GET /health 的 modal_connected 变为 true。", curl: "curl -X POST http://127.0.0.1:3213/modal/connect \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"token_id\":\"...\",\"token_secret\":\"...\"}'" },
  { method: "DELETE", path: "/modal/connect", summary: "断开 Modal 连接", detail: "清除本地 Modal 客户端会话。", curl: "curl -X DELETE http://127.0.0.1:3213/modal/connect" },
  { method: "GET", path: "/v1/capabilities", summary: "完整 capability 文档", detail: "返回 provider 的 contract / generation / models 全量文档。需要 Modal 已连接。", curl: "curl http://127.0.0.1:3213/v1/capabilities" },
  { method: "GET", path: "/v1/models", summary: "可用模型列表", detail: "返回 { models: [...] }，仅 enabled 模型。", curl: "curl http://127.0.0.1:3213/v1/models" },
  { method: "GET", path: "/v1/jobs", summary: "列出任务", detail: "返回 { jobs: [...] }，按创建时间倒序，可传 ?limit=50（上限 200）。", curl: "curl 'http://127.0.0.1:3213/v1/jobs?limit=20'" },
  { method: "POST", path: "/v1/jobs", summary: "提交生成任务", detail: "multipart: file（PNG/JPEG/WebP）+ model + profile + seed + 可选 job_id。", curl: "curl -X POST http://127.0.0.1:3213/v1/jobs \\\n  -F 'file=@source.png' \\\n  -F 'model=fastsam3d-plus-plus' \\\n  -F 'profile=recommended' \\\n  -F 'seed=42'" },
  { method: "GET", path: "/v1/jobs/{id}", summary: "查询任务状态", detail: "返回单个 job 的完整 public 状态（含 result / conditioning）。", curl: "curl http://127.0.0.1:3213/v1/jobs/job_xxx" },
  { method: "DELETE", path: "/v1/jobs/{id}", summary: "取消任务", detail: "请求取消；最终状态变为 cancelled（或已终态则直接返回）。", curl: "curl -X DELETE http://127.0.0.1:3213/v1/jobs/job_xxx" },
  { method: "GET", path: "/v1/jobs/{id}/artifact", summary: "下载 GLB 产物", detail: "成功时返回 model/gltf-binary 文件，带 ETag 与 X-Artifact-SHA256 头。", curl: "curl -o asset.glb http://127.0.0.1:3213/v1/jobs/job_xxx/artifact" },
];

function renderApi(content) {
  content.dataset.section = "api";
  content.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div><h2>接口一览</h2><p class="card-desc">所有可被 curl 调用的端点。点击展开详情与示例。</p></div>
      </div>
      <div id="api-list">${API_ENDPOINTS.map(apiItemHtml).join("")}</div>
    </div>
  `;
  $("#api-list").addEventListener("click", (e) => {
    const head = e.target.closest(".api-item-head");
    if (!head) return;
    toggleApiItem(head);
  });
  $("#api-list").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const head = e.target.closest(".api-item-head");
    if (!head) return;
    e.preventDefault();
    toggleApiItem(head);
  });
}

function toggleApiItem(head) {
  const item = head.closest(".api-item");
  const body = $(".api-item-body", item);
  body.hidden = !body.hidden;
}

function apiItemHtml(ep) {
  const methodClass = "method-" + ep.method.toLowerCase();
  return `
    <div class="api-item">
      <div class="api-item-head" role="button" tabindex="0">
        <span class="method ${methodClass}">${ep.method}</span>
        <span class="api-path">${escapeHtml(ep.path)}</span>
        <span class="api-summary">${escapeHtml(ep.summary)}</span>
      </div>
      <div class="api-item-body" hidden>
        <div class="text-muted" style="font-size:var(--fs-sm)">${escapeHtml(ep.detail)}</div>
        <div class="code-block">${escapeHtml(ep.curl)}</div>
      </div>
    </div>`;
}

/* ============================================================
   start
   ============================================================ */

boot();
