/**
 * Thin client for modal-provider sidecars (modal-2D-client / modal-3D-client).
 * See API-INTEGRATION.md in the 3daistudio project root.
 */
const base3d = () => (import.meta.env.VITE_MODAL_3D_URL || "http://127.0.0.1:3213").replace(/\/$/, "");
const base2d = () => (import.meta.env.VITE_MODAL_2D_URL || "http://127.0.0.1:8022").replace(/\/$/, "");
const sessionHeader = () => {
  const t = import.meta.env.VITE_MODAL_3D_SESSION || import.meta.env.VITE_MODAL_SESSION;
  return t ? { "X-Modal-3D-Session": t } : {};
};

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function health3d() {
  const res = await fetch(`${base3d()}/health`, { headers: sessionHeader() });
  return jsonOrThrow(res);
}

export async function listModels3d() {
  const res = await fetch(`${base3d()}/v1/models`, { headers: sessionHeader() });
  return jsonOrThrow(res);
}

export async function listCapabilities3d() {
  const res = await fetch(`${base3d()}/v1/capabilities`, { headers: sessionHeader() });
  return jsonOrThrow(res);
}

export async function listOperations3d() {
  const res = await fetch(`${base3d()}/v1/operations`, { headers: sessionHeader() });
  return jsonOrThrow(res);
}

export async function uploadAsset3d(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${base3d()}/v1/assets`, {
    method: "POST",
    body: fd,
    headers: sessionHeader(),
  });
  return jsonOrThrow(res);
}

export async function submitOperation3d({ operation, inputs, options = {}, jobId }) {
  const res = await fetch(`${base3d()}/v1/operations/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...sessionHeader() },
    body: JSON.stringify({
      operation,
      inputs,
      options,
      ...(jobId ? { job_id: jobId } : {}),
    }),
  });
  return jsonOrThrow(res);
}

export async function submitImageTo3d({ file, model, profile = "recommended", seed = 42, jobId }) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("model", model);
  fd.append("profile", profile);
  fd.append("seed", String(seed));
  if (jobId) fd.append("job_id", jobId);
  const res = await fetch(`${base3d()}/v1/jobs`, { method: "POST", body: fd, headers: sessionHeader() });
  return jsonOrThrow(res);
}

export function jobArtifactRef(jobId, role = "primary-glb") {
  return { job_id: jobId, role };
}

export async function getJob3d(jobId) {
  const res = await fetch(`${base3d()}/v1/jobs/${encodeURIComponent(jobId)}`, { headers: sessionHeader() });
  return jsonOrThrow(res);
}

export async function fetchArtifactBlob3d(jobId, role = "primary-glb") {
  const res = await fetch(`${base3d()}/v1/jobs/${encodeURIComponent(jobId)}/artifact?role=${encodeURIComponent(role)}`, {
    headers: sessionHeader(),
  });
  if (!res.ok) throw new Error(`artifact ${res.status}`);
  return res.blob();
}

export async function connectModal3d(tokenId, tokenSecret) {
  const res = await fetch(`${base3d()}/modal/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...sessionHeader() },
    body: JSON.stringify({ token_id: tokenId, token_secret: tokenSecret }),
  });
  return jsonOrThrow(res);
}

/** Poll until terminal status or timeout. */
export async function pollJob3d(
  jobId,
  { intervalMs = 2000, timeoutMs = 10 * 60 * 1000, onUpdate, signal } = {},
) {
  const t0 = Date.now();
  for (;;) {
    if (signal?.aborted) throw new DOMException("Polling aborted", "AbortError");
    const job = await getJob3d(jobId);
    onUpdate?.(job);
    const status = String(job.status || job.state || "").toLowerCase();
    if (["succeeded", "failed", "cancelled", "canceled", "expired", "submission_unknown"].includes(status)) return job;
    if (Date.now() - t0 > timeoutMs) throw new Error(`job ${jobId} timeout`);
    await new Promise((resolve, reject) => {
      const id = setTimeout(resolve, intervalMs);
      if (signal) {
        signal.addEventListener("abort", () => {
          clearTimeout(id);
          reject(new DOMException("Polling aborted", "AbortError"));
        }, { once: true });
      }
    });
  }
}

export async function generateImage2d({ prompt, model, ...rest }) {
  const res = await fetch(`${base2d()}/v1/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...sessionHeader() },
    body: JSON.stringify({ prompt, model, ...rest }),
  });
  return jsonOrThrow(res);
}

/** Map UI model labels → sidecar model ids (extend from GET /v1/models). */
export const MODEL_ALIASES = {
  "Prism 3.1": "prism-3.1",
  "Hunyuan 3.1 Pro": "hunyuan-3.1-pro",
  "Tripo P2": "tripo-p2",
};

export function resolveModelId(uiName) {
  return MODEL_ALIASES[uiName] || uiName;
}
