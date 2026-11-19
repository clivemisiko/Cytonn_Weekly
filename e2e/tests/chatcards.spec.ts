import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, PERIOD, VARIANT, WEEK, overviewUrl, topbar } from "./helpers";

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
  await card.getByRole("button", { name: "Show the list" }).click(); // the list starts folded
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
  await expect(form).toHaveAttribute("href", /\/overview\?report=weekly&period=Week\+ending\+2026-08-28&section=fixed_income&from=chat$/);
  await form.click();
  await expect(page.getByRole("heading", { name: "Fixed Income: analyst review", level: 1 })).toBeVisible();
});

test("T121 Real Estate shows its snip counts and Focus its source counts as they are, with the not-judged note; Focus sends the topic to the Focus page", async ({ page }) => {
  const NOT_JUDGED = "The snip and source counts are as they are: this check does not say whether they are enough.";
  await page.goto(chatUrl("real_estate"));
  const readiness = page.getByRole("region", { name: /What Real Estate needs/ });
  await readiness.getByRole("button", { name: "Show the list" }).click(); // the list starts folded
  await expect(readiness.getByText("Land: 0 uploaded, 0 read, 0 confirmed")).toBeVisible();
  await expect(readiness.getByText("0 saved, 0 dated inside the week, 0 outside it")).toBeVisible();
  await expect(readiness.getByText(NOT_JUDGED)).toBeVisible();
  const sources = page.getByRole("region", { name: "Sources and snips" });
  await expect(sources.getByText("Hospitality and Tourism: 0 uploaded, 0 read, 0 confirmed")).toBeVisible();
  await expect(sources.getByText(NOT_JUDGED)).toBeVisible();
  await expect(sources.getByRole("link", { name: /Open snips and sources/ })).toHaveAttribute("href", /section=real_estate&from=chat$/);

  await page.goto(chatUrl("focus"));
  await expect(page.getByRole("region", { name: "Sources and snips" }).or(page.getByRole("region", { name: "Sources" })).getByText("0 saved, 0 dated inside the week, 0 outside it")).toBeVisible();
  await expect(live(page).getByText("This section needs a topic and section titles, which are typed on the Focus page.")).toBeVisible();
  await expect(live(page).getByRole("button", { name: /Start draft/ })).toHaveCount(0);
  await live(page).getByRole("link", { name: "Open the Focus page" }).click();
  await expect(page.getByRole("heading", { name: "Focus of the Week: analyst review", level: 1 })).toBeVisible();
  await expect(page.getByLabel(/topic/i).first()).toBeVisible(); // where the topic is typed
  await page.getByRole("link", { name: "Back to chat" }).click();
  await expect(page).toHaveURL(/\/chat\?.*section=focus/);
  await expect(page.getByRole("heading", { name: "Focus of the Week", level: 2 })).toBeVisible();
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

test("T125 the rail and the chat have no way to the old pages: no Overview or Previous reports item, no Old page or overview link, and a rail section opens its chat", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const OLD = 'a[href*="/overview"], a[href*="/previous"], a[href*="/runs/"], a[href*="/sources/"]';
  for (const url of [`/chat?period=${encodeURIComponent(PERIOD)}`, chatUrl("fixed_income"), chatUrl("real_estate"), chatUrl("focus")]) {
    await page.goto(url);
    await expect(rail(page).getByRole("button", { name: /^Fixed Income, / })).toBeVisible();
    for (const name of ["Overview", "Previous reports", "Change report"]) await expect(rail(page).getByRole("button", { name, exact: true })).toHaveCount(0);
    await expect(rail(page).locator(OLD)).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Old page/ })).toHaveCount(0);
    await expect(page.getByRole("banner").locator(OLD)).toHaveCount(0); // the top bar's Home is the chat
  }
  // Only the chat buttons that need an old page reach one, and each says it comes back (T126); nothing in the picker or the aside does.
  await page.goto(`/chat?period=${encodeURIComponent(PERIOD)}`);
  await expect(page.getByRole("main").locator(OLD)).toHaveCount(0);
  await page.goto(chatUrl("fixed_income"));
  await expect(aside(page).locator(OLD)).toHaveCount(0);
  await rail(page).getByRole("button", { name: /^Equities, / }).click();
  await expect(page).toHaveURL(/\/chat\?.*section=equities/);
});

test("T126 Open inputs form opens the form, and Back to chat returns to the same section and week", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const bare = "Week ending 2026-08-28";
  await page.goto(chatUrl("fixed_income", bare));
  await page.getByRole("region", { name: "Needs you" }).getByRole("link", { name: "Open inputs form" }).click();
  await expect(page.getByRole("heading", { name: "Fixed Income: analyst review", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Weekly analyst inputs" })).toBeVisible();
  await expect(topbar(page).getByRole("button", { name: "Back to chat" })).toBeVisible(); // the top bar's Back goes there too
  await page.getByRole("link", { name: "Back to chat" }).click();
  await expect(page).toHaveURL(/\/chat\?.*section=fixed_income/);
  expect(new URL(page.url()).searchParams.get("period")).toBe(bare);
  await expect(page.getByRole("heading", { name: "Fixed Income", level: 2 })).toBeVisible();
  await expect(page.getByLabel("Week", { exact: true })).toHaveValue(bare);

  // The same page by its address, not from the chat: no Back to chat, and it works as it always did.
  await page.goto(`${overviewUrl(bare)}&section=fixed_income`);
  await expect(page.getByRole("heading", { name: "Weekly analyst inputs" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to chat" })).toHaveCount(0);
});

test("T127 the export card has This week's rows (xlsx): it saves the workbook, and the 409 and 422 answers are shown in plain words", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(chatUrl("equities"));
  const button = page.getByRole("button", { name: "This week's rows (xlsx)" });
  await expect(button).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(download.suggestedFilename()).toBe(`Weekly rows, week ending ${WEEK}.xlsx`);
  await expect(button).toBeEnabled();

  const refuse = (status: number, detail: string) => page.route("**/api/export/weekly-rows/*", (route) => route.fulfill({ status, headers: json, body: JSON.stringify({ detail }) }));
  await refuse(409, "An uploaded workbook cannot be read, so the layout cannot be taken from it: eq.xlsx could not be opened");
  await button.click();
  const alert = page.getByRole("alert").filter({ hasText: "cannot be taken from it" });
  await expect(alert).toContainText("Upload that workbook again or remove it, then try again.");
  await page.unroute("**/api/export/weekly-rows/*");
  await refuse(422, "'2026-10-01' is not a Friday");
  await button.click();
  await expect(page.getByRole("alert").filter({ hasText: "Choose the Friday the week ends on, then try again." })).toBeVisible();
  await expect(alert).toHaveCount(0); // the new answer replaced the old one
  await page.unroute("**/api/export/weekly-rows/*");
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeVisible(); // the weekly report's own button is as it was
});

test("T128 the needs-you card has a fetch button for the interbank rates, and a refusal is shown in words that say to type them", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const sentence = "Daily interbank rates could not be fetched from CBK. E2E: CBK is down. Type them under \"Weekly analyst inputs\" instead.";
  await page.route("**/api/inputs/weekly/*/analyst/fetch/interbank*", (route) =>
    route.fulfill({ status: 502, headers: json, body: JSON.stringify({ detail: sentence, problems: [{ code: "item_fetch_failed", headline: "The figures could not be fetched", target: "analyst-form" }] }) }),
  );
  await page.goto(chatUrl("fixed_income", "Week ending 2026-08-28"));
  const needs = page.getByRole("region", { name: "Needs you" });
  const sections = page.waitForRequest((r) => r.url().includes("/api/sections"));
  await needs.getByRole("button", { name: /^Fetch interbank rates from CBK/ }).click();
  await expect(needs.getByRole("alert")).toContainText("Type them under");
  await sections;
});

test("T129 the needs-you card has a fetch button for the Eurobond openings, and a refusal says to type them", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const sentence = "Eurobond yields on days the bulletin does not print are not available yet: the issue of 2026-08-07 is not in CBK's archive. Try again later, or type them under \"Weekly analyst inputs\".";
  await page.route("**/api/inputs/weekly/*/analyst/fetch/eurobond_yields*", (route) =>
    route.fulfill({ status: 404, headers: json, body: JSON.stringify({ detail: sentence, problems: [{ code: "item_fetch_failed", headline: "The figures could not be fetched", target: "analyst-form" }] }) }),
  );
  await page.goto(chatUrl("fixed_income", "Week ending 2026-08-28"));
  const needs = page.getByRole("region", { name: "Needs you" });
  await needs.getByRole("button", { name: /^Fetch Eurobond openings from CBK/ }).click();
  await expect(needs.getByRole("alert")).toContainText("type them under");
});

test("T130 the fund snip card: upload, list, read, decide, type a cell and a fund the page lacks, then Use this table keeps a ranked table that shares ranks", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const bare = "Week ending 2026-08-28";
  await page.goto(chatUrl("fixed_income", bare));
  const card = page.getByRole("region", { name: "Money market fund table" });
  await expect(card).toBeVisible();
  await expect(card.getByRole("button", { name: "Read the page" })).toHaveCount(0);

  await card.locator('input[type="file"]').setInputFiles({ name: "page.png", mimeType: "image/png", buffer: Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("invented")]) });
  await expect(card.getByRole("img", { name: "The Daily Nation page uploaded for this week" })).toBeVisible();

  await card.getByText(/^Fund list \(/).click();
  await card.getByLabel(/^The funds the report's table uses/).fill(["Alpha Money Market Fund", "Beta Money Market Fund", "Gamma Money Market Fund", "Delta Money Market Fund", "Eta Money Market Fund", "Omega Money Market Fund"].join("\n"));
  await card.getByRole("button", { name: "Save the list" }).click();
  await expect(card.getByText("Fund list (6 funds)")).toBeVisible();

  await card.getByRole("button", { name: "Read the page" }).click();
  await expect(card.getByTestId("fund-counts")).toHaveText("8 rows read: 5 on the list, 1 to decide, 1 left out, 1 dollar fund (not in the table).");
  const use = card.getByRole("button", { name: "Use this table" });
  await expect(use).toBeDisabled();
  await expect(card.getByText("1 row has a cell to type or a row to ignore.")).toBeVisible();
  await expect(card.getByText("1 fund not on the list is still to decide.")).toBeVisible();

  await card.getByLabel("Annual rate, row 8").fill("7.0");
  await card.getByLabel("Annual rate, row 8").press("Tab");
  await expect(card.getByText("1 row has a cell to type or a row to ignore.")).toHaveCount(0);
  await card.getByRole("button", { name: /^Leave out\s*: Zeta Money Market Fund$/ }).click();
  await expect(card.getByText("Left out (2)")).toBeVisible();
  await expect(card.getByTestId("fund-counts")).toContainText("5 on the list, 0 to decide, 2 left out");

  await card.getByLabel("Annual rate for Omega Money Market Fund").fill("9.5");
  await card.getByRole("button", { name: /^Add\s*: Omega Money Market Fund$/ }).click();
  await expect(card.getByText("Omega Money Market Fund: 9.5%")).toBeVisible();

  await card.getByLabel("Fund table published on").fill("2026-08-28");
  await expect(use).toBeEnabled();
  await use.click();
  await expect(card.getByRole("status")).toContainText("The table of 6 funds is kept on the form.");

  const form = await (await request.get(`${API}/api/inputs/weekly/2026-08-28/analyst?section=fixed_income`)).json();
  const table = form.groups.flatMap((g: { items: { key: string }[] }) => g.items).find((i: { key: string }) => i.key === "mmf");
  expect(table.rows.map((r: { rank: string }) => r.rank)).toEqual(["1", "1", "3", "4", "5", "6"]); // the two 10.5 funds share a rank
  expect(table.carried.from).toBe("snip");
  await expect(page.getByRole("region", { name: "Needs you" }).getByText(/Money market fund table/)).toHaveCount(0);
});

// A bare Fixed Income week has four inline steps: 1 placements (a field), 2 Eurobond issues (the grid), 3 the borrowing target
// (a field), 4 other bond redemptions (the paste table).  Each test takes its own Friday, so a save in one never shows in another.
const typedCard = (page: Page) => page.getByRole("region", { name: "Type these here" });

test("T131 a typed value is saved from the chat: a refusal keeps the text under the API's words, Enter saves and moves on", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(chatUrl("fixed_income", "Week ending 2026-08-14"));
  const card = typedCard(page);
  const box = card.getByLabel("3-month bank placements");
  await expect(card.getByText("Step 1 of 4", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Needs you" }).getByText(/3-month bank placements/)).toHaveCount(0);

  const save = card.getByRole("button", { name: /^Save\s*: 3-month bank placements$/ });
  await save.click();
  await expect(card.getByText("Type a value before saving.")).toBeVisible();
  await box.fill("not a figure");
  await save.click();
  await expect(card.getByText(/is not a number/)).toBeVisible();
  await expect(box).toHaveValue("not a figure");
  await expect(card.getByText("Step 1 of 4", { exact: true })).toBeVisible();

  await box.fill("5.55");
  await box.press("Enter");
  await expect(card.getByText("Step 2 of 4", { exact: true })).toBeVisible();
  await expect(card.locator("[aria-live]").first()).toHaveText("Step 2 of 4, Eurobond issues"); // the polite announcement
  await card.getByRole("button", { name: "Previous" }).click();
  await expect(card.getByText("Saved: 5.55")).toBeVisible(); // the step stays in place, marked
  await expect(card.getByText("Step 1 of 4", { exact: true })).toBeVisible();
});

test("T132 Next and Previous move between steps, typed text survives going back, a skipped line is still to type", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(chatUrl("fixed_income", "Week ending 2026-07-31"));
  const card = typedCard(page);
  const previous = card.getByRole("button", { name: "Previous" });
  const next = card.getByRole("button", { name: "Next" });
  await expect(previous).toBeDisabled();
  await card.getByLabel("3-month bank placements").fill("7.77");
  await next.click();
  await expect(card.getByText("Step 2 of 4", { exact: true })).toBeVisible();
  await expect(card.getByLabel("3-month bank placements")).toBeHidden();
  await next.click();
  await expect(card.getByLabel("Net domestic borrowing target for the fiscal year")).toBeFocused();
  await previous.click();
  await previous.click();
  await expect(card.getByLabel("3-month bank placements")).toHaveValue("7.77");
  await expect(card.getByLabel("3-month bank placements")).toBeFocused();

  for (let i = 0; i < 3; i++) await next.click();
  await card.getByRole("button", { name: "Done" }).click();
  await expect(card.getByText("4 still to type", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Go to the first one" }).click();
  await expect(card.getByText("Step 1 of 4", { exact: true })).toBeVisible();
  await expect(card.getByLabel("3-month bank placements")).toHaveValue("7.77");
  // Skipped, so nothing was saved: the readiness check still lists it as needing the analyst.
  const job = page.waitForResponse((r) => /\/api\/jobs\/\d+\/readiness/.test(r.url()));
  await page.reload();
  const groups = (await (await job).json()).readiness.groups;
  expect(groups.needs_analyst.map((e: { key: string }) => e.key)).toContain("placements");
});

test("T133 every step saved, the grid and the paste table included: the confirmation shows and focus is on the heading", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(chatUrl("fixed_income", "Week ending 2026-07-24"));
  const card = typedCard(page);
  await card.getByLabel("3-month bank placements").fill("5.55");
  await card.getByLabel("3-month bank placements").press("Enter");

  await expect(card.getByText("Step 2 of 4", { exact: true })).toBeVisible();
  await card.locator('[data-step="1"] input').first().fill("1000");
  await card.locator('[data-step="1"]').getByRole("button", { name: "Save", exact: true }).click();

  await expect(card.getByText("Step 3 of 4", { exact: true })).toBeVisible();
  await card.getByLabel("Net domestic borrowing target for the fiscal year").fill("100");
  await card.getByLabel("Net domestic borrowing target for the fiscal year").press("Enter");

  await expect(card.getByText("Step 4 of 4", { exact: true })).toBeVisible();
  await card.getByLabel("Other bond redemptions: paste the rows").fill("2026-07-20  FAKE/0000/01  123.45");
  await card.getByRole("button", { name: "Save table" }).click();

  await expect(card.getByText("All typed values are saved.")).toBeVisible();
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("live-title");
});

// ---- The prepare page: Equities with no draft opens on it, with no conversation. Each test takes its own Friday. ----
const prepare = (page: Page) => page.locator('[data-card="prepare"]');

test("T134 the prepare page: the banner counts, the source table, an upload and a fetch refused in words, and no conversation opened", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const opened: string[] = [];
  page.on("request", (r) => r.method() === "POST" && r.url().endsWith("/api/jobs") && opened.push(r.url()));
  await page.goto(chatUrl("equities", "Week ending 2026-06-05"));
  const p = prepare(page);
  await expect(p.getByRole("heading", { name: "Equities", level: 2 })).toBeVisible();
  await expect(p.getByText("Not drafted", { exact: true })).toBeVisible();
  await expect(p.getByText(/^\d+ required items? missing$/)).toBeVisible();
  await expect(page.getByRole("log", { name: "Conversation" })).toHaveCount(0);

  const checklist = p.getByRole("button", { name: "View checklist" });
  await expect(checklist).toHaveAttribute("aria-expanded", "false");
  await checklist.click();
  await expect(p.getByRole("button", { name: "Hide checklist" })).toHaveAttribute("aria-expanded", "true");
  await expect(p.locator("#prepare-checklist").getByText("Equities workbook: not uploaded")).toBeVisible();

  const table = p.getByRole("table");
  await expect(table.getByRole("columnheader")).toHaveText(["Document", "Status", "Action"]);
  await expect(table.getByRole("row", { name: /Equities workbook/ })).toContainText("Not uploaded");
  await expect(p.getByText("0 of 4 added")).toBeVisible();

  await p.getByLabel("Upload Equities workbook").setInputFiles({ name: "fake.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("not a workbook") });
  await expect(p.getByRole("alert")).toContainText("fake.xlsx:");
  await expect(table.getByText("Chosen: fake.xlsx")).toBeVisible();

  await p.getByRole("button", { name: /^Fetch from CBK\s*: CBK Weekly Bulletin$/ }).click();
  await expect(p.getByRole("alert")).toContainText("E2E: no bulletin is saved for 2026-06-05");
  expect(opened).toEqual([]); // reading, uploading and fetching opened no conversation
});

test("T135 the prepare page's inputs: Save moves on and lowers the banner count, Previous shows it saved, a skip keeps what was typed", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(chatUrl("equities", "Week ending 2026-06-12"));
  const p = prepare(page);
  const banner = p.getByText(/^\d+ required items? missing$/);
  const before = Number((await banner.textContent())!.split(" ")[0]);
  await expect(p.getByText("Step 1 of 9", { exact: true })).toBeVisible();
  await expect(p.getByRole("button", { name: "Previous" })).toBeDisabled();

  const first = p.getByLabel("Year-to-date equities turnover");
  await first.fill("123.4");
  await first.press("Enter");
  await expect(p.getByText("Step 2 of 9", { exact: true })).toBeVisible();
  await expect(p.getByLabel("Year-to-date foreign net position")).toBeFocused();
  await expect(p.getByText(`${before - 1} required item${before - 1 === 1 ? "" : "s"} missing`)).toBeVisible();

  await p.getByLabel("Year-to-date foreign net position").fill("1.5");
  await p.getByRole("button", { name: "Next" }).click(); // a skip: nothing is saved
  await expect(p.getByText("Step 3 of 9", { exact: true })).toBeVisible();
  await p.getByRole("button", { name: "Previous" }).click();
  await expect(p.getByLabel("Year-to-date foreign net position")).toHaveValue("1.5");
  await p.getByRole("button", { name: "Previous" }).click();
  await expect(p.getByText("Saved: 123.4")).toBeVisible();
  await expect(p.getByText(`${before - 1} required item${before - 1 === 1 ? "" : "s"} missing`)).toBeVisible(); // the skip lowered nothing
});

test("T136 Create draft opens the conversation and starts the draft; a drafted section shows the conversation with a way back", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "Week ending 2026-09-04"; // a demo Friday the test backend drafts Equities for with no outside source
  await page.goto(chatUrl("equities", period));
  await prepare(page).getByRole("button", { name: /Create draft/ }).click();
  const ask = page.getByRole("dialog", { name: "Draft this section?" });
  await expect(ask.or(page.getByRole("log", { name: "Conversation" }))).toBeVisible();
  if (await ask.isVisible()) await ask.getByRole("button", { name: "Draft anyway" }).click();
  await expect(page).toHaveURL(/view=conversation/);
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
  await expect(live(page).getByRole("region", { name: /^Review of Equities/ })).toBeVisible({ timeout: 180_000 });

  await page.goto(chatUrl("equities", period)); // no flag: the section has a draft, so the conversation view
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
  await expect(prepare(page)).toHaveCount(0);
  await page.getByRole("link", { name: "Back to sources and inputs" }).click();
  await expect(prepare(page).getByText("In review", { exact: true })).toBeVisible();
  await expect(prepare(page).getByRole("link", { name: "Open the conversation" })).toHaveCount(0); // only the snapshot is in it
});

test("T137 the prepare page offers the conversation when one already holds more than its snapshot, and only then", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "Week ending 2026-06-19";
  await page.goto(chatUrl("equities", period));
  await expect(prepare(page).getByRole("heading", { name: "Source documents" })).toBeVisible();
  await expect(prepare(page).getByRole("link", { name: "Open the conversation" })).toHaveCount(0);
  // Someone talked before drafting: the readiness route is stood in for, saying so.
  await page.route("**/api/sections/equities/readiness*", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), conversation: true } });
  });
  await page.reload();
  const link = prepare(page).getByRole("link", { name: "Open the conversation" });
  await expect(link).toHaveAttribute("href", /view=conversation/);
  await link.click();
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
});
