import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, draftAndApprove, overviewUrl, release } from "./helpers";

/**
 * The notes of a rejected draft, shown on the next draft of the same section. Company Updates is used because the test
 * instance can draft, reject and draft it again with no provider (T23 rejects it too). This file has its own run on a
 * freshly restored test backend (`playwright test notes`), and each test uses its own week, so none sees another's runs.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const json = { "Content-Type": "application/json" };
const TITLE = /^Notes from the rejected draft \(run \d+\)$/;

/** Draft Company Updates for that week through the API and return the new run's id. */
async function draftCompanyUpdates(request: APIRequestContext, period: string, text: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/company_updates/draft`, { headers: json, data: { report_type: "weekly", period, text } });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

async function openReview(page: Page, period: string, runId: number) {
  await page.goto(`${overviewUrl(period)}&review=${runId}`);
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
}

test("T37 a rejected draft’s fix-needed item and its note are listed on the next draft, with the run number", async ({ page, request }) => {
  const period = "Week ending 2026-10-16";
  const first = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, first draft.");
  await openReview(page, period, first);
  await expect(page.getByRole("heading", { name: TITLE })).toHaveCount(0); // a first draft has no panel

  // Marked Fix needed with a note, then rejected, on the screen.
  await page.getByRole("radio", { name: "Fix needed" }).click();
  const note = page.getByLabel(/^Note for /);
  await note.fill("SYNTHETIC e2e: the hospitality line is missing.");
  await note.press("Enter");
  await expect(page.getByText("Saved as run")).toBeVisible();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog", { name: "Reject this section?" }).getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Rejected and locked")).toBeVisible();

  // The next draft shows the earlier one's note, read-only, and approval still follows only its own items.
  const second = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, second draft.");
  await openReview(page, period, second);
  const panel = page.getByRole("region", { name: `Notes from the rejected draft (run ${first})` });
  await expect(panel.getByRole("heading", { name: `Notes from the rejected draft (run ${first})`, level: 2 })).toBeVisible();
  await expect(panel).toContainText("Item labels can differ between drafts; these notes were not carried onto the new items.");
  const entries = panel.getByRole("listitem");
  await expect(entries).toHaveCount(1);
  await expect(entries.first()).toContainText("Company Updates (supplied by you)");
  await expect(entries.first()).toContainText("Fix needed");
  await expect(entries.first()).toContainText("SYNTHETIC e2e: the hospitality line is missing.");
  await expect(panel.getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Accept", exact: true })).not.toBeChecked(); // nothing was copied onto the new item
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  // Still shown once the new draft is decided.
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog", { name: "Approve this section?" }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Approved and locked")).toBeVisible();
  await expect(panel).toBeVisible();
});

test("T38 a first draft shows no notes panel", async ({ page, request }) => {
  const period = "Week ending 2026-10-23";
  const run = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, only draft.");
  await openReview(page, period, run);
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await expect(page.getByRole("heading", { name: TITLE })).toHaveCount(0);
});

test("T39 no notes panel when the previous draft was approved", async ({ page, request }) => {
  const period = "Week ending 2026-10-30";
  await draftAndApprove(request, "company_updates", period, "weekly", "Investment Updates:\nSYNTHETIC e2e text, approved.");
  const run = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, drafted after an approval.");
  await openReview(page, period, run);
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await expect(page.getByRole("heading", { name: TITLE })).toHaveCount(0);
});
