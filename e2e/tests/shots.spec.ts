import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

/**
 * Screenshots of every page and state, for comparing the two apps by eye: light and dark, desktop and 390 px.
 * Not part of the suite: it runs only with E2E_SHOTS=1 (`npm run shots`), and writes to screenshots/parity/<target>/
 * at the repository root. It drafts and approves on the test backend as the suite does. It also writes tokens.json,
 * every colour token as the browser resolves it in each theme, which e2e/compare_shots.py reads.
 */
const TARGET = process.env.E2E_TARGET ?? "vue";
const OUT = join(import.meta.dirname, "..", "..", "screenshots", "parity", TARGET);
const WEEK = "2026-10-09";
const PERIOD = `Week ending ${WEEK}`;
const OVERVIEW = `/overview?report=weekly&period=${encodeURIComponent(PERIOD)}`;
const SIZES = { desktop: { width: 1280, height: 800 }, phone: { width: 390, height: 844 } } as const;
const TOKENS = [
  "background", "foreground", "card", "card-foreground", "popover", "popover-foreground", "primary", "primary-hover",
  "primary-foreground", "secondary", "secondary-foreground", "muted", "muted-foreground", "accent", "accent-foreground",
  "destructive", "border", "input", "ring", "link", "band", "band-foreground", "band-muted", "band-rule", "flag",
  "flag-fg", "flag-on", "warn", "warn-fg", "ok", "ok-fg", "ok-on", "dev-a", "dev-b", "dev-ink", "dev-rule",
];

test.skip(!process.env.E2E_SHOTS, "screenshots are taken with `npm run shots`");
test.describe.configure({ mode: "serial" });

/** The page as it is now, in both themes at both widths. The theme follows the (emulated) device: System. */
async function shoot(page: Page, name: string, fullPage = true) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    await page.setViewportSize(viewport);
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.waitForTimeout(250);
      await page.screenshot({ path: join(OUT, `${name}-${scheme}-${size}.png`), fullPage });
    }
  }
  await page.setViewportSize(SIZES.desktop);
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
}

const card = (page: Page, title: string) => page.locator("li", { has: page.getByRole("heading", { name: title, exact: true }) });

async function openStart(page: Page, title: string) {
  await page.goto(OVERVIEW);
  await card(page, title).getByRole("button", { name: /Draft section|Add your text/ }).click();
  await expect(page.getByRole("heading", { name: `${title}: coordinator review`, level: 1 })).toBeVisible();
}

test("screenshots of every page and state", async ({ page }) => {
  test.setTimeout(20 * 60_000);
  mkdirSync(OUT, { recursive: true });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /^Good .*Welcome to Cytonn Weekly\.$/ })).toBeVisible();
  await shoot(page, "01-landing");

  // Every colour token, as resolved in each theme.
  const tokens: Record<string, Record<string, string>> = {};
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    tokens[scheme] = await page.evaluate((names) => {
      const out: Record<string, string> = {};
      for (const name of names) {
        // A fresh element each time: a reused one would answer with the colour it is still moving from.
        const probe = document.createElement("div");
        probe.style.cssText = `transition: none; color: var(--${name})`;
        document.body.appendChild(probe);
        out[name] = getComputedStyle(probe).color;
        probe.remove();
      }
      return out;
    }, TOKENS);
  }
  writeFileSync(join(OUT, "tokens.json"), JSON.stringify(tokens, null, 1));
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });

  // Focus rings: the top bar's Home, then the landing page's own link.
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await shoot(page, "02-focus-home", false);
  await page.getByRole("link", { name: "Continue without signing in" }).focus();
  await shoot(page, "03-focus-button", false);

  await page.goto(OVERVIEW);
  await expect(page.getByRole("heading", { name: "Export weekly report" })).toBeVisible();
  await shoot(page, "04-overview-weekly");
  await page.getByLabel("Issue (optional)").focus();
  await shoot(page, "05-focus-field", false);

  await page.goto("/overview?report=quarterly&period=Q2'2026");
  await page.getByLabel("Report type").selectOption("quarterly");
  await page.getByLabel("Period", { exact: true }).fill("Q2'2026");
  await page.getByRole("button", { name: "Show sections" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "half-year review" })).toBeVisible();
  await shoot(page, "06-picker-refusal", false);
  await page.getByLabel("Period", { exact: true }).fill("Q3'2026");
  await page.getByRole("button", { name: "Show sections" }).click();
  await expect(page.getByText("Quarterly Markets Review, Q3'2026: 9 report sections.", { exact: false })).toBeVisible();
  await shoot(page, "07-overview-quarterly");

  await openStart(page, "Fixed Income");
  await expect(page.locator("#analyst-placements")).toBeVisible();
  await expect(page.getByText("5 of 5 received")).toBeVisible();
  await shoot(page, "08-start-fixed-income");
  await page.locator("#analyst-placements").fill("0.09");
  await page.locator("#analyst-placements").press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "3-month bank placements" })).toBeVisible();
  await page.locator("#analyst-placements").scrollIntoViewIfNeeded();
  await shoot(page, "09-analyst-refusal", false);

  await openStart(page, "Company Updates");
  await shoot(page, "10-start-company-updates");
  await page.getByLabel("Your Company Updates text").fill("Investment Updates:\nSYNTHETIC e2e text, not real.");
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open review" })).toBeVisible();
  await shoot(page, "11-run-finished");
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await shoot(page, "12-review-open");
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Approvable: every item is resolved and none needs a fix.")).toBeVisible();
  await page.getByRole("radio", { name: "Accept", exact: true }).focus();
  await shoot(page, "13-review-approvable-focus-radio", false);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Approve this section?" })).toBeVisible();
  await shoot(page, "14-confirm-dialog", false);
  await page.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Approved and locked")).toBeVisible();
  await shoot(page, "15-review-approved-locked");

  await openStart(page, "Real Estate");
  await page.getByRole("button", { name: `Draft the ${PERIOD} section` }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The draft stopped." })).toBeVisible();
  await shoot(page, "16-run-stopped");

  await page.goto("/runs/not-a-run");
  await expect(page.getByText("This run is no longer available.", { exact: false })).toBeVisible();
  await shoot(page, "17-run-gone");

  await openStart(page, "Fixed Income");
  await page.getByRole("button", { name: `Draft the ${PERIOD} section` }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 8 * 60_000 });
  await expect(page.getByRole("link", { name: "Open review" })).toBeVisible();
  await shoot(page, "18-run-finished-fixed-income");
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Review items", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: /Clean \(\d+\)$/ }).click();
  await expect(page.locator('li[data-status="clean"]').first()).toBeVisible();
  await shoot(page, "19-review-mixed-statuses");

  await page.goto(OVERVIEW);
  await expect(page.getByText("Available once every section is approved: 5 of 6 still to go.")).toBeVisible();
  await shoot(page, "20-overview-after");
});
