import { expect, test, type Page } from "@playwright/test";
import { PERIOD, VARIANT, card, overviewUrl } from "./helpers";

/**
 * What the overview did, now on the section chooser: the report's figures, its tally, the section cards and the export
 * with its notices in the chooser's aside, and the export's notices on a section's own page too.
 * Two tests change the API's answer for /api/sections on the way to the page (as T14 does for the export) so that a state
 * the demo week does not have, a flagged review and an unavailable section, can be looked at; what is under test is what the
 * page does with it. This file has its own run on a freshly restored test backend (`playwright test overview`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
// The chooser re-reads the sections while a draft runs; a read still in flight when a test ends is not part of it.
test.afterEach(({ page }) => page.unrouteAll({ behavior: "ignoreErrors" }));

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

const aside = (page: Page) => page.getByRole("complementary", { name: "This conversation" });

test("T66 the chooser's aside holds the report's figures, its tally and the export, beside the sections and below them on a narrow window", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl());
  const panel = aside(page);
  const figures = panel.getByRole("group", { name: "This report in figures" });
  await expect(figures).toContainText("Approved0 / 5");
  for (const label of ["In review", "Flagged", "Drafting"]) await expect(figures.getByText(label, { exact: true })).toBeVisible();
  await expect(panel.getByRole("group", { name: "Sections by state" })).toContainText("Not drafted5 / 5");
  await expect(panel.getByRole("button", { name: "Export weekly report" })).toBeVisible();
  const chooser = (await page.getByRole("heading", { name: "Choose a section" }).boundingBox())!;
  expect((await panel.boundingBox())!.x).toBeGreaterThan(chooser.x + chooser.width); // beside the chooser, on its right

  // Under 1100px wide the aside follows the chooser.
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(panel.getByRole("group", { name: "This report in figures" })).toBeVisible();
  expect((await panel.boundingBox())!.y).toBeGreaterThan((await page.getByRole("heading", { name: "Choose a section" }).boundingBox())!.y);
});

test("T67 a card shows what the payload says, the figures count its flagged items, and it needs the analyst's attention", async ({ page }) => {
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
  await expect(fi.getByText("10 review items")).toBeVisible();
  await expect(fi.getByText("3 flagged")).toBeVisible();
  await expect(fi.getByRole("button", { name: "Resume review" })).toBeVisible();
  await expect(fi.getByRole("button", { name: "Draft again" })).toBeVisible();
  await expect(card(page, "Equities").getByRole("button")).toHaveText(["Draft section"]);
  await expect(aside(page).getByRole("group", { name: "This report in figures" })).toContainText("Flagged3");

  // The attention list puts the flagged review first and opens that section here, on the chooser.
  const attention = aside(page).getByRole("region", { name: "Needs your attention" }).getByRole("button");
  await expect(attention.first()).toContainText("Fixed Income3 items flagged");
  await attention.first().click();
  await expect(page).toHaveURL(/\/chat\?period=.*&section=fixed_income/);

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
  await expect(page.getByRole("group", { name: "Sections by state" })).toContainText("Not available yet1 / 5");

  await expect(re.getByText("SYNTHETIC built part one")).toBeHidden();
  await re.locator("summary").click();
  await expect(re.getByText("Already built")).toBeVisible();
  await expect(re.getByText("SYNTHETIC built part one")).toBeVisible();
});

test("T70 the export's notices are shown once beside the export, on the chooser and on a section's own page", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  // No section in this test API is a dev draft and every chart has an image, so the export status read is changed.
  await page.route(/\/api\/export\/weekly/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    Object.assign(body, { charts_missing: 3, is_dev_draft: true, dev_mode_label: "DEV MODE DRAFT (stub): NOT FOR PUBLICATION OR CIRCULATION.", dev_sections: ["Fixed Income", "Equities"] });
    await route.fulfill({ response, json: body });
  });
  await page.goto(overviewUrl());
  const notice = page.getByRole("alert").filter({ hasText: "Export Notice: This document contains test content" });
  const charts = page.getByText("3 charts have no image. The Word file will contain placeholders for them.");
  await expect(notice).toHaveCount(1); // once only
  await expect(notice).toHaveText("Export Notice: This document contains test content (Fixed Income, Equities) and includes a developer watermark on every page. It cannot be circulated or published externally.");
  await expect(charts).toHaveCount(1);
  await expect(aside(page).getByRole("button", { name: "Export weekly report" })).toBeVisible();

  // A section's prepare page has the export too, and the same notices with it.
  await page.getByRole("button", { name: "Fixed Income", exact: true }).click();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeVisible();
  await expect(notice).toHaveCount(1);
  await expect(charts).toHaveCount(1);
});
