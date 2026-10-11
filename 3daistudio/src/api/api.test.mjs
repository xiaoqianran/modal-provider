import test from "node:test";
import assert from "node:assert/strict";
import * as legacy from "./modal.js";
import * as client from "./client.js";
import * as jobs from "./jobs.js";
import * as assets from "./assets.js";
import * as capabilities from "./capabilities.js";
import * as projects from "./projects.js";

test("legacy API retains each established named export", () => {
  const expected = [
    "api", "errorMessage", "terminal",
    "listCapabilities3d", "capabilities", "health3d", "listModels3d",
    "listOperations3d", "uploadAsset3d", "submitJob", "submitOperation3d",
    "submitImageTo3d", "jobArtifactRef", "getJob3d", "cancelJob",
    "assetContentUrl", "fetchArtifactBlob3d", "pollJob3d", "generateImage2d",
  ];
  for (const name of expected) assert.equal(typeof legacy[name], "function", name);
  assert.equal(legacy.TEXT_IMAGE, "modal-2d.image.text_to_image.v1");
  assert.equal(legacy.IMAGE_3D, "modal-3d.asset.image_to_3d.v1");
});

test("facade reuses domain exports rather than duplicating implementations", () => {
  assert.equal(legacy.api, client.api);
  assert.equal(legacy.submitJob, jobs.submitJob);
  assert.equal(legacy.uploadAsset3d, assets.uploadAsset3d);
  assert.equal(legacy.listCapabilities3d, capabilities.listCapabilities3d);
  assert.equal(legacy.listProjects, projects.listProjects);
  assert.equal(assets.assetContentUrl("a/b"), "/api/v1/assets/a%2Fb/content");
});

test("domain endpoints preserve same-origin request contracts", async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({jobs: [], projects: [], assets: [], job: {id: "j1"}})};
  };
  try {
    await jobs.listJobs();
    await assets.listAssets();
    await projects.listProjects();
    await projects.createProject("Example");
    await jobs.submitJob({operation: "test.operation"}, "stable-id");
    assert.deepEqual(calls.map(call => call.url), [
      "/api/v1/jobs", "/api/v1/assets", "/api/v1/projects",
      "/api/v1/projects", "/api/v1/jobs",
    ]);
    assert(calls.every(call => call.options.credentials === "same-origin"));
    assert.equal(JSON.parse(calls[3].options.body).name, "Example");
    assert.equal(calls[4].options.headers["Idempotency-Key"], "stable-id");
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("pollJob3d stops local waiting when page aborts without cancelling remote job", async () => {
  const previousFetch = globalThis.fetch;
  const controller = new AbortController();
  const calls = [];
  globalThis.fetch = async url => {
    calls.push(url);
    return {ok: true, json: async () => ({job: {id: "pending-1", status: "running"}})};
  };
  try {
    await assert.rejects(
      jobs.pollJob3d("pending-1", {
        intervalMs: 100,
        signal: controller.signal,
        onUpdate: () => controller.abort(),
      }),
      {name: "AbortError"},
    );
    assert.deepEqual(calls, ["/api/v1/jobs/pending-1"]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("restoring a running job only performs GET requests and eventually returns its artifact", async () => {
  const previousFetch = globalThis.fetch;
  const statuses = ["queued", "running", "succeeded"];
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, method: options.method || "GET"});
    const status = statuses.shift();
    return {ok: true, json: async () => ({job: {id: "recover-42", status, result: status === "succeeded" ? {artifacts: [{id: "asset-42", role: "primary-glb"}]} : null}})};
  };
  try {
    const updates = [];
    const finished = await jobs.pollJob3d("recover-42", {intervalMs: 1, onUpdate: job => updates.push(job.status)});
    assert.equal(finished.result.artifacts[0].id, "asset-42");
    assert.deepEqual(updates, ["queued", "running", "succeeded"]);
    assert.deepEqual(calls.map(call => call.method), ["GET", "GET", "GET"]);
    assert(calls.every(call => call.url === "/api/v1/jobs/recover-42"));
  } finally {globalThis.fetch = previousFetch;}
});

test("network errors while polling do not create a duplicate submission", async () => {
  const previousFetch = globalThis.fetch;
  let count = 0;
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(options.method || "GET", "GET");
    assert.equal(url, "/api/v1/jobs/recover-42");
    if (++count === 1) throw new TypeError("Network offline");
    return {ok: true, json: async () => ({job: {id: "recover-42", status: "succeeded"}})};
  };
  try {
    await assert.rejects(jobs.getJob3d("recover-42"), /Network offline/);
    assert.equal((await jobs.getJob3d("recover-42")).status, "succeeded");
    assert.equal(count, 2);
  } finally {globalThis.fetch = previousFetch;}
});

test("abort after in-flight GET suppresses stale job updates", async () => {
  const previousFetch = globalThis.fetch;
  const controller = new AbortController();
  const updates = [];
  globalThis.fetch = async () => {
    controller.abort();
    return {ok: true, json: async () => ({job: {id: "stale", status: "succeeded"}})};
  };
  try {
    await assert.rejects(jobs.pollJob3d("stale", {signal: controller.signal, onUpdate: job => updates.push(job)}), {name: "AbortError"});
    assert.deepEqual(updates, []);
  } finally {globalThis.fetch = previousFetch;}
});

test("retrying a network-failed submission reuses its original idempotency key", async () => {
  const previousFetch = globalThis.fetch;
  const keys = [];
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/jobs");
    keys.push(options.headers["Idempotency-Key"]);
    if (keys.length === 1) throw new TypeError("Lost response");
    return {ok: true, json: async () => ({job: {id: "original", status: "queued"}})};
  };
  try {
    assert.equal((await jobs.submitJob({operation: "test"}, "stable-456")).id, "original");
    assert.deepEqual(keys, ["stable-456", "stable-456"]);
  } finally {globalThis.fetch = previousFetch;}
});
