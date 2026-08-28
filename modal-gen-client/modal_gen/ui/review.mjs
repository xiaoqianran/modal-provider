import pkg from "/workspace/wk/modal-3D-client/node_modules/playwright/index.js";
const { chromium } = pkg;

const BASE = "http://127.0.0.1:48124/ui/";
import { mkdirSync } from "node:fs";
mkdirSync("/tmp/shots", { recursive: true });
const log = [];
const errors = [];

async function shoot(page, name) {
  await page.screenshot({ path: `/tmp/shots/${name}.png` });
  log.push("shot " + name);
}
function check(cond, msg) { log.push((cond ? "PASS " : "FAIL ") + msg); }

async function overflow(page) {
  return await page.evaluate(() => ({
    h: document.documentElement.scrollWidth,
    w: window.innerWidth,
    v: document.documentElement.scrollHeight,
    vw: window.innerHeight,
  }));
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error") errors.push("[console] " + m.text()); });
page.on("pageerror", (e) => errors.push("[pageerror] " + e.message));

// 1) Connect
await page.goto(BASE + "#/connect", { waitUntil: "networkidle" });
await page.waitForTimeout(300);
check((await page.$$(".panel")).length >= 2, "connect: >=2 panels");
check(await page.$(".conn-card") !== null, "connect: rail conn-card present");
const modeTxt = await page.$eval("#mode-badge", (e) => e.textContent).catch(() => "");
check(modeTxt.includes("演示"), "connect: demo badge shows 演示");
let o = await overflow(page);
check(o.h <= o.w + 1, `connect: no h-overflow (${o.h}<=${o.w})`);
await shoot(page, "01-connect");

// 2) Create (default)
await page.goto(BASE + "#/create", { waitUntil: "networkidle" });
await page.waitForTimeout(300);
check((await page.$$(".panel")).length >= 1, "create: form panel present");
check((await page.$$("input,select")).length >= 3, "create: form controls rendered");
check((await page.$$(".flow__stage")).length === 3, "create: 3 pipeline stages");
const submit = await page.$("button.btn--block");
check(submit !== null, "create: submit button present");
o = await overflow(page);
check(o.h <= o.w + 1, `create: no h-overflow (${o.h}<=${o.w})`);
await shoot(page, "02-create");

// 3) Create with 3D unavailable
await page.evaluate(async () => { const r = await fetch("/ui/api/dev/set", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ three_d_unavailable: true }) }); return await r.text(); });
await page.goto(BASE + "#/create", { waitUntil: "networkidle" });
await page.reload({ waitUntil: "networkidle" });   // same-hash goto does not re-render
await page.waitForTimeout(800);
const warnCount = (await page.$$(".banner--warn")).length;
check(warnCount >= 1, `create-3d-off: unavailable banner rendered (${warnCount})`);
const unavailTitle = await page.$$eval(".panel__title", (els) => els.map((e) => e.textContent).join("|")).catch(() => "");
check(unavailTitle.includes("不可用 Provider"), "create-3d-off: unavailable provider panel visible");
await shoot(page, "03-create-3d-off");
await page.evaluate(async () => { const r = await fetch("/ui/api/dev/set", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ three_d_unavailable: false }) }); return await r.text(); });

// 4) Jobs
await page.goto(BASE + "#/jobs", { waitUntil: "networkidle" });
await page.waitForTimeout(500);
const rows = await page.$$("table tbody tr");
check(rows.length >= 3, `jobs: >=3 rows (${rows.length})`);
check((await page.$$(".badge")).length >= 1, "jobs: status badges rendered");
check((await page.$$(".chip")).length === 4, "jobs: 4 status filters");
o = await overflow(page);
check(o.h <= o.w + 1, `jobs: no h-overflow (${o.h}<=${o.w})`);
await shoot(page, "04-jobs");

// 5) Job drawer
if (rows[0]) {
  await rows[0].click();
  await page.waitForTimeout(400);
  const drawer = await page.$(".drawer--open");
  check(drawer !== null, "jobs: drawer opens on row click");
  const hasHash = await page.$$eval(".drawer .hash", (els) => els.length).catch(() => 0);
  check(hasHash >= 1, "jobs: drawer shows hash chips");
  await shoot(page, "05-job-drawer");
  // close
  await page.keyboard.press("Escape").catch(() => {});
}

// 6) Artifacts
await page.goto(BASE + "#/artifacts", { waitUntil: "networkidle" });
await page.waitForTimeout(600);
const cards = await page.$$(".art-card");
check(cards.length >= 1, `artifacts: >=1 card (${cards.length})`);
const imgOk = await page.$$eval(".art-card__prev img", (els) => els.every((e) => e.complete && e.naturalWidth > 0)).catch(() => false);
check(imgOk, "artifacts: png preview loaded");
const dlBtn = await page.$(".art-card .btn--primary");
check(dlBtn !== null, "artifacts: download+verify button present");
o = await overflow(page);
check(o.h <= o.w + 1, `artifacts: no h-overflow (${o.h}<=${o.w})`);
await shoot(page, "06-artifacts");

// 7) Mobile connect
const m = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
const mp = await m.newPage();
await mp.goto(BASE + "#/connect", { waitUntil: "networkidle" });
await mp.waitForTimeout(300);
const mo = await overflow(mp);
check(mo.h <= mo.w + 1, `mobile-connect: no h-overflow (${mo.h}<=${mo.w})`);
await mp.screenshot({ path: "/tmp/shots/07-mobile-connect.png" });
log.push("shot 07-mobile-connect");

await browser.close();
console.log(log.join("\n"));
console.log("\n=== errors ===");
console.log(errors.length ? errors.join("\n") : "none");
