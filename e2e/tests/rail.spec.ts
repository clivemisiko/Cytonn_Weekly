import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, card, openStart, overviewUrl, startRun, topbar } from "./helpers";

/**
 * The side rail: the report's sections with their state, the way to open one, the narrow and absent forms, the guard
 * that Home and Back share, and that its states follow an approval or a rejection and are neutral when not known. This
 * file has its own run on a freshly restored test backend (`playwright test rail`); each test that decides a section
 * uses its own week, because a decision is final.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const json = { "Content-Type": "application/json" };
const TITLES = ["Company Updates", "Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"];
const rail = (page: Page) => page.getByRole("navigation", { name: "Report sections" });
const heading = (title: string) => ({ name: `${title}: coordinator review`, level: 1 }) as const;

/** Company Updates drafted through the API for that week (it calls no model); left in review. */
async function draftCompanyUpdates(request: APIRequestContext, period: string, text: string) {
  const res = await request.post(`${API}/api/sections/company_updates/draft`, { headers: json, data: { report_type: "weekly", period, text } });
  expect(res.status(), await res.text()).toBe(200);
}

/** From the overview of that week, open Company Updates' review and wait for the screen. */
async function openReview(page: Page, period: string) {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl(period));
  await expect(rail(page).getByRole("button", { name: "Company Updates, In review" })).toBeVisible();
  await card(page, "Company Updates").getByRole("button", { name: "Resume review" }).click();
  await expect(page.getByRole("heading", heading("Company Updates"))).toBeVisible();
}

test("T59 the rail lists the six sections with their state; it is a full rail, a narrow strip or absent by width, and sits under the dev ribbon", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl());
  const nav = rail(page);
  for (const title of TITLES) await expect(nav.getByRole("button", { name: `${title}, Not drafted` })).toBeVisible();
  await expect(nav.getByRole("button", { name: "Overview", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("progressbar")).toHaveCount(0); // the overview shows the tally itself
  expect((await nav.boundingBox())?.width).toBe(224);
  expect((await nav.getByRole("button", { name: /^Fixed Income, / }).boundingBox())!.width).toBeGreaterThan(150); // its label shows

  // The dev ribbon is directly under the top bar and the rail starts under the ribbon, not behind it.
  const ribbon = page.getByRole("status").filter({ hasText: "DEV MODE DRAFT (local model): NOT FOR PUBLICATION OR CIRCULATION" });
  expect(Math.round((await ribbon.boundingBox())!.y)).toBe(44);
  expect(Math.round((await ribbon.boundingBox())!.height)).toBe(28);
  expect(Math.round((await nav.boundingBox())!.y)).toBe(72);
  // It sticks: after the page has scrolled, the rail is still under the ribbon, as tall as the room left, not scrolled away.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(200);
  await expect.poll(async () => Math.round((await nav.boundingBox())!.y)).toBe(72);
  expect(Math.round((await nav.boundingBox())!.height)).toBe(768 - 72);
  await expect(nav.getByRole("button", { name: "Focus of the Week, Not drafted" })).toBeInViewport();
  await page.evaluate(() => window.scrollTo(0, 0));

  // From 768px it is a narrow strip of icons that a button expands over the page; Escape folds it again.
  await page.setViewportSize({ width: 1280, height: 720 });
  expect((await nav.boundingBox())?.width).toBe(56);
  expect((await nav.getByRole("button", { name: /^Fixed Income, / }).boundingBox())!.width).toBeLessThan(60);
  await nav.getByRole("button", { name: "Expand the rail" }).click();
  expect((await nav.boundingBox())?.width).toBe(224);
  expect((await nav.getByRole("button", { name: /^Fixed Income, / }).boundingBox())!.width).toBeGreaterThan(150);
  await page.keyboard.press("Escape");
  await expect(nav.getByRole("button", { name: "Expand the rail" })).toBeVisible();
  expect((await nav.boundingBox())?.width).toBe(56);

  // On a phone there is no rail; the top bar's Home and Back are what there is, as before.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(nav).toBeHidden();
  await expect(topbar(page).getByRole("link", { name: "Home" })).toBeVisible();
  await expect(topbar(page).getByRole("button", { name: "Back to Home" })).toBeVisible();
});

test("T60 a section opens from the rail, from the overview and from another section, and the rail marks the one on screen", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(overviewUrl());
  await rail(page).getByRole("button", { name: "Company Updates, Not drafted" }).click();
  await expect(page.getByRole("heading", heading("Company Updates"))).toBeVisible();
  await expect(rail(page).getByRole("button", { name: "Company Updates, Not drafted, this section is on screen" })).toHaveAttribute("aria-current", "page");
  await expect(rail(page).getByText("0 of 6 sections approved")).toBeVisible();
  await expect(rail(page).getByRole("progressbar", { name: "Sections approved" })).toHaveAttribute("aria-valuenow", "0");
  await expect(rail(page).getByText("Export unlocks when all 6 are approved.")).toBeVisible();
  await expect(rail(page).getByText("Dev mode · local model")).toBeVisible();

  await rail(page).getByRole("button", { name: "Real Estate, Not drafted" }).click();
  await expect(page.getByRole("heading", heading("Real Estate"))).toBeVisible();
  await expect(rail(page).getByRole("button", { name: /^Real Estate, Not drafted, this section is on screen$/ })).toHaveAttribute("aria-current", "page");
  await expect(rail(page).getByRole("button", { name: "Company Updates, Not drafted" })).not.toHaveAttribute("aria-current", "page");

  await rail(page).getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  await expect(rail(page).getByRole("button", { name: "Overview", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(rail(page).getByRole("progressbar")).toHaveCount(0);
});

test("T61 the rail asks first when something typed is unsaved, as Home and Back do", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Weekly analyst inputs" }) }).first();
  const placements = panel.locator("#analyst-placements");
  await placements.fill("9.25");
  const questions: string[] = [];
  page.once("dialog", (d) => {
    questions.push(d.message());
    void d.dismiss();
  });
  await rail(page).getByRole("button", { name: "Equities, Not drafted" }).click();
  await expect.poll(() => questions.length).toBe(1);
  expect(questions[0]).toBe('Something typed under "Weekly analyst inputs" is not saved yet. Leave this page and lose it?');
  await expect(page.getByRole("heading", heading("Fixed Income"))).toBeVisible();
  await expect(placements).toHaveValue("9.25"); // Cancel: still here, typing intact

  page.once("dialog", (d) => void d.accept());
  await rail(page).getByRole("button", { name: "Equities, Not drafted" }).click();
  await expect(page.getByRole("heading", heading("Equities"))).toBeVisible();
});

test("T62 on the run view the rail's sections do nothing and say so; its Overview item goes back to the sections", async ({ page, request }) => {
  const run = await startRun(request, "real_estate"); // stops by design in the test API and saves nothing
  await page.goto(`/runs/${run}`);
  await expect(page.getByRole("heading", { name: "Real Estate: draft run", level: 1 })).toBeVisible();
  const item = rail(page).getByRole("button", { name: "Fixed Income, Not drafted, open the overview first" });
  await expect(item).toHaveAttribute("aria-disabled", "true");
  await item.click({ force: true }); // Playwright waits forever to click an aria-disabled control; the point is that nothing happens
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByRole("heading", { name: "Real Estate: draft run", level: 1 })).toBeVisible();

  await rail(page).getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page).toHaveURL(/\/overview/);
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
});

test("T63 a rejection changes the rail's state at once and leaves the approved count where it was", async ({ page, request }) => {
  const period = "Week ending 2026-11-13";
  await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, to be rejected.");
  await openReview(page, period);
  await expect(rail(page).getByText("0 of 6 sections approved")).toBeVisible();

  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog", { name: "Reject this section?" }).getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Rejected and locked")).toBeVisible();
  await expect(rail(page).getByRole("button", { name: "Company Updates, Rejected, this section is on screen" })).toBeVisible();
  await expect(rail(page).getByText("0 of 6 sections approved")).toBeVisible(); // a rejected section is not an approved one

  await page.getByRole("button", { name: "Back to all sections" }).last().click();
  await expect(card(page, "Company Updates")).toContainText("Rejected"); // the overview says the same
  await expect(rail(page).getByRole("button", { name: "Company Updates, Rejected" })).toBeVisible();
});

test("T64 an approval changes the rail's state and its approved count", async ({ page, request }) => {
  const period = "Week ending 2026-11-20";
  await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, to be approved.");
  await openReview(page, period);
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog", { name: "Approve this section?" }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Approved and locked")).toBeVisible();
  await expect(rail(page).getByRole("button", { name: "Company Updates, Approved, this section is on screen" })).toBeVisible();
  await expect(rail(page).getByText("1 of 6 sections approved")).toBeVisible();
  await expect(rail(page).getByRole("progressbar", { name: "Sections approved" })).toHaveAttribute("aria-valuenow", "1");
});

test("T65 when the sections cannot be read again, every state is the neutral mark and the count is not known", async ({ page, request }) => {
  const period = "Week ending 2026-11-27";
  await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, decided while the API's list is down.");
  await openReview(page, period);
  await page.route(/\/api\/sections(\?|$)/, (route) => route.abort());
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("dialog", { name: "Approve this section?" }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Approved and locked")).toBeVisible(); // the decision itself went through
  // The rail does not go on saying "In review": it says it does not know.
  await expect(rail(page).getByRole("button", { name: "Company Updates, State not known, this section is on screen" })).toBeVisible();
  await expect(rail(page).getByRole("button", { name: "Fixed Income, State not known, open the overview first" })).toHaveCount(0); // the overview page is still here, so it is not inert
  await expect(rail(page).getByRole("button", { name: "Fixed Income, State not known" })).toBeVisible();
  await expect(rail(page).getByText("Approved count not known")).toBeVisible();
  await expect(rail(page).getByRole("progressbar")).toHaveCount(0);
});

test("T69 the dev ribbon is the shell's: on the overview, a start screen and a review of a dev draft, never on the start page, and the review's sticky bar sits below it", async ({ page, request }) => {
  const period = "Week ending 2026-12-11";
  await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, for the ribbon.");
  await page.setViewportSize({ width: 1366, height: 500 });
  const ribbon = page.getByRole("status").filter({ hasText: "DEV MODE DRAFT" });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Welcome to Cytonn Weekly\./ })).toBeVisible();
  await expect(ribbon).toHaveCount(0); // the start page makes no API call and carries no dev mark

  // The test API is in dev mode, so the overview and a section's start screen show it, directly under the top bar.
  await openStart(page, "Equities", period);
  await expect(ribbon).toBeVisible();
  expect(Math.round((await ribbon.boundingBox())!.y)).toBe(44);

  // A review is a dev draft only if it says so; this API has none, so its answer for the review is changed to say it.
  await page.route(/\/api\/reviews\/\d+$/, async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    body.is_dev_draft = true;
    body.dev_mode_label = "DEV MODE DRAFT (stub): NOT FOR PUBLICATION OR CIRCULATION";
    await route.fulfill({ response, json: body });
  });
  await page.goto(overviewUrl(period));
  await card(page, "Company Updates").getByRole("button", { name: "Resume review" }).click();
  await expect(page.getByRole("heading", heading("Company Updates"))).toBeVisible();
  const reviewRibbon = page.getByRole("status").filter({ hasText: "DEV MODE DRAFT (stub)" });
  await expect(reviewRibbon).toBeVisible();
  expect(Math.round((await reviewRibbon.boundingBox())!.y)).toBe(44);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(50);
  const bar = page.locator("div.sticky", { has: page.getByRole("progressbar", { name: "Items resolved" }) });
  await expect.poll(async () => Math.round((await bar.boundingBox())?.y ?? -1)).toBe(72); // 44px top bar, then the ribbon's 28px
});
