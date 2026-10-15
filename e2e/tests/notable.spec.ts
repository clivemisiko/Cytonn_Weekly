import { expect, test, type Locator, type Page } from "@playwright/test";
import { API, VARIANT, openStart, overviewUrl } from "./helpers";

/**
 * "Notable this week": suggestions computed by code, shown with their working, accepted, edited or dismissed by the analyst.
 * The test instance is the only one that has any: e2e/notable_demo.py hands it invented items (each says "invented demo item"),
 * and the real server's registry is empty. Each test uses its own Friday, because a decision belongs to its week. This file has
 * its own run on a freshly restored test backend (`playwright test notable`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const json = { "Content-Type": "application/json" };
const period = (week: string) => `Week ending ${week}`;
const panel = (page: Page) => page.getByRole("region", { name: "Notable this week" });
const candidates = (page: Page) => panel(page).getByRole("list", { name: "Suggestions" }).getByRole("listitem");
const selected = (page: Page) => panel(page).getByRole("list", { name: "Selected items" }).getByRole("listitem");
const item = (list: Locator, headline: string | RegExp) => list.filter({ hasText: headline });

// The headlines the real detector library builds from e2e/notable_demo.py's invented series. A headline that carries a date
// (it moves with the week) is matched by its start.
const STREAK = "The Invented 91-day yield has risen for 9 weeks in a row, from 8.10% to 9.05%.";
const RECORD = "The Invented 364-day bill subscription, 152.30%, is the highest in the available history, 25 weeks";
const SINCE = "The Invented 3-month bank placement rate, 9.40%, is the lowest since";
const PACE = "The Invented net domestic borrowing is at";

async function fixedIncome(page: Page, week: string) {
  await openStart(page, "Fixed Income", period(week));
  await expect(panel(page)).toBeVisible();
  await expect(candidates(page).first()).toBeVisible();
}

/** Leave and come back, as after a reload: the start screen is a phase of /overview, so a reload lands on the overview. */
async function reopen(page: Page, title: string, week: string) {
  await page.reload();
  await openStart(page, title, period(week));
  await expect(panel(page)).toBeVisible();
}

test("T47 the panel lists the top five by rank, each saying it is an invented demo item, and show all reveals the rest", async ({ page }) => {
  await fixedIncome(page, "2026-12-11");
  await expect(candidates(page)).toHaveCount(5);
  await expect(candidates(page).first()).toContainText(STREAK);
  await expect(candidates(page).nth(1)).toContainText(RECORD);
  await expect(candidates(page).nth(2)).toContainText(SINCE);
  for (const li of await candidates(page).all()) await expect(li).toContainText("invented demo item");

  await panel(page).getByRole("button", { name: "Show all (7)" }).click();
  await expect(candidates(page)).toHaveCount(7);
  await expect(candidates(page).last()).toContainText(PACE);
  await panel(page).getByRole("button", { name: "Show top 5" }).click();
  await expect(candidates(page)).toHaveCount(5);

  // The working: the rule, the window and the points, only once asked for.
  const first = candidates(page).first();
  await expect(first.getByRole("table")).toHaveCount(0);
  const toggle = first.getByRole("button", { name: "Show working" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(first.getByRole("button", { name: "Hide working" })).toHaveAttribute("aria-expanded", "true");
  await expect(first).toContainText("Consecutive weekly rises ending at the latest point.");
  await expect(first).toContainText("current run");
  await expect(first.getByRole("table").getByRole("row")).toHaveCount(1 + 10); // a header row and ten points: nine rises and where they began
  await first.getByRole("button", { name: "Hide working" }).click();
  await expect(first.getByRole("table")).toHaveCount(0);
});

test("T48 accept: the item moves to the Selected list, survives a reload, and copies as text", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const week = "2026-12-18";
  await fixedIncome(page, week);
  await expect(panel(page)).toContainText("Nothing selected yet.");
  await item(candidates(page), STREAK).getByRole("button", { name: "Accept" }).click();

  await expect(item(candidates(page), STREAK)).toHaveCount(0);
  await expect(selected(page)).toHaveCount(1);
  await expect(selected(page).first()).toContainText(STREAK);
  await expect(candidates(page).first()).toContainText(RECORD);

  await reopen(page, "Fixed Income", week);
  await expect(selected(page)).toHaveCount(1);
  await expect(selected(page).first()).toContainText(STREAK);

  await panel(page).getByRole("button", { name: "Copy as text" }).click();
  await expect(panel(page).getByText("Copied to the clipboard.")).toBeVisible();
  // Windows hands the clipboard's line breaks back as CRLF.
  const copiedText = (await page.evaluate(() => navigator.clipboard.readText())).split("\r\n").join("\n");
  expect(copiedText).toBe(`Selected for this week: Fixed Income, week ending ${week}\n\n1. ${STREAK}\n   Source: invented demo item`);

  // Taking it off the list puts it back among the suggestions.
  await selected(page).first().getByRole("button", { name: "Remove from list" }).click();
  await expect(selected(page)).toHaveCount(0);
  await expect(candidates(page).first()).toContainText(STREAK);
});

test("T49 edit: the new wording is saved and selected, and the original is kept and shown", async ({ page }) => {
  await fixedIncome(page, "2026-12-25");
  const row = item(candidates(page), RECORD);
  await row.getByRole("button", { name: "Edit" }).click();
  const original = ((await row.getByText(RECORD).textContent()) ?? "").trim(); // the whole headline, whose date moves with the week
  const box = row.getByLabel("Reworded headline");
  await expect(box).toHaveValue(original);

  await box.fill("   ");
  await expect(row.getByText("The headline cannot be empty.")).toBeVisible();
  await expect(row.getByRole("button", { name: "Save edit" })).toBeDisabled();
  await box.fill("364-day bill subscription: a 2026 high.");
  await row.getByRole("button", { name: "Save edit" }).click();

  await expect(item(candidates(page), RECORD)).toHaveCount(0);
  const saved = selected(page).first();
  await expect(saved).toContainText("364-day bill subscription: a 2026 high.");
  await expect(saved).toContainText(`Original: ${original}`);

  await reopen(page, "Fixed Income", "2026-12-25");
  await expect(selected(page).first()).toContainText("364-day bill subscription: a 2026 high.");
  await expect(selected(page).first()).toContainText(`Original: ${original}`);

  // Cancel leaves it as it was.
  await selected(page).first().getByRole("button", { name: "Edit" }).click();
  await selected(page).first().getByLabel("Reworded headline").fill("Something else entirely.");
  await selected(page).first().getByRole("button", { name: "Cancel" }).click();
  await expect(selected(page).first()).toContainText("364-day bill subscription: a 2026 high.");
});

test("T50 dismiss: hidden with its reason, still hidden after a reload, and can be restored", async ({ page }) => {
  await fixedIncome(page, "2027-01-01");
  const row = item(candidates(page), SINCE);
  await row.getByRole("button", { name: "Dismiss" }).click();
  await row.getByLabel("Reason (optional)").selectOption({ label: "Already covered" });
  await row.getByRole("button", { name: "Confirm dismissal" }).click();

  await expect(item(candidates(page), SINCE)).toHaveCount(0);
  await expect(candidates(page)).toHaveCount(5); // the sixth moved up
  await reopen(page, "Fixed Income", "2027-01-01");
  await expect(item(candidates(page), SINCE)).toHaveCount(0);

  const dismissed = panel(page).getByRole("button", { name: "Dismissed (1)" });
  await expect(dismissed).toHaveAttribute("aria-expanded", "false");
  await dismissed.click();
  const gone = panel(page).getByRole("list", { name: "Dismissed items" }).getByRole("listitem");
  await expect(gone).toHaveCount(1);
  await expect(gone.first()).toContainText(SINCE);
  await expect(gone.first()).toContainText("Reason: Already covered");

  await gone.first().getByRole("button", { name: "Restore" }).click();
  await expect(panel(page).getByRole("button", { name: /^Dismissed/ })).toHaveCount(0);
  await expect(item(candidates(page), SINCE)).toHaveCount(1);
  await reopen(page, "Fixed Income", "2027-01-01");
  await expect(item(candidates(page), SINCE)).toHaveCount(1);
  await expect(candidates(page).nth(2)).toContainText(SINCE); // back in its place by rank
});

test("T51 a section with nothing computed shows the quiet empty state and no actions", async ({ page }) => {
  await openStart(page, "Digital Payments", period("2027-01-08"));
  await expect(panel(page)).toContainText("Nothing notable has been computed for this section yet.");
  await expect(panel(page).getByRole("button")).toHaveCount(0);
  await expect(panel(page).getByRole("list", { name: "Suggestions" })).toHaveCount(0);
});

test("T52 a detector that fails is one quiet line, never a stack trace, and the others still show", async ({ page }) => {
  await openStart(page, "Equities", period("2027-01-15"));
  await expect(panel(page).getByRole("status").filter({ hasText: "One check could not run." })).toBeVisible();
  await expect(candidates(page)).toHaveCount(2);
  await expect(panel(page)).not.toContainText(/traceback|error:|RuntimeError|\.py/i);
  const res = await page.request.get(`${API}/api/notable/equities?week_ending=2027-01-15`);
  expect((await res.json()).failed_checks).toBe(1);
});

test("T53 the panel is on the review screen too, and accepting, editing and dismissing leave the review, the overview and the export exactly as they were", async ({ page, request }) => {
  const week = "2027-01-22";
  const drafted = await request.post(`${API}/api/sections/company_updates/draft`, {
    headers: json, data: { report_type: "weekly", period: period(week), text: "Investment Updates:\nSYNTHETIC e2e text for the notable test." },
  });
  expect(drafted.status(), await drafted.text()).toBe(200);
  const runId: number = (await drafted.json()).run_id;

  const state = async () => ({
    review: await (await request.get(`${API}/api/reviews/${runId}`)).json(),
    overview: await (await request.get(`${API}/api/sections?report_type=weekly&period=${encodeURIComponent(period(week))}`)).json(),
    exportStatus: await (await request.get(`${API}/api/export/weekly?period=${encodeURIComponent(period(week))}`)).json(),
    refused: await (await request.post(`${API}/api/export/weekly?period=${encodeURIComponent(period(week))}`)).text(),
  });
  const before = await state();

  await page.goto(`${overviewUrl(period(week))}&review=${runId}`);
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await expect(panel(page)).toBeVisible();
  await expect(candidates(page)).toHaveCount(2);

  const first = candidates(page).first();
  await first.getByRole("button", { name: "Accept" }).click();
  await expect(selected(page)).toHaveCount(1);
  await candidates(page).first().getByRole("button", { name: "Edit" }).click();
  await candidates(page).first().getByLabel("Reworded headline").fill("Reworded on the review screen.");
  await candidates(page).first().getByRole("button", { name: "Save edit" }).click();
  await expect(selected(page)).toHaveCount(2);
  await selected(page).last().getByRole("button", { name: "Remove from list" }).click();
  await candidates(page).first().getByRole("button", { name: "Dismiss" }).click();
  await candidates(page).first().getByRole("button", { name: "Confirm dismissal" }).click();
  await expect(panel(page).getByRole("button", { name: "Dismissed (1)" })).toBeVisible();

  // What the coordinator sees is unchanged: the same count line, the same items, nothing resolved by it.
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Accept" })).not.toBeChecked();
  const after = await state();
  expect(after.review).toEqual(before.review);
  expect(after.overview).toEqual(before.overview);
  expect(after.exportStatus).toEqual(before.exportStatus);
  expect(after.refused).toEqual(before.refused);
  expect(after.exportStatus.ready).toBe(false); // the instance cannot export; the backend test writes the real .docx and compares it
});

test("T54 when the suggestions cannot be reached the panel says so briefly and the rest of the screen works", async ({ page }) => {
  await page.route("**/api/notable/**", (route) => route.abort());
  await openStart(page, "Fixed Income", period("2027-01-29"));
  await expect(panel(page).getByRole("alert")).toContainText("could not be loaded");
  await expect(panel(page).getByRole("alert")).not.toContainText(/traceback/i);
  await expect(panel(page).getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What a run does" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Draft the Week ending 2027-01-29 section$/ })).toBeVisible();

  // And back, once the API answers.
  await page.unroute("**/api/notable/**");
  await panel(page).getByRole("button", { name: "Try again" }).click();
  await expect(candidates(page).first()).toBeVisible();
});

test("T55 on a phone-width screen nothing overflows, and the actions work from the keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixedIncome(page, "2027-02-05");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  const accept = candidates(page).first().getByRole("button", { name: "Accept" });
  await accept.focus();
  await expect(accept).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(selected(page)).toHaveCount(1);

  const toggle = selected(page).first().getByRole("button", { name: "Show working" });
  await toggle.focus();
  await page.keyboard.press("Space");
  await expect(selected(page).first().getByRole("table")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});

test("T56 Show working on a card the real detector library built: the rule, the window and the points table are shown", async ({ page }) => {
  await fixedIncome(page, "2027-02-12");
  await panel(page).getByRole("button", { name: "Show all (7)" }).click(); // this card ranks sixth of seven
  const card = item(candidates(page), "Invented interbank volume");
  await expect(card).toContainText(
    "is 24.7% above the average of the previous 12 weeks, Kshs 14.8 bn. That is 6.8 standard deviations above the average.",
  );
  await expect(card.getByRole("table")).toHaveCount(0); // nothing of the working until it is asked for
  await card.getByRole("button", { name: "Show working" }).click();

  // The rule, in the library's words, with the parameters the check was made with.
  await expect(card).toContainText("Latest value against the mean of the previous 12 weekly points (the latest point is not in the mean), measured as a percentage difference.");
  await expect(card).toContainText("Shown when the difference is at least 18.7 (percent).");
  // The series and the window, as the id knows them: no date and no value in either.
  await expect(card.getByText("Invented interbank volume", { exact: true })).toBeVisible();
  await expect(card.getByText("previous 12 weeks", { exact: true })).toBeVisible();
  // The points: the twelve before and the latest, each with its date and its value.
  const rows = card.getByRole("table").getByRole("row");
  await expect(rows).toHaveCount(1 + 13);
  await expect(rows.nth(1)).toContainText("20 Nov 2026");
  await expect(rows.nth(1)).toContainText("Kshs 14.2 bn");
  await expect(rows.last()).toContainText("12 Feb 2027");
  await expect(rows.last()).toContainText("Kshs 18.4 bn");
});

test("T57 Show working draws the points as a line: a dot for each, the scale and the latest value labelled, and no doubled colon in the figures", async ({ page }) => {
  await fixedIncome(page, "2027-02-19");
  const first = candidates(page).first();
  // A figure's label may hold a colon of its own ("<series>: latest"); the value is joined to it with " = ".
  await expect(first).toContainText("Invented 91-day yield: latest = 9.05%");
  await expect(first).not.toContainText("latest: 9.05%");

  await first.getByRole("button", { name: "Show working" }).click();
  const chart = first.getByRole("img", { name: /^Invented 91-day yield: 10 points from 18 Dec 2026, 8\.10%, to 19 Feb 2027, 9\.05%$/ });
  await expect(chart).toBeVisible();
  await expect(chart.locator("circle")).toHaveCount(10); // one dot for each point of the table below it
  await expect(chart.locator("polyline")).toHaveCount(1);
  await expect(chart.locator("text").filter({ hasText: /^8\.10%$/ })).toHaveCount(1); // the foot of the scale
  await expect(chart.locator("text").filter({ hasText: /^9\.05%$/ })).toHaveCount(2); // the head of the scale, and the latest point's own label
  await expect(chart.locator("text").filter({ hasText: /^18 Dec 2026$/ })).toHaveCount(1);
  await expect(chart.locator("text").filter({ hasText: /^19 Feb 2027$/ })).toHaveCount(1);
  await expect(first.getByRole("table").getByRole("row")).toHaveCount(1 + 10);

  // On a phone the page does not scroll sideways because of it.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(chart).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});


test("T58 at 390px the working chart fits its box: no sideways scroll, and the latest point and its label lie inside the chart, even for a long value", async ({ page }) => {
  // The first card's points are swapped for four with long display strings (the API's answer is edited in the browser only).
  const longPoints = [
    { date: "2027-01-29", value: 450, display: "Kshs 450.0 bn" },
    { date: "2027-02-05", value: 612.5, display: "Kshs 612.5 bn" },
    { date: "2027-02-12", value: 1100.2, display: "Kshs 1,100.2 bn" },
    { date: "2027-02-19", value: 1234.5, display: "Kshs 1,234.5 bn" },
  ];
  await page.route("**/api/notable/fixed_income**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.suggestions[0].working.points = longPoints;
    await route.fulfill({ response, json: body });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await fixedIncome(page, "2027-02-19");
  const first = candidates(page).first();
  await first.getByRole("button", { name: "Show working" }).click();
  const chart = first.getByRole("img", { name: /Kshs 1,234\.5 bn$/ });
  await expect(chart).toBeVisible();

  const fits = async () => {
    const box = await chart.evaluate((svg) => {
      const parent = svg.parentElement!;
      return { scroll: parent.scrollWidth, client: parent.clientWidth, drawn: svg.getBoundingClientRect().width };
    });
    expect(box.scroll).toBeLessThanOrEqual(box.client); // nothing to scroll inside the chart
    expect(box.drawn).toBeLessThanOrEqual(box.client + 0.5); // and the drawing is no wider than its box
    const outer = (await chart.boundingBox())!;
    for (const part of ["latest-label", "latest-dot"]) {
      const inner = (await chart.locator(`[data-part="${part}"]`).boundingBox())!;
      expect(inner.x, part).toBeGreaterThanOrEqual(outer.x - 0.5);
      expect(inner.x + inner.width, part).toBeLessThanOrEqual(outer.x + outer.width + 0.5);
      expect(inner.y, part).toBeGreaterThanOrEqual(outer.y - 0.5);
      expect(inner.y + inner.height, part).toBeLessThanOrEqual(outer.y + outer.height + 0.5);
    }
  };
  await expect(chart.locator('[data-part="latest-label"]')).toHaveText("Kshs 1,234.5 bn");
  await fits();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.setViewportSize({ width: 1280, height: 800 }); // and the same chart on a desktop screen
  await expect.poll(async () => (await chart.boundingBox())!.width).toBeGreaterThan(450);
  await fits();
});
