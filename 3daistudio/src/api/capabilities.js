import {api} from "./client.js";
export const TEXT_IMAGE = "modal-2d.image.text_to_image.v1";
export const IMAGE_3D = "modal-3d.asset.image_to_3d.v1";
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
