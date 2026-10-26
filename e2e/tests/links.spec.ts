import { expect, test, type Page } from "@playwright/test";
import { VARIANT, openStart, release } from "./helpers";

/**
 * Company Updates text that holds, or may hold, a web link is flagged for the reviewer; nothing is fetched or opened. This
 * file has its own run on a freshly restored test backend (`playwright test links`), each test in its own week.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

async function draftAndOpen(page: Page, period: string, text: string) {
  await openStart(page, "Company Updates", period);
  await page.getByLabel("Your Company Updates text").fill(text);
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
}

test("T40 a link in Company Updates is flagged as plain text, and the section can still be approved", async ({ page }) => {
  await draftAndOpen(page, "Week ending 2026-11-13",
    "Investment Updates:\nRead the rates at https://cytonn.example/cmmf-rates. Prices are on nse.co.ke as usual.");
  const card = page.locator('li[data-status="flagged"]');
  await expect(card).toHaveCount(1);
  await card.getByRole("button", { name: /Show details/ }).click();
  await expect(card).toContainText("Link: https://cytonn.example/cmmf-rates (a web address starting http:// or https://), position 39");
  await expect(card).toContainText("Possible link: nse.co.ke (a domain without http), position 88");
  // Shown as text, never as something to click: no anchor anywhere on the page points at either address.
  await expect(page.locator('a[href*="cytonn.example"], a[href*="nse.co.ke"]')).toHaveCount(0);
  await expect(card.getByRole("link")).toHaveCount(0);
  // The flag asks for a look; it does not block approval.
  await card.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
});

test("T41 Company Updates text with no link carries no link flag", async ({ page }) => {
  await draftAndOpen(page, "Week ending 2026-11-20",
    "Investment Updates:\nThe Cytonn Money Market Fund closed the week at 11.0%, e.g. ahead of KES 1.2bn in flows. Hospitality Updates: Cysuites Ltd. offers.");
  await expect(page.locator('li[data-status="flagged"]')).toHaveCount(0);
  const card = page.locator('li[data-status="not_auto_verified"]');
  await expect(card).toHaveCount(1);
  await card.getByRole("button", { name: /Show details/ }).click();
  await expect(card).not.toContainText(/link|email address/i);
});
