/** Same-origin Studio API; Modal credentials never enter the browser. */
const BASE = "/api/v1";
export const TEXT_IMAGE = "modal-2d.image.text_to_image.v1";
export const IMAGE_3D = "modal-3d.asset.image_to_3d.v1";
export const terminal = job => ["succeeded", "failed", "cancelled", "expired", "submission_unknown"].includes(job.status);
export const errorMessage = error => typeof error === "string" ? error : error?.message || error?.code || "Request failed";
export async function api(path, options = {}) {
  const response = await fetch(BASE + path, {credentials: "same-origin", ...options});
  if (!response.ok) {
    let message = `Studio API returned ${response.status}`;
    try { const body = await response.json(); message = errorMessage(body.detail || body); } catch {}
    throw new Error(message);
  }
  return response.json();
}
export const listCapabilities3d = () => api("/capabilities");
export const capabilities = snapshot => (snapshot.providers || []).flatMap(p => (p.capabilities || []).map(c => ({...c, provider: p.id, available: p.status === "available" && c.status === "available"})));
export async function health3d() {
  return {modal_connected: capabilities(await listCapabilities3d()).some(c => c.operation === IMAGE_3D && c.available)};
}
export async function listModels3d() {
  const cap = capabilities(await listCapabilities3d()).find(c => c.operation === IMAGE_3D);
  return {models: (cap?.input?.schema?.properties?.model?.enum || []).map(id => ({id, name: id, status: cap.available ? "enabled" : "disabled", profiles: Object.keys(cap.profiles || {}).map(id => ({id, name: id}))}))};
}
export async function listOperations3d() {
  return {operations: capabilities(await listCapabilities3d()).filter(c => c.available && c.category === "asset-processing").map(c => ({...c, id: c.operation.split(".").at(-2)}))};
}
async function pngFile(file) {
  if (!file.type.startsWith("image/") || file.type === "image/png") return file;
  const bitmap = await createImageBitmap(file);
  try {
    if (bitmap.width * bitmap.height > 32000000) throw new Error("Image is too large");
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width; canvas.height = bitmap.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("Could not convert image to PNG");
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".png", {type: "image/png"});
  } finally { bitmap.close(); }
}
export async function uploadAsset3d(file, projectId) {
  file = await pngFile(file);
  const mime = file.name.toLowerCase().endsWith(".glb") ? "model/gltf-binary" : file.type;
  const params = new URLSearchParams({name: file.name});
  if (projectId) params.set("projectId", projectId);
  return (await api(`/uploads?${params}`, {method: "POST", headers: {"Content-Type": mime}, body: file})).asset;
}
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
export const assetContentUrl = id => `${BASE}/assets/${encodeURIComponent(id)}/content`;
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
    onUpdate?.(job);
    if (terminal(job)) return job;
    if (Date.now() - started > timeoutMs) throw new Error("Task still running. Follow it in Dashboard.");
    await new Promise((resolve, reject) => {
      const abort = () => {clearTimeout(timer); reject(new DOMException("Aborted", "AbortError"));};
      const timer = setTimeout(() => {signal?.removeEventListener("abort", abort); resolve();}, intervalMs);
      signal?.addEventListener("abort", abort, {once: true});
    });
  }
}
export const generateImage2d = inputs => submitJob({operation: TEXT_IMAGE, inputs});
