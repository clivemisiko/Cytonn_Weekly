import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { API, DRAFT, PERIOD, REPO, VARIANT, WEEK, card, draftAndApprove, hold, openStart, overviewUrl, putAnalyst, release, startRun, topbar } from "./helpers";

/**
 * The behaviours the first sixteen tests never exercised, against either app. This file has its own run on a freshly
 * restored test backend (`playwright test more`; the npm scripts do that): a section that has a review no longer
 * offers its start screen, and app.spec.ts leaves several in review. Each test leaves the week's inputs as it found them.
 * Where a test needs a state the screens cannot make quickly (a section approved, a value saved for another week, a
 * draft already running), it makes it through the API and then looks at the screens.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const inputsPanel = (page: import("@playwright/test").Page) => page.locator("section", { has: page.getByRole("heading", { name: "This week’s inputs" }) }).first();
const analystPanel = (page: import("@playwright/test").Page) => page.locator("section", { has: page.getByRole("heading", { name: "Weekly analyst inputs" }) }).first();

test("T17 inputs: remove a report and upload it again, Fetch from CBK (from a saved file), the two notes boxes", async ({ page, request }) => {
  await openStart(page, "Fixed Income");
  const panel = inputsPanel(page);
  await expect(panel.getByText("5 of 5 received")).toBeVisible();

  // Remove one day's KCB report; the slot counts it missing; upload the same file again.
  await panel.getByRole("button", { name: "Remove Monday’s report" }).click();
  await expect(panel.getByText("4 of 5 received")).toBeVisible();
  await expect(panel.getByText("Missing", { exact: true })).toBeVisible();
  await panel.locator('input[type="file"]').nth(2).setInputFiles(join(REPO, "backend", "data", "demo", "inputs", "SYNTHETIC_KCB_daily_2026-10-05.pdf"));
  await expect(panel.getByText("5 of 5 received")).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);

  // The bulletin: removed, the slot offers the fetch; fetched, it says where it came from. The test API answers the
  // fetch from a file saved in the repository, so nothing here reaches CBK.
  const bulletin = panel.locator("li", { hasText: "CBK Weekly Bulletin" }).first();
  await expect(bulletin.getByRole("button", { name: "Fetch from CBK" })).toHaveCount(0);
  await bulletin.getByRole("button", { name: /^Remove / }).click();
  await expect(bulletin).toContainText("Not received");
  await bulletin.getByRole("button", { name: "Fetch from CBK" }).click();
  await expect(bulletin).toContainText("Received, this week’s");
  await expect(bulletin).toContainText("fetched from CBK");
  await expect(bulletin).toContainText("dated 9 Oct 2026");
  const slots = (await (await request.get(`${API}/api/inputs/weekly/${WEEK}`)).json()).slots as { slug: string; file?: { fetched_from?: string } }[];
  expect(slots.find((s) => s.slug === "cbk_bulletin")?.file?.fetched_from).toContain("e2e.invalid");

  // The notes save when the box is left, and only then.
  const notes = async () => (await (await request.get(`${API}/api/inputs/weekly/${WEEK}`)).json()).notes as Record<string, string>;
  const before = await notes();
  const range = panel.getByLabel("T-bond bidding range (the analysts’ recommendation)");
  await expect(range).toHaveValue(before.bidding_range ?? "");
  await range.fill("SYNTHETIC e2e: bidding range 13.40% - 13.70%.");
  expect((await notes()).bidding_range ?? "").toBe(before.bidding_range ?? "");
  await range.blur();
  await expect.poll(async () => (await notes()).bidding_range).toBe("SYNTHETIC e2e: bidding range 13.40% - 13.70%.");
  const previous = panel.getByLabel("Previous issue (optional)");
  await previous.fill("891");
  await previous.blur();
  await expect.poll(async () => (await notes()).previous_issue).toBe("891");
  await expect(panel.getByRole("alert")).toHaveCount(0);
  // Opened again, the screen shows what was saved. Then both are put back.
  await openStart(page, "Fixed Income");
  await expect(inputsPanel(page).getByLabel("T-bond bidding range (the analysts’ recommendation)")).toHaveValue("SYNTHETIC e2e: bidding range 13.40% - 13.70%.");
  await expect(inputsPanel(page).getByLabel("Previous issue (optional)")).toHaveValue("891");
  await inputsPanel(page).getByLabel("Previous issue (optional)").fill("");
  await inputsPanel(page).getByLabel("Previous issue (optional)").blur();
  await expect.poll(async () => (await notes()).previous_issue ?? "").toBe("");
  await inputsPanel(page).getByLabel("T-bond bidding range (the analysts’ recommendation)").fill(before.bidding_range ?? "");
  await inputsPanel(page).getByLabel("T-bond bidding range (the analysts’ recommendation)").blur();
  await expect.poll(async () => (await notes()).bidding_range ?? "").toBe(before.bidding_range ?? "");
});

test("T18 analyst inputs: a typed table is saved, shown as the rows in use, and cleared again", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = analystPanel(page);
  const table = panel.locator("#analyst-mmf");
  await expect(panel.getByText("From the workbook, 12 rows", { exact: true })).toBeVisible();
  await table.fill("1 Alpha Fund 11.9\n2 Beta Fund 11.5\n3 Gamma Fund 11.1\n4 Delta Fund 10.8\n5 Epsilon Fund 10.2");
  await panel.getByRole("button", { name: "Save table" }).and(page.locator(":enabled")).click();
  await expect(panel.getByText(/^Typed, 5 rows/)).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  const rows = panel.getByRole("region", { name: "Money market fund table: rows in use" });
  await expect(rows.getByRole("row")).toHaveCount(6);
  await expect(rows).toContainText("Epsilon Fund");
  await expect(page.getByRole("button", { name: DRAFT })).toBeEnabled();
  await panel.getByRole("button", { name: "Clear typed table" }).first().click(); // the fund table is the first one
  await expect(panel.getByText("From the workbook, 12 rows", { exact: true })).toBeVisible();
  await expect(table).toHaveValue("");
  await expect(rows.getByRole("row")).toHaveCount(13);
});

test("T19 analyst inputs: start from last week’s form; a weekly figure waits to be confirmed", async ({ page, request }) => {
  const NEXT_WEEK = "2026-10-16";
  await putAnalyst(request, WEEK, "fixed_income", { placements: "9.5" }); // last week's form holds a weekly-changing figure
  try {
    await openStart(page, "Fixed Income", `Week ending ${NEXT_WEEK}`);
    const panel = analystPanel(page);
    const draft = page.getByRole("button", { name: `Draft the Week ending ${NEXT_WEEK} section` });
    await expect(panel.getByText("No workbook is uploaded for this week: the draft uses only what is typed here.", { exact: false })).toBeVisible();
    await expect(panel.getByText(/^Copies what was saved for the week ending 9 Oct 2026 into every item still empty here/)).toBeVisible();
    await expect(draft).toBeEnabled();
    await panel.getByRole("button", { name: "Start from last week’s form" }).click();

    // The weekly figure is carried but not used: it is named, the draft waits, and its box says why.
    await expect(panel.getByRole("status").filter({ hasText: "1 value needs confirming before a draft:" })).toContainText("3-month bank placements.");
    await expect(panel.getByText("Carried from week ending 9 Oct 2026, not confirmed", { exact: true })).toBeVisible();
    await expect(panel.locator("#analyst-placements")).toHaveValue("9.5");
    await expect(panel.getByText("This changes every week. Last week’s value is not used in a draft until you confirm it for this week or type this week’s.")).toBeVisible();
    await expect(draft).toBeDisabled();
    await expect(page.getByText("Something under “Weekly analyst inputs” is not saved yet", { exact: false })).toBeVisible();
    // A slow-changing table is carried and used at once, marked as carried.
    await expect(panel.getByText("Carried from week ending 9 Oct 2026, 5 rows", { exact: true })).toBeVisible();
    await expect(panel.getByText("Shaded cells with a dashed edge are carried from week ending 9 Oct 2026. Type over any that changed.")).toBeVisible();
    await expect(panel.getByLabel("2018 10-year issue: Amount issued (USD mn)")).toHaveAttribute("title", "Carried from week ending 9 Oct 2026");

    await panel.getByRole("button", { name: /^Confirm for this week\s*: 3-month bank placements$/ }).click();
    await expect(panel.getByText("Carried from week ending 9 Oct 2026", { exact: true })).toBeVisible();
    await expect(panel.getByText(/needs? confirming before a draft/)).toHaveCount(0);
    await expect(draft).toBeEnabled();
  } finally {
    await putAnalyst(request, WEEK, "fixed_income", { placements: null });
  }
});

test("T20 analyst inputs: a running total is suggested from last week’s, refused when there is none, and waits to be confirmed", async ({ page, request }) => {
  await putAnalyst(request, "2026-10-02", "equities", { turnover_ytd: "600.5" }); // the total saved for the week before
  try {
    await openStart(page, "Equities");
    const panel = analystPanel(page);
    const draft = page.getByRole("button", { name: DRAFT });
    // No total is saved for the foreign position, so there is nothing to add to: the API says so.
    await panel.getByRole("button", { name: /^Suggest from last week’s total\s*: Year-to-date foreign net position$/ }).click();
    await expect(panel.getByRole("alert")).toContainText("Year-to-date foreign net position: no total is saved for the week ending 2026-10-02 to add this week's figure to.");

    await panel.getByRole("button", { name: /^Suggest from last week’s total\s*: Year-to-date equities turnover$/ }).click();
    await expect(panel.getByText("Suggested, not confirmed", { exact: true })).toBeVisible();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(panel.locator("#analyst-turnover_ytd")).toHaveValue(/^6\d\d\.\d{4}$/);
    await expect(panel.getByText("A suggestion only. It is not used in a draft until you confirm it or type the figure yourself.")).toBeVisible();
    await expect(panel.getByText(/^Suggested: 600\.5000 saved for the week ending 2026-10-02 \+ /)).toBeVisible();
    await expect(panel.getByRole("status").filter({ hasText: "1 value needs confirming before a draft:" })).toContainText("Year-to-date equities turnover.");
    await expect(draft).toBeDisabled();
    await panel.getByRole("button", { name: /^Confirm for this week\s*: Year-to-date equities turnover$/ }).click();
    await expect(panel.getByText("Suggested, not confirmed", { exact: true })).toHaveCount(0);
    await expect(draft).toBeEnabled();
  } finally {
    await putAnalyst(request, WEEK, "equities", { turnover_ytd: null });
  }
});

test("T21 Focus of the Week: the topic is counted as the API counts it and blocks the draft over 500 characters", async ({ page }) => {
  await openStart(page, "Focus of the Week");
  const draft = page.getByRole("button", { name: DRAFT });
  const topic = page.getByLabel("This week’s topic");
  await expect(draft).toBeDisabled(); // no topic yet
  await expect(page.getByText("0 of 500 characters.")).toBeVisible();
  await topic.fill("  Eurobonds   in  2026 ");
  await expect(page.getByText("17 of 500 characters.")).toBeVisible(); // edges dropped, runs of spaces as one
  await expect(draft).toBeEnabled();
  await topic.fill("x".repeat(501));
  await expect(page.getByText("501 of 500 characters.", { exact: false })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Over the limit by 1 character. Shorten it to submit." })).toBeVisible();
  await expect(topic).toHaveAttribute("aria-invalid", "true");
  await expect(topic).toHaveValue("x".repeat(501)); // never cut
  await expect(draft).toBeDisabled();
  await topic.fill("x".repeat(502));
  await expect(page.getByRole("status").filter({ hasText: "Over the limit by 2 characters. Shorten it to submit." })).toBeVisible();
  await topic.fill("x".repeat(500));
  await expect(page.getByText("500 of 500 characters.")).toBeVisible();
  await expect(topic).not.toHaveAttribute("aria-invalid", "true");
  await expect(draft).toBeEnabled();
});

test("T22 weekly Digital Payments: its own review shape (highlights, the stock table, the outlook)", async ({ page }) => {
  await openStart(page, "Digital Payments");
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(page.getByRole("heading", { name: "Digital Payments: draft run", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Digital Payments: coordinator review", level: 1 })).toBeVisible();
  const draft = page.locator("section", { has: page.getByRole("heading", { name: /^Drafted section: / }) }).first();
  // The highlights under the report's own numerals, each with where it came from.
  const highlights = draft.locator("article");
  expect(await highlights.count()).toBeGreaterThanOrEqual(3);
  await expect(highlights.first().getByRole("heading", { level: 3 })).toHaveAttribute("id", "hl-I");
  await expect(highlights.nth(1).getByRole("heading", { level: 3 })).toHaveAttribute("id", "hl-II");
  await expect(highlights.first()).toContainText("Visa");
  await expect(highlights.first()).toContainText("Drafted by ");
  for (const link of await highlights.first().getByRole("link").all()) {
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("href", /^https?:/);
  }
  // The stock table, item V, with the weekly columns.
  const table = draft.getByRole("region", { name: /scrolls sideways on narrow screens$/ });
  await expect(table.getByRole("columnheader")).toHaveText(["Company", "Ticker", "Price", "Price 7 days ago", "Year Open", "w/w %", "YTD %", "Forward P/E"]);
  await expect(table.getByRole("row")).toHaveCount(4);
  await expect(table).toContainText("Mastercard");
  // The outlook and its figures.
  const outlook = draft.getByRole("region", { name: "Outlook" }).or(draft.locator('section[aria-label="Outlook"]'));
  await expect(outlook.locator("dl > div").first()).toBeVisible();
  // Its review items are the Digital Payments kinds.
  await page.getByRole("button", { name: /Clean \(\d+\)$/ }).click();
  const items = page.locator("li[data-status]");
  await expect(items.filter({ hasText: "Table row" }).first()).toBeVisible();
  await expect(items.filter({ hasText: "Outlook stat" }).first()).toBeVisible();
  await expect(items.filter({ hasText: "Highlight claim" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
});

test("T23 rejecting a section is final: the dialog, the locked review, the overview afterwards", async ({ page }) => {
  await openStart(page, "Company Updates");
  await page.getByLabel("Your Company Updates text").fill("Investment Updates:\nSYNTHETIC e2e text to be rejected.");
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
  const review = new URL(page.url()).searchParams.get("review");

  // Reject needs nothing resolved; it asks first.
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Reject this section?" });
  await expect(dialog).toContainText("The draft is sent back and frozen as it is. This is recorded once and cannot be changed; a new draft would have to be run.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await dialog.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(dialog).toBeHidden();

  await expect(page.getByText("Rejected and locked")).toBeVisible();
  await expect(page.getByText("Decision recorded: rejected.")).toBeVisible();
  await expect(page.getByText(/Decision recorded on .* UTC\. Every value below is frozen as drafted; nothing on\s+this screen can be changed\./)).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByLabel(/^Note for /)).toHaveAttribute("readonly", "");
  // Still rejected when opened again by its address.
  await page.goto(`${overviewUrl()}&review=${review}`);
  await expect(page.getByText("Rejected and locked")).toBeVisible();
  await page.getByRole("button", { name: "Back to all sections" }).last().click();
  await expect(card(page, "Company Updates")).toContainText("Rejected");
  await expect(card(page, "Company Updates").getByRole("button", { name: "View review" })).toBeVisible();
  await expect(page.getByText("Company Updates: Rejected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeDisabled();
  // "Draft again" opens the start screen, which says what happened and offers a new draft (T42 to T44 go through it).
  await card(page, "Company Updates").getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
  await expect(page.getByText(new RegExp(`review \\(run ${review}\\) was rejected`))).toBeVisible();
  await expect(page.getByRole("button", { name: "View it" })).toBeVisible();
  await expect(page.getByText("Or start over with a new draft.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save your text as the section" })).toBeVisible();
});

test("T24 a draft holding the one draft slot: the overview and the other sections say so, and unlock when it ends", async ({ page, request }) => {
  hold();
  const run = await startRun(request, "real_estate");
  await page.goto(overviewUrl());
  await expect(page.getByRole("status").filter({ hasText: "Drafting Real Estate" })).toContainText("One draft runs at a time, across every section; it is saved and shows");
  await expect(card(page, "Real Estate")).toContainText("Drafting now");
  await expect(card(page, "Real Estate")).toContainText("Drafting now; the review shows here when it finishes.");
  await expect(card(page, "Fixed Income")).not.toContainText("Drafting now");

  // Another drafting section: told which draft is running, and its own draft is off.
  await openStart(page, "Focus of the Week");
  await page.getByLabel("This week’s topic").fill("Eurobonds");
  const notice = page.getByRole("status").filter({ hasText: /^Real Estate \(Week ending 2026-10-09\) is drafting now \(/ });
  await expect(notice).toContainText("Only one draft runs at a time, across every section; drafting here unlocks when it finishes.");
  await expect(page.getByRole("button", { name: DRAFT })).toBeDisabled();
  // The API refuses a second draft in the same words, whatever the screen does.
  const second = await request.post(`${API}/api/runs`, { headers: { "Content-Type": "application/json" }, data: { section: "focus", report_type: "weekly", period: PERIOD, topic: "Eurobonds" } });
  expect(second.status()).toBe(409);
  expect((await second.json()).detail).toContain("Real Estate");

  // The section that is drafting says it is its own.
  await openStart(page, "Real Estate");
  await expect(page.getByRole("status").filter({ hasText: "This section is drafting now (" })).toContainText("It is saved when it finishes, and this screen then offers it for review.");
  await expect(page.getByRole("button", { name: DRAFT })).toBeDisabled();
  // A section that calls no provider takes no slot: no notice, and it can be saved.
  await openStart(page, "Company Updates");
  await expect(page.getByText("drafting now", { exact: false })).toHaveCount(0);

  // The run view of the held draft: running, nothing invented.
  await page.goto(`/runs/${run}`);
  await expect(page.getByText(/^Running\. Started .* UTC\.$/)).toBeVisible();
  await expect(page.getByRole("log", { name: "Steps of this draft" }).getByRole("listitem")).toHaveText(["Done: Starting the draft."]);

  // Let it end: the waiting screen unlocks by itself on its next poll.
  await openStart(page, "Focus of the Week");
  await page.getByLabel("This week’s topic").fill("Eurobonds");
  await expect(page.getByRole("button", { name: DRAFT })).toBeDisabled();
  release();
  await expect(page.getByRole("button", { name: DRAFT })).toBeEnabled({ timeout: 20_000 });
  await expect(page.getByText("is drafting now", { exact: false })).toHaveCount(0);
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Drafting Real Estate" })).toHaveCount(0);
});

test("T25 Executive Summary: refused until every section is approved, then composed, with what it leaves out", async ({ page, request }) => {
  test.setTimeout(240_000);
  const Q3 = "Q3'2026";
  await openStart(page, "Executive Summary", Q3, "quarterly");
  await expect(page.getByText(`Not composed for ${Q3} yet. It is built only from sections you have approved.`)).toBeVisible();
  await expect(page.getByText("Nothing is searched or drafted: each approved section’s lead piece is carried with its sources and checked again.")).toBeVisible();
  await page.getByRole("button", { name: `Compose the ${Q3} summary` }).click();
  // Nothing is approved yet: the run stops and names each section.
  const stopped = page.getByRole("alert").filter({ hasText: "The draft stopped." });
  await expect(stopped).toContainText("The Executive Summary is composed from approved sections only. Still to approve:");
  await expect(stopped).toContainText("Fixed Income");

  // Draft and approve the other eight sections through the API (on the test suite's captured sources).
  await draftAndApprove(request, "company_updates", Q3, "quarterly", "Investment Updates: SYNTHETIC e2e text. Hospitality Updates: SYNTHETIC e2e text.");
  for (const slug of ["global_markets", "ssa", "kenya_macro", "fixed_income", "equities", "real_estate", "digital_payments"]) {
    await draftAndApprove(request, slug, Q3, "quarterly");
  }
  await page.goto(overviewUrl(Q3, "quarterly"));
  await expect(page.getByRole("group", { name: "Sections by state" })).toContainText("Approved8 / 9");

  await openStart(page, "Executive Summary", Q3, "quarterly");
  await page.getByRole("button", { name: `Compose the ${Q3} summary` }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Executive Summary: coordinator review", level: 1 })).toBeVisible();
  await expect(page.getByText(`Quarterly Markets Review, ${Q3}, run`, { exact: false })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Composed from the lead piece of each section. It does not summarize tables, parts not yet drafted, or Cytonn's own outlook." })).toBeVisible();
  // The panel: per included section, what its approved review holds that the summary does not carry.
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Not covered by this summary" }) }).last();
  await expect(panel.getByRole("listitem").filter({ hasText: "Fixed Income" })).toContainText(/run \d+/);
  await expect(panel.getByRole("listitem").filter({ hasText: "Fixed Income" })).toContainText("Tables");
  await expect(panel.getByRole("listitem").filter({ hasText: "Fixed Income" })).toContainText("Parts not yet drafted");
  await expect(panel).toContainText("Further pieces");
  await expect(page.locator("li[data-status]").first()).toBeVisible();
});
