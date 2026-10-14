import { defineConfig, devices } from "@playwright/test";

/**
 * The app under test is frontend/ on Vite's dev server, which proxies /api to the test API.
 * E2E_BASE_URL overrides the address (then start the app yourself; set E2E_NO_WEB=1 so none is started here).
 * The API is always e2e/serve_e2e.py on port 8011: a throwaway copy of the synthetic demo week, restored at each start.
 */
const API = "http://127.0.0.1:8011";
const web = { command: "npm run dev -- --port 5183 --strictPort --host 127.0.0.1", cwd: "../frontend", url: "http://127.0.0.1:5183" };
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
  use: { baseURL, ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    { command: "python e2e/serve_e2e.py", cwd: "..", url: `${API}/api/health`, reuseExistingServer: false, timeout: 120_000 },
    ...(process.env.E2E_NO_WEB
      ? []
      : [{ ...web, env: { VITE_API_TARGET: API }, reuseExistingServer: false, timeout: 120_000 }]),
  ],
});
