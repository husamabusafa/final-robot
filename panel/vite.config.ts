import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * In dev, Vite serves the client and proxies the two WebSocket endpoints to the
 * Fastify relay, so the client can always assume same-origin -- exactly as in
 * production, where Fastify serves `dist/` itself.
 */
const RELAY = process.env.RELAY_ORIGIN ?? "http://127.0.0.1:4001";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/panel": { target: RELAY, ws: true },
      "/robot": { target: RELAY, ws: true },
      "/api": { target: RELAY },
      "/healthz": { target: RELAY },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
