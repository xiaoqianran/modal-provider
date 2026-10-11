import {api} from "./client.js";
import {TEXT_IMAGE, IMAGE_3D} from "./capabilities.js";
import {uploadAsset3d, assetContentUrl} from "./assets.js";
export const terminal = job => ["succeeded", "failed", "cancelled", "expired", "submission_unknown"].includes(job.status);
export async function submitJob(spec, key = crypto.randomUUID()) {
  const options = {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": key}, body: JSON.stringify(spec)};
  try { return (await api("/jobs", options)).job; }
  catch (error) {
    if (!(error instanceof TypeError)) throw error;
    return (await api("/jobs", options)).job;
  }
}
export function submitOperation3d({operation, inputs, options = {}, jobId}) {
  return submitJob({operation: `modal-3d.asset.${operation}.v1`, inputs, options}, jobId);
}
export async function submitImageTo3d({file, model, profile = "recommended", seed = 42, jobId}) {
  const asset = await uploadAsset3d(file);
  return submitJob({operation: IMAGE_3D, inputs: {sourceArtifact: {artifact_id: asset.id}, model, seed}, profile}, jobId);
}
export const jobArtifactRef = (jobId, role = "primary-glb") => ({job_id: jobId, role});
export const getJob3d = async id => (await api(`/jobs/${encodeURIComponent(id)}`)).job;
export const cancelJob = async id => (await api(`/jobs/${encodeURIComponent(id)}/cancel`, {method: "POST"})).job;
export async function fetchArtifactBlob3d(jobId, role = "primary-glb") {
  const job = await getJob3d(jobId);
  const artifact = job.result?.artifacts?.find(a => a.role === role);
  if (!artifact) throw new Error(`No ${role} artifact in this task`);
  const response = await fetch(assetContentUrl(artifact.id), {credentials: "same-origin"});
  if (!response.ok) throw new Error(`Artifact download failed (${response.status})`);
  return response.blob();
}
export async function pollJob3d(id, {intervalMs = 2000, timeoutMs = 3600000, onUpdate, signal} = {}) {
  const started = Date.now();
  for (;;) {
    signal?.throwIfAborted();
    const job = await getJob3d(id);
    signal?.throwIfAborted();
    onUpdate?.(job);
    if (terminal(job)) return job;
    if (Date.now() - started > timeoutMs) throw new Error("Task still running. Follow it in Dashboard.");
    await new Promise((resolve, reject) => {
      const abort = () => {clearTimeout(timer); signal?.removeEventListener("abort", abort); reject(new DOMException("Aborted", "AbortError"));};
      const timer = setTimeout(() => {signal?.removeEventListener("abort", abort); resolve();}, intervalMs);
      signal?.addEventListener("abort", abort, {once: true});
      if (signal?.aborted) abort();
    });
  }
}
export const generateImage2d = inputs => submitJob({operation: TEXT_IMAGE, inputs});
export const listJobs = () => api("/jobs");
