import pkg from "/workspace/wk/modal-3D-client/node_modules/playwright/index.js";
const { chromium } = pkg;
const BASE = "http://127.0.0.1:48124/ui/";
const log = [];
const errors = [];
function check(c, m) { log.push((c ? "PASS " : "FAIL ") + m); }

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push("[pageerror] " + e.message));

// A) Validation error on Create (submit empty required field)
await page.goto(BASE + "#/create", { waitUntil: "networkidle" });
await page.waitForTimeout(400);
await page.click("button.btn--block");
await page.waitForTimeout(200);
const errText = await page.$$eval(".field__error", (els) => els.map((e) => e.textContent).filter(Boolean).join("|"));
check(errText.length > 0, `create: validation error shown (${errText})`);
const invalid = await page.$$eval('[aria-invalid="true"]', (els) => els.length);
check(invalid >= 1, "create: field marked aria-invalid");
await page.screenshot({ path: "/tmp/shots/08-create-validation.png" });

// B) Offline state: point UI at dead connector by stubbing bootstrap fetch
await page.route("**/ui/api/bootstrap", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "offline" }) }));
await page.goto(BASE + "#/connect", { waitUntil: "networkidle" });
await page.reload({ waitUntil: "networkidle" });   // force bootstrap() to re-run
await page.waitForTimeout(500);
const offlineBanner = await page.$(".banner--offline");
const connState = await page.$eval("#conn-state", (e) => e.textContent.trim()).catch(() => "");
check(offlineBanner !== null, `connect: offline banner shown (conn-state=${connState})`);
await page.screenshot({ path: "/tmp/shots/09-offline.png" });
await page.unroute("**/ui/api/bootstrap");

// C) Empty jobs state (fresh page so the offline stub above cannot leak)
await page.unroute("**/ui/api/bootstrap").catch(() => {});
await page.route("**/ui/api/jobs*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ jobs: [], page: 1, total: 0 }) }));
await page.goto(BASE + "#/jobs", { waitUntil: "networkidle" });
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(600);
const emptyTitle = await page.$eval(".empty__title", (e) => e.textContent).catch(() => "");
check(emptyTitle.includes("暂无任务"), `jobs: empty state shown (${emptyTitle})`);
await page.screenshot({ path: "/tmp/shots/10-jobs-empty.png" });
await page.unroute("**/ui/api/jobs*");

// D) Loading state (slow artifacts)
let holdArtifacts = true;
await page.route("**/ui/api/artifacts", (route) => {
  if (!holdArtifacts) return route.continue();
  setTimeout(() => {
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ artifacts: [] }) }).catch(() => {});
  }, 2500);
});
await page.goto(BASE + "#/artifacts");
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
const skeletons = await page.$$eval(".art-grid .skeleton", (e) => e.length).catch(() => 0);
check(skeletons >= 1, `artifacts: skeleton loading shown (${skeletons})`);
await page.screenshot({ path: "/tmp/shots/11-artifacts-loading.png" });
holdArtifacts = false;
await page.unroute("**/ui/api/artifacts").catch(() => {});

// E) Artifact download + SHA-256 verification (real bytes)
await page.goto(BASE + "#/artifacts", { waitUntil: "networkidle" });
await page.waitForTimeout(700);
const dl = await page.$(".art-card .btn--primary");
if (dl) {
  await page.evaluate(() => { window.__dl = null; const o = URL.createObjectURL; });
  await dl.click();
  await page.waitForTimeout(1200);
  const badge = await page.$eval(".art-card .badge", (e) => e.textContent.trim()).catch(() => "");
  check(badge.includes("已校验"), `artifacts: SHA-256 verify badge -> ${badge}`);
}
await page.screenshot({ path: "/tmp/shots/12-artifact-verified.png" });

await browser.close();
console.log(log.join("\n"));
console.log("\n=== errors ===");
console.log(errors.length ? errors.join("\n") : "none");
