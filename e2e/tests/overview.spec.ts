import { expect, test, type Page } from "@playwright/test";
import { VARIANT, card, overviewUrl } from "./helpers";

/**
 * The overview's layout: the report-status panel and its fold, and what a section card shows of the overview's payload.
 * Two tests change the API's answer for /api/sections on the way to the page (as T14 does for the export) so that a state
 * the demo week does not have, a flagged review and an unavailable section, can be looked at; what is under test is what the
 * page does with it. This file has its own run on a freshly restored test backend (`playwright test overview`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

type Section = { slug: string; [key: string]: unknown };
type Overview = { sections: Section[] };

/** Serve the real overview with one change made to it. */
async function changeOverview(page: Page, change: (body: Overview) => void) {
  await page.route(/\/api\/sections(\?|$)/, async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Overview;
    change(body);
    await route.fulfill({ response, json: body });
  });
}

const sectionOf = (body: Overview, slug: string) => body.sections.find((s) => s.slug === slug)!;

test("T66 the report-status panel folds, stays folded after a reload, and is below the feed on a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl());
  const panel = page.getByRole("complementary", { name: "Report status" });
  const tally = page.getByRole("group", { name: "Sections by state" });
  await expect(tally).toBeVisible();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeVisible();
  const feed = (await card(page, "Company Updates").boundingBox())!;
  expect((await panel.boundingBox())!.x).toBeGreaterThan(feed.x + feed.width); // beside the feed, on its right

  await panel.getByRole("button", { name: "Hide Report status" }).click();
  await expect(tally).toBeHidden();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeHidden();
  expect((await panel.boundingBox())!.width).toBeLessThan(80); // a strip
  await page.reload();
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Show Report status" })).toBeVisible(); // remembered in this browser
  await expect(tally).toBeHidden();

  await panel.getByRole("button", { name: "Show Report status" }).click();
  await expect(tally).toBeVisible();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeVisible();

  // Under 1100px wide the panel is not beside anything: it follows the feed, open, with no fold button.
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(panel.getByRole("button", { name: /Report status$/ })).toBeHidden();
  await expect(tally).toBeVisible();
  const narrowFeed = (await card(page, "Company Updates").boundingBox())!;
  expect((await panel.boundingBox())!.y).toBeGreaterThan(narrowFeed.y);
});

test("T67 a card shows what the payload says, and folding the group keeps the flagged total in view", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const counts = (total: number) => ({ total, unresolved: total, fix_needed: 0 });
  await changeOverview(page, (body) => {
    sectionOf(body, "fixed_income").latest = {
      run_id: 99,
      run_date: "2026-10-09",
      this_week: true,
      current: true,
      decision: null,
      decided_at: null,
      progress: { total: 10, resolved: 4, unresolved: 6, fix_needed: 0 },
      counts: { flagged: counts(3), not_auto_verified: counts(2), clean: counts(5) },
      is_dev_draft: true,
      week_start: "2026-10-05",
      week_end: "2026-10-09",
      topic: null,
    };
  });
  await page.goto(overviewUrl());
  const fi = card(page, "Fixed Income");
  await expect(fi.getByText("In review", { exact: true })).toBeVisible();
  await expect(fi.getByText("DEV DRAFT")).toBeVisible(); // the dev mark is on the card
  await expect(fi).toContainText("Run 99");
  await expect(fi.getByText("4 of 10 items resolved")).toBeVisible();
  await expect(fi.getByRole("progressbar", { name: "Fixed Income: items resolved" })).toHaveAttribute("aria-valuenow", "4");
  await expect(fi.getByText("3 flagged")).toBeVisible();
  await expect(fi.getByRole("button", { name: "Resume review" })).toBeVisible();
  await expect(fi.getByRole("button", { name: "Draft again" })).toBeVisible();
  await expect(card(page, "Company Updates").getByRole("button")).toHaveText(["Add your text"]);

  // The group's heading says how many are approved and how many items are flagged; folding it hides the cards, not that.
  const group = page.getByRole("button", { name: "Week ending 9 Oct 2026 · 0 of 6 approved" });
  await expect(page.getByText("3 flagged").filter({ visible: true })).toHaveCount(2); // the heading's and the card's
  await group.click();
  await expect(fi).toBeHidden();
  await expect(page.getByText("3 flagged").filter({ visible: true })).toHaveCount(1);
  await group.click();
  await expect(fi).toBeVisible();
});

test("T68 an unavailable section's reason and what unblocks it are always in full; the rest is behind Show more", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await changeOverview(page, (body) => {
    Object.assign(sectionOf(body, "real_estate"), {
      available: false,
      latest: null,
      reason: "SYNTHETIC reason: nothing here can be drafted yet, whatever the length of this sentence is.",
      unblock: "SYNTHETIC unblock: someone supplies the sample.",
      built_parts: ["SYNTHETIC built part one"],
    });
  });
  await page.goto(overviewUrl());
  const re = card(page, "Real Estate");
  await expect(re.getByText("Not available yet", { exact: true })).toBeVisible();
  await expect(re.getByText("SYNTHETIC reason: nothing here can be drafted yet, whatever the length of this sentence is.")).toBeVisible();
  await expect(re.getByText("Unblocked by:")).toBeVisible();
  await expect(re.getByText("SYNTHETIC unblock: someone supplies the sample.")).toBeVisible();
  await expect(re.getByRole("button")).toHaveCount(0); // nothing can be done to it
  await expect(page.getByRole("group", { name: "Sections by state" })).toContainText("Not available yet1 / 6");

  await expect(re.getByText("SYNTHETIC built part one")).toBeHidden();
  await re.locator("summary").click();
  await expect(re.getByText("Already built")).toBeVisible();
  await expect(re.getByText("SYNTHETIC built part one")).toBeVisible();
  await expect(re.getByText("SYNTHETIC reason: nothing here can be drafted yet, whatever the length of this sentence is.")).toBeVisible();
});

test("T70 the export's dev-mode notice is in the feed right under the dev-mode notice, shown once, and stays when the panel is folded", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  // No section in this test API is a dev draft, so the export status the page reads is changed to say one is.
  await page.route(/\/api\/export\/weekly/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    Object.assign(body, { is_dev_draft: true, dev_mode_label: "DEV MODE DRAFT (stub): NOT FOR PUBLICATION OR CIRCULATION.", dev_sections: ["Fixed Income", "Equities"] });
    await route.fulfill({ response, json: body });
  });
  await page.goto(overviewUrl());
  const panel = page.getByRole("complementary", { name: "Report status" });
  const notice = page.getByRole("alert").filter({ hasText: "The export carries a DEV MODE watermark" });
  await expect(notice).toHaveCount(1); // once only
  await expect(notice).toHaveText("DEV MODE DRAFT (stub): NOT FOR PUBLICATION OR CIRCULATION. The export carries a DEV MODE watermark on every page and must not be sent or published (Fixed Income, Equities).");
  await expect(panel.getByText("The export carries a DEV MODE watermark")).toHaveCount(0); // not in the panel
  await expect(panel.getByRole("button", { name: "Export weekly report" })).toBeVisible(); // the button is

  const dev = page.getByRole("alert").filter({ hasText: "CYTONN_LLM_PROVIDER=local: DEV MODE." });
  const above = (await dev.boundingBox())!;
  const below = (await notice.boundingBox())!;
  expect(below.y).toBeGreaterThan(above.y + above.height - 1); // after it
  expect(below.y - (above.y + above.height)).toBeLessThan(40); // and right under it, in the same column

  await panel.getByRole("button", { name: "Hide Report status" }).click();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeHidden(); // folded away with the panel
  await expect(notice).toBeVisible(); // the warning is not
  await expect(notice).toHaveCount(1);
  await page.reload();
  await expect(panel.getByRole("button", { name: "Show Report status" })).toBeVisible(); // still folded after a reload
  await expect(notice).toBeVisible();
});
