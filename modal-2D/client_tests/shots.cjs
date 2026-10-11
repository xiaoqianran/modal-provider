const { chromium } = require('/workspace/wk/modal-3D-client/node_modules/playwright');

const BASE = 'http://127.0.0.1:3212/';
const OUT = '/tmp/shots';
const TOKEN = 'dev-session-token';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({
    executablePath: '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

  await page.goto(BASE, { waitUntil: 'networkidle' });

  // ── 1. 首屏（步骤 1，未连接态由 stub 决定） ──────────────────────────
  await sleep(600);
  await page.screenshot({ path: `${OUT}/01-step1.png` });

  // ── 2. 会话令牌面板展开 ─────────────────────────────────────────────
  await page.click('#session-toggle');
  await page.fill('#session-input', TOKEN);
  await page.click('#session-save');
  await sleep(300);
  await page.screenshot({ path: `${OUT}/02-session.png` });
  await page.click('#session-toggle');

  // ── 3. 连接（走真实 POST /modal/connect） ───────────────────────────
  await page.fill('#token-id', 'ak-dev-stub');
  await page.fill('#token-secret', 'as-dev-stub');
  await page.click('#btn-connect');
  await sleep(700);
  await page.screenshot({ path: `${OUT}/03-connected.png` });

  // ── 4. 步骤 2 能力 ─────────────────────────────────────────────────
  await page.click('.rec-card[data-step="2"]');
  await sleep(800);
  await page.click('#capability-raw-wrap > summary');
  await sleep(200);
  await page.screenshot({ path: `${OUT}/04-capabilities.png` });

  // ── 5. 步骤 3 提交（批量模式） ─────────────────────────────────────
  await page.click('.rec-card[data-step="3"]');
  await page.fill('#prompt', 'a glossy red apple on a wooden table, studio light');
  await page.click('.tab[data-mode="batch"]');
  await page.fill('#seeds', '42, 73, 104, 135');
  await sleep(200);
  await page.screenshot({ path: `${OUT}/05-submit-batch.png` });

  // 高级选项展开态
  await page.click('#step-3 .disclose > summary');
  await sleep(200);
  await page.screenshot({ path: `${OUT}/06-submit-advanced.png` });

  // ── 6. 提交 → 自动跳转步骤 4 ───────────────────────────────────────
  await page.click('#btn-submit');
  await sleep(1200);
  await page.screenshot({ path: `${OUT}/07-tracking-running.png` });

  // 选中预置的失败 Job，看终态 + 错误码
  await page.click('tr[data-job-id="job_seed_failed"]');
  await sleep(700);
  await page.screenshot({ path: `${OUT}/08-job-failed.png` });

  // 选中预置的批量成功 Job
  await page.click('tr[data-job-id="job_seed_done"]');
  await sleep(700);
  await page.screenshot({ path: `${OUT}/09-job-succeeded-batch.png` });

  // ── 7. 步骤 5 取产物 ───────────────────────────────────────────────
  await page.click('#btn-goto-artifact');
  await sleep(1500);
  await page.screenshot({ path: `${OUT}/10-artifact-0.png` });

  // 切到索引 2
  await page.click('.index-btn[data-index="2"]');
  await sleep(1200);
  await page.screenshot({ path: `${OUT}/11-artifact-2.png` });

  // ── 8. 日志展开 ────────────────────────────────────────────────────
  await page.click('.log-entry .log-head');
  await sleep(300);
  await page.screenshot({ path: `${OUT}/12-log-expanded.png` });

  // ── 9. 窄屏 ────────────────────────────────────────────────────────
  await page.setViewportSize({ width: 430, height: 900 });
  await sleep(400);
  await page.screenshot({ path: `${OUT}/13-narrow.png`, fullPage: false });

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
})();
