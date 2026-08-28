// Render → Critique → Fix review harness for the bundled web UI.
//
// Usage (from the modal-3D-client repo root, with the demo server running):
//   MODAL_3D_CLIENT_DEMO=1 uv run python -m modal_3d_client   # in another shell
//   npm --prefix .pw install playwright                         # one-time, dev only
//   node .pw/ui-review.mjs
//
// Emits screenshots and a JSON findings report to $SHOT_DIR (default /tmp/m3d-shots).
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.env.BASE_URL || 'http://127.0.0.1:3213';
const outDir = process.env.SHOT_DIR || '/tmp/m3d-shots';
fs.mkdirSync(outDir, { recursive: true });

const findings = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

async function checkOverflow() {
  return page.evaluate(() => {
    const docW = document.documentElement.clientWidth;
    const bad = [];
    if (document.documentElement.scrollWidth > docW + 1) {
      bad.push({ type: 'horizontal-scroll', width: document.documentElement.scrollWidth, docW });
    }
    document.querySelectorAll('*').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.right > docW + 2 && el.offsetWidth > 0) {
        const cls = typeof el.className === 'string' ? el.className.slice(0, 60) : el.tagName;
        bad.push({ type: 'element-overflow', tag: el.tagName, cls, right: Math.round(r.right) });
      }
    });
    return bad.slice(0, 10);
  });
}

const sections = ['workspace', 'jobs', 'models', 'connection', 'api'];
for (const s of sections) {
  await page.goto(`${base}/ui/#${s}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const overflow = await checkOverflow();
  if (overflow.length) findings.push({ section: s, kind: 'overflow', overflow });
  await page.screenshot({ path: path.join(outDir, `${s}.png`) });
}

// Exercise the primary generate flow.
await page.goto(`${base}/ui/#workspace`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
findings.push({ section: 'workspace', kind: 'info', modelOptions: await page.locator('#ws-model option').count() });
await page.locator('#ws-model').selectOption({ index: 0 });
await page.waitForTimeout(200);
findings.push({ section: 'workspace', kind: 'info', profileOptions: await page.locator('#ws-profile option').count() });

const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);
await page.locator('#ws-file').setInputFiles({ name: 't.png', mimeType: 'image/png', buffer: png });
await page.waitForTimeout(300);
findings.push({ section: 'workspace', kind: 'info', submitEnabledAfterUpload: !(await page.locator('#ws-submit').isDisabled()) });

await page.locator('#ws-submit').click();
await page.waitForTimeout(1500);
findings.push({ section: 'workspace', kind: 'info', recentHasJob: /job_/.test(await page.locator('#ws-recent-body').innerText()) });
await page.screenshot({ path: path.join(outDir, 'workspace-after-submit.png') });

await page.goto(`${base}/ui/#jobs`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
findings.push({ section: 'jobs', kind: 'info', rowCount: await page.locator('#jobs-body tr').count() });
await page.screenshot({ path: path.join(outDir, 'jobs-after-submit.png') });

findings.push({ section: 'console', kind: 'errors', consoleErrors });
fs.writeFileSync(path.join(outDir, 'findings.json'), JSON.stringify(findings, null, 2));
console.log(JSON.stringify(findings, null, 2));

await browser.close();
