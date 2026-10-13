import { expect, test } from "@playwright/test";
import { API, DRAFT, PERIOD, VARIANT, card, hold, openStart, overviewUrl, release, startRun } from "./helpers";

/**
 * Two states the default test backend is never in, each with its own start of the API (E2E_VARIANT, see
 * e2e/serve_e2e.py). Each test runs only under its variant: `npm run test:variants`.
 */
test.afterEach(() => void release());

test("T26 a provider problem: said on the start screen, drafting is off, and the API refuses a run", async ({ page, request }) => {
  test.skip(VARIANT !== "no-key", "needs E2E_VARIANT=no-key");
  const config = await (await request.get(`${API}/api/config`)).json();
  expect(config.provider).toBe("anthropic");
  expect(config.provider_problem).toBeTruthy();

  await page.goto(overviewUrl());
  await expect(card(page, "Fixed Income")).toBeVisible();
  await expect(page.getByText("DEV MODE", { exact: false })).toHaveCount(0); // not the local provider, so no dev mark

  await openStart(page, "Focus of the Week");
  await page.getByLabel("This week’s topic").fill("Eurobonds");
  await expect(page.getByRole("alert").filter({ hasText: "Drafting is off until then." })).toContainText(config.provider_problem);
  await expect(page.getByRole("button", { name: DRAFT })).toBeDisabled();
  await expect(page.getByText("A run spends real API budget", { exact: false })).toHaveCount(0);
  // Enter in the topic box does not start one either.
  await page.getByLabel("This week’s topic").press("Enter");
  await expect(page).toHaveURL(/\/overview/);

  // The problem never reaches the run view, because no run starts: the API refuses it up front, in the same words.
  const refused = await request.post(`${API}/api/runs`, { headers: { "Content-Type": "application/json" }, data: { section: "focus", report_type: "weekly", period: PERIOD, topic: "Eurobonds" } });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).detail).toContain(config.provider_problem);

  // A section that calls no provider is not affected.
  await openStart(page, "Company Updates");
  await expect(page.getByText("Drafting is off until then.", { exact: false })).toHaveCount(0);
  await page.getByLabel("Your Company Updates text").fill("Investment Updates:\nSYNTHETIC e2e text.");
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
});

test("T27 a stale draft: shown as stuck, the next draft takes the slot over and the stuck one's result is discarded", async ({ page, request }) => {
  test.skip(VARIANT !== "stale", "needs E2E_VARIANT=stale");
  hold();
  const stuck = await startRun(request, "real_estate");
  await page.waitForTimeout(7_000); // this variant counts a draft as stuck after six seconds

  await page.goto(overviewUrl());
  const banner = page.getByRole("status").filter({ hasText: /^Real Estate \(Week ending 2026-10-09\) has been drafting for/ });
  await expect(banner).toContainText("longer than any healthy draft takes. It looks stuck: the next draft started, in");
  await expect(banner).toContainText("replaces it, and its result will be discarded.");
  await expect(card(page, "Real Estate")).toContainText("Looks stuck");
  await expect(card(page, "Real Estate")).toContainText("A draft has run far longer than it should and looks stuck. Drafting again replaces it.");

  // Another section: warned, and free to draft.
  await openStart(page, "Digital Payments");
  const warning = page.getByRole("status").filter({ hasText: /^Real Estate \(Week ending 2026-10-09\) has been drafting for/ });
  await expect(warning).toContainText("longer than any healthy draft takes, and looks stuck. Starting a draft replaces it; its result will be discarded.");
  await expect(page.getByRole("button", { name: DRAFT })).toBeEnabled();
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 60_000 });

  // The stuck draft ends later; it was replaced, so it ends as stopped and saves nothing.
  release();
  await page.goto(`/runs/${stuck}`);
  await expect(page.getByRole("alert").filter({ hasText: "The draft stopped." })).toBeVisible({ timeout: 20_000 });
  await page.goto(overviewUrl());
  await expect(card(page, "Real Estate")).toContainText("Not drafted for w/e 9 Oct 2026");
  await expect(card(page, "Digital Payments")).toContainText("In review");
});
