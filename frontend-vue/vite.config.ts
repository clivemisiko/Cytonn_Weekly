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

/** Puts the theme script inline in <head>, so a stored Light or Dark is applied before the first paint. */
const themeBeforePaint: Plugin = {
  name: "theme-before-paint",
  transformIndexHtml: () => [{ tag: "script", children: THEME_SCRIPT, injectTo: "head-prepend" }],
};

export default defineConfig({
  plugins: [vue(), tailwindcss(), themeBeforePaint],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // 127.0.0.1 only: the app has no sign-in, so it is never served to another machine.
  server: { host: "127.0.0.1", port: 5173, proxy },
  preview: { host: "127.0.0.1", port: 4173, proxy },
  test: { include: ["src/**/*.test.ts"] },
});
