import { expect, test, type Page } from "@playwright/test";

/**
 * The suite for the web app in frontend/. The tests use only what a person sees (roles, names, text) plus the few
 * ids and data attributes the app carries, so they do not depend on how it is built.
 * The tests run in order against one backend; T09 approves a section, which is final, so the backend restores its data
 * at every start (e2e/serve_e2e.py).
 */
const WEEK = "2026-10-09";
const PERIOD = `Week ending ${WEEK}`;
const OVERVIEW = `/overview?report=weekly&period=${encodeURIComponent(PERIOD)}`;
const DRAFT = `Draft the ${PERIOD} section`;
const RUN_TIMEOUT = 8 * 60_000;

const card = (page: Page, title: string) => page.locator("li", { has: page.getByRole("heading", { name: title, exact: true }) });
const topbar = (page: Page) => page.getByRole("navigation", { name: "App" });

async function openOverview(page: Page) {
  await page.goto(OVERVIEW);
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
}

/** A section's start screen, from the overview card's own button. */
async function openStart(page: Page, title: string, button: RegExp = /Draft section|Add your text/) {
  await openOverview(page);
  await card(page, title).getByRole("button", { name: button }).click();
  await expect(page.getByRole("heading", { name: `${title}: coordinator review`, level: 1 })).toBeVisible();
}

test.skip(!!process.env.E2E_VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

test("T01 landing page loads, with Home current and Back disabled", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Welcome to Cytonn Weekly\./ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Good (morning|afternoon|evening)\. Welcome to Cytonn Weekly\.$/ })).toBeVisible();
  await expect(page.getByText("Ready. Nothing is drafted until you ask.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in with Cytonn SSO" })).toBeDisabled();
  await expect(page.getByText("Not connected yet.", { exact: true })).toBeVisible();
  await expect(page.getByText(/this tool has no sign-in and should only be used by the\s+team/)).toBeVisible();
  await expect(page).toHaveTitle("Cytonn Weekly review");
  await expect(topbar(page).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  await expect(topbar(page).getByRole("button", { name: "Back (this is the start screen)" })).toBeDisabled();
  await page.getByRole("link", { name: "Continue without signing in" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
});

test("T02 an old bookmark of a report at / goes to the overview with its query kept", async ({ page }) => {
  await page.goto(`/?report=weekly&period=${encodeURIComponent(PERIOD)}`);
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  const url = new URL(page.url());
  expect(url.pathname).toBe("/overview");
  expect(url.searchParams.get("report")).toBe("weekly");
  expect(url.searchParams.get("period")).toBe(PERIOD);
});

test("T03 overview lists the six weekly sections, the dev mark and the export gate", async ({ page }) => {
  await openOverview(page);
  for (const title of ["Company Updates", "Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"]) {
    await expect(card(page, title)).toBeVisible();
  }
  await expect(page.getByText(`Weekly, ${PERIOD}: 6 report sections.`, { exact: false })).toBeVisible();
  await expect(card(page, "Fixed Income").getByText("Not drafted for w/e 9 Oct 2026")).toBeVisible();
  await expect(page.getByRole("group", { name: "Sections by state" })).toContainText("Not drafted6 / 6");
  // Dev mode: the ribbon under the top bar and the notice in the page.
  await expect(page.getByRole("status").filter({ hasText: "DEV MODE DRAFT (local model): NOT FOR PUBLICATION OR CIRCULATION" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "CYTONN_LLM_PROVIDER=local: DEV MODE." })).toBeVisible();
  // Export: there, and off until every section is approved.
  await expect(page.getByRole("heading", { name: "Export weekly report" })).toBeVisible();
  await expect(page.getByText("Available once every section is approved: 6 of 6 still to go.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeDisabled();
  await expect(page.getByText("Fixed Income: Not drafted")).toBeVisible();
});

test("T04 report picker shows the API's refusal, switches report, keeps it on reload; Back from the overview goes Home", async ({ page }) => {
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  await page.getByLabel("Report type").selectOption("quarterly");
  await expect(page.getByLabel("Period", { exact: true })).toHaveValue("Q3'2026");
  await page.getByLabel("Period", { exact: true }).fill("Q2'2026");
  await page.getByRole("button", { name: "Show sections" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Cytonn publishes the second quarter as the half-year review (H1); choose Half-year" })).toBeVisible();
  await expect(page.getByLabel("Period", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await page.getByLabel("Period", { exact: true }).fill("q3 2026");
  await page.getByRole("button", { name: "Show sections" }).click();
  await expect(page.getByText("Quarterly Markets Review, Q3'2026: 9 report sections.", { exact: false })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("period")).toBe("Q3'2026");
  await page.reload();
  await expect(page.getByText("Quarterly Markets Review, Q3'2026: 9 report sections.", { exact: false })).toBeVisible();
  await expect(card(page, "Fixed Income").getByText("Not drafted for Q3'2026")).toBeVisible();
  await topbar(page).getByRole("button", { name: "Back to Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: /Welcome to Cytonn Weekly\./ })).toBeVisible();
});

test("T05 theme toggle: Light, Dark, System, kept after a reload and applied before the first paint", async ({ page }) => {
  // What the page looks like at its first frame, before any framework code has run.
  await page.addInitScript(() => {
    requestAnimationFrame(() => {
      (window as unknown as { __firstFrame: string }).__firstFrame = document.documentElement.dataset.theme ?? "system";
    });
  });
  const firstFrame = () => page.evaluate(() => (window as unknown as { __firstFrame: string }).__firstFrame);
  const stored = () => page.evaluate(() => localStorage.getItem("cytonn-theme"));
  const paper = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const group = page.getByRole("radiogroup", { name: /^Theme: / });
  await expect(group).toHaveAccessibleName("Theme: System");
  expect(await firstFrame()).toBe("system");

  await page.getByRole("radio", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(group).toHaveAccessibleName("Theme: Dark");
  await expect(page.getByRole("radio", { name: "Dark theme" })).toBeChecked();
  expect(await stored()).toBe("dark");
  expect(await paper()).toBe("rgb(14, 14, 14)");
  await page.reload();
  expect(await firstFrame()).toBe("dark");
  await expect(page.getByRole("radio", { name: "Dark theme" })).toBeChecked();

  await page.getByRole("radio", { name: "Light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await stored()).toBe("light");
  expect(await paper()).toBe("rgb(243, 243, 243)");
  await page.emulateMedia({ colorScheme: "dark" }); // the device says dark; the stored Light still wins
  await page.reload();
  expect(await firstFrame()).toBe("light");
  expect(await paper()).toBe("rgb(243, 243, 243)");

  await page.getByRole("radio", { name: "System theme" }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
  expect(await stored()).toBeNull();
  expect(await paper()).toBe("rgb(14, 14, 14)"); // follows the (dark) device
  await page.reload();
  expect(await firstFrame()).toBe("system");
  await expect(group).toHaveAccessibleName("Theme: System");
});

test("T06 top bar stays in view after scrolling; Back goes to the section list, Home to /", async ({ page }) => {
  await openStart(page, "Fixed Income");
  await expect(page.getByRole("heading", { name: "Weekly analyst inputs" })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);
  await expect.poll(async () => (await page.locator("header").first().boundingBox())?.y).toBe(0);
  expect((await page.locator("header").first().boundingBox())?.height).toBe(44);
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("period")).toBe(PERIOD);
  await expect(card(page, "Equities")).toBeVisible();

  // From a deep link to a run (one the API does not know): Back names the section list, Home goes to /.
  await page.goto("/runs/not-a-run");
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await topbar(page).getByRole("link", { name: "Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: /Welcome to Cytonn Weekly\./ })).toBeVisible();
});

test("T07 inputs panel: what was received, an upload refused with its reason, a week that is not a Friday", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "This week’s inputs" }) }).first();
  await expect(panel.getByText("Week ending 9 Oct 2026: Monday 5 Oct 2026 to Friday.")).toBeVisible();
  await expect(panel.locator("li", { hasText: "Fixed income workbook" }).first()).toContainText("Received, this week’s");
  await expect(panel.getByText("5 of 5 received")).toBeVisible();
  await expect(panel.getByText("Not received (optional)")).toBeVisible();

  // The NSE yield curve slot is empty; a file that is not a PDF is refused in the API's own words and nothing is kept.
  await panel.locator('input[type="file"]').nth(5).setInputFiles({ name: "not-a-pdf.pdf", mimeType: "application/pdf", buffer: Buffer.from("hello") });
  await expect(panel.getByRole("alert").filter({ hasText: "not-a-pdf.pdf: NSE yield curve: this is not a PDF file" })).toBeVisible();
  await expect(panel.getByText("Not received (optional)")).toBeVisible();
  // The same file can be chosen again after a refusal.
  await panel.locator('input[type="file"]').nth(5).setInputFiles({ name: "not-a-pdf.pdf", mimeType: "application/pdf", buffer: Buffer.from("hello") });
  await expect(panel.getByRole("alert").filter({ hasText: "not-a-pdf.pdf: NSE yield curve: this is not a PDF file" })).toBeVisible();

  await panel.getByLabel("Week ending (a Friday)").fill("2026-10-08");
  await expect(panel.getByRole("alert").filter({ hasText: "8 Oct 2026 is a Thursday. A weekly report's week ends on a Friday, so choose a Friday." })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Show this week" })).toBeDisabled();
});

test("T08 analyst inputs: refusals listed, the draft button waits for unsaved typing, Home and Back ask first", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Weekly analyst inputs" }) }).first();
  const draft = page.getByRole("button", { name: DRAFT });
  const waiting = page.getByText("Something under “Weekly analyst inputs” is not saved yet", { exact: false });
  const placements = panel.locator("#analyst-placements");
  await expect(placements).toHaveAttribute("placeholder", "9.75 (workbook)");
  await expect(panel.getByText("From the workbook", { exact: true }).first()).toBeVisible();
  await expect(draft).toBeEnabled();

  // A field: typing makes it unsaved; leaving it saves; a refused value stays typed, with the API's reason.
  await placements.fill("0.09");
  await expect(draft).toBeDisabled();
  await expect(waiting).toBeVisible();
  await placements.press("Enter");
  await expect(panel.getByRole("alert").filter({ hasText: "3-month bank placements: 0.09 is outside the expected range, 1 to 40%. Type a percentage as 9.0, not 0.09." })).toBeVisible();
  await expect(placements).toHaveValue("0.09");
  await expect(draft).toBeDisabled();
  await placements.fill("9.5");
  await placements.press("Enter");
  await expect(panel.getByText("Typed, differs from the workbook", { exact: true })).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(draft).toBeEnabled();
  await expect(panel.getByText("The reviewer is shown each difference.")).toBeVisible();
  await placements.fill("");
  await placements.press("Enter");
  await expect(panel.getByText("Typed, differs from the workbook", { exact: true })).toHaveCount(0);
  await expect(draft).toBeEnabled();

  // A table: its own Save; all or nothing, every reason on its own line.
  const table = panel.locator("#analyst-mmf");
  await table.fill("1 Alpha Fund 0.11\n3 Beta Fund 250");
  await expect(panel.getByText("Not saved yet.")).toBeVisible();
  await expect(draft).toBeDisabled();
  await expect(waiting).toBeVisible();

  // Back and Home ask before leaving; Cancel stays on the page with the typing intact.
  const questions: string[] = [];
  page.once("dialog", (d) => {
    questions.push(d.message());
    void d.dismiss();
  });
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  expect(questions).toEqual(['Something typed under "Weekly analyst inputs" is not saved yet. Leave this page and lose it?']);
  await expect(table).toHaveValue("1 Alpha Fund 0.11\n3 Beta Fund 250");
  page.once("dialog", (d) => {
    questions.push(d.message());
    void d.dismiss();
  });
  await topbar(page).getByRole("link", { name: "Home" }).click();
  expect(questions).toHaveLength(2);
  await expect(page).toHaveURL(/\/overview/);

  await panel.getByRole("button", { name: "Save table" }).and(page.locator(":enabled")).click(); // only the edited table can be saved
  const refusal = panel.getByRole("alert").filter({ hasText: "Money market fund table, line 1" });
  await expect(refusal).toContainText("Money market fund table, line 1: 0.11 is outside the expected range, 1 to 40%. Type a percentage as 9.0, not 0.09.");
  await expect(refusal).toContainText("Money market fund table, line 2: 250 is outside the expected range, 1 to 40%.");
  await expect(refusal).toHaveCSS("white-space", "pre-line");
  await expect(table).toHaveValue("1 Alpha Fund 0.11\n3 Beta Fund 250");
  await expect(draft).toBeDisabled();
  await panel.getByRole("button", { name: "Discard changes" }).click();
  await expect(table).toHaveValue("");
  await expect(draft).toBeEnabled();
  await expect(waiting).toHaveCount(0);

  // Saying yes leaves.
  await table.fill("1 Alpha Fund 11.0");
  page.once("dialog", (d) => void d.accept());
  await topbar(page).getByRole("link", { name: "Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  // Nothing was stored by any of it.
  await openStart(page, "Fixed Income");
  await expect(page.locator("#analyst-mmf")).toHaveValue("");
  await expect(page.locator("#analyst-placements")).toHaveValue("");
});

let companyReview = "";

test("T09 Company Updates: run to done, open the review, Approve is gated, the decision is final", async ({ page }) => {
  await openStart(page, "Company Updates");
  const save = page.getByRole("button", { name: "Save your text as the section" });
  await expect(save).toBeDisabled();
  await expect(page.getByText("Nothing is searched or drafted: your text is carried as written and listed once for you to accept.")).toBeVisible();
  await page.getByLabel("Your Company Updates text").fill("Investment Updates:\nSYNTHETIC e2e text, not real.");
  await save.click();

  // The run view: it reaches done and waits; it never opens the review by itself.
  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Company Updates: draft run", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await expect(page.getByText(/^Finished .* EAT\.$/)).toBeVisible();
  const steps = page.getByRole("log", { name: "Steps of this draft" });
  await expect(steps.getByRole("listitem")).toHaveText(["Done: Starting the draft.", "Done: Draft ready for review."]);
  await expect(page.getByRole("group", { name: "Review items by status" })).toContainText("Not auto-verified1");
  await expect(page).toHaveURL(/\/runs\//);
  await page.getByRole("link", { name: "Open review" }).click();

  await expect(page.getByRole("heading", { name: "Company Updates: coordinator review", level: 1 })).toBeVisible();
  companyReview = new URL(page.url()).searchParams.get("review") ?? "";
  expect(companyReview).toMatch(/^\d+$/);
  const approve = page.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
  await expect(page.getByText("Approve unlocks once every item is resolved and none needs a fix.")).toBeVisible();
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();
  await expect(page.locator('li[data-status="not_auto_verified"]')).toHaveCount(1);

  // Fix needed blocks approval and says why; Accept unlocks it.
  await page.getByRole("radio", { name: "Fix needed" }).click();
  await expect(page.getByText("Not approvable yet: 1 marked fix needed.")).toBeVisible();
  await expect(approve).toBeDisabled();
  await page.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Approvable: every item is resolved and none needs a fix.")).toBeVisible();
  await expect(page.getByText("0 unresolved · 1 of 1 resolved")).toBeVisible();
  await expect(page.getByText(`Saved as run ${companyReview}`)).toBeVisible();
  await expect(approve).toBeEnabled();

  // The confirm dialog: Cancel and Escape close it without deciding.
  await approve.click();
  const dialog = page.getByRole("dialog", { name: "Approve this section?" });
  await expect(dialog).toContainText("Every value is accepted as drafted. This is recorded once and cannot be changed.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await approve.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(approve).toBeEnabled();
  await approve.click();
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(dialog).toBeHidden();

  await expect(page.getByText("Approved and locked")).toBeVisible();
  await expect(page.getByText("Decision recorded: approved.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByLabel(/^Note for /)).toHaveAttribute("readonly", "");

  // The review's own address opens it again; Back goes to its report's sections, where it now reads Approved.
  await page.goto(`/overview?report=weekly&period=${encodeURIComponent(PERIOD)}&review=${companyReview}`);
  await expect(page.getByText("Approved and locked")).toBeVisible();
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  await expect(card(page, "Company Updates")).toContainText("Approved");
  await expect(card(page, "Company Updates").getByRole("button", { name: "View review" })).toBeVisible();
  await expect(page.getByText("Available once every section is approved: 5 of 6 still to go.")).toBeVisible();
  await expect(page.getByText("Company Updates: Approved")).toBeVisible();
});

test("T10 the sticky status bar stays under the top bar while a review scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 500 });
  await page.goto(`/overview?review=${companyReview}`);
  await expect(page.getByText("Decision recorded: approved.")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
  const bar = page.locator("div.sticky", { has: page.getByRole("progressbar", { name: "Items resolved" }) });
  // 44px top bar, then the dev ribbon's 28px when the review is a dev draft (this one is not).
  await expect.poll(async () => Math.round((await bar.boundingBox())?.y ?? -1)).toBe(44); // once the screen has settled into place
  await expect(page.getByRole("button", { name: "Back to all sections" }).last()).toBeInViewport();
});

test("T11 a stopped run shows the error text and the way back", async ({ page }) => {
  await openStart(page, "Real Estate");
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Real Estate: draft run", level: 1 })).toBeVisible();
  const alert = page.getByRole("alert").filter({ hasText: "The draft stopped." });
  await expect(alert).toContainText("the Ibuka summary could not be fetched (a deliberate failure for the tests)");
  await expect(page.getByText(/^Stopped .* EAT\.$/)).toBeVisible();
  await expect(page.getByRole("log", { name: "Steps of this draft" }).getByRole("listitem").last()).toContainText("Failed: The draft stopped.");
  await expect(page.getByRole("heading", { name: "Draft ready for review" })).toHaveCount(0);
  await page.getByRole("link", { name: "Back to overview" }).click();
  await expect(page.getByRole("heading", { name: "Coordinator review", level: 1 })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("period")).toBe(PERIOD);
  await expect(card(page, "Real Estate").getByText("Not drafted for w/e 9 Oct 2026")).toBeVisible();
});

test("T12 Fixed Income: run view steps to done, review lists the three statuses, accepting, notes, the leave prompt", async ({ page }) => {
  test.setTimeout(RUN_TIMEOUT + 120_000);
  await openStart(page, "Fixed Income");
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Fixed Income: draft run", level: 1 })).toBeVisible();
  await expect(page.getByText(`Weekly, ${PERIOD}. Each line below is a step the draft has really taken.`)).toBeVisible();
  // While a development draft runs: the ribbon, a Running status line, and real steps arriving.
  await expect(page.getByRole("status").filter({ hasText: "DEV MODE DRAFT (local model)" })).toBeVisible();
  const steps = page.getByRole("log", { name: "Steps of this draft" });
  await expect(steps.getByRole("listitem").first()).toHaveText("Done: Starting the draft.");
  await expect(page.getByText(/^(Running\. Started|Finished) .* EAT\.$/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: RUN_TIMEOUT });
  await expect(steps.getByRole("listitem").last()).toHaveText("Done: Draft ready for review.");
  expect(await steps.getByRole("listitem").count()).toBeGreaterThan(5);
  await expect(steps.getByRole("listitem").filter({ hasText: /^Done: Checked .*: \d+ clean, \d+ flagged, \d+ not auto-verified\.$/ }).first()).toBeVisible();
  await expect(steps.getByRole("listitem").filter({ hasText: /^In progress: / })).toHaveCount(0);
  const tiles = page.getByRole("group", { name: "Review items by status" });
  await expect(tiles).toContainText("Flagged");
  await expect(tiles).toContainText("Not auto-verified");
  await expect(tiles).toContainText("Clean");
  await page.getByRole("link", { name: "Open review" }).click();

  await expect(page.getByRole("heading", { name: "Fixed Income: coordinator review", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review items", level: 2 })).toBeVisible();
  const flaggedHead = page.getByRole("button", { name: /^! Flagged by the checker \(\d+\)$|^Flagged by the checker \(\d+\)$/ });
  const unverifiedHead = page.getByRole("button", { name: /Not automatically verified \(\d+\)$/ });
  const cleanHead = page.getByRole("button", { name: /Clean \(\d+\)$/ });
  await expect(flaggedHead).toHaveAttribute("aria-expanded", "true");
  await expect(unverifiedHead).toHaveAttribute("aria-expanded", "true");
  await expect(cleanHead).toHaveAttribute("aria-expanded", "false"); // coverage, not work: starts closed
  const flagged = page.locator('li[data-status="flagged"]');
  const unverified = page.locator('li[data-status="not_auto_verified"]');
  const clean = page.locator('li[data-status="clean"]');
  expect(await flagged.count()).toBeGreaterThan(0);
  expect(await unverified.count()).toBeGreaterThan(0);
  await expect(clean).toHaveCount(0);
  await cleanHead.click();
  await expect(cleanHead).toHaveAttribute("aria-expanded", "true");
  expect(await clean.count()).toBeGreaterThan(0);
  await expect(flagged.first()).toContainText("Flagged");
  await expect(unverified.first()).toContainText("Not auto-verified");
  await expect(clean.first()).toContainText("Clean");
  // The scorecard's totals are the lists' lengths.
  const total = (await flagged.count()) + (await unverified.count()) + (await clean.count());
  await expect(page.getByText(new RegExp(`${total} unresolved · 0 of ${total} resolved`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  // A dev draft carries its mark on the review too.
  await expect(page.getByRole("heading", { name: /^Drafted section: / })).toBeVisible();

  // Accept one item: its chip changes at once and the count follows the server.
  const first = unverified.first();
  await expect(first.getByText("Unresolved", { exact: true }).first()).toBeVisible();
  await first.getByRole("radio", { name: "Accept", exact: true }).click();
  await expect(first.getByText("Accepted", { exact: true })).toBeVisible();
  await expect(first.getByRole("radio", { name: "Accept", exact: true })).toBeChecked();
  await expect(page.getByText(new RegExp(`${total - 1} unresolved · 1 of ${total} resolved`))).toBeVisible();

  // Every clean item at once.
  const cleanCount = await clean.count();
  await page.getByRole("button", { name: `Mark all clean as accepted (${cleanCount} unresolved)` }).click();
  await expect(page.getByRole("button", { name: "Mark all clean as accepted (0 unresolved)" })).toBeDisabled();
  await expect(page.getByText(new RegExp(`${total - 1 - cleanCount} unresolved · ${1 + cleanCount} of ${total} resolved`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled(); // flagged items are still open

  // A note is saved when the box is left; until then the browser asks before the page is left.
  const note = first.getByLabel(/^Note for /);
  await note.fill("checked against the bulletin");
  let asked = "";
  page.once("dialog", (d) => {
    asked = d.type();
    void d.dismiss();
  });
  await page.evaluate(() => window.location.reload());
  await expect.poll(() => asked).toBe("beforeunload");
  await expect(note).toHaveValue("checked against the bulletin");
  await note.press("Enter");
  await expect(page.getByText(/^Saved as run \d+$/)).toBeVisible();
  await page.reload(); // saved now: no prompt, and the note is the server's
  await expect(page.locator('li[data-status="not_auto_verified"]').first().getByLabel(/^Note for /)).toHaveValue("checked against the bulletin");
  await expect(page.locator('li[data-status="not_auto_verified"]').first().getByRole("radio", { name: "Accept", exact: true })).toBeChecked();

  // The overview now offers it for resuming.
  await topbar(page).getByRole("button", { name: "Back to all sections" }).click();
  await expect(card(page, "Fixed Income").getByText("In review", { exact: true })).toBeVisible();
  await expect(card(page, "Fixed Income").getByRole("button", { name: "Resume review" })).toBeVisible();
});

test("T13 Equities: run to done and its review opens with items", async ({ page }) => {
  test.setTimeout(RUN_TIMEOUT + 120_000);
  await openStart(page, "Equities");
  await page.getByRole("button", { name: DRAFT }).click();
  await expect(page.getByRole("heading", { name: "Equities: draft run", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: RUN_TIMEOUT });
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Equities: coordinator review", level: 1 })).toBeVisible();
  expect(await page.locator("li[data-status]").count()).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: /Flagged by the checker \(\d+\)$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();
});

test("T14 Word export: off until every section is approved; when the API says ready, the file downloads under its name", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByRole("button", { name: "Export weekly report" })).toBeDisabled();
  await expect(page.getByText("Available once every section is approved: 5 of 6 still to go.")).toBeVisible();

  // Approving all six sections needs live sources the test instance does not have, so the API's two export answers
  // are stood in for here; what is under test is what the page does with them.
  const cors = { "access-control-allow-origin": "*", "access-control-expose-headers": "Content-Disposition" };
  const sections = ["Company Updates", "Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"];
  await page.route(/\/api\/export\/weekly/, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: { period: PERIOD, ready: true, is_dev_draft: false, dev_mode_label: "", dev_sections: [], sections: sections.map((title) => ({ slug: title, title, state: "approved", run_id: 1 })) },
        headers: cors,
      });
    } else {
      await route.fulfill({
        body: Buffer.from("PK synthetic"),
        contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers: { ...cors, "content-disposition": 'attachment; filename="Cytonn-Weekly-e2e.docx"' },
      });
    }
  });
  await page.reload();
  await expect(page.getByText("Every section is approved.", { exact: false })).toBeVisible();
  const button = page.getByRole("button", { name: "Export weekly report" });
  await expect(button).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(download.suggestedFilename()).toBe("Cytonn-Weekly-e2e.docx");
  await expect(button).toBeEnabled();
});

test("T15 a run the API no longer has says so and links to the overview", async ({ page }) => {
  await page.goto("/runs/not-a-run");
  await expect(page.getByRole("heading", { name: "Draft run", level: 1 })).toBeVisible();
  await expect(page.getByText("This run is no longer available. If the draft finished, open the section from the overview.")).toBeVisible();
  await page.getByRole("link", { name: "Go to the overview" }).click();
  await expect(page).toHaveURL(/\/overview$/);
});

test("T16 keyboard: the skip link comes first, the theme group is one tab stop moved by arrow keys", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Welcome to Cytonn Weekly\./ })).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main$/);
  await expect(page.locator("main#main")).toHaveAttribute("tabindex", "-1");

  // A held key, as a person presses it: the group moves focus a moment after the key goes down.
  const arrowLeftTo = async (name: string) => {
    await page.keyboard.down("ArrowLeft");
    await expect(page.getByRole("radio", { name })).toBeFocused();
    await page.keyboard.up("ArrowLeft");
    await expect(page.getByRole("radio", { name })).toBeChecked();
  };
  await page.getByRole("radio", { name: "System theme" }).focus();
  await arrowLeftTo("Dark theme");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await arrowLeftTo("Light theme");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("Tab"); // one tab stop: the next Tab leaves the group
  await expect(page.getByRole("radio", { name: /theme$/ }).and(page.locator(":focus"))).toHaveCount(0);
});
