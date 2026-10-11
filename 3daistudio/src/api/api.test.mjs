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
