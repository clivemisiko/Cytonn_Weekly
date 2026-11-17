import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, PERIOD, VARIANT, overviewUrl } from "./helpers";

test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const json = { "Content-Type": "application/json" };
const chatUrl = (section: string, period = PERIOD) => `/chat?section=${section}&period=${encodeURIComponent(period)}`;
const live = (page: Page) => page.getByRole("region", { name: "What you can do now" });
const aside = (page: Page) => page.getByRole("complementary", { name: "This conversation" });
const rail = (page: Page) => page.getByRole("navigation", { name: "Report sections" });

/** The test backend drafts Digital Payments for this one week with flagged items (e2e/serve_e2e.py, TAMPERED_FRIDAY). */
async function draftFlagged(request: APIRequestContext, period: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/digital_payments/draft`, { headers: json, data: { report_type: "weekly", period }, timeout: 120_000 });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

test("T120 the readiness card shows every group, and the needs-you card works: fetch and upload are refused in words, the rail is read again, the form is one link away", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  // A week with its inputs in: four groups, with a count each, in words; a group with nothing in it is left out.
  await page.goto(chatUrl("fixed_income"));
  const card = page.getByRole("region", { name: /What Fixed Income needs for the week ending 2026-10-09/ });
  await expect(card.getByText(/Needs you \(1\)/)).toBeVisible();
  await expect(card.getByText(/Fetched \(1\)/)).toBeVisible();
  await expect(card.getByText(/In place \(\d+\)/)).toBeVisible();
  await expect(card.getByText(/Optional \(2\)/)).toBeVisible();
  await expect(card.getByText(/Carried or suggested/)).toHaveCount(0);
  await expect(card.getByText("As it was when this conversation opened")).toBeVisible();

  // A bare week: the uploads that are missing, each with the button the old page's inputs panel has.
  const bare = "Week ending 2026-08-28";
  await page.goto(chatUrl("fixed_income", bare));
  const needs = page.getByRole("region", { name: "Needs you" });
  await expect(needs.getByText("not received; fetch it or upload it")).toBeVisible();
  const sections = page.waitForRequest((r) => r.url().includes("/api/sections"));
  const readiness = page.waitForRequest((r) => /\/api\/jobs\/\d+\/readiness/.test(r.url()));
  await needs.getByRole("button", { name: /^Fetch from CBK/ }).click();
  await expect(needs.getByRole("alert")).toContainText("E2E: no bulletin is saved for 2026-08-28");
  await sections; // the rail and the overview were read again after the press
  await readiness; // and so was the card
  await expect(rail(page).getByRole("button", { name: /^Fixed Income, / })).toBeVisible();

  await needs.getByLabel("Upload Fixed income workbook").setInputFiles({ name: "bad.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("not a workbook") });
  await expect(needs.getByRole("alert")).toContainText("bad.xlsx:");

  const form = needs.getByRole("link", { name: "Open inputs form" });
  await expect(form).toHaveAttribute("href", /\/overview\?report=weekly&period=Week%20ending%202026-08-28&section=fixed_income$/);
  await form.click();
  await expect(page.getByRole("heading", { name: "Fixed Income: analyst review", level: 1 })).toBeVisible();
});

test("T121 Real Estate shows its snip counts and Focus its source counts as they are, with the not-judged note; Focus sends the topic to the old page", async ({ page }) => {
  const NOT_JUDGED = "The snip and source counts are as they are: this check does not say whether they are enough.";
  await page.goto(chatUrl("real_estate"));
  const readiness = page.getByRole("region", { name: /What Real Estate needs/ });
  await expect(readiness.getByText("Land: 0 uploaded, 0 read, 0 confirmed")).toBeVisible();
  await expect(readiness.getByText("0 saved, 0 dated inside the week, 0 outside it")).toBeVisible();
  await expect(readiness.getByText(NOT_JUDGED)).toBeVisible();
  const sources = page.getByRole("region", { name: "Sources and snips" });
  await expect(sources.getByText("Hospitality and Tourism: 0 uploaded, 0 read, 0 confirmed")).toBeVisible();
  await expect(sources.getByText(NOT_JUDGED)).toBeVisible();
  await expect(sources.getByRole("link", { name: /Open snips and sources/ })).toHaveAttribute("href", /section=real_estate$/);

  await page.goto(chatUrl("focus"));
  await expect(page.getByRole("region", { name: "Sources and snips" }).or(page.getByRole("region", { name: "Sources" })).getByText("0 saved, 0 dated inside the week, 0 outside it")).toBeVisible();
  await expect(live(page).getByText("This section needs a topic and section titles, which are typed on the old page.")).toBeVisible();
  await expect(live(page).getByRole("button", { name: /Start draft/ })).toHaveCount(0);
});

test("T122 Start draft shows the steps as they happen, then the review summary joins the conversation and the review is read-only in the aside until it is decided here", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "Week ending 2026-11-20";
  await page.goto(chatUrl("digital_payments", period));
  const draft = page.getByRole("region", { name: "Draft" });
  await expect(draft.getByRole("heading", { name: "Ready to draft" })).toBeVisible();
  await draft.getByRole("button", { name: "Start draft" }).click();
  // Either the steps are still on screen or the draft was quick; the summary card is what matters, and it is code that saved it.
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log.getByRole("region", { name: /Digital Payments draft saved as review \d+/ })).toBeVisible({ timeout: 90_000 });
  const review = page.getByRole("region", { name: "Review of Digital Payments" });
  await expect(review).toBeVisible();
  await expect(review.getByText(/0 flagged/)).toBeVisible();
  await expect(rail(page).getByRole("button", { name: /^Digital Payments, In review/ })).toBeVisible();

  // The export control is the old page's own, and says what it says there.
  await expect(page.getByText(/Available once every section is approved: \d of \d still to go\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeDisabled();

  // Open full view: the review's own items in the aside, nothing in it that changes anything.
  await review.getByRole("button", { name: /^Open full view of the whole review/ }).click();
  const full = aside(page).getByRole("region", { name: "Full view" });
  await expect(full.getByText("Nothing can be changed here.")).toBeVisible();
  await expect(full.getByRole("heading", { name: "Review items" })).toBeVisible();
  await expect(full.getByRole("button", { name: /^(Approve|Reject|Edit this sentence|Remove|Fix|Save)/ })).toHaveCount(0);
  await full.getByRole("button", { name: "Close the full view" }).click();
  await expect(full).toHaveCount(0);

  // Approve with the old page's own control: nothing is flagged, so it records at once.
  await review.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(review.getByText(/Approved and locked/)).toBeVisible();
  await expect(rail(page).getByRole("button", { name: /^Digital Payments, Approved/ })).toBeVisible();
  await review.getByRole("button", { name: "Back to all sections" }).click();
  await expect(page.getByRole("heading", { name: "Choose what to talk about" })).toBeVisible();
});

test("T123 flagged items: each has Open full view, and approving from the chat without the acknowledgement is refused in the review page's own words, recording nothing", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "Week ending 2027-01-08";
  const id = await draftFlagged(request, period);

  await page.goto(chatUrl("digital_payments", period));
  const review = page.getByRole("region", { name: "Review of Digital Payments" });
  const items = review.locator('[data-card="flagged_item"]');
  await expect(items.first()).toBeVisible(); // the wrong price and the missing row
  const flaggedCount = await items.count();
  expect(flaggedCount).toBeGreaterThanOrEqual(1);
  await items.first().getByRole("button", { name: /^Open full view/ }).click();
  const full = aside(page).getByRole("region", { name: "Full view" });
  await expect(full.locator('li[data-status="flagged"]')).toHaveCount(1);
  await expect(full.getByRole("button", { name: /^(Approve|Reject|Edit this sentence|Remove|Fix|Save)/ })).toHaveCount(0);

  // The same request with the acknowledged count taken out, from the chat and from the review page.
  await page.route("**/api/reviews/*/decide", async (route) => {
    const { acknowledged_flagged: _dropped, ...rest } = route.request().postDataJSON();
    await route.continue({ postData: JSON.stringify(rest) });
  });
  await review.getByRole("button", { name: "Approve", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Approve with flagged items?" });
  await expect(dialog).toContainText(`This section has ${flaggedCount} flagged item`);
  await dialog.getByRole("button", { name: "Approve anyway" }).click();
  // The shared handler opens the same dialog it opens on the review page; "Show me" goes to the sentence in the card.
  const refused = page.getByRole("alertdialog", { name: "The decision was not recorded" });
  await expect(refused).toBeVisible();
  await refused.getByRole("button", { name: "Show me" }).click();
  const fromChat = review.getByRole("alert");
  await expect(fromChat).toContainText("flagged item");
  const chatWords = (await fromChat.innerText()).trim();
  expect((await (await request.get(`${API}/api/reviews/${id}`)).json()).decision).toBeNull(); // nothing was recorded

  await page.goto(`${overviewUrl(period)}&review=${id}`);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog", { name: "Approve with flagged items?" }).getByRole("button", { name: "Approve anyway" }).click();
  await expect(page.getByRole("alertdialog", { name: "The decision was not recorded" })).toBeVisible(); // the same dialog
  await page.getByRole("alertdialog", { name: "The decision was not recorded" }).getByRole("button", { name: "Show me" }).click();
  const onPage = page.locator('[data-attention="review-status-bar"]').getByRole("alert");
  await expect(onPage).toContainText("flagged item");
  expect((await onPage.innerText()).trim()).toBe(chatWords); // refused the same way
  expect((await (await request.get(`${API}/api/reviews/${id}`)).json()).decision).toBeNull();

  // With the count the dialog named, the chat records it.
  await page.unroute("**/api/reviews/*/decide");
  await page.goto(chatUrl("digital_payments", period));
  const again = page.getByRole("region", { name: "Review of Digital Payments" });
  await again.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog", { name: "Approve with flagged items?" }).getByRole("button", { name: "Approve anyway" }).click();
  await expect(again.getByText(/Approved and locked/)).toBeVisible();
  expect((await (await request.get(`${API}/api/reviews/${id}`)).json()).decision).toBe("approved");
});

test("T124 a queued draft has Cancel and a running one shows its steps and no Cancel; the cancel is the old route", async ({ page }) => {
  const period = "Week ending 2026-11-06";
  let state: "queued" | "running" = "queued";
  const when = "2026-11-06T08:00:00+00:00";
  const event = (seq: number, kind: string, label: string) => ({ seq, kind, label, detail: null, at: when });
  await page.route("**/api/sections?*", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const entry = { section: "fixed_income", slug: "fixed_income", state, position: state === "queued" ? 2 : null, run_id: "stubrun", title: "Fixed Income", report_type: "weekly", period, started_at: when, elapsed_seconds: 3, stale: false, stale_after_seconds: 900, step: null, reason: null };
    await route.fulfill({ json: { ...body, drafting: null, drafting_list: [entry] } });
  });
  await page.route("**/api/runs/stubrun", (route) =>
    route.fulfill({
      json: {
        run_id: "stubrun", report_type: "weekly", report_title: "Cytonn Weekly", period, section: "fixed_income", section_title: "Fixed Income", status: state,
        position: state === "queued" ? 2 : null, review_id: null, is_dev_draft: null, dev_mode_label: null,
        events: state === "running" ? [event(1, "run_started", "")] : [],
      },
    }),
  );
  let cancelled = 0;
  await page.route("**/api/runs/stubrun/cancel", (route) => {
    cancelled++;
    return route.fulfill({ json: { run_id: "stubrun", status: "cancelled" } });
  });

  await page.goto(chatUrl("fixed_income", period));
  const draft = page.getByRole("region", { name: "Draft" });
  await expect(draft.getByRole("heading", { name: "Draft queued" })).toBeVisible();
  await expect(draft.getByRole("status")).toContainText("It starts by itself when a drafting seat is free.");
  await draft.getByRole("button", { name: "Cancel this draft" }).click();
  await expect.poll(() => cancelled).toBe(1);

  state = "running";
  await page.reload();
  await expect(page.getByRole("region", { name: "Draft" }).getByRole("heading", { name: "Draft running" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Draft steps" }).getByText("Starting the draft.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Draft" }).getByRole("button", { name: "Cancel this draft" })).toHaveCount(0);
  await expect(page.getByText("A draft that is running cannot be stopped.")).toBeVisible();
});
