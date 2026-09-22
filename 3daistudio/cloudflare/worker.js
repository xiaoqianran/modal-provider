/** Cloudflare owns authentication at the edge and durable asset archival in R2. */
const PRODUCT_HEADERS = [
  "content-type",
  "accept",
  "idempotency-key",
  "origin",
  "sec-fetch-site",
  "range",
];

function originHeaders(request, env, assertion) {
  const headers = new Headers();
  for (const name of PRODUCT_HEADERS) {
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  }
  headers.set("cf-access-jwt-assertion", assertion);
  if (env.STUDIO_EDGE_SECRET) headers.set("x-studio-edge-secret", env.STUDIO_EDGE_SECRET);
  return headers;
}

function originUrl(env, path, search = "") {
  const origin = new URL(env.STUDIO_API_ORIGIN);
  if (origin.protocol !== "https:") throw new Error("HTTPS origin required");
  origin.pathname = path;
  origin.search = search;
  return origin;
}

async function fetchOrigin(request, env, assertion, path, search = "") {
  return fetch(originUrl(env, path, search), {
    method: request.method,
    headers: originHeaders(request, env, assertion),
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual",
  });
}

function privateResponse(response) {
  const result = new Response(response.body, response);
  result.headers.set("Cache-Control", "private, no-store");
  result.headers.set("X-Content-Type-Options", "nosniff");
  return result;
}

function assetKey(assetId) {
  return `studio/assets/${assetId}`;
}

function collectAssets(payload) {
  const found = new Map();
  const visit = (value, key = "") => {
    if (!value || typeof value !== "object") return;
    if (
      (key === "asset" || key === "artifacts" || key === "assets") &&
      !Array.isArray(value) &&
      typeof value.id === "string" &&
      typeof value.mime === "string"
    ) {
      found.set(value.id, value);
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (
          (key === "artifacts" || key === "assets") &&
          item &&
          typeof item.id === "string" &&
          typeof item.mime === "string"
        ) {
          found.set(item.id, item);
        }
        visit(item, key);
      }
      return;
    }
    for (const [childKey, child] of Object.entries(value)) visit(child, childKey);
  };
  visit(payload);
  return [...found.values()];
}

async function archiveAsset(asset, env, assertion) {
  if (!env.STUDIO_ASSETS || !asset?.id || !asset?.mime) return;
  const key = assetKey(asset.id);
  if (await env.STUDIO_ASSETS.head(key)) return;
  const request = new Request("https://edge.internal/", {headers: {accept: asset.mime}});
  const response = await fetchOrigin(
    request,
    env,
    assertion,
    `/api/v1/assets/${encodeURIComponent(asset.id)}/content`,
  );
  if (!response.ok || !response.body) return;
  await env.STUDIO_ASSETS.put(key, response.body, {
    httpMetadata: {contentType: asset.mime},
    customMetadata: {
      artifactId: asset.id,
      hash: typeof asset.hash === "string" ? asset.hash : "",
      role: typeof asset.role === "string" ? asset.role : "",
    },
  });
}

async function archiveResponse(response, env, assertion) {
  if (!env.STUDIO_ASSETS || !response.ok) return;
  if (!(response.headers.get("content-type") || "").includes("application/json")) return;
  let payload;
  try {
    payload = await response.clone().json();
  } catch {
    return;
  }
  await Promise.allSettled(collectAssets(payload).map((asset) => archiveAsset(asset, env, assertion)));
}

async function serveAssetContent(request, env, assertion, assetId, ctx) {
  // Always authorize the asset against Studio metadata before touching the shared bucket.
  const authRequest = new Request(request.url, {headers: {accept: "application/json"}});
  const metadataResponse = await fetchOrigin(
    authRequest,
    env,
    assertion,
    `/api/v1/assets/${encodeURIComponent(assetId)}`,
  );
  if (!metadataResponse.ok) return privateResponse(metadataResponse);
  const payload = await metadataResponse.json();
  const asset = payload?.asset;
  if (!asset || typeof asset.id !== "string" || typeof asset.mime !== "string") {
    return Response.json({message: "Invalid asset metadata"}, {status: 502});
  }

  // Range requests continue to the origin for now; never persist a partial response as a full object.
  if (!request.headers.has("range")) {
    const object = await env.STUDIO_ASSETS.get(assetKey(asset.id));
    if (object) {
      const headers = new Headers({
        "content-type": asset.mime,
        "cache-control": "private, no-store",
        "x-content-type-options": "nosniff",
        "x-studio-storage": "r2",
      });
      if (object.httpEtag) headers.set("etag", object.httpEtag);
      if (object.size != null) headers.set("content-length", String(object.size));
      return new Response(object.body, {status: 200, headers});
    }
  }

  const response = await fetchOrigin(
    request,
    env,
    assertion,
    `/api/v1/assets/${encodeURIComponent(assetId)}/content`,
  );
  if (
    response.ok &&
    response.body &&
    !request.headers.has("range") &&
    env.STUDIO_ASSETS
  ) {
    const [clientBody, archiveBody] = response.body.tee();
    const archiveResponse = new Response(archiveBody, {
      headers: {"content-type": asset.mime},
    });
    const task = env.STUDIO_ASSETS.put(assetKey(asset.id), archiveResponse.body, {
      httpMetadata: {contentType: asset.mime},
      customMetadata: {
        artifactId: asset.id,
        hash: typeof asset.hash === "string" ? asset.hash : "",
        role: typeof asset.role === "string" ? asset.role : "",
      },
    });
    ctx?.waitUntil?.(task.catch(() => undefined));
    const result = new Response(clientBody, response);
    result.headers.set("Cache-Control", "private, no-store");
    result.headers.set("X-Content-Type-Options", "nosniff");
    result.headers.set("X-Studio-Storage", "origin+archive");
    return result;
  }
  return privateResponse(response);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (!env.STUDIO_API_ORIGIN) {
      return Response.json({message: "Studio gateway not configured"}, {status: 503});
    }
    const assertion = request.headers.get("cf-access-jwt-assertion");
    if (!assertion) {
      return Response.json({message: "Sign in through Cloudflare Access"}, {status: 401});
    }

    const contentMatch =
      request.method === "GET" &&
      url.pathname.match(/^\/api\/v1\/assets\/([^/]+)\/content$/);
    if (contentMatch && env.STUDIO_ASSETS) {
      try {
        return await serveAssetContent(
          request,
          env,
          assertion,
          decodeURIComponent(contentMatch[1]),
          ctx,
        );
      } catch {
        return Response.json({message: "Studio service unavailable"}, {status: 502});
      }
    }

    try {
      const response = await fetchOrigin(request, env, assertion, url.pathname, url.search);
      if (ctx?.waitUntil) {
        ctx.waitUntil(archiveResponse(response, env, assertion).catch(() => undefined));
      }
      return privateResponse(response);
    } catch {
      return Response.json({message: "Studio service unavailable"}, {status: 502});
    }
  },
};
