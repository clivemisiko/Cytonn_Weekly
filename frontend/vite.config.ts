import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import { THEME_SCRIPT } from "./src/lib/theme-script.ts";

// The review API. /api is proxied to it, so the browser only ever talks to this app's own origin and the backend
// needs no CORS entry for it. VITE_API_TARGET points the proxy at another instance (the tests use port 8011).
const api = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";
const proxy = { "/api": { target: api, changeOrigin: true } };

// Vite refuses a request whose Host header it does not know, which is what keeps a stray name from
// reaching the app. Served behind a proxy under a real name, that name has to be said here or every
// request is "Blocked request": VITE_ALLOWED_HOSTS is a comma-separated list (deploy/Caddyfile sets
// it). Unset, only the loopback names a native or Docker run uses are allowed.
const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

/** Puts the theme script inline in <head>, so a stored Light or Dark is applied before the first paint. */
const themeBeforePaint: Plugin = {
  name: "theme-before-paint",
  transformIndexHtml: () => [{ tag: "script", children: THEME_SCRIPT, injectTo: "head-prepend" }],
};

export default defineConfig({
  plugins: [vue(), tailwindcss(), themeBeforePaint],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // 127.0.0.1 only: the app has no sign-in, so it is never served to another machine.
  // VITE_USE_POLLING: file events do not cross the Windows mount into a container (docker-compose.dev.yml sets it).
  server: { host: "127.0.0.1", port: 5173, proxy, watch: { usePolling: !!process.env.VITE_USE_POLLING } },
  preview: { host: "127.0.0.1", port: 4173, proxy, allowedHosts },
  test: { include: ["src/**/*.test.ts"] },
});
