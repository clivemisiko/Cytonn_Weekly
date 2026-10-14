import { defineConfig, devices } from "@playwright/test";

/**
 * One suite, two apps. E2E_TARGET picks the app under test:
 *   next  a production build of frontend/ made with NEXT_PUBLIC_API_URL=http://127.0.0.1:8011, in E2E_NEXT_DIR
 *   vue   frontend-vue/ on Vite's dev server, which proxies /api to the same test API (the default)
 * E2E_BASE_URL overrides the address (then start that app yourself; set E2E_NO_WEB=1 so none is started here).
 * The API is always e2e/serve_e2e.py on port 8011: a throwaway copy of the synthetic demo week, restored at each start.
 */
const API = "http://127.0.0.1:8011";
const target = process.env.E2E_TARGET ?? "vue";
const web =
  target === "next"
    ? { command: "npx next start -p 3011 -H 127.0.0.1", cwd: process.env.E2E_NEXT_DIR, url: "http://127.0.0.1:3011" }
    : { command: "npm run dev -- --port 5183 --strictPort --host 127.0.0.1", cwd: "../frontend-vue", url: "http://127.0.0.1:5183" };
if (target === "next" && !web.cwd && !process.env.E2E_NO_WEB) throw new Error("E2E_TARGET=next needs E2E_NEXT_DIR (see e2e/README.md)");
const baseURL = process.env.E2E_BASE_URL ?? web.url;

export default defineConfig({
  testDir: "tests",
  // The tests share one backend and run in order: a section drafted by one is reviewed by the next.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  metadata: { target },
  use: { baseURL, ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    { command: "python e2e/serve_e2e.py", cwd: "..", url: `${API}/api/health`, reuseExistingServer: false, timeout: 120_000 },
    ...(process.env.E2E_NO_WEB
      ? []
      : [{ ...web, env: { VITE_API_TARGET: API }, reuseExistingServer: false, timeout: 120_000 }]),
  ],
});
