import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

// The bank results slot, on with E2E_RESULTS_SEASON=1 only (run this file in its own command). The two PDFs are public:
// the banks' own published statements, saved as backend fixtures.
const FIXTURES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../backend/tests/fixtures/sources");
const url = `/chat?section=equities&period=${encodeURIComponent("Week ending 2027-05-07")}`;

test.skip(process.env.E2E_RESULTS_SEASON !== "1", "the results season switch is off");

test("T200 Equities: two banks' statements upload at once and show bank, period and status; Create draft is not blocked", async ({ page }) => {
  await page.goto(url);
  const block = page.locator('[data-slot="bank_results"]');
  await expect(block.getByText("Bank results (quarterly financial statements)")).toBeVisible();
  await block.getByLabel("Upload Bank results (quarterly financial statements)").setInputFiles([
    path.join(FIXTURES, "results_kcb_2026-09-30.pdf"),
    path.join(FIXTURES, "results_equity_2026-09-30.pdf"),
  ]);
  const rows = block.locator("[data-bank-row]");
  await expect(rows).toHaveCount(2, { timeout: 60_000 });
  for (const bank of ["KCB Group", "Equity Group Holdings"]) {
    const row = rows.filter({ hasText: bank });
    await expect(row.getByText(/^Period ended 30 Sep/)).toBeVisible();
    await expect(row.getByText("Read OK")).toBeVisible();
    await expect(row.getByRole("button", { name: `Remove ${bank}` })).toBeVisible();
  }
  await expect(page.locator("[data-banner]")).not.toContainText("Bank results");
  const create = page.getByRole("button", { name: /Create draft/ });
  await expect(create).not.toHaveAttribute("aria-disabled", "true");
  await page.getByRole("button", { name: /View checklist/ }).click();
  await expect(page.locator("#prepare-checklist")).toContainText("Bank results (quarterly financial statements): 2 files uploaded");
});
