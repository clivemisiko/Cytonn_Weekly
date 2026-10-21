import { expect, test, type Page } from "@playwright/test";
import { VARIANT, startRun } from "./helpers";

/**
 * The run view's layout: the steps and what came of the run in the feed, the run's facts in the panel beside it (below
 * the feed when the window is narrow), and nothing the coordinator has to see in the panel: the status, the failure and
 * the ways back to the overview stay in the feed. This file has its own run on a freshly restored test backend
 * (`playwright test runview`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const facts = (page: Page) => page.getByRole("complementary", { name: "This run" });

test("T73 a finished run: its facts are in the panel beside the steps, the result and the way on are in the feed, and nothing overflows", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const run = await startRun(request, "digital_payments", "Week ending 2026-12-25");
  await page.goto(`/runs/${run}`);
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 60_000 });
  const panel = facts(page);
  const steps = page.getByRole("log", { name: "Steps of this draft" });
  await expect(panel.locator("dt")).toHaveText(["Section", "Report", "Started", "Finished"]);
  await expect(panel.locator("dd").first()).toHaveText("Digital Payments");
  const feed = (await steps.boundingBox())!;
  expect((await panel.boundingBox())!.x).toBeGreaterThan(feed.x + feed.width); // beside the steps, on their right

  // Everything to act on or to read is in the feed, none of it in the panel.
  await expect(page.getByText(/^Finished .* UTC\.$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open review" })).toBeVisible();
  await expect(panel.getByRole("link")).toHaveCount(0);
  await expect(panel.getByRole("button")).toHaveCount(0);
  await expect(panel.getByRole("status")).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveCount(0);

  // The three counts sit in one row in the feed's width, and stack in a phone's. The result block rises into place for a
  // moment (a transform), so their rows are read from the layout (offsetTop), which a transform does not move.
  const tiles = page.getByRole("group", { name: "Review items by status" }).locator("> *");
  const rows = async () => new Set(await Promise.all([0, 1, 2].map((i) => tiles.nth(i).evaluate((el) => (el as HTMLElement).offsetTop)))).size;
  expect(await rows()).toBe(1);

  // Under 1100px the panel follows the steps; at a phone's width nothing is wider than the window.
  await page.setViewportSize({ width: 1024, height: 768 });
  expect((await panel.boundingBox())!.y).toBeGreaterThan((await steps.boundingBox())!.y);
  await page.setViewportSize({ width: 390, height: 800 });
  expect(await rows()).toBe(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("T74 a stopped run: the failure and the way back are in the feed, and the panel says when it stopped", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const run = await startRun(request, "real_estate"); // stops by design in the test API and saves nothing
  await page.goto(`/runs/${run}`);
  const panel = facts(page);
  const alert = page.getByRole("alert").filter({ hasText: "The draft stopped." });
  await expect(alert).toContainText("the Ibuka summary could not be fetched (a deliberate failure for the tests)");
  await expect(panel.locator("dt")).toHaveText(["Section", "Report", "Started", "Stopped"]);
  const side = (await panel.boundingBox())!;
  for (const where of [alert, page.getByRole("link", { name: "Back to overview" }), page.getByText(/^Stopped .* UTC\.$/)]) {
    await expect(where).toBeVisible();
    const box = (await where.boundingBox())!;
    expect(box.x + box.width).toBeLessThan(side.x); // in the feed, left of the panel
  }
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel.getByRole("link")).toHaveCount(0);
});

test("T75 a run the API no longer has: its notice is in the middle of the page, with no panel and no empty column", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/runs/not-a-run");
  const notice = page.getByRole("status").filter({ hasText: "This run is no longer available." });
  await expect(notice).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to the overview" })).toBeVisible();
  await expect(facts(page)).toHaveCount(0);
  // Centred between the rail and the window's edge, as a feed with no panel is (not pushed left by a column nothing fills).
  const rail = (await page.getByRole("navigation", { name: "Report sections" }).boundingBox())!;
  const box = (await notice.boundingBox())!;
  const middle = rail.x + rail.width + (1366 - (rail.x + rail.width)) / 2;
  expect(Math.abs(box.x + box.width / 2 - middle)).toBeLessThan(40);
});
