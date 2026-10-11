import {api, BASE} from "./client.js";
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
export const assetContentUrl = id => `${BASE}/assets/${encodeURIComponent(id)}/content`;
export const listAssets = () => api("/assets");
