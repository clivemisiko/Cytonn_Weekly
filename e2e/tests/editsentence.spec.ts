import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, overviewUrl, release } from "./helpers";

// A flagged sentence of a drafted piece, edited or removed by hand. The test backend drafts a topic that says "bad figure"
// with a second sentence whose figure (Sh99.9 billion) is not in the text its source cited (e2e/serve_e2e.py), so every
// test has a flagged sentence. Each test uses its own week.
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const json = { "Content-Type": "application/json" };
const GOOD = "Lending rose to Sh30.1 billion over the quarter.";
const BAD = "Lending rose to Sh88.8 billion over the quarter.";

async function draftFocus(request: APIRequestContext, period: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/focus/draft`, {
    headers: json,
    data: { report_type: "weekly", period, topic: "SYNTHETIC bad figure topic" },
    timeout: 120_000,
  });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

async function open(page: Page, period: string, runId: number) {
  await page.goto(`${overviewUrl(period)}&review=${runId}`);
  await expect(page.getByRole("heading", { name: "Focus of the Week: coordinator review", level: 1 })).toBeVisible();
}

const flagged = (page: Page) => page.locator('li[data-status="flagged"]');

test("T99 an edited sentence with a figure the source has is no longer flagged, and is marked as edited", async ({ page, request }) => {
  const period = "Week ending 2026-10-30";
  const first = await draftFocus(request, period);
  await open(page, period, first);
  await expect(flagged(page)).toHaveCount(1);

  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  const box = page.getByRole("textbox", { name: "Your sentence" });
  await expect(box).toHaveValue("Lending rose to Sh99.9 billion.");
  await box.fill(GOOD);
  await page.getByRole("button", { name: "Save as a new version" }).click();

  await expect(page.getByRole("heading", { name: "Sentence edited. The figures were checked again." })).toBeVisible();
  await expect(flagged(page)).toHaveCount(0);
  await expect(page.getByText(/Edited by you, .* EAT/).first()).toBeVisible();
  await expect(page.getByLabel("Sentences you edited")).toContainText(GOOD);

  // The earlier review is still there, as drafted.
  const old = await (await request.get(`${API}/api/reviews/${first}`)).json();
  expect(old.decision).toBeNull();
  expect(old.section.blocks.find((b: { kind: string }) => b.kind === "narrative").body_md).toContain("Sh99.9 billion.");
});

test("T100 an edited sentence with a figure no source has stays flagged and says so", async ({ page, request }) => {
  const period = "Week ending 2026-11-06";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  await page.getByRole("textbox", { name: "Your sentence" }).fill(BAD);
  await page.getByRole("button", { name: "Save as a new version" }).click();

  await expect(page.getByRole("heading", { name: "Sentence edited. The figures were checked again." })).toBeVisible();
  const item = flagged(page);
  await expect(item).toHaveCount(1);
  await expect(item).toContainText("Edited by you");
  await item.getByRole("button", { name: /Show details/ }).click();
  await expect(item).toContainText("88.8 do not appear in the text the search tool cited");
  // Accepting it knowingly is allowed: nothing is suppressed.
  await item.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(item.getByRole("radio", { name: "Accept", exact: true })).toBeChecked();
});

test("T101 a removed sentence is gone from the text and listed as removed by you", async ({ page, request }) => {
  const period = "Week ending 2026-11-13";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Remove this sentence/ }).click();

  await expect(page.getByRole("heading", { name: "Sentence removed." })).toBeVisible();
  await expect(flagged(page)).toHaveCount(0);
  const removed = page.locator("li[data-index]", { hasText: "(removed by you)" });
  await expect(removed).toHaveCount(1);
  await expect(removed).toContainText("Removed by you");
  await expect(page.getByLabel("Sentences you edited")).toHaveCount(0); // a removal is not shown inside the text
  await expect(page.locator("article").getByText("Sh99.9 billion.")).toHaveCount(0);
});

test("T102 text that is not plain is refused beside the box and nothing is saved", async ({ page, request }) => {
  const period = "Week ending 2026-11-20";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  const box = page.getByRole("textbox", { name: "Your sentence" });
  await box.fill("See [the report](https://example.org/x) for Sh30.1 billion.");
  await page.getByRole("button", { name: "Save as a new version" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Type plain text only" })).toBeVisible();
  await expect(box).toHaveValue("See [the report](https://example.org/x) for Sh30.1 billion."); // what was typed is kept
  await expect(page.getByRole("heading", { name: /^Sentence edited/ })).toHaveCount(0);
});

test("T103 over 600 characters cannot be saved, and the count says by how much", async ({ page, request }) => {
  const period = "Week ending 2026-11-27";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  await page.getByRole("textbox", { name: "Your sentence" }).fill("x".repeat(603));
  await expect(page.getByText("Over the limit by 3 characters.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save as a new version" })).toBeDisabled();
});

test("T104 on an approved section it asks first and says the approval is removed", async ({ page, request }) => {
  const period = "Week ending 2026-12-04";
  const first = await draftFocus(request, period);
  const review = await (await request.get(`${API}/api/reviews/${first}`)).json();
  for (const item of review.review_items) {
    expect((await request.patch(`${API}/api/reviews/${first}/items/${item.index}`, { headers: json, data: { resolution: "accept" } })).ok()).toBe(true);
  }
  expect((await request.post(`${API}/api/reviews/${first}/decide`, { headers: json, data: { decision: "approved" } })).ok()).toBe(true);
  await open(page, period, first);

  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  await page.getByRole("textbox", { name: "Your sentence" }).fill(GOOD);
  await page.getByRole("button", { name: "Save as a new version" }).click();
  const dialog = page.getByRole("dialog", { name: "Save your sentence as a new version?" });
  await expect(dialog).toContainText("removes the approval");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect((await (await request.get(`${API}/api/reviews/${first}`)).json()).decision).toBe("approved");

  await page.getByRole("button", { name: "Save as a new version" }).click();
  await page.getByRole("dialog", { name: "Save your sentence as a new version?" }).getByRole("button", { name: "Save a new version" }).click();
  await expect(page.getByText("The earlier version was approved, so this one needs approving again.")).toBeVisible();
  expect((await (await request.get(`${API}/api/reviews/${first}`)).json()).decision).toBe("approved"); // the approved version is untouched
});
