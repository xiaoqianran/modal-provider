import { chromium } from "playwright";
import path from "node:path";

const PROFILE = path.resolve("crawler", ".profile");
const url = process.argv[2] || "https://www.3daistudio.com/";

const context = await chromium.launchPersistentContext(PROFILE, {
  channel: "chrome",
  headless: false,
  viewport: { width: 1440, height: 1000 },
});

const page = context.pages()[0] || await context.newPage();
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });

console.log("\\nChrome opened with persistent profile:");
console.log(PROFILE);
console.log("\\nLog in manually. When login succeeds, close the browser window.");
await new Promise(resolve => context.on("close", resolve));
