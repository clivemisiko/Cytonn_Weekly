import { expect, test } from "@playwright/test";
import { API, VARIANT, card, overviewUrl } from "./helpers";

/**
 * The review screen's layout: the draft in the content column and the review items as the panel beside it, which is never
 * folded, the status bar across both and still under the top bar, and the items following the draft when the window is narrow.
 * This file has its own run on a freshly restored test backend (`playwright test reviewscreen`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

test("T72 the review items are the panel beside the draft and never fold, the status bar spans both and sticks, and below 1100px the items follow the draft", async ({ page, request }) => {
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
  await expect(page.getByRole("heading", { name: "Digital Payments: coordinator review", level: 1 })).toBeVisible();
  const items = page.getByRole("complementary", { name: "Review items" });
  const draft = page.locator("section", { has: page.getByRole("heading", { name: /^Drafted section: / }) }).first();
  await expect(items.getByRole("heading", { name: "Review items", level: 2 })).toBeVisible();
  await expect(items.getByRole("button", { name: /Flagged by the checker \(\d+\)$/ })).toBeVisible();

  // The items are the panel on the right, and it has no fold button: the review items are the work and they hold the flags.
  const d = (await draft.boundingBox())!;
  const i = (await items.boundingBox())!;
  expect(i.x).toBeGreaterThan(d.x + d.width);
  await expect(items.getByRole("button", { name: /^(Hide|Show) Review items$/ })).toHaveCount(0);

  // The three counts are one row in the draft's column; the table in the draft needs no sideways scroll at this width.
  const tiles = page.getByRole("group", { name: "Review items by status" });
  const rows = new Set(await Promise.all([0, 1, 2].map(async (n) => Math.round((await tiles.locator(":scope > div").nth(n).boundingBox())!.y))));
  expect(rows.size).toBe(1);
  const table = draft.getByRole("region", { name: /scrolls sideways on narrow screens$/ });
  await expect(table).toBeVisible();
  expect(await table.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

  // In the panel's width the three options of each item (Unresolved, Accept, Fix needed) stay whole: no word is broken and
  // no option is clipped by the control's frame. Checked at 1366px and again at 1100px, where the panel is at its narrowest.
  const options = items.getByRole("radio");
  expect(await options.count()).toBeGreaterThanOrEqual(6);
  const damaged = async () =>
    (await options.evaluateAll((all) => all.filter((el) => el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight).length)) +
    (await items.getByRole("radiogroup").evaluateAll((all) => all.filter((el) => el.scrollWidth > el.clientWidth).length));
  expect(await damaged()).toBe(0);

  // The status bar spans both columns and, once the page has scrolled, is still directly under the top bar.
  const bar = page.locator("div.sticky", { has: page.getByRole("progressbar", { name: "Items resolved" }) });
  const b = (await bar.boundingBox())!;
  expect(b.x + b.width).toBeGreaterThanOrEqual(i.x + i.width);
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);
  await expect.poll(async () => Math.round((await bar.boundingBox())!.y)).toBe(44);
  await page.evaluate(() => window.scrollTo(0, 0));

  await page.setViewportSize({ width: 1100, height: 768 });
  await expect.poll(async () => Math.round((await items.boundingBox())!.width)).toBe(320);
  expect(await damaged()).toBe(0);

  // Under 1100px wide the items follow the draft, and the table is still a region a keyboard can scroll.
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect.poll(async () => (await items.boundingBox())!.y >= (await draft.boundingBox())!.y + (await draft.boundingBox())!.height - 2).toBe(true);
  await expect(table).toHaveAttribute("tabindex", "0");
  await expect(items.getByRole("button", { name: /Flagged by the checker \(\d+\)$/ })).toBeVisible();
});
