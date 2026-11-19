import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, overviewUrl, release } from "./helpers";

// A flagged sentence of a drafted piece, edited or removed by hand. The test backend drafts a topic that says "bad figure"
// with a sentence whose figure (Sh99.9 billion) is not in the text its source cited (e2e/serve_e2e.py). Each test uses
// one typed section and its own week.
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const json = { "Content-Type": "application/json" };
const GOOD = "Lending rose to Sh30.1 billion over the quarter.";
const BAD = "Lending rose to Sh88.8 billion over the quarter.";

async function draftFocus(request: APIRequestContext, period: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/focus/draft`, {
    headers: json,
    data: { report_type: "weekly", period, topic: "SYNTHETIC bad figure topic", sections: "Overview of the topic" },
    timeout: 120_000,
  });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

async function open(page: Page, period: string, runId: number) {
  await page.goto(`${overviewUrl(period)}&review=${runId}`);
  await expect(page.getByRole("heading", { name: "Focus of the Week: analyst review", level: 1 })).toBeVisible();
}

const flagged = (page: Page) => page.locator('li[data-status="flagged"]');
const overviewClaim = (page: Page, status: string, text: string) =>
  page.locator(`li[data-status="${status}"]`).filter({ hasText: `I Overview of the topic: ${text}` });

test("T99 an edited sentence with a figure the source has is no longer flagged, and is marked as edited", async ({ page, request }) => {
  const period = "Week ending 2026-10-30";
  const first = await draftFocus(request, period);
  await open(page, period, first);
  await expect(flagged(page)).toHaveCount(2); // the mismatched claim and the carried disclaimer

  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  const box = page.getByRole("textbox", { name: "Your sentence" });
  await expect(box).toHaveValue("Lending rose to Sh99.9 billion.");
  await box.fill(GOOD);
  await page.getByRole("button", { name: "Save as a new version" }).click();

  await expect(page.getByRole("heading", { name: "Sentence edited. The figures were checked again." })).toBeVisible();
  await expect(overviewClaim(page, "not_auto_verified", GOOD)).toBeVisible();
  await expect(flagged(page)).toHaveCount(1); // only the carried disclaimer remains flagged
  await expect(page.getByText(/Edited by you, .* EAT/).first()).toBeVisible();
  await expect(page.getByLabel("Sentences you edited")).toContainText(GOOD);

  // The earlier review is still there, as drafted.
  const old = await (await request.get(`${API}/api/reviews/${first}`)).json();
  expect(old.decision).toBeNull();
  expect(old.section.blocks.find((b: { kind: string; body_md: string }) => b.kind === "narrative" && b.body_md.includes("Sh99.9 billion."))).toBeTruthy();
});

test("T100 an edited sentence with a figure no source has stays flagged and says so, and the approval dialog still counts it", async ({ page, request }) => {
  const period = "Week ending 2026-11-06";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Edit this sentence/ }).click();
  await page.getByRole("textbox", { name: "Your sentence" }).fill(BAD);
  await page.getByRole("button", { name: "Save as a new version" }).click();

  await expect(page.getByRole("heading", { name: "Sentence edited. The figures were checked again." })).toBeVisible();
  const item = overviewClaim(page, "flagged", BAD);
  await expect(item).toHaveCount(1);
  await expect(flagged(page)).toHaveCount(2);
  await expect(item).toContainText("Edited by you");
  await item.getByRole("button", { name: /Show details/ }).click();
  await expect(item).toContainText("88.8 do not appear in the text the search tool cited");
  // Nothing is suppressed: approving still asks first and counts the edited sentence among the flagged items. Cancelling records nothing.
  const approve = page.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeEnabled();
  await approve.click();
  const dialog = page.getByRole("dialog", { name: "Approve with flagged items?" });
  await expect(dialog).toContainText("This section has 2 flagged items:");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  const saved = await page.getByText(/^Saved as run \d+$/).textContent(); // the status bar names the review on screen: the edited one
  const runId = saved?.match(/\d+/)?.[0];
  expect(runId).toBeTruthy();
  expect((await (await request.get(`${API}/api/reviews/${runId}`)).json()).decision).toBeNull();
});

test("T101 a removed sentence is gone from the text and listed as removed by you", async ({ page, request }) => {
  const period = "Week ending 2026-11-13";
  await open(page, period, await draftFocus(request, period));
  await page.getByRole("button", { name: /^Remove this sentence/ }).click();

  await expect(page.getByRole("heading", { name: "Sentence removed." })).toBeVisible();
  await expect(flagged(page)).toHaveCount(1); // only the carried disclaimer remains flagged
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
  const flagged = review.review_items.filter((i: { status: string }) => i.status === "flagged").length;
  expect((await request.post(`${API}/api/reviews/${first}/decide`, { headers: json, data: { decision: "approved", acknowledged_flagged: flagged } })).ok()).toBe(true);
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

test("T105 the server refuses an approval that does not name the flagged count, records nothing, and takes the right count", async ({ request }) => {
  const id = await draftFocus(request, "Week ending 2026-12-11");
  const review = await (await request.get(`${API}/api/reviews/${id}`)).json();
  const flagged = review.review_items.filter((i: { status: string }) => i.status === "flagged").length;
  expect(flagged).toBeGreaterThan(1);
  const decide = (data: object) => request.post(`${API}/api/reviews/${id}/decide`, { headers: json, data: { decision: "approved", ...data } });

  for (const sent of [{}, { acknowledged_flagged: 0 }, { acknowledged_flagged: flagged - 1 }, { acknowledged_flagged: flagged + 1 }]) {
    const refused = await decide(sent);
    expect(refused.status(), JSON.stringify(sent)).toBe(409);
    expect(JSON.stringify(await refused.json())).toContain("flagged item");
  }
  const untouched = await (await request.get(`${API}/api/reviews/${id}`)).json();
  expect(untouched.decision).toBeNull();
  expect(untouched.review_items.every((i: { resolution: string | null }) => i.resolution === null)).toBe(true);

  const approved = await decide({ acknowledged_flagged: flagged });
  expect(approved.status(), await approved.text()).toBe(200);
  expect((await approved.json()).decision).toBe("approved");
  // A decision is made once: the same call again is refused, whatever it names.
  expect((await decide({ acknowledged_flagged: flagged })).status()).toBe(409);
});

test("T115 rejecting a section whose item carries a fix-needed note: the next draft shows that note, read-only, and its own approval does not depend on it", async ({ page, request }) => {
  const period = "Week ending 2026-12-18";
  const first = await draftFocus(request, period);
  const earlier = await (await request.get(`${API}/api/reviews/${first}`)).json();
  const item = earlier.review_items.find((i: { status: string }) => i.status === "flagged");
  const note = "Check the Sh99.9 billion figure against its source.";
  // The screen no longer sets a resolution or a note, but the API still stores one, and a rejection carries it to the next draft.
  const marked = await request.patch(`${API}/api/reviews/${first}/items/${item.index}`, { headers: json, data: { resolution: "fix_needed", note } });
  expect(marked.ok()).toBe(true);

  await open(page, period, first);
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Reject this section?" });
  await dialog.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Decision recorded: rejected.")).toBeVisible();
  await expect(page.getByText("Rejected and locked")).toBeVisible();
  expect((await (await request.get(`${API}/api/reviews/${first}`)).json()).decision).toBe("rejected");

  const second = await draftFocus(request, period);
  expect(second).not.toBe(first);
  await open(page, period, second);
  const notes = page.getByRole("region", { name: `Notes from the rejected draft (run ${first})` });
  await expect(notes).toContainText(note);
  await expect(notes).toContainText("Fix needed");
  await expect(notes).toContainText("these notes were not carried onto the new items");
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled(); // the new review is undecided and its own
  expect((await (await request.get(`${API}/api/reviews/${second}`)).json()).decision).toBeNull();
});
