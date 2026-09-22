import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({mode}) => {
  const env = {...loadEnv(mode, process.cwd(), ""), ...process.env};
  return {
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: {
    "/api": {target: env.STUDIO_API_ORIGIN || "http://127.0.0.1:48125", changeOrigin: true,
      configure(proxy) {
        proxy.on("proxyReq", proxyReq => {
          proxyReq.removeHeader("authorization");
          if (env.STUDIO_DEV_TOKEN) proxyReq.setHeader("Authorization", `Bearer ${env.STUDIO_DEV_TOKEN}`);
        });
      }},
  }},
};
});
