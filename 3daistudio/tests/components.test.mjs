import test from "node:test";
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {chromium} from "playwright";

test("generation components handle models, schema, uploads and job progress", {timeout: 45000}, async () => {
  const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5197", "--strictPort"], {stdio:"ignore"});
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 80; i++) {
      if (server.exitCode !== null) throw new Error("Vite exited before component tests");
      try { if ((await fetch("http://127.0.0.1:5197/tests/component-fixture.html")).ok) {ready = true;break;} } catch {}
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    assert.ok(ready, "Vite fixture must start");
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:5197/tests/component-fixture.html");
    await page.getByLabel("Model", {exact:true}).selectOption("b");
    assert.equal(await page.getByTestId("selected-model").innerText(), "b");
    assert.equal(await page.getByLabel("Model", {exact:true}).locator("option[value=c]").getAttribute("disabled"), "");
    await page.getByLabel("Source image").setInputFiles({name:"source.png",mimeType:"image/png",buffer:Buffer.from("sample")});
    assert.equal(await page.getByTestId("file-name").innerText(), "source.png");
    assert.equal(await page.getByLabel("Disabled input").isDisabled(), true);
    await page.getByLabel("seed").fill("13");
    await page.getByLabel("enabled").check();
    await page.getByLabel("model", {exact:true}).selectOption("b");
    await page.getByLabel("asset", {exact:true}).selectOption("png-1");
    assert.equal(await page.getByLabel("asset", {exact:true}).locator("option[value=glb-1]").count(), 0);
    await page.getByLabel("Upload asset").setInputFiles({name:"input.png",mimeType:"image/png",buffer:Buffer.from("sample")});
    assert.equal(await page.getByTestId("uploaded").innerText(), "asset:input.png");
    const values = JSON.parse(await page.getByTestId("form-value").innerText());
    assert.equal(values.seed, 13);
    assert.equal(values.enabled, true);
    assert.equal(values.model, "b");
    assert.equal(values.asset, "input.png");
    assert.match(await page.locator("body").innerText(), /Job running…/);
    assert.match(await page.locator("body").innerText(), /j-42/);
    await page.getByRole("button", {name:"Show artifact phase"}).click();
    assert.match(await page.locator("body").innerText(), /Downloading verified GLB/);
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    server.kill();
  }
});
