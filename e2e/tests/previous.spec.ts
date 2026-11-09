import { expect, test } from "@playwright/test";
import { VARIANT } from "./helpers";

// The test instance cannot reach five approved sections, so the list is empty there; the one listed row below is the
// API's answer changed on its way to the page, as T14 does for the export.
test.skip(!!VARIANT, "runs on the default test backend");

test("T106 Previous reports is a rail item with its own page, empty until a week is fully approved", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/overview");
  const rail = page.getByRole("navigation", { name: "Report sections" });
  await expect(page.getByText("All five sections of this week are approved.")).toHaveCount(0);
  await rail.getByRole("button", { name: "Previous reports" }).click();
  await expect(page).toHaveURL(/\/previous$/);
  await expect(page.getByRole("heading", { name: "Previous reports", level: 1 })).toBeVisible();
  await expect(rail.getByRole("button", { name: "Previous reports" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("No approved weeks yet.")).toBeVisible();

  await page.route("**/api/previous/weekly", (route) =>
    route.fulfill({
      json: {
        next_week_ending: "2026-10-16",
        default_week_ending: "2026-10-09",
        choices: [],
        weeks: [{ period: "Week ending 2026-10-09", week_ending: "2026-10-09", approved_at: "2026-10-12T07:30:00+00:00", is_dev_draft: true, can_export: true, sections: [] }],
      },
    }),
  );
  await page.reload();
  const row = page.getByRole("list", { name: "Approved weeks" }).getByRole("listitem");
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("heading", { name: "Week ending 9 Oct 2026" })).toBeVisible();
  await expect(row.getByText("All five approved")).toBeVisible();
  await expect(row.getByText("Dev draft: watermarked, not for circulation")).toBeVisible();
  await expect(row.getByRole("button", { name: "Read Week ending 9 Oct 2026" })).toBeVisible();
  await expect(row.getByRole("button", { name: "Download Word for Week ending 9 Oct 2026" })).toBeEnabled();
});
