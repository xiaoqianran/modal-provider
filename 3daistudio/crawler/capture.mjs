import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import readline from "node:readline/promises";

const ROOT = path.resolve("reference", "3daistudio");
const PROFILE = path.resolve("crawler", ".profile");
const seed = process.argv[2] || "https://www.3daistudio.com/";

const safe = (s) => s.replace(/^https?:\/\//, "").replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 160) || "page";

await fs.mkdir(ROOT, { recursive: true });

const context = await chromium.launchPersistentContext(PROFILE, {
  channel: "chrome",
  headless: false,
  viewport: { width: 1440, height: 1000 },
  recordHar: {
    path: path.join(ROOT, "network.har"),
    content: "embed",
    mode: "full",
  },
});

const page = context.pages()[0] || await context.newPage();
const responses = [];
const apiBodies = [];

page.on("response", async (response) => {
  const req = response.request();
  const item = {
    url: response.url(),
    status: response.status(),
    method: req.method(),
    resourceType: req.resourceType(),
    contentType: response.headers()["content-type"] || "",
  };
  responses.push(item);

  const ct = item.contentType;
  const isUseful = ["xhr", "fetch"].includes(item.resourceType) || /application\/json|text\/plain/.test(ct);
  if (isUseful) {
    try {
      const body = await response.text();
      if (body && body.length <= 2000000) apiBodies.push({ ...item, body });
    } catch {}
  }
});

console.log("\\nUsing persistent profile:");
console.log(PROFILE);
console.log("\\nIf login is required, log in normally in the opened Chrome window.\\n");

const mainResponse = await page.goto(seed, { waitUntil: "domcontentloaded", timeout: 90000 });

console.log("\nBrowser is open.");
console.log("Complete login/authentication if needed.");
console.log("When the final page you want to capture is fully visible, return here and press ENTER.\n");

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
await rl.question("Press ENTER to start capture...");
rl.close();

await page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {});
await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1500);

const url = page.url();
const pathname = new URL(url).pathname === "/" ? "home" : new URL(url).pathname;
const dir = path.join(ROOT, "pages", safe(pathname));
await fs.mkdir(dir, { recursive: true });

let rawHtml = "";
try {
  if (mainResponse && mainResponse.request().resourceType() === "document") rawHtml = await mainResponse.text();
} catch {}

await fs.writeFile(path.join(dir, "raw.html"), rawHtml, "utf8");
await fs.writeFile(path.join(dir, "rendered.html"), await page.content(), "utf8");
await page.screenshot({ path: path.join(dir, "screenshot.png"), fullPage: true });

const snapshot = await page.evaluate(() => {
  const selectors = ["a","button","input","textarea","select","[role=button]","[role=tab]","[role=menuitem]","[role=dialog]"];
  const controls = [...document.querySelectorAll(selectors.join(","))].map((el, index) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return {
      index,
      tag: el.tagName,
      text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 500),
      href: el.href || null,
      role: el.getAttribute("role"),
      ariaLabel: el.getAttribute("aria-label"),
      type: el.getAttribute("type"),
      disabled: "disabled" in el ? !!el.disabled : null,
      visible: r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none",
      rect: { x: r.x, y: r.y, width: r.width, height: r.height },
      style: {
        display: s.display,
        position: s.position,
        color: s.color,
        background: s.background,
        fontFamily: s.fontFamily,
        fontSize: s.fontSize,
        fontWeight: s.fontWeight,
        lineHeight: s.lineHeight,
        borderRadius: s.borderRadius,
      }
    };
  });

  const links = [...new Set([...document.querySelectorAll("a[href]")].map(a => a.href))];
  const stylesheets = [...document.styleSheets].map(s => s.href).filter(Boolean);
  const assets = [...document.querySelectorAll("img[src], source[src], video[src], link[href], script[src]")]
    .map(el => el.src || el.href)
    .filter(Boolean);

  return {
    title: document.title,
    url: location.href,
    lang: document.documentElement.lang,
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
    links,
    stylesheets,
    assets: [...new Set(assets)],
    controls,
    localStorage: Object.fromEntries(Object.entries(localStorage)),
    sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
  };
});

await fs.writeFile(path.join(dir, "page.json"), JSON.stringify(snapshot, null, 2), "utf8");
await fs.writeFile(path.join(dir, "responses.json"), JSON.stringify(responses, null, 2), "utf8");
await fs.writeFile(path.join(dir, "api-bodies.json"), JSON.stringify(apiBodies, null, 2), "utf8");

const sameOriginLinks = snapshot.links.filter((u) => {
  try { return new URL(u).origin === new URL(url).origin; } catch { return false; }
});
await fs.writeFile(path.join(ROOT, "discovered-links.json"), JSON.stringify(sameOriginLinks, null, 2), "utf8");

console.log("Captured:", url);
console.log("Output:", dir);
console.log("Controls:", snapshot.controls.length);
console.log("Same-origin links:", sameOriginLinks.length);
console.log("Network responses:", responses.length);
console.log("\\nCapture complete. Closing Chrome to finalize HAR...");

await context.close();


