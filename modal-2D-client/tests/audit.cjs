/* 渲染审查：用 DOM 几何与状态断言代替肉眼检查。
 * 检查项：控制台错误、横向溢出、文本裁切、按钮命中区、层级/密度、状态完备性。
 *
 * 默认对真实 Agent（Modal 已连通、可能有真实 Job）运行。
 * Modal 凭据从 ~/.modal.toml 的 active profile 读取，不写死在脚本里。
 */
const { chromium } = require('/workspace/wk/modal-3D-client/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:3212/';
const TOKEN = 'dev-session-token';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readModalCredentials() {
  const file = path.join(process.env.HOME || '/root', '.modal.toml');
  const text = fs.readFileSync(file, 'utf8');
  const section = text.split(/\n(?=\[)/).find((block) => /active\s*=\s*true/i.test(block));
  const pick = (key) => {
    const m = section && section.match(new RegExp(`${key}\\s*=\\s*"([^"]+)"`));
    if (!m) throw new Error(`~/.modal.toml 缺少 ${key}`);
    return m[1];
  };
  return { token_id: pick('token_id'), token_secret: pick('token_secret') };
}

async function waitForJob(page, jobId, timeoutMs = 240000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await page.evaluate(async (id) => {
      // dev stub 需要 session token；这里从 sessionStorage 取，兜底为空。
      const token = sessionStorage.getItem('modal2d.session') || '';
      const headers = {};
      if (token) headers['X-Modal-2D-Session'] = token;
      const res = await fetch(`/v1/jobs/${id}`, { cache: 'no-store', headers });
      if (!res.ok) return 'missing';
      return (await res.json()).status;
    }, jobId);
    if (['succeeded', 'failed', 'cancelled', 'expired'].includes(status)) return status;
    await sleep(5000);
  }
  return 'timeout';
}

const problems = [];
const note = (msg) => { problems.push(msg); console.log('  ✗ ' + msg); };
const ok = (msg) => console.log('  ✓ ' + msg);

async function auditViewport(page, width, height, label) {
  console.log(`\n[${label}] ${width}x${height}`);
  await page.setViewportSize({ width, height });
  await sleep(350);

  // 1. 横向溢出
  const overflow = await page.evaluate(() => {
    const de = document.documentElement;
    const out = [];
    if (de.scrollWidth > de.clientWidth + 1) {
      out.push({ what: 'document', scroll: de.scrollWidth, client: de.clientWidth });
    }
    document.querySelectorAll('main *').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0) return;
      if (r.right > de.clientWidth + 1) {
        out.push({ what: el.tagName + '.' + (el.className || '').toString().slice(0, 40), right: Math.round(r.right) });
      }
    });
    return out.slice(0, 8);
  });
  if (overflow.length) note(`横向溢出: ${JSON.stringify(overflow)}`);
  else ok('无横向溢出');

  // 2. 文本溢出（内容宽 > 可视宽，且没有 ellipsis / 滚动）
  const clipped = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('main *, .log *, header *').forEach((el) => {
      if (!el.children.length && el.textContent.trim()) {
        const style = getComputedStyle(el);
        const hides = style.textOverflow === 'ellipsis' || style.overflowX === 'auto' || style.overflowX === 'scroll';
        if (!hides && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
          out.push({ text: el.textContent.trim().slice(0, 40), scroll: el.scrollWidth, client: el.clientWidth });
        }
      }
    });
    return out.slice(0, 8);
  });
  if (clipped.length) note(`文本被裁切: ${JSON.stringify(clipped)}`);
  else ok('无文本裁切');

  // 3. 按钮命中区（>=24px 高）
  const small = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('button').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      if (r.height < 24) out.push({ text: el.textContent.trim().slice(0, 20), h: Math.round(r.height) });
    });
    return out.slice(0, 8);
  });
  if (small.length) note(`按钮命中区过小: ${JSON.stringify(small)}`);
  else ok('按钮命中区充足');

  // 4. 主内容区未被固定元素遮挡 / 有足够可用高度
  const mainBox = await page.evaluate(() => {
    const m = document.getElementById('main');
    const r = m.getBoundingClientRect();
    return { top: Math.round(r.top), height: Math.round(r.height), scrollH: m.scrollHeight };
  });
  if (mainBox.height < 200) note(`主内容区过矮: ${JSON.stringify(mainBox)}`);
  else ok(`主内容区可用高度 ${mainBox.height}px`);
}

(async () => {
  const browser = await chromium.launch({
    executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const jsErrors = [];
  page.on('pageerror', (e) => jsErrors.push('pageerror: ' + e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (t.includes('401')) return; // 未设 session 时的预期探测失败
    jsErrors.push('console: ' + t);
  });

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await sleep(400);

  // 设置会话令牌
  await page.click('#session-toggle');
  await page.fill('#session-input', TOKEN);
  await page.click('#session-save');
  await page.click('#session-toggle');

  console.log('=== 步骤 1：连接 ===');
  const step1 = await page.evaluate(() => ({
    panel: document.querySelector('#step-1:not([hidden])') !== null,
    eps: document.querySelectorAll('#step-1 .ep').length,
  }));
  step1.eps === 4 ? ok('步骤1 端点数 = 4') : note(`步骤1 端点数 ${step1.eps} != 4`);

  // 凭据从 ~/.modal.toml 的 active profile 读取，不写死在脚本里。
  const creds = readModalCredentials();
  await page.fill('#token-id', creds.token_id);
  await page.fill('#token-secret', creds.token_secret);
  await page.click('#btn-connect');
  // 真实 Modal 握手可能超过 1s；等连接态确定下来再断言。
  await page
    .waitForFunction(
      () => ['ok', 'err'].includes(document.getElementById('conn-pill').dataset.state),
      { timeout: 60000 },
    )
    .catch(() => {});
  const connState = await page.$eval('#conn-pill', (e) => e.dataset.state);
  connState === 'ok' ? ok('连接态 = ok') : note(`连接态 = ${connState}`);

  console.log('\n=== 步骤 2：能力 ===');
  await page.click('.rec-card[data-step="2"]');
  // 真实 Modal 的 capabilities 调用需 1–4s；等条件成立而不是赌固定 sleep。
  await page
    .waitForFunction(
      () => document.querySelectorAll('#contract-summary .metric').length >= 8
        && document.querySelectorAll('#models-body tr').length >= 1,
      { timeout: 60000 },
    )
    .catch(() => {});
  const step2 = await page.evaluate(() => ({
    kvRows: document.querySelectorAll('#contract-summary .metric').length,
    modelRows: document.querySelectorAll('#models-body tr').length,
    emptyHidden: document.getElementById('capability-empty').hidden,
    rawHidden: document.getElementById('capability-raw-wrap').hidden,
  }));
  step2.kvRows >= 8 ? ok(`契约摘要 ${step2.kvRows} 行`) : note(`契约摘要仅 ${step2.kvRows} 行`);
  step2.modelRows >= 1 ? ok(`模型表 ${step2.modelRows} 行`) : note(`模型表 ${step2.modelRows} 行`);
  step2.emptyHidden ? ok('空态已隐藏') : note('空态未隐藏');
  !step2.rawHidden ? ok('原始 JSON 可展开') : note('原始 JSON 未出现');
  await auditViewport(page, 1440, 900, '步骤2 宽屏');

  console.log('\n=== 步骤 3：提交 ===');
  await page.click('.rec-card[data-step="3"]');
  await page.fill('#prompt', 'a glossy red apple on a wooden table, studio light');
  await page.click('.tab[data-mode="batch"]');
  await page.fill('#seeds', '42, 73, 104, 135');
  await sleep(250);
  const step3 = await page.evaluate(() => ({
    batchPaneVisible: !document.querySelector('[data-pane="batch"]').hidden,
    singlePaneHidden: document.querySelector('[data-pane="single"]').hidden,
    counter: document.getElementById('prompt-count').textContent.trim(),
  }));
  step3.batchPaneVisible && step3.singlePaneHidden ? ok('批量/单张面板互斥正确') : note('面板切换异常');
  const promptLen = 'a glossy red apple on a wooden table, studio light'.length;
  step3.counter.startsWith(String(promptLen))
    ? ok(`字数计数器 ${step3.counter}`)
    : note(`计数 ${step3.counter} != ${promptLen}`);

  // 非法输入应被前端拦截：不产生 /v1/jobs 请求（轮询产生的日志不算）。
  await page.fill('#seeds', '42, 42');
  const before = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.log-path')).filter((e) => e.textContent === '/v1/jobs').length);
  await page.click('#btn-submit');
  await sleep(600);
  const after = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.log-path')).filter((e) => e.textContent === '/v1/jobs').length);
  const errShown = await page.$eval('#submit-error', (e) => !e.hidden && e.textContent.trim());
  after === before && errShown
    ? ok(`重复 seed 被前端拦截，未提交 (${errShown.slice(0, 24)}…)`)
    : note(`校验未拦截 (submit ${before}->${after}, err=${errShown})`);
  await page.fill('#seeds', '42, 73, 104, 135');
  await auditViewport(page, 1440, 900, '步骤3 宽屏');

  console.log('\n=== 步骤 4：跟踪 ===');
  await page.click('#btn-submit');
  // 提交是异步的：等列表有行且详情面板出现，而不是赌一个固定 sleep。
  await page
    .waitForFunction(
      () => document.querySelectorAll('#jobs-body tr').length >= 1
        && !document.getElementById('job-detail').hidden,
      { timeout: 90000 },
    )
    .catch(() => {});
  const step4 = await page.evaluate(() => {
    return {
      rows: document.querySelectorAll('#jobs-body tr').length,
      detailVisible: !document.getElementById('job-detail').hidden,
      selectedId: document.getElementById('job-detail-id').textContent.trim(),
    };
  });
  step4.rows >= 1 ? ok(`Job 列表 ${step4.rows} 行`) : note(`Job 列表仅 ${step4.rows} 行`);
  step4.detailVisible ? ok('详情面板可见') : note('详情面板不可见');

  // 真实 GPU 出图需要时间：等到终态再检查取消按钮禁用与错误展示。
  const finalStatus = await waitForJob(page, step4.selectedId);
  finalStatus === 'succeeded'
    ? ok(`真实 Job 已出图 (${finalStatus})`)
    : note(`Job 终态 = ${finalStatus}`);
  await sleep(1200);

  const terminalState = await page.evaluate(() => ({
    cancelDisabled: document.getElementById('btn-cancel-job').disabled,
    ctaVisible: !document.getElementById('job-success-cta').hidden,
  }));
  terminalState.cancelDisabled ? ok('终态取消按钮已禁用') : note('终态取消按钮未禁用');
  terminalState.ctaVisible ? ok('完成 CTA 已出现') : note('完成 CTA 未出现');
  await auditViewport(page, 1440, 900, '步骤4 宽屏');

  console.log('\n=== 步骤 5：产物 ===');
  // 选中刚完成的 Job 并取产物
  await page.evaluate((id) => {
    const row = document.querySelector(`tr[data-job-id="${id}"]`);
    if (row) row.click();
  }, step4.selectedId);
  await sleep(1000);
  await page.click('#btn-goto-artifact');
  await sleep(2500);
  const step5 = await page.evaluate(() => {
    const img = document.getElementById('artifact-img');
    return {
      viewVisible: !document.getElementById('artifact-view').hidden,
      imgLoaded: img && !img.hidden && img.naturalWidth > 0,
      natural: img ? `${img.naturalWidth}x${img.naturalHeight}` : '—',
      verify: document.getElementById('verify-chip').dataset.state,
      verifyText: document.getElementById('verify-text').textContent.trim(),
      indexButtons: document.querySelectorAll('.index-btn').length,
      kv: document.getElementById('artifact-kv').textContent,
    };
  });
  step5.viewVisible ? ok('产物视图可见') : note('产物视图不可见');
  step5.imgLoaded ? ok(`PNG 已解码 ${step5.natural}`) : note(`PNG 未加载 (${step5.natural})`);
  step5.verify === 'ok' ? ok(`SHA-256 校验通过: ${step5.verifyText}`) : note(`校验态=${step5.verify} (${step5.verifyText})`);
  step5.indexButtons >= 2 ? ok(`${step5.indexButtons} 个候选索引`) : note(`索引数 ${step5.indexButtons}`);
  step5.kv.includes('1024×1024') ? ok('尺寸元数据正确') : note('尺寸元数据缺失');
  await auditViewport(page, 1440, 900, '步骤5 宽屏');

  // 切换到最后一个索引，校验仍应通过
  const lastIndex = step5.indexButtons - 1;
  await page.click(`.index-btn[data-index="${lastIndex}"]`);
  await sleep(2000);
  const afterSwitch = await page.evaluate(() => ({
    verify: document.getElementById('verify-chip').dataset.state,
    current: document.querySelector('.index-btn[aria-current="true"]').dataset.index,
  }));
  afterSwitch.current === String(lastIndex) && afterSwitch.verify === 'ok'
    ? ok(`切索引 ${lastIndex} 校验通过`)
    : note(`切索引异常 ${JSON.stringify(afterSwitch)}`);

  console.log('\n=== 日志 ===');
  await page.click('.log-entry .log-head');
  await sleep(300);
  const log = await page.evaluate(() => {
    const entry = document.querySelector('.log-entry');
    const code = entry.querySelector('pre.code');
    return {
      entries: document.querySelectorAll('.log-entry').length,
      open: entry.dataset.open,
      detailVisible: !entry.querySelector('.log-detail').hidden,
      curl: code ? code.textContent : '',
    };
  });
  log.detailVisible ? ok('日志可展开') : note('日志未展开');
  log.curl.startsWith('curl') ? ok('curl 已渲染') : note('curl 缺失');
  log.curl.includes('X-Modal-2D-Session: dev-session-token')
    ? note('curl 泄露了会话令牌（默认应脱敏）')
    : ok('curl 默认已脱敏');

  await page.click('#show-secrets');
  await sleep(300);
  const unmasked = await page.$eval('.log-entry pre.code', (e) => e.textContent);
  unmasked.includes('dev-session-token') ? ok('勾选后显示真实令牌') : note('勾选后仍未显示令牌');
  await page.click('#show-secrets');

  console.log('\n=== 窄屏 430 ===');
  await auditViewport(page, 430, 900, '步骤5 窄屏');

  console.log('\n=== JS 错误 ===');
  if (jsErrors.length) note(`JS 错误 ${jsErrors.length}: ${JSON.stringify(jsErrors.slice(0, 5))}`);
  else ok('无 JS 错误');

  console.log(`\n===== ${problems.length ? problems.length + ' 项待修' : '审查通过'} =====`);
  await browser.close();
  process.exit(problems.length ? 1 : 0);
})();
