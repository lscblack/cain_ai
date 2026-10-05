import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// The frontend proxies /api -> the backend, so the browser always talks to the
// SAME origin it loaded the page from. That makes KAI reachable identically from
// localhost, a LAN IP, or the public Tailscale URL with no per-host API config.
const API_TARGET = "http://127.0.0.1:8001";

const proxy = {
  "/api": {
    target: API_TARGET,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 5174,
    strictPort: true,
    allowedHosts: true, // reachable via localhost, LAN IP and the Tailscale host
    proxy,
  },
});
