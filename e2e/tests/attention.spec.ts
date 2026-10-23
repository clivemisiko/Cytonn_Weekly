import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { DRAFT, VARIANT, openStart, release } from "./helpers";

/**
 * T87 to T93: what the page does when an action fails with a named problem (frontend/src/lib/attention.ts). A whole
 * action that failed opens one alert dialog (the headline, "The details are shown on the page.", Show me and Close)
 * and the full sentence stays on the page once; an inline problem opens no dialog and the page goes to it. Failures
 * the test instance cannot produce are stood in for with page.route, in the API's own shape (detail and problems).
 * With E2E_SHOTS=<folder>, T93 also writes screenshots there.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const MODE = "The tool's drafting mode changed after this page was opened. Reload the page to see what a draft will use, then start it again.";
const modeChanged = { detail: MODE, problems: [{ code: "draft_mode_changed", headline: "The drafting mode changed", target: "start-draft" }] };
const dialog = (page: Page, name: string) => page.getByRole("alertdialog", { name });

/** Focus of the Week's start screen, with a topic typed and every draft answered with the given failure. */
async function failingDraft(page: Page, body: unknown, status = 409) {
  await page.route("**/api/runs", (route) => (route.request().method() === "POST" ? route.fulfill({ status, json: body }) : route.fallback()));
  await openStart(page, "Focus of the Week");
  await page.getByLabel("This week’s topic").fill("Eurobonds");
  await page.getByRole("button", { name: DRAFT }).click();
}

test("T87 a whole action that failed: one alert dialog with the headline, the sentence once on the page, Show me goes to it", async ({ page }) => {
  await failingDraft(page, modeChanged);
  const open = dialog(page, "The drafting mode changed");
  await expect(open).toBeVisible();
  await expect(open.getByText("The details are shown on the page.", { exact: true })).toBeVisible();
  await expect(open.getByRole("button")).toHaveText(["Close", "Show me"]);
  await expect(page.getByText(MODE, { exact: true })).toHaveCount(1); // the full sentence is on the page, not in the dialog
  await expect(open.getByText(MODE)).toHaveCount(0);

  await open.getByRole("button", { name: "Show me" }).click();
  await expect(open).toBeHidden();
  const problem = page.locator('[data-attention="start-draft"] [data-problem]');
  await expect(problem).toBeFocused();
  await expect(problem).toBeInViewport();
  await expect(problem).toHaveText(MODE);
});

test("T88 Escape and Close shut the dialog; focus goes back where it was, or to the notice when that is gone", async ({ page }) => {
  await failingDraft(page, modeChanged);
  const open = dialog(page, "The drafting mode changed");
  const problem = page.locator('[data-attention="start-draft"] [data-problem]');
  await expect(open).toBeVisible();
  // The Draft button disables itself while it works, so it had lost focus before the dialog opened: focus goes to the notice.
  await page.keyboard.press("Escape");
  await expect(open).toBeHidden();
  await expect(problem).toBeFocused();
  // Close does the same.
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(open).toBeVisible();
  await open.getByRole("button", { name: "Close" }).click();
  await expect(open).toBeHidden();
  await expect(problem).toBeFocused();
});

test("T89 an inline problem opens no dialog: the page goes to the refusal and focuses it", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = page.locator('[data-attention="inputs-panel"]');
  await panel.locator('input[type="file"]').nth(5).setInputFiles({ name: "not-a-pdf.pdf", mimeType: "application/pdf", buffer: Buffer.from("hello") });
  const refusal = panel.getByRole("alert").filter({ hasText: "not-a-pdf.pdf: NSE yield curve: this is not a PDF file" });
  await expect(refusal).toBeVisible();
  await expect(refusal).toBeFocused();
  await expect(refusal).toBeInViewport();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});

test("T90 a refused value saved from a field: no dialog; the form disables its fields while saving, so focus goes to the refusal", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const placements = page.locator("#analyst-placements");
  await placements.fill("0.09");
  await placements.press("Enter");
  const refusal = page.locator('[data-attention="analyst-form"]').getByRole("alert").filter({ hasText: "3-month bank placements: 0.09 is outside the expected range" });
  await expect(refusal).toBeVisible();
  await expect(refusal).toBeFocused();
  await expect(placements).toHaveValue("0.09"); // what was typed is kept, to be corrected
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});

test("T91 a review change the API refuses as already decided: the dialog, then Show me goes to the status bar's notice", async ({ page }) => {
  await openStart(page, "Company Updates");
  await page.getByLabel("Your Company Updates text").fill("The firm opened a new office in Nairobi.");
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();

  const decided = "This section was already approved (review 1), so it cannot be changed. Reload the page to see the decision.";
  await page.route("**/api/reviews/*/items/*", (route) =>
    route.fulfill({ status: 409, json: { detail: decided, problems: [{ code: "review_already_decided", headline: "This section was already decided", target: "review-status-bar" }] } }),
  );
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  const open = dialog(page, "This section was already decided");
  await expect(open).toBeVisible();
  await open.getByRole("button", { name: "Show me" }).click();
  const notice = page.locator('[data-attention="review-status-bar"] [data-problem]');
  await expect(notice).toBeFocused();
  await expect(notice).toContainText(decided);
  // The rail holds no alert, status or dialog of any kind.
  const rail = page.getByRole("navigation", { name: "Report sections" });
  if (await rail.count()) await expect(rail.locator('[role="alert"], [role="status"], [role="alertdialog"]')).toHaveCount(0);
});

test("T92 under reduced motion, Show me puts the notice in view at once", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 500 });
  await failingDraft(page, modeChanged);
  await page.evaluate(() => window.scrollTo(0, 0));
  await dialog(page, "The drafting mode changed").getByRole("button", { name: "Show me" }).click();
  await expect(page.locator('[data-attention="start-draft"] [data-problem]')).toBeInViewport({ timeout: 1000 });
});

test("T93 screenshots of the dialog (light, dark, 390px) and of an inline problem (only with E2E_SHOTS=<folder>)", async ({ page }) => {
  const dir = process.env.E2E_SHOTS;
  test.skip(!dir, "set E2E_SHOTS to a folder to write them");
  mkdirSync(dir!, { recursive: true });
  for (const [name, scheme, width] of [["dialog-light", "light", 1280], ["dialog-dark", "dark", 1280], ["dialog-390", "light", 390]] as const) {
    await page.setViewportSize({ width, height: 800 });
    await page.emulateMedia({ colorScheme: scheme });
    await page.unrouteAll();
    await failingDraft(page, modeChanged);
    await expect(dialog(page, "The drafting mode changed")).toBeVisible();
    await page.waitForTimeout(400); // screenshots only: let the 150ms opening fade finish
    await page.screenshot({ path: join(dir!, `${name}.png`) });
  }
  await page.unrouteAll();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.emulateMedia({ colorScheme: "light" });
  await openStart(page, "Fixed Income");
  const panel = page.locator('[data-attention="inputs-panel"]');
  await panel.locator('input[type="file"]').nth(5).setInputFiles({ name: "not-a-pdf.pdf", mimeType: "application/pdf", buffer: Buffer.from("hello") });
  const refusal = panel.getByRole("alert").filter({ hasText: "not-a-pdf.pdf" });
  await expect(refusal).toBeFocused();
  await expect(refusal).toBeInViewport({ ratio: 1 });
  await page.waitForTimeout(600); // screenshots only: let the smooth scroll settle
  await page.screenshot({ path: join(dir!, "inline-after-goto.png") });
});
