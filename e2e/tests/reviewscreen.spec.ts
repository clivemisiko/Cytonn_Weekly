import { expect, test } from "@playwright/test";
import { API, VARIANT, card, overviewUrl, reviewHeading } from "./helpers";

/**
 * The review screen's layout: the review items as a list and a detail pane above the draft, the status bar still under the
 * top bar, and the panes stacked at phone width.
 * This file has its own run on a freshly restored test backend (`playwright test reviewscreen`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

test("T72 the review items are a list and a detail pane above the draft, the status bar sticks, and at 390px the panes stack", async ({ page, request }) => {
  const period = "Week ending 2026-12-18";
  const drafted = await request.post(`${API}/api/sections/digital_payments/draft`, {
    headers: { "Content-Type": "application/json" },
    data: { report_type: "weekly", period },
    timeout: 120_000,
  });
  expect(drafted.status(), await drafted.text()).toBe(200);

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl(period));
  await card(page, "Digital Payments").getByRole("button", { name: "Resume review" }).click();
  await expect(page.getByRole("heading", reviewHeading("Digital Payments"))).toBeVisible();
  const items = page.getByRole("complementary", { name: "Review items" });
  const draft = page.locator("section", { has: page.getByRole("heading", { name: /^Drafted section: / }) }).first();
  await expect(items.getByRole("heading", { name: /Review items/, level: 2 })).toBeVisible();

  // The items are two panes (the list and the selected item) above the draft, which runs at full width.
  const i = (await items.boundingBox())!;
  const d = (await draft.boundingBox())!;
  expect(d.y).toBeGreaterThanOrEqual(i.y + i.height - 2);
  const list = items.locator("ul").first();
  const detail = items.getByRole("region", { name: "Selected review item" });
  expect((await detail.boundingBox())!.x).toBeGreaterThan((await list.boundingBox())!.x + (await list.boundingBox())!.width - 2);

  // The three counts are one row; the table in the draft needs no sideways scroll at this width.
  const tiles = page.getByRole("group", { name: "Review items by status" });
  await expect
    .poll(async () => new Set(await Promise.all([0, 1, 2].map(async (n) => Math.round((await tiles.locator(":scope > *").nth(n).boundingBox())!.y)))).size)
    .toBe(1);
  // The first status with items starts pressed; pressing a pressed tile shows every item.
  const counts = (await (await request.get(`${API}/api/reviews/${new URL(page.url()).searchParams.get("review")}`)).json()).counts;
  const first = (["flagged", "not_auto_verified", "clean"] as const).find((s) => counts[s].total > 0)!;
  const names = { flagged: /Flagged/, not_auto_verified: /Not auto-verified/, clean: /Clean/ } as const;
  await expect(tiles.getByRole("button", { name: names[first] })).toHaveAttribute("aria-pressed", "true");
  await tiles.getByRole("button", { name: names[first] }).click();
  let sum = 0;
  for (const status of ["flagged", "not_auto_verified", "clean"] as const) {
    const tile = tiles.getByRole("button", { name: names[status] });
    await expect(tile).toHaveAttribute("aria-pressed", "false");
    await tile.click();
    await expect(tile).toHaveAttribute("aria-pressed", "true");
    const shown = items.locator("li[data-status]");
    await expect(items.locator(`li[data-status]:not([data-status="${status}"])`)).toHaveCount(0);
    expect(await tile.textContent()).toContain(String(await shown.count()));
    sum += await shown.count();
    await tile.click();
    await expect(tile).toHaveAttribute("aria-pressed", "false");
  }
  await expect(page.getByText("Not auto-verified is not the same as incorrect")).toBeVisible();
  expect(await items.locator("li[data-status]").count()).toBe(sum);
  const table = draft.getByRole("region", { name: /scrolls sideways on narrow screens$/ });
  await expect(table).toBeVisible();
  expect(await table.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

  // Arrow keys move the selection, and Next issue moves to the next item.
  const rows = items.locator("li[data-status] > button");
  await rows.first().click();
  await rows.first().press("ArrowDown");
  await expect(rows.nth(1)).toBeFocused();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await detail.getByRole("button", { name: "Next issue" }).click();
  await expect(rows.nth(2)).toHaveAttribute("aria-current", "true");
  await expect(detail).toBeFocused();

  // No row is clipped or runs past its frame.
  const damaged = () => rows.evaluateAll((all) => all.filter((el) => el.scrollWidth > el.clientWidth).length);
  expect(await damaged()).toBe(0);

  // The status bar spans the page and, once the page has scrolled, is still directly under the top bar.
  const bar = page.locator('[data-attention="review-status-bar"]');
  const b = (await bar.boundingBox())!;
  expect(b.x + b.width).toBeGreaterThanOrEqual(i.x + i.width);
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);
  await expect.poll(async () => Math.round((await bar.boundingBox())!.y)).toBe(44);
  await page.evaluate(() => window.scrollTo(0, 0));

  // At 390px the panes stack, list above detail, with a way back to the list.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => (await detail.boundingBox())!.y >= (await list.boundingBox())!.y + (await list.boundingBox())!.height - 2).toBe(true);
  await detail.getByRole("button", { name: "Back to the list" }).click();
  await expect(rows.nth(2)).toBeFocused();
  await expect(table).toHaveAttribute("tabindex", "0");
});
