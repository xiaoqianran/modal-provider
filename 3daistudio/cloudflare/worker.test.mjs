import {test} from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

test("serves SPA assets without proxying private admin paths", async () => {
  let count = 0;
  const env = {ASSETS: {fetch: async () => {count++; return new Response("shell");}}};
  assert.equal(await (await worker.fetch(new Request("https://studio.example/v1/providers"), env)).text(), "shell");
  assert.equal(count, 1);
});
test("rejects unauthenticated API requests", async () => {
  const response = await worker.fetch(new Request("https://studio.example/api/v1/jobs"), {
    STUDIO_API_ORIGIN: "https://origin.example", STUDIO_EDGE_SECRET: "server-secret",
  });
  assert.equal(response.status, 401);
});
test("forwards only product headers and never follows storage redirects with identity", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url.href, "https://origin.example/api/v1/assets/a/content");
    assert.equal(options.headers.get("authorization"), null);
    assert.equal(options.headers.get("cookie"), null);
    assert.equal(options.headers.get("x-studio-edge-secret"), "server-secret");
    assert.equal(options.redirect, "manual");
    return new Response(null, {status: 307, headers: {location: "https://storage.example/signed"}});
  };
  try {
    const response = await worker.fetch(new Request("https://studio.example/api/v1/assets/a/content", {
      headers: {"cf-access-jwt-assertion": "jwt", authorization: "admin-secret", cookie: "session=private",
        "x-studio-edge-secret": "attacker"},
    }), {STUDIO_API_ORIGIN: "https://origin.example", STUDIO_EDGE_SECRET: "server-secret"});
    assert.equal(response.status, 307);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  } finally {globalThis.fetch = original;}
});
