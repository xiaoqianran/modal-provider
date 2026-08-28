/* 状态完备性审查：empty / offline / disconnected / long-content / overflow。
 * 与 audit.cjs 分工：那个审"正常流"，这个审"异常与边界"。
 */
const { chromium } = require('/workspace/wk/modal-3D-client/node_modules/playwright');

const BASE = 'http://127.0.0.1:3212/';
const TOKEN = 'dev-session-token';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
const note = (m) => { problems.push(m); console.log('  ✗ ' + m); };
const ok = (m) => console.log('  ✓ ' + m);
const skip = (m) => console.log('  – 跳过：' + m);

(async () => {
  const browser = await chromium.launch({
    executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const jsErrors = [];
  page.on('pageerror', (e) => jsErrors.push(e.message));

  // 探测后端类型：dev stub 设了 MODAL_2D_AGENT_TOKEN，未带头的 /health 会 401；
  // 真实 agent 未设 token 时直接 200。这决定 409 分支能否被验证。
  const probe = await page.request.get(`${BASE}health`);
  const isStub = probe.status() === 401;
  console.log(`后端：${isStub ? 'dev stub（含 409 模拟）' : '真实 agent（无 token）'}`);

  console.log('=== 状态 A：首次加载时的连接态 ===');
  // 不假设后端起始状态：后端可能已被前一次运行连上或断开。
  // 这里只断言"没有谎报"，具体态由后端决定。
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await sleep(900);
  const a = await page.evaluate(() => ({
    pill: document.getElementById('conn-pill').dataset.state,
    bannerVisible: !document.getElementById('offline-banner').hidden,
    step1Visible: document.querySelector('#step-1:not([hidden])') !== null,
  }));
  // 两种后端都要成立：
  //   真实 agent（未设 token）→ /health 200 且 modal_connected:false → idle
  //   dev stub（设了 token 但没 session）→ 401 → unknown
  ['idle', 'unknown', 'ok'].includes(a.pill)
    ? ok(`连接态 = ${a.pill}`)
    : note(`连接态异常 = ${a.pill}`);
  a.step1Visible ? ok('停留在步骤 1') : note('未停留在步骤 1');

  console.log('\n=== 状态 B：设置会话令牌后仍可读状态 ===');
  await page.click('#session-toggle');
  await page.fill('#session-input', TOKEN);
  await page.click('#session-save');
  await page.click('#session-toggle');
  await page.click('#offline-retry');
  await sleep(900);
  const bState = await page.evaluate(() => ({
    pill: document.getElementById('conn-pill').dataset.state,
    bannerHidden: document.getElementById('offline-banner').hidden,
  }));
  ['idle', 'ok', 'unknown'].includes(bState.pill)
    ? ok(`连接态 = ${bState.pill}`)
    : note(`连接态异常 = ${bState.pill}`);
  bState.bannerHidden ? ok('离线横幅已收起') : note('离线横幅未收起');

  console.log('\n=== 状态 C：断开连接 ===');
  await page.click('.rec-card[data-step="1"]');
  await page.click('#btn-disconnect');
  await sleep(700);
  const c = await page.evaluate(() => ({
    pill: document.getElementById('conn-pill').dataset.state,
    response: document.querySelector('[data-step-response="1"]').textContent.slice(0, 60),
  }));
  c.pill === 'idle' ? ok('断开后 = idle') : note(`断开后 = ${c.pill}`);
  c.response.includes('connected') ? ok('DELETE 响应已呈现') : note('响应未呈现');

  console.log('\n=== 状态 D：未连接时拉能力 → 409 错误态 ===');
  // C 步已断开；后端此时处于未连接态，验证 UI 是否把 409 呈现出来。
  await page.click('.rec-card[data-step="2"]');
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-step-response="2"]');
      return el && el.textContent !== '尚未发起请求';
    },
    { timeout: 30000 },
  ).catch(() => {});
  const d = await page.evaluate(() => {
    const el = document.querySelector('[data-step-response="2"]');
    return {
      state: el.dataset.state,
      text: el.textContent.slice(0, 120),
      emptyVisible: !document.getElementById('capability-empty').hidden,
    };
  });
  if (!isStub) {
    // 真实 agent 的 /v1/capabilities 不按连接态拦截，断开后仍可能 200。
    skip('真实 agent 不模拟未连接 409（需在 dev stub 下验证）');
    d.text.length > 0 ? ok('能力响应已呈现') : note('能力响应为空');
  } else {
    d.state === 'err' ? ok('错误态已标记') : note(`响应态 = ${d.state}`);
    d.text.includes('409') ? ok('409 已呈现给用户') : note(`未呈现 409: ${d.text}`);
    d.emptyVisible ? ok('能力空态保留') : note('空态丢失');
  }

  console.log('\n=== 状态 E：未连接时提交 → 前端不吞错误 ===');
  await page.click('.rec-card[data-step="3"]');
  await page.fill('#prompt', 'should fail without connection');
  await page.click('#btn-submit');
  await sleep(900);
  const e = await page.evaluate(() => {
    const el = document.querySelector('[data-step-response="3"]');
    return { state: el.dataset.state, text: el.textContent.slice(0, 140) };
  });
  e.state === 'err' ? ok('提交错误态已标记') : note(`提交态 = ${e.state}`);
  e.text.includes('409') || e.text.includes('Modal')
    ? ok('错误原因可读')
    : note(`错误信息不明确: ${e.text}`);

  console.log('\n=== 状态 F：离线（服务不可达）===');
  await page.route('**/v1/**', (route) => route.abort());
  await page.route('**/health', (route) => route.abort());
  await page.click('#offline-retry').catch(() => {});
  await sleep(800);
  const f = await page.evaluate(() => ({
    bannerVisible: !document.getElementById('offline-banner').hidden,
    text: document.getElementById('offline-text').textContent.trim(),
  }));
  f.bannerVisible ? ok('离线横幅出现') : note('离线横幅未出现');
  f.text.includes('无法访问 Agent') ? ok('离线文案可读') : note(`离线文案: ${f.text}`);
  await page.unroute('**/v1/**');
  await page.unroute('**/health');

  console.log('\n=== 状态 G：超长内容 ===');
  await page.click('#offline-retry');
  await sleep(600);
  const longPrompt = 'a very long prompt '.repeat(30).trim();
  await page.click('.rec-card[data-step="3"]');
  await page.fill('#prompt', longPrompt);
  await sleep(300);
  const g = await page.evaluate(() => {
    const ta = document.getElementById('prompt');
    const de = document.documentElement;
    return {
      counter: document.getElementById('prompt-count').textContent.trim(),
      textareaNoOverflow: ta.scrollWidth <= ta.clientWidth + 2,
      docOverflow: de.scrollWidth > de.clientWidth + 1,
    };
  });
  const longLen = 'a very long prompt '.repeat(30).trim().length;
  g.counter.startsWith(String(longLen)) ? ok(`长文本计数 ${g.counter}`) : note(`计数 ${g.counter} != ${longLen}`);
  g.textareaNoOverflow ? ok('textarea 不撑破布局') : note('textarea 撑破布局');
  !g.docOverflow ? ok('长文本下无横向溢出') : note('长文本导致横向溢出');

  console.log('\n=== 状态 H：Job 表格不撑破视口 ===');
  await page.click('.rec-card[data-step="4"]');
  await sleep(800);
  const h = await page.evaluate(() => {
    const rows = document.querySelectorAll('#jobs-body tr').length;
    const cell = document.querySelector('#jobs-body .cell-id');
    const de = document.documentElement;
    return {
      rows,
      clipped: cell ? getComputedStyle(cell).textOverflow : null,
      emptyVisible: document.getElementById('jobs-empty') !== null
        && !document.getElementById('jobs-empty').hidden,
      docOverflow: de.scrollWidth > de.clientWidth + 1,
    };
  });
  // 真实 agent 可能是空列表；此时应显示空态而不是留一块空白。
  if (h.rows === 0) {
    h.emptyVisible ? ok('Job 列表空态正确显示') : note('空列表但未显示空态');
  } else {
    h.clipped === 'ellipsis' ? ok('长 ID 省略号生效') : note(`text-overflow = ${h.clipped}`);
  }
  !h.docOverflow ? ok('表格未撑破视口') : note('表格撑破视口');

  console.log('\n=== 状态 I：清空日志 → 空态 ===');
  await page.click('#log-clear');
  await sleep(300);
  const i = await page.evaluate(() => ({
    count: document.getElementById('log-count').textContent.trim(),
    emptyVisible: document.getElementById('log-empty') !== null,
  }));
  i.count === '0' ? ok('日志计数归零') : note(`日志计数 = ${i.count}`);
  i.emptyVisible ? ok('日志空态出现') : note('日志空态缺失');

  console.log('\n=== JS 错误 ===');
  if (jsErrors.length) note(`JS 错误: ${JSON.stringify(jsErrors.slice(0, 5))}`);
  else ok('无 JS 错误');

  console.log(`\n===== ${problems.length ? problems.length + ' 项待修' : '状态审查通过'} =====`);
  await browser.close();
  process.exit(problems.length ? 1 : 0);
})();
