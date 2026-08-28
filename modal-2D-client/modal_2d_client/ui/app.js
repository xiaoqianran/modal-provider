/* modal-2D Agent Console
 *
 * 目的：把 modal-2D-client 本地 HTTP API 的每一个端点显式暴露成一个可执行的步骤，
 * 并让每一步都显示它真实发出的 curl。这里没有业务抽象——它就是这个 API 的镜像。
 *
 * 约束：纯 ES2020，无依赖、无构建步骤。
 */
'use strict';

/* ── API 清单：唯一事实来源 ─────────────────────────────────────────────
 * 每个端点的 method / path / note 都对应 app.py 中的真实路由。
 * path 中的 {name} 会在请求时替换为具体值。
 */
const ENDPOINTS = {
  health:          { method: 'GET',    path: '/health',                          note: '进程存活 + 连接态' },
  modalStatus:     { method: 'GET',    path: '/modal/status',                    note: '只读连接状态' },
  modalConnect:    { method: 'POST',   path: '/modal/connect',                   note: '凭据只进内存' },
  modalDisconnect: { method: 'DELETE', path: '/modal/connect',                   note: '丢弃进程内 client' },
  capabilities:    { method: 'GET',    path: '/v1/capabilities',                 note: '客户端独立校验契约' },
  models:          { method: 'GET',    path: '/v1/models',                       note: '来自能力文档' },
  submitJob:       { method: 'POST',   path: '/v1/jobs',                         note: '异步返回，非阻塞' },
  listJobs:        { method: 'GET',    path: '/v1/jobs?limit=50',                note: '本地 SQLite 镜像' },
  getJob:          { method: 'GET',    path: '/v1/jobs/{jobId}',                 note: '推进远端状态机' },
  cancelJob:       { method: 'DELETE', path: '/v1/jobs/{jobId}',                 note: '尽力而为' },
  artifact:        { method: 'GET',    path: '/v1/jobs/{jobId}/artifact',        note: '单图 Job' },
  batchArtifact:   { method: 'GET',    path: '/v1/jobs/{jobId}/artifacts/{index}', note: '按索引取候选' },
};

const STEP_ENDPOINTS = {
  1: ['health', 'modalStatus', 'modalConnect', 'modalDisconnect'],
  2: ['capabilities', 'models'],
  3: ['submitJob'],
  4: ['listJobs', 'getJob', 'cancelJob'],
  5: ['artifact', 'batchArtifact'],
};

const STEPS = [
  { id: 1, label: '连接 Modal',   short: 'Connect',     tone: 'connect' },
  { id: 2, label: '确认能力',     short: 'Capabilities',tone: 'capability' },
  { id: 3, label: '提交 Job',     short: 'Generate',    tone: 'generate' },
  { id: 4, label: '跟踪 Job',     short: 'Track',       tone: 'track' },
  { id: 5, label: '取出产物',     short: 'Artifact',    tone: 'artifact' },
];

const TERMINAL = ['succeeded', 'failed', 'cancelled', 'expired'];
const POLL_MS = 2000;
const SESSION_KEY = 'modal2d.session';

/* ── 运行时状态 ───────────────────────────────────────────────────────── */
const state = {
  step: 1,
  connected: null,      // null = 未知
  online: true,
  capabilities: null,
  models: [],
  jobs: [],
  selectedJobId: null,
  jobDetail: null,
  artifactIndex: 0,
  artifactBlobUrl: null,
  logs: [],
  epRuntime: {},        // epId -> { path, curl, curlMasked }
  inflight: new Set(),
};

/* ── 工具 ─────────────────────────────────────────────────────────────── */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(value) {
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function escShell(value) {
  return String(value).replace(/'/g, `'\\''`);
}

function pretty(value) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function isTerminal(status) {
  return TERMINAL.includes(status);
}

/* ── 会话令牌 ─────────────────────────────────────────────────────────── */
function getSession() {
  try { return sessionStorage.getItem(SESSION_KEY) || ''; } catch { return ''; }
}
function setSession(value) {
  try {
    if (value) sessionStorage.setItem(SESSION_KEY, value);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch { /* 隐私模式下不可用，忽略 */ }
}

/* ── curl 渲染 ────────────────────────────────────────────────────────── */
function renderCurl({ method, url, headers, body, secrets = [], masked = false }) {
  const parts = ['curl'];
  if (method !== 'GET') parts.push(`-X ${method}`);

  let renderedUrl = url;
  let renderedBody = body;
  let renderedHeaders = { ...headers };

  if (masked) {
    for (const secret of secrets) {
      if (!secret) continue;
      renderedUrl = renderedUrl.split(secret).join('***');
      if (renderedBody) renderedBody = renderedBody.split(secret).join('***');
      for (const key of Object.keys(renderedHeaders)) {
        renderedHeaders[key] = String(renderedHeaders[key]).split(secret).join('***');
      }
    }
  }

  parts.push(`'${escShell(renderedUrl)}'`);
  for (const [key, value] of Object.entries(renderedHeaders)) {
    parts.push(`-H '${escShell(key)}: ${escShell(value)}'`);
  }
  if (renderedBody !== undefined && renderedBody !== null) {
    parts.push(`-d '${escShell(renderedBody)}'`);
  }
  return parts.join(' \\\n  ');
}

/* ── 请求 ─────────────────────────────────────────────────────────────── */
async function api(epId, opts = {}) {
  const ep = ENDPOINTS[epId];
  if (!ep) throw new Error(`unknown endpoint: ${epId}`);

  const params = opts.params || {};
  const url = new URL(
    ep.path.replace(/\{(\w+)\}/g, (_, key) => encodeURIComponent(params[key] ?? `{${key}}`)),
    window.location.origin,
  );

  const headers = {};
  const session = getSession();
  if (session) headers['X-Modal-2D-Session'] = session;

  let body;
  const secrets = [];
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
    for (const key of ['token_id', 'token_secret']) {
      if (typeof opts.body[key] === 'string' && opts.body[key]) secrets.push(opts.body[key]);
    }
  }
  if (session) secrets.push(session);

  const curl      = renderCurl({ method: ep.method, url: url.toString(), headers, body, secrets });
  const curlMasked = renderCurl({ method: ep.method, url: url.toString(), headers, body, secrets, masked: true });

  // 端点行更新为具体路径，让"这一步在调用什么"始终是真实值。
  state.epRuntime[epId] = { path: url.pathname + url.search, curl, curlMasked };

  const entry = {
    id: `log-${state.logs.length}-${Date.now()}`,
    epId,
    method: ep.method,
    path: url.pathname + url.search,
    curl,
    curlMasked,
    time: new Date(),
    status: null,
    ms: null,
    responseText: '',
    error: null,
  };
  state.logs.unshift(entry);
  if (state.logs.length > 50) state.logs.pop();
  renderLog();

  const key = `${ep.method} ${url.pathname}`;
  state.inflight.add(key);
  renderStep(epId);

  const started = performance.now();
  try {
    const response = await fetch(url.toString(), {
      method: ep.method,
      headers,
      body,
      cache: 'no-store',
    });
    entry.ms = Math.round(performance.now() - started);
    entry.status = response.status;

    if (opts.expectBinary) {
      await readBinary(entry, response);
    } else {
      const text = await response.text();
      entry.responseText = text;
      let parsed = null;
      try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
      if (!response.ok) {
        const detail = parsed && parsed.detail ? parsed.detail : (text || response.statusText);
        entry.error = `HTTP ${response.status} · ${detail}`;
      }
      if (opts.step) setResponse(opts.step, entry, parsed);
      // body 已被消费，调用方只能用此处解析好的数据，不能再 response.json()。
      entry.parsedData = parsed;
    }
    state.online = true;
    renderOffline();
    // 返回 entry 引用：调用方不能用 logs[0] 猜——轮询可能已插入更新的日志。
    return { ok: response.ok, status: response.status, data: entry.parsedData, response, entry };
  } catch (err) {
    entry.ms = Math.round(performance.now() - started);
    entry.error = err instanceof Error ? err.message : String(err);
    state.online = false;
    renderOffline(entry.error);
    if (opts.step) setResponse(opts.step, entry, null);
    throw err;
  } finally {
    state.inflight.delete(key);
    renderLogEntry(entry);
    renderStep(epId);
    renderEndpoints();
  }
}

async function readBinary(entry, response) {
  const headerSha = response.headers.get('x-artifact-sha256');
  const headerId = response.headers.get('x-artifact-id');
  const etag = response.headers.get('etag');
  const summary = {
    note: '<binary PNG>',
    bytes: Number(response.headers.get('content-length') || 0),
    headers: { 'content-type': response.headers.get('content-type'), etag, 'x-artifact-id': headerId, 'x-artifact-sha256': headerSha },
  };
  if (!response.ok) {
    const text = await response.text();
    entry.responseText = text;
    entry.error = `HTTP ${response.status} · ${text || response.statusText}`;
    return;
  }
  const blob = await response.blob();
  entry.responseText = JSON.stringify(summary, null, 2);
  entry.blob = blob;
  entry.headerSha = headerSha;
  entry.headerId = headerId;
}

function setResponse(step, entry, parsed) {
  const el = $(`[data-step-response="${step}"]`);
  if (!el) return;
  const payload = parsed ?? (entry.responseText ? safeParse(entry.responseText) : null);
  const statusLine = entry.status === null
    ? `${entry.method} ${entry.path} · 网络失败`
    : `${entry.method} ${entry.path} → ${entry.status} · ${entry.ms}ms`;
  el.textContent = entry.error
    ? `${statusLine}\n${entry.error}\n${payload ? '\n' + pretty(payload) : ''}`
    : `${statusLine}\n\n${pretty(payload)}`;
  el.dataset.state = entry.error ? 'err' : 'ok';
}

function safeParse(text) {
  try { return JSON.parse(text); } catch { return text; }
}

/* ── 渲染：步骤条 ─────────────────────────────────────────────────────── */
function renderHero() {
  const nav = $('#hero-recs');
  if (!nav) return;
  nav.innerHTML = STEPS.map((step) => {
    const done = isStepDone(step.id);
    return `
      <button class="rec-card" data-tone="${step.tone}" data-step="${step.id}"
              data-done="${done}" type="button">
        <small>${done ? 'DONE' : '0' + step.id}</small>
        <strong>${esc(step.label)}</strong>
      </button>`;
  }).join('');
}

function isStepDone(stepId) {
  if (stepId === 1) return state.connected === true;
  if (stepId === 2) return Boolean(state.capabilities);
  if (stepId === 3) return state.jobs.length > 0;
  if (stepId === 4) return state.jobs.some((j) => j.status === 'succeeded');
  if (stepId === 5) return Boolean(state.artifactBlobUrl);
  return false;
}

function renderStep(changedEpId) {
  if (changedEpId) renderEndpoints();
  renderHero();
}

function showStep(stepId) {
  state.step = stepId;
  const section = $(`#step-${stepId}`);
  if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  // 懒加载：进入对应区块时拉取一次数据
  if (stepId === 2 && !state.capabilities) refreshCapabilities({ silent: true });
  if (stepId === 4 && state.jobs.length === 0) listJobs({ silent: true });
}

/* ── 渲染：端点清单 ───────────────────────────────────────────────────── */
function renderEndpoints() {
  $$('.eps').forEach((container) => {
    const ids = (container.dataset.eps || '').split(',').map((s) => s.trim()).filter(Boolean);
    container.innerHTML = ids.map((id) => {
      const ep = ENDPOINTS[id];
      const runtime = state.epRuntime[id];
      const path = runtime ? runtime.path : ep.path;
      const busy = state.inflight.has(`${ep.method} ${new URL(ep.path.replace(/\{\w+\}/g, 'x'), window.location.origin).pathname}`);
      return `
        <div class="ep">
          <span class="ep-method" data-method="${ep.method}">${ep.method}</span>
          <span class="ep-path" title="${esc(path)}">${esc(path)}${busy ? ' <span class="dim">· 请求中</span>' : ''}</span>
          <span class="ep-note">${esc(ep.note)}</span>
        </div>`;
    }).join('');
  });
}

/* ── 渲染：请求日志 ───────────────────────────────────────────────────── */
function renderLog() {
  const body = $('#log-body');
  const empty = $('#log-empty');
  $('#log-count').textContent = String(state.logs.length);
  if (state.logs.length === 0) {
    body.innerHTML = '<div class="empty" id="log-empty">还没有请求。从第 1 步开始。</div>';
    return;
  }
  body.innerHTML = state.logs.map((entry) => logEntryHtml(entry)).join('');
  bindLogToggles();
}

function logEntryHtml(entry) {
  const masked = !$('#show-secrets').checked;
  const curlText = masked ? entry.curlMasked : entry.curl;
  const statusClass = entry.status === null ? '' : entry.status >= 400 ? 'err' : 'ok';
  const statusBadge = entry.status === null
    ? '<span class="badge" data-status="failed">ERR</span>'
    : `<span class="badge" data-status="${entry.status >= 400 ? 'failed' : 'succeeded'}">${entry.status}</span>`;
  return `
    <div class="log-entry" data-id="${entry.id}" data-open="false">
      <button class="log-head" type="button">
        ${statusBadge}
        <span class="ep-method" data-method="${entry.method}">${entry.method}</span>
        <span class="log-path" title="${esc(entry.path)}">${esc(entry.path)}</span>
        <span class="log-time">${entry.ms === null ? '' : entry.ms + 'ms · '}${formatTime(entry.time.toISOString())}</span>
        <span class="log-chev" aria-hidden="true">›</span>
      </button>
      <div class="log-detail" hidden>
        <div class="log-row">
          <span class="log-row-key">curl${masked ? '（已脱敏）' : ''}</span>
          <pre class="code">${esc(curlText)}</pre>
        </div>
        <div class="log-row">
          <span class="log-row-key">响应</span>
          <pre class="code" data-role="log-response">${esc(entry.error ? entry.error + '\n' + entry.responseText : entry.responseText || '(空)')}</pre>
        </div>
      </div>
    </div>`;
}

function renderLogEntry(entry) {
  const el = $(`.log-entry[data-id="${entry.id}"]`);
  if (!el) { renderLog(); return; }
  el.outerHTML = logEntryHtml(entry);
  bindLogToggles();
}

function bindLogToggles() {
  $$('.log-entry .log-head').forEach((head) => {
    if (head.dataset.bound === 'true') return;
    head.dataset.bound = 'true';
    head.addEventListener('click', () => {
      const entryEl = head.closest('.log-entry');
      const open = entryEl.dataset.open === 'true';
      entryEl.dataset.open = String(!open);
      $('.log-detail', entryEl).hidden = open;
    });
  });
}

/* ── 渲染：连接状态 ───────────────────────────────────────────────────── */
function renderConnection() {
  const pill = $('#conn-pill');
  const text = $('#conn-pill-text');
  if (state.connected === null) {
    pill.dataset.state = 'unknown';
    text.textContent = '状态未知 · 检查会话令牌';
  } else if (state.connected) {
    pill.dataset.state = 'ok';
    text.textContent = 'Modal 已连接';
  } else {
    pill.dataset.state = 'idle';
    text.textContent = 'Modal 未连接';
  }
}

function renderOffline(message) {
  const banner = $('#offline-banner');
  if (state.online) { banner.hidden = true; return; }
  banner.hidden = false;
  $('#offline-text').textContent = message
    ? `无法访问 Agent：${message}（确认 uv run modal-2d-agent 正在运行）`
    : '无法访问 Agent（确认 uv run modal-2d-agent 正在运行）';
}

function renderSession() {
  const session = getSession();
  $('#session-state').textContent = session ? '已设置' : '未设置';
  $('#session-state').dataset.set = String(Boolean(session));
  $('#session-input').value = '';
}

/* ── 步骤 1：连接 ─────────────────────────────────────────────────────── */
async function checkHealth() {
  try {
    const res = await api('health', { step: 1 });
    // 401/网络失败 = 无从得知状态，不能谎报"未连接"。
    if (!res.ok) {
      state.connected = null;
    } else {
      state.connected = Boolean(res.data && res.data.modal_connected);
    }
  } catch {
    state.connected = null;
  }
  renderConnection();
  renderStep();
}

function parseTokenCommand(command) {
  // 从整条 `modal token set --token-id X --token-secret Y` 命令里提取 id 与密钥。
  const result = { token_id: '', token_secret: '' };
  if (!command) return result;
  const idMatch = command.match(/--token-id\s+(\S+)/i);
  const secretMatch = command.match(/--token-secret\s+(\S+)/i);
  if (idMatch) result.token_id = idMatch[1].replace(/[;'"&|`]/g, '');
  if (secretMatch) result.token_secret = secretMatch[1].replace(/[;'"&|`]/g, '');
  return result;
}

function parseTokenCommandIntoFields() {
  const command = $('#token-command').value.trim();
  const hint = $('#token-command-hint');
  const parsed = parseTokenCommand(command);
  if (!parsed.token_id && !parsed.token_secret) {
    hint.textContent = '未识别到 token。请粘贴整条命令，例如 modal token set --token-id ak-… --token-secret as-…';
    return;
  }
  if (parsed.token_id) $('#token-id').value = parsed.token_id;
  if (parsed.token_secret) $('#token-secret').value = parsed.token_secret;
  const parts = [];
  if (parsed.token_id) parts.push(`id ${parsed.token_id.slice(0, 8)}…`);
  if (parsed.token_secret) parts.push(`密钥 ${parsed.token_secret.slice(0, 8)}…`);
  hint.textContent = `已填入 ${parts.join('、')}。`;
  $('#token-command').value = '';
}

async function connect() {
  const tokenId = $('#token-id').value.trim();
  const tokenSecret = $('#token-secret').value.trim();
  if (!tokenId || !tokenSecret) {
    toast('请填写 token_id 与 token_secret', 'err');
    return;
  }
  try {
    await api('modalConnect', { body: { token_id: tokenId, token_secret: tokenSecret }, step: 1 });
    state.connected = true;
    $('#token-id').value = '';
    $('#token-secret').value = '';
    toast('已连接 Modal', 'ok');
    await refreshCapabilities();
  } catch (err) {
    state.connected = false;
    toast('连接失败，见响应面板', 'err');
  }
  renderConnection();
  renderStep();
}

async function disconnect() {
  try {
    await api('modalDisconnect', { step: 1 });
    state.connected = false;
    state.capabilities = null;
    state.models = [];
    renderCapabilities();
    toast('已断开');
  } catch { /* 已在响应面板呈现 */ }
  renderConnection();
  renderStep();
}

/* ── 步骤 2：能力 ─────────────────────────────────────────────────────── */
async function refreshCapabilities({ silent = false } = {}) {
  try {
    const res = await api('capabilities', { step: 2 });
    if (!res.ok) throw new Error('capabilities 请求失败');
    state.capabilities = res.data;
    renderCapabilities();
    await refreshModels({ silent: true });
    if (!silent) toast('能力文档已更新', 'ok');
  } catch {
    if (!silent) toast('拉取能力失败（Modal 未连接？）', 'err');
  }
  renderStep();
}

function renderCapabilities() {
  const summary = $('#contract-summary');
  const empty = $('#capability-empty');
  const rawWrap = $('#capability-raw-wrap');
  const doc = state.capabilities;

  if (!doc) {
    summary.innerHTML = '';
    empty.hidden = false;
    rawWrap.hidden = true;
    return;
  }
  empty.hidden = true;
  rawWrap.hidden = false;

  const gen = doc.generation || {};
  const art = doc.artifact || {};
  const exec = doc.execution || {};
  const rows = [
    ['contract', doc.contract],
    ['operation', doc.operation],
    ['kind', doc.kind],
    ['app / worker', `${gen.app} · ${gen.worker_class}`],
    ['batch', `${gen.batch_generate_method || '—'} · max ${gen.batch_max_size ?? '—'}`],
    ['job transport', gen.job_transport],
    ['artifact volume', gen.artifact_volume],
    ['execution', `${exec.mode || '—'}${exec.cancellable ? ' · cancellable' : ''}`],
    ['artifact', `${art.mime || '—'}${art.lossless ? ' · lossless' : ''}`],
  ];
  summary.innerHTML = rows.map(([k, v]) => `
    <div class="metric">
      <span>${esc(k)}</span>
      <strong>${esc(v ?? '—')}</strong>
    </div>`).join('');
  $('#capability-raw').textContent = pretty(doc);
}

async function refreshModels({ silent = false } = {}) {
  try {
    const res = await api('models', { step: 2 });
    if (!res.ok) throw new Error('models 请求失败');
    state.models = Array.isArray(res.data && res.data.models) ? res.data.models : [];
    renderModels();
    if (!silent) toast('模型列表已刷新', 'ok');
  } catch {
    if (!silent) toast('拉取模型失败', 'err');
  }
}

function renderModels() {
  const wrap = $('#models-wrap');
  const body = $('#models-body');
  const select = $('#model-select');
  const current = select.value;

  if (state.models.length === 0) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  body.innerHTML = state.models.map((m) => {
    const profile = Array.isArray(m.profiles) && m.profiles[0] ? m.profiles[0] : {};
    return `
      <tr>
        <td class="cell-id" title="${esc(m.id)}">${esc(m.id)}</td>
        <td>${esc(m.parameters || '—')}</td>
        <td>${esc(profile.steps ?? m.steps ?? '—')}</td>
        <td>${esc(profile.guidance ?? m.guidance ?? '—')}</td>
        <td>${esc(m.width ?? '—')}×${esc(m.height ?? '—')}</td>
      </tr>`;
  }).join('');

  select.innerHTML = state.models
    .map((m) => `<option value="${esc(m.id)}">${esc(m.name || m.id)} · ${esc(m.id)}</option>`)
    .join('');
  if (state.models.some((m) => m.id === current)) select.value = current;
  else if (state.models.some((m) => m.id === 'sana-sprint-1.6b')) select.value = 'sana-sprint-1.6b';
}

/* ── 步骤 3：提交 ─────────────────────────────────────────────────────── */
function parseSeeds(raw) {
  const parts = raw.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) return null;
  const seeds = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    const value = Number(part);
    if (!Number.isSafeInteger(value) || value < 0 || value > 4294967295) return null;
    seeds.push(value);
  }
  if (seeds.length > 8) return null;
  if (new Set(seeds).size !== seeds.length) return null;
  return seeds;
}

function currentMode() {
  const active = $('#mode-tabs .tab.is-active');
  return active ? active.dataset.mode : 'single';
}

function buildSubmitBody() {
  const prompt = $('#prompt').value.trim();
  const body = { prompt, model: $('#model-select').value || 'sana-sprint-1.6b' };

  if (currentMode() === 'batch') {
    const seeds = parseSeeds($('#seeds').value);
    if (!seeds) throw new Error('seeds 需为 1–8 个不重复的整数（0 – 4294967295）');
    body.seeds = seeds;
  } else {
    const seed = Number($('#seed').value);
    if (!Number.isSafeInteger(seed) || seed < 0 || seed > 4294967295) {
      throw new Error('seed 需为 0 – 4294967295 的整数');
    }
    body.seed = seed;
  }

  const guidance = $('#guidance').value.trim();
  if (guidance !== '') {
    const value = Number(guidance);
    if (!Number.isFinite(value) || value < 0 || value > 20) throw new Error('guidance 需在 0 – 20 之间');
    body.guidance = value;
  }
  const jobId = $('#job-id').value.trim();
  if (jobId) body.job_id = jobId;
  return body;
}

async function submitJob() {
  const errorLine = $('#submit-error');
  errorLine.hidden = true;
  if (!$('#prompt').value.trim()) {
    errorLine.textContent = '请先填写 prompt。';
    errorLine.hidden = false;
    return;
  }
  let body;
  try {
    body = buildSubmitBody();
  } catch (err) {
    errorLine.textContent = err.message;
    errorLine.hidden = false;
    return;
  }

  try {
    const res = await api('submitJob', { body, step: 3 });
    const job = res.data;
    if (!res.ok) {
      errorLine.textContent = (job && job.detail) || `提交失败（HTTP ${res.status}）`;
      errorLine.hidden = false;
      return;
    }
    state.selectedJobId = job.id;
    state.artifactIndex = 0;
    toast(`Job 已提交 · ${job.id}`, 'ok');
    await listJobs({ silent: true });
    showStep(4);
    startPolling();
  } catch {
    errorLine.textContent = '提交失败，见下方响应面板。';
    errorLine.hidden = false;
  }
}

/* ── 步骤 4：跟踪 ─────────────────────────────────────────────────────── */
async function listJobs({ silent = false } = {}) {
  const body = $('#jobs-body');
  try {
    if (!silent) body.innerHTML = '<tr><td colspan="5"><div class="skeleton"></div></td></tr>';
    const res = await api('listJobs', { step: 4 });
    if (!res.ok) throw new Error('jobs 请求失败');
    state.jobs = Array.isArray(res.data && res.data.jobs) ? res.data.jobs : [];
    renderJobs();
  } catch {
    if (!silent) toast('拉取 Job 列表失败', 'err');
    renderJobs();
  }
  renderStep();
}

function renderJobs() {
  const body = $('#jobs-body');
  const empty = $('#jobs-empty');

  if (state.jobs.length === 0) {
    body.innerHTML = '';
    empty.hidden = false;
    renderJobDetail();
    return;
  }
  empty.hidden = true;
  body.innerHTML = state.jobs.map((job) => {
    const selected = job.id === state.selectedJobId ? ' class="is-selected"' : '';
    const canCancel = !isTerminal(job.status) && job.status !== 'cancel_requested';
    return `
      <tr${selected} data-job-id="${esc(job.id)}">
        <td class="cell-id" title="${esc(job.id)}">${esc(job.id)}</td>
        <td>${esc(job.model || '—')}</td>
        <td><span class="badge" data-status="${esc(job.status)}">${esc(job.status)}</span></td>
        <td class="cell-time">${esc(formatTime(job.created_at))}</td>
        <td class="cell-actions">
          <button class="btn ${canCancel ? 'danger' : 'ghost'} sm" data-action="cancel" ${canCancel ? '' : 'disabled'}>
            ${isTerminal(job.status) ? '已结束' : '取消'}
          </button>
        </td>
      </tr>`;
  }).join('');
  renderJobDetail();
}

function selectJob(jobId) {
  state.selectedJobId = jobId;
  state.artifactIndex = 0;
  renderJobs();
  pollJob({ silent: true });
  startPolling();
}

function renderJobDetail() {
  const wrap = $('#job-detail');
  const job = state.jobs.find((j) => j.id === state.selectedJobId);
  if (!job) { wrap.hidden = true; return; }
  wrap.hidden = false;
  $('#job-detail-id').textContent = job.id;

  const canCancel = !isTerminal(job.status) && job.status !== 'cancel_requested';
  $('#btn-cancel-job').disabled = !canCancel;

  const rows = [
    ['status', job.status],
    ['model', job.model],
    ['retryable', job.retryable === null ? '—' : String(job.retryable)],
    ['error_code', job.error_code],
    ['created', formatTime(job.created_at)],
    ['updated', formatTime(job.updated_at)],
  ];
  $('#job-kv').innerHTML = rows.map(([k, v]) => `
    <div class="metric">
      <span>${esc(k)}</span>
      <strong>${esc(v ?? '—')}</strong>
    </div>`).join('');

  $('#job-raw').textContent = pretty(job);
  $('#job-success-cta').hidden = job.status !== 'succeeded';

  const artifacts = job.result && Array.isArray(job.result.artifacts) ? job.result.artifacts : null;
  if (artifacts) {
    const timing = job.result.timing || {};
    $('#job-raw').textContent = pretty(job);
    if (timing.batch_total_ms !== undefined) {
      $('#job-success-cta').hidden = false;
      $('#job-success-cta').firstElementChild.textContent =
        `Job 已完成 · ${artifacts.length} 个候选 · ${Math.round(timing.batch_total_ms)}ms`;
    }
  }
}

async function pollJob({ silent = false } = {}) {
  if (!state.selectedJobId) return;
  try {
    const res = await api('getJob', { params: { jobId: state.selectedJobId }, step: 4 });
    if (!res.ok) return;
    const job = res.data;
    const index = state.jobs.findIndex((j) => j.id === job.id);
    if (index >= 0) state.jobs[index] = job; else state.jobs.unshift(job);
    renderJobs();
    if (job.status === 'succeeded' && !silent) toast(`Job 完成 · ${job.id}`, 'ok');
    if (isTerminal(job.status)) stopPolling();
  } catch { /* 已在响应面板呈现 */ }
}

async function cancelJob() {
  if (!state.selectedJobId) return;
  try {
    await api('cancelJob', { params: { jobId: state.selectedJobId }, step: 4 });
    toast('已请求取消（尽力而为）');
    await pollJob({ silent: true });
  } catch { /* 已在响应面板呈现 */ }
}

/* ── 步骤 5：产物 ─────────────────────────────────────────────────────── */
function selectedArtifactCount() {
  const job = state.jobs.find((j) => j.id === state.selectedJobId);
  if (!job || !job.result) return 0;
  if (Array.isArray(job.result.artifacts)) return job.result.artifacts.length;
  if (job.result.artifact) return 1;
  return 0;
}

function selectedDescriptor(index) {
  const job = state.jobs.find((j) => j.id === state.selectedJobId);
  if (!job || !job.result) return null;
  if (Array.isArray(job.result.artifacts)) return job.result.artifacts[index] || null;
  if (job.result.artifact && index === 0) return job.result.artifact;
  return null;
}

async function loadArtifact(index) {
  const count = selectedArtifactCount();
  if (count === 0) return;
  state.artifactIndex = Math.max(0, Math.min(index, count - 1));
  renderArtifactIndex();

  const isBatch = count > 1;
  const epId = isBatch ? 'batchArtifact' : 'artifact';
  const params = isBatch
    ? { jobId: state.selectedJobId, index: state.artifactIndex }
    : { jobId: state.selectedJobId };

  setVerify('unknown', '校验中…');
  try {
    const res = await api(epId, { params, expectBinary: true, step: 5 });
    if (!res.ok) {
      setVerify('err', `取出失败 · HTTP ${res.status}`);
      return;
    }
    // 用返回的 entry 引用，而不是 state.logs[0]：
    // 自动轮询可能已插入更新的日志条目。
    const entry = res.entry;
    if (!entry || !entry.blob) { setVerify('err', '响应不是二进制'); return; }

    if (state.artifactBlobUrl) URL.revokeObjectURL(state.artifactBlobUrl);
    state.artifactBlobUrl = URL.createObjectURL(entry.blob);

    const img = $('#artifact-img');
    img.src = state.artifactBlobUrl;
    img.hidden = false;
    $('#img-placeholder').hidden = true;
    $('#artifact-view').hidden = false;
    $('#artifact-empty').hidden = true;

    const descriptor = selectedDescriptor(state.artifactIndex);
    renderArtifactMeta(descriptor, entry, entry.blob.size, isBatch);

    // 端到端校验：响应头 SHA-256 必须与描述符一致。
    if (descriptor && descriptor.sha256 && entry.headerSha) {
      if (entry.headerSha.toLowerCase() === String(descriptor.sha256).toLowerCase()) {
        setVerify('ok', `SHA-256 一致 · ${entry.headerSha.slice(0, 12)}…`);
      } else {
        setVerify('err', 'SHA-256 不一致，拒绝信任该产物');
      }
    } else {
      setVerify('unknown', '响应缺少 SHA-256 头，无法校验');
    }
  } catch {
    setVerify('err', '取出失败，见响应面板');
  }
}

function renderArtifactMeta(descriptor, entry, bytes, isBatch) {
  const rows = [
    ['artifact id', (descriptor && descriptor.id) || entry.headerId || '—'],
    ['media type', (descriptor && (descriptor.mediaType || descriptor.mime)) || 'image/png'],
    ['bytes', bytes],
    ['尺寸', descriptor ? `${descriptor.width}×${descriptor.height}` : '1024×1024'],
    ['索引', isBatch ? `${state.artifactIndex} / ${selectedArtifactCount() - 1}` : '单图'],
    ['ETag', entry.headerSha ? `"${entry.headerSha.slice(0, 12)}…"` : '—'],
    ['sha256 (descriptor)', descriptor ? descriptor.sha256 : '—'],
    ['remote_path', descriptor && descriptor.remote_path ? descriptor.remote_path : '—'],
  ];
  $('#artifact-kv').innerHTML = rows.map(([k, v]) => `
    <div class="metric">
      <span>${esc(k)}</span>
      <strong>${esc(v)}</strong>
    </div>`).join('');
}

function renderArtifactIndex() {
  const count = selectedArtifactCount();
  const row = $('#artifact-index-card');
  const bar = $('#artifact-index');
  if (count <= 1) { row.hidden = true; return; }
  row.hidden = false;
  bar.innerHTML = Array.from({ length: count }, (_, i) => `
    <button class="index-btn" data-index="${i}" aria-current="${i === state.artifactIndex}">${i}</button>
  `).join('');
}

function setVerify(stateName, text) {
  $('#verify-chip').dataset.state = stateName;
  $('#verify-text').textContent = text;
}

/* ── 轮询 ─────────────────────────────────────────────────────────────── */
let pollTimer = null;

function startPolling() {
  stopPolling();
  pollTimer = setInterval(tick, POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function tick() {
  if (!$('#auto-poll').checked) return;
  if (!state.selectedJobId) return;
  const job = state.jobs.find((j) => j.id === state.selectedJobId);
  if (job && isTerminal(job.status)) { stopPolling(); return; }
  await pollJob({ silent: true });
}

/* ── Toast ────────────────────────────────────────────────────────────── */
function toast(message, kind = 'info') {
  const el = document.createElement('div');
  el.className = 'toast';
  el.dataset.kind = kind;
  el.textContent = message;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/* ── 事件绑定 ─────────────────────────────────────────────────────────── */
function bind() {
  $('#base-url').textContent = window.location.origin;

  $('#hero-recs').addEventListener('click', (event) => {
    const btn = event.target.closest('.rec-card');
    if (btn) showStep(Number(btn.dataset.step));
  });

  $('#session-toggle').addEventListener('click', () => {
    const panel = $('#session-panel');
    const open = panel.hidden;
    panel.hidden = !open;
    $('#session-toggle').setAttribute('aria-expanded', String(open));
    if (open) $('#session-input').focus();
  });
  $('#session-save').addEventListener('click', () => {
    setSession($('#session-input').value.trim());
    renderSession();
    toast(getSession() ? '会话令牌已保存到本标签页' : '已清除会话令牌', 'ok');
  });
  $('#session-clear').addEventListener('click', () => {
    setSession('');
    renderSession();
    toast('已清除会话令牌');
  });

  $('#offline-retry').addEventListener('click', () => checkHealth());

  $('#btn-parse-token').addEventListener('click', parseTokenCommandIntoFields);
  $('#token-command').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      parseTokenCommandIntoFields();
    }
  });
  $('#btn-connect').addEventListener('click', connect);
  $('#btn-disconnect').addEventListener('click', disconnect);
  $('#btn-capabilities').addEventListener('click', () => refreshCapabilities());
  $('#btn-models').addEventListener('click', () => refreshModels());
  $('#btn-submit').addEventListener('click', submitJob);

  $('#prompt').addEventListener('input', (event) => {
    $('#prompt-count').textContent = `${event.target.value.length} / 4000`;
  });

  $('#mode-tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('.tab');
    if (!tab) return;
    $$('#mode-tabs .tab').forEach((t) => {
      const active = t === tab;
      t.classList.toggle('is-active', active);
      t.setAttribute('aria-selected', String(active));
    });
    $$('[data-pane]').forEach((pane) => { pane.hidden = pane.dataset.pane !== tab.dataset.mode; });
  });

  $$('[data-seeds-preset]').forEach((btn) => {
    btn.addEventListener('click', () => { $('#seeds').value = btn.dataset.seedsPreset; });
  });

  $('#btn-list-jobs').addEventListener('click', () => listJobs());
  $('#btn-poll-job').addEventListener('click', () => pollJob());
  $('#btn-cancel-job').addEventListener('click', cancelJob);
  $('#btn-goto-artifact').addEventListener('click', () => {
    showStep(5);
    loadArtifact(state.artifactIndex);
  });

  $('#jobs-body').addEventListener('click', (event) => {
    const actionBtn = event.target.closest('[data-action="cancel"]');
    const row = event.target.closest('tr[data-job-id]');
    if (!row) return;
    if (actionBtn) {
      event.stopPropagation();
      state.selectedJobId = row.dataset.jobId;
      renderJobs();
      cancelJob();
      return;
    }
    selectJob(row.dataset.jobId);
  });

  $('#artifact-index').addEventListener('click', (event) => {
    const btn = event.target.closest('.index-btn');
    if (btn) loadArtifact(Number(btn.dataset.index));
  });

  $('#btn-download').addEventListener('click', () => {
    if (!state.artifactBlobUrl) return;
    const link = document.createElement('a');
    link.href = state.artifactBlobUrl;
    const descriptor = selectedDescriptor(state.artifactIndex);
    link.download = `${descriptor ? descriptor.id : 'artifact'}.png`;
    link.click();
  });

  $('#log-toggle').addEventListener('click', () => {
    const log = $('#log');
    const open = log.dataset.open === 'true';
    log.dataset.open = String(!open);
    $('#log-toggle').setAttribute('aria-expanded', String(!open));
  });

  $('#show-secrets').addEventListener('change', renderLog);
  $('#log-clear').addEventListener('click', () => {
    state.logs = [];
    renderLog();
  });

  $('#auto-poll').addEventListener('change', (event) => {
    if (event.target.checked && state.selectedJobId) startPolling();
    else stopPolling();
  });
}

/* ── 启动 ─────────────────────────────────────────────────────────────── */
function init() {
  bind();
  renderHero();
  renderEndpoints();
  renderCapabilities();
  renderModels();
  renderJobs();
  renderSession();
  renderConnection();
  renderLog();
  showStep(1);
  // 首屏停在 hero，不自动滚动到第 1 步。
  window.scrollTo(0, 0);
  checkHealth();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
