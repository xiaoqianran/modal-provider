import {test} from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

const auth = {"cf-access-jwt-assertion": "jwt"};

function context() {
  const tasks = [];
  return {tasks, waitUntil(promise) {tasks.push(promise);}};
}

function fakeR2(entries = new Map()) {
  const puts = [];
  return {
    puts,
    async head(key) {return entries.has(key) ? {key} : null;},
    async get(key) {
      if (!entries.has(key)) return null;
      const value = entries.get(key);
      return {body: new Response(value.body).body, size: value.body.length, httpEtag: '"etag"'};
    },
    async put(key, body, options) {
      const bytes = new Uint8Array(await new Response(body).arrayBuffer());
      entries.set(key, {body: bytes});
      puts.push({key, bytes, options});
    },
  };
}

test("serves SPA assets without proxying private admin paths", async () => {
  let count = 0;
  const env = {ASSETS: {fetch: async () => {count++; return new Response("shell");}}};
  assert.equal(await (await worker.fetch(new Request("https://studio.example/v1/providers"), env)).text(), "shell");
  assert.equal(count, 1);
});

test("rejects unauthenticated API requests", async () => {
  const response = await worker.fetch(new Request("https://studio.example/api/v1/jobs"), {
    STUDIO_API_ORIGIN: "https://origin.example",
  });
  assert.equal(response.status, 401);
});

test("serves authorized asset content from R2 without leaking browser credentials", async () => {
  const original = globalThis.fetch;
  const r2 = fakeR2(new Map([["studio/assets/a", {body: new TextEncoder().encode("from-r2")}]]));
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url: url.href, options});
    assert.equal(options.headers.get("authorization"), null);
    assert.equal(options.headers.get("cookie"), null);
    return Response.json({asset: {id: "a", mime: "image/png", hash: "sha256:x", role: "primary-image"}});
  };
  try {
    const response = await worker.fetch(
      new Request("https://studio.example/api/v1/assets/a/content", {
        headers: {...auth, authorization: "browser-secret", cookie: "private"},
      }),
      {STUDIO_API_ORIGIN: "https://origin.example", STUDIO_ASSETS: r2},
      context(),
    );
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-studio-storage"), "r2");
    assert.equal(await response.text(), "from-r2");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://origin.example/api/v1/assets/a");
  } finally {
    globalThis.fetch = original;
  }
});

test("fills an R2 miss from the Modal origin and archives the full object", async () => {
  const original = globalThis.fetch;
  const r2 = fakeR2();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url.href);
    if (url.pathname.endsWith("/assets/a")) {
      return Response.json({asset: {id: "a", mime: "image/png", hash: "sha256:x", role: "primary-image"}});
    }
    return new Response("origin-bytes", {headers: {"content-type": "image/png"}});
  };
  const ctx = context();
  try {
    const response = await worker.fetch(
      new Request("https://studio.example/api/v1/assets/a/content", {headers: auth}),
      {STUDIO_API_ORIGIN: "https://origin.example", STUDIO_ASSETS: r2},
      ctx,
    );
    assert.equal(await response.text(), "origin-bytes");
    await Promise.all(ctx.tasks);
    assert.equal(r2.puts.length, 1);
    assert.equal(r2.puts[0].key, "studio/assets/a");
    assert.equal(new TextDecoder().decode(r2.puts[0].bytes), "origin-bytes");
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = original;
  }
});

test("archives assets returned by successful product JSON responses", async () => {
  const original = globalThis.fetch;
  const r2 = fakeR2();
  globalThis.fetch = async (url) => {
    if (url.pathname === "/api/v1/jobs/a") {
      return Response.json({
        job: {id: "a", status: "succeeded", result: {artifacts: [
          {id: "asset-1", mime: "model/gltf-binary", hash: "sha256:h", role: "primary-glb"},
        ]}},
      });
    }
    if (url.pathname === "/api/v1/assets/asset-1/content") {
      return new Response("glb-data", {headers: {"content-type": "model/gltf-binary"}});
    }
    throw new Error("unexpected origin request " + url.href);
  };
  const ctx = context();
  try {
    const response = await worker.fetch(
      new Request("https://studio.example/api/v1/jobs/a", {headers: auth}),
      {STUDIO_API_ORIGIN: "https://origin.example", STUDIO_ASSETS: r2},
      ctx,
    );
    assert.equal(response.status, 200);
    await Promise.all(ctx.tasks);
    assert.equal(r2.puts.length, 1);
    assert.equal(r2.puts[0].key, "studio/assets/asset-1");
  } finally {
    globalThis.fetch = original;
  }
});
