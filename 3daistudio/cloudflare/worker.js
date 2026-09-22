/** Origin verifies the Access JWT signature and audience. No admin API is proxied. */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (!env.STUDIO_API_ORIGIN || !env.STUDIO_EDGE_SECRET) return Response.json({message: "Studio gateway not configured"}, {status: 503});
    const assertion = request.headers.get("cf-access-jwt-assertion");
    if (!assertion) return Response.json({message: "Sign in through Cloudflare Access"}, {status: 401});
    const origin = new URL(env.STUDIO_API_ORIGIN);
    if (origin.protocol !== "https:") return Response.json({message: "HTTPS origin required"}, {status: 503});
    const headers = new Headers();
    for (const name of ["content-type", "accept", "idempotency-key", "origin", "sec-fetch-site"]) {
      if (request.headers.has(name)) headers.set(name, request.headers.get(name));
    }
    headers.set("cf-access-jwt-assertion", assertion);
    headers.set("x-studio-edge-secret", env.STUDIO_EDGE_SECRET);
    origin.pathname = url.pathname; origin.search = url.search;
    try {
      const response = await fetch(origin, {method: request.method, headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body, redirect: "manual"});
      const result = new Response(response.body, response);
      result.headers.set("Cache-Control", "private, no-store");
      return result;
    } catch { return Response.json({message: "Studio service unavailable"}, {status: 502}); }
  },
};
