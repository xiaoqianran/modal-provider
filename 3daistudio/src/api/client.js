/** Same-origin API boundary. */
export const BASE = "/api/v1";
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
