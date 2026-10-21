import { expect, test } from "@playwright/test";
import { VARIANT, openStart } from "./helpers";

/**
 * The start screen's layout: the panel of inputs and steps beside the form, above it when the window is narrow, never
 * folded (it holds the uploads' warnings), and what is inside it laying out by the panel's own width. This file has its
 * own run on a freshly restored test backend (`playwright test startscreen`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

test("T71 the start screen's inputs panel is beside the form and never folds, above it on a narrow window, and its day grid follows its own width", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await openStart(page, "Fixed Income");
  const panel = page.getByRole("complementary", { name: "Inputs and steps" });
  const analyst = page.locator("section", { has: page.getByRole("heading", { name: "Weekly analyst inputs" }) }).first();
  await expect(panel.getByRole("heading", { name: "This week’s inputs" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "What a run does" })).toBeVisible();
  const form = (await analyst.boundingBox())!;
  const side = (await panel.boundingBox())!;
  expect(side.x).toBeGreaterThan(form.x + form.width); // beside the form, on its right
  await expect(panel.getByRole("button", { name: /^(Hide|Show) Inputs and steps$/ })).toHaveCount(0); // no fold: it holds the uploads' warnings

  // The five days of the KCB daily reports: two columns in the panel's width.
  const columns = async () => new Set(await Promise.all(DAYS.map(async (day) => Math.round((await panel.getByText(day, { exact: true }).boundingBox())!.x)))).size;
  expect(await columns()).toBe(2);

  // A tall panel is left in the flow: once the page has scrolled, its top is gone from the window.
  await page.evaluate(() => window.scrollTo(0, 900));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(800);
  expect((await panel.boundingBox())!.y).toBeLessThan(0);
  await page.evaluate(() => window.scrollTo(0, 0));

  // The analyst's grids are wider than their column: each is a region a keyboard can scroll, and says so.
  const grids = analyst.getByRole("region", { name: /rows, scrolls sideways on narrow screens$/ });
  expect(await grids.count()).toBeGreaterThan(0);
  await expect(grids.first()).toHaveAttribute("tabindex", "0");

  // Under 1100px wide the panel comes first, as wide as the content, and the five days sit in a row.
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect.poll(async () => (await panel.boundingBox())!.y < (await analyst.boundingBox())!.y).toBe(true);
  await expect.poll(columns).toBe(5);
});
