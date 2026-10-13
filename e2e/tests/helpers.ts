import { existsSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Shared by more.spec.ts and variants.spec.ts. */
export const API = "http://127.0.0.1:8011";
export const WEEK = "2026-10-09";
export const PERIOD = `Week ending ${WEEK}`;
export const DRAFT = `Draft the ${PERIOD} section`;
export const REPO = join(import.meta.dirname, "..", "..");
export const VARIANT = process.env.E2E_VARIANT ?? "";

export const overviewUrl = (period = PERIOD, type = "weekly") => `/overview?report=${type}&period=${encodeURIComponent(period)}`;
export const card = (page: Page, title: string) => page.locator("li", { has: page.getByRole("heading", { name: title, exact: true }) });
export const topbar = (page: Page) => page.getByRole("navigation", { name: "App" });

/** A section's start screen, from the overview card's own button. */
export async function openStart(page: Page, title: string, period = PERIOD, type = "weekly") {
  await page.goto(overviewUrl(period, type));
  await card(page, title).getByRole("button", { name: /Draft section|Add your text|Compose summary|View review|Resume review/ }).click();
  await expect(page.getByRole("heading", { name: `${title}: coordinator review`, level: 1 })).toBeVisible();
}

// While this file exists the test API's weekly Real Estate draft waits, holding the one draft slot (e2e/serve_e2e.py).
const HOLD = join(process.env.E2E_DATA_DIR ?? join(REPO, "backend", "data", "demo-e2e", "data"), "e2e-hold");
export const hold = () => writeFileSync(HOLD, "held by a test");
export const release = () => existsSync(HOLD) && rmSync(HOLD);

const json = { "Content-Type": "application/json" };

/** Start a draft through the API and return its run id (the run goes on in the API). */
export async function startRun(request: APIRequestContext, section: string, period = PERIOD, type = "weekly"): Promise<string> {
  const res = await request.post(`${API}/api/runs`, { headers: json, data: { section, report_type: type, period } });
  expect(res.status(), await res.text()).toBe(202);
  return (await res.json()).run_id;
}

/** Draft a section through the API, accept every item and approve it: the set-up for what needs approved sections. */
export async function draftAndApprove(request: APIRequestContext, section: string, period: string, type: string, text?: string) {
  const drafted = await request.post(`${API}/api/sections/${section}/draft`, { headers: json, data: { report_type: type, period, text }, timeout: 120_000 });
  expect(drafted.status(), await drafted.text()).toBe(200);
  const review = await drafted.json();
  for (const item of review.review_items) {
    const res = await request.patch(`${API}/api/reviews/${review.run_id}/items/${item.index}`, { headers: json, data: { resolution: "accept" } });
    expect(res.ok()).toBe(true);
  }
  const decided = await request.post(`${API}/api/reviews/${review.run_id}/decide`, { headers: json, data: { decision: "approved" } });
  expect(decided.status(), await decided.text()).toBe(200);
}

/** Save typed values on the analyst form through the API (set-up and tidy-up; the screens under test use the form itself). */
export async function putAnalyst(request: APIRequestContext, week: string, section: string, fields: Record<string, string | null>) {
  const res = await request.put(`${API}/api/inputs/weekly/${week}/analyst?section=${section}`, { headers: json, data: { fields } });
  expect(res.status(), await res.text()).toBe(200);
}
