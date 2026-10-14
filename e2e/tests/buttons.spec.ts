import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, REPO, VARIANT, WEEK, openStart, putAnalyst, release } from "./helpers";

/**
 * Every button of the two input panels not already exercised by T07, T08 and T17 to T20, each where it applies with the
 * week before present and absent. This file has its own run on a freshly restored test backend (`playwright test
 * buttons`), and each test puts back what it changed. A week before is made by saving a form through the API, or, for
 * a state the screens never write by themselves (a value held but never confirmed), by writing that week's form file
 * in the test backend's throwaway data folder. Nothing here touches the pristine copy or real data.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const DATA = process.env.E2E_DATA_DIR ?? join(REPO, "backend", "data", "demo-e2e", "data");
const formFile = (week: string) => join(DATA, "inputs", "weekly", week, "analyst.json");
const json = { "Content-Type": "application/json" };

/** A week's form holding values that were carried or suggested and never confirmed (the screens make this only over time). */
function writeUnconfirmed(week: string, fields: Record<string, string>) {
  mkdirSync(join(DATA, "inputs", "weekly", week), { recursive: true });
  const carried = Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, { from: "suggested", value: v, note: "seeded by the test" }]));
  writeFileSync(formFile(week), JSON.stringify({ fields, tables: {}, carried, unconfirmed: Object.keys(fields), saved_at: null }));
}
const dropForm = (week: string) => existsSync(formFile(week)) && rmSync(formFile(week));

async function putTable(request: APIRequestContext, week: string, section: string, key: string, text: string | null) {
  const res = await request.put(`${API}/api/inputs/weekly/${week}/analyst?section=${section}`, {
    headers: json,
    data: { tables: { [key]: text === null ? null : { text } } },
  });
  expect(res.status(), await res.text()).toBe(200);
}

const inputsPanel = (page: Page) => page.locator("section", { has: page.getByRole("heading", { name: "This week’s inputs" }) }).first();
const analystPanel = (page: Page) => page.locator("section", { has: page.getByRole("heading", { name: "Weekly analyst inputs" }) }).first();
const suggestButton = (page: Page, label: string) =>
  analystPanel(page).getByRole("button", { name: new RegExp(`^Suggest from last week’s total\\s*: ${label}$`) });

test("T28 start from last week’s form, with no week before: the button is off and says why", async ({ page }) => {
  await openStart(page, "Equities", "Week ending 2026-10-02");
  const panel = analystPanel(page);
  await expect(panel.getByRole("button", { name: "Start from last week’s form" })).toBeDisabled();
  await expect(panel.getByText("Nothing confirmed is saved for the week ending 25 Sept 2026 to start from.")).toBeVisible();
});

test("T29 start from last week’s form, when the week before holds only values never confirmed: the button is off, as the API would refuse", async ({ page, request }) => {
  writeUnconfirmed("2026-10-16", { placements: "9.5" });
  try {
    const refused = await request.post(`${API}/api/inputs/weekly/2026-10-23/analyst/carry?section=fixed_income`);
    expect(refused.status()).toBe(409);
    expect((await refused.json()).detail).toContain("No analyst inputs are saved for the week ending 2026-10-16");
    await openStart(page, "Fixed Income", "Week ending 2026-10-23");
    const panel = analystPanel(page);
    await expect(panel.getByRole("button", { name: "Start from last week’s form" })).toBeDisabled();
    await expect(panel.getByText("Nothing confirmed is saved for the week ending 16 Oct 2026 to start from.")).toBeVisible();
  } finally {
    dropForm("2026-10-16");
  }
});

test("T30 a carried weekly table waits for its own Confirm; carrying again says there is nothing left to carry", async ({ page, request }) => {
  await putTable(request, WEEK, "fixed_income", "mmf", "1 Alpha Fund 11.9\n2 Beta Fund 11.5\n3 Gamma Fund 11.1\n4 Delta Fund 10.8\n5 Epsilon Fund 10.2");
  try {
    await openStart(page, "Fixed Income", "Week ending 2026-10-16");
    const panel = analystPanel(page);
    const draft = page.getByRole("button", { name: "Draft the Week ending 2026-10-16 section" });
    const mmf = panel.locator("div.space-y-2", { has: page.locator("#analyst-mmf") }).first();
    await panel.getByRole("button", { name: "Start from last week’s form" }).click();
    await expect(mmf.getByText("Carried from week ending 9 Oct 2026, 5 rows, not confirmed", { exact: true })).toBeVisible();
    await expect(panel.getByRole("status").filter({ hasText: "needs confirming before a draft:" })).toContainText("Money market fund table");
    await expect(draft).toBeDisabled();
    await panel.getByRole("button", { name: /^Confirm for this week\s*: Money market fund table$/ }).click();
    await expect(mmf.getByText("Carried from week ending 9 Oct 2026, 5 rows", { exact: true })).toBeVisible();
    await expect(panel.getByText(/needs? confirming before a draft/)).toHaveCount(0);
    await expect(draft).toBeEnabled();

    // Everything last week held is now held here: a second carry is refused, in the API's words, under the button.
    await panel.getByRole("button", { name: "Start from last week’s form" }).click();
    await expect(panel.getByRole("alert")).toContainText("Nothing to carry from the week ending 2026-10-09: every item it holds is already typed for this week");
  } finally {
    await putTable(request, WEEK, "fixed_income", "mmf", null);
    dropForm("2026-10-16");
  }
});

test("T31 suggest a running total with no total saved the week before: the reason and what to do, under the button", async ({ page }) => {
  await openStart(page, "Equities");
  const panel = analystPanel(page);
  await expect(panel).not.toContainText("none is suggested or filled in"); // the panel no longer says nothing is ever suggested
  await suggestButton(page, "Year-to-date equities turnover").click();
  const why = panel.locator("#analyst-turnover_ytd-error");
  await expect(why).toHaveAttribute("role", "alert");
  await expect(why).toContainText("Year-to-date equities turnover: no total is saved for the week ending 2026-10-02 to add this week's figure to.");
  await expect(why).toContainText("Type this week's total yourself");
  await expect(panel.locator("#analyst-turnover_ytd")).toHaveAttribute("aria-describedby", /analyst-turnover_ytd-error/);
  await expect(panel.getByRole("alert")).toHaveCount(1); // only there, not again at the top of the panel
  await expect(panel.locator("#analyst-turnover_ytd")).toHaveValue(""); // nothing was filled in
  // Typing the total instead clears the refusal.
  await panel.locator("#analyst-turnover_ytd").fill("650.25");
  await panel.locator("#analyst-turnover_ytd").press("Enter");
  await expect(panel.getByText(/^Typed/).first()).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await panel.locator("#analyst-turnover_ytd").fill("");
  await panel.locator("#analyst-turnover_ytd").press("Enter");
  await expect(suggestButton(page, "Year-to-date equities turnover")).toBeVisible();
});

test("T32 suggest the foreign position with a total saved the week before: a suggestion with its working, then confirmed", async ({ page, request }) => {
  await putAnalyst(request, "2026-10-02", "equities", { foreign_ytd: "-150.5" });
  try {
    await openStart(page, "Equities");
    const panel = analystPanel(page);
    await suggestButton(page, "Year-to-date foreign net position").click();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(panel.locator("#analyst-foreign_ytd")).toHaveValue(/^-?\d+\.\d{4}$/);
    await expect(panel.getByText(/^Suggested: -150\.5000 saved for the week ending 2026-10-02 \+ /)).toBeVisible();
    await expect(panel.getByRole("status").filter({ hasText: "1 value needs confirming before a draft:" })).toContainText("Year-to-date foreign net position.");
    await panel.getByRole("button", { name: /^Confirm for this week\s*: Year-to-date foreign net position$/ }).click();
    await expect(panel.getByText(/needs? confirming before a draft/)).toHaveCount(0);
  } finally {
    await putAnalyst(request, WEEK, "equities", { foreign_ytd: null });
    await putAnalyst(request, "2026-10-02", "equities", { foreign_ytd: null });
  }
});

test("T33 suggest a running total when the week before holds one never confirmed: says so, and fills nothing in", async ({ page }) => {
  writeUnconfirmed("2026-10-02", { turnover_ytd: "600.5" });
  try {
    await openStart(page, "Equities");
    const panel = analystPanel(page);
    await suggestButton(page, "Year-to-date equities turnover").click();
    const why = panel.locator("#analyst-turnover_ytd-error");
    await expect(why).toContainText("no total is saved for the week ending 2026-10-02");
    await expect(why).toContainText("never confirmed");
    await expect(panel.locator("#analyst-turnover_ytd")).toHaveValue("");
  } finally {
    dropForm("2026-10-02");
  }
});

test("T34 Show this week switches the week; Fetch from CBK for a week CBK has not published says so", async ({ page }) => {
  await openStart(page, "Fixed Income");
  const panel = inputsPanel(page);
  await panel.getByLabel("Week ending (a Friday)").fill("2026-10-16");
  await panel.getByRole("button", { name: "Show this week" }).click();
  await expect(page).toHaveURL(/period=Week(%20|\+)ending(%20|\+)2026-10-16/);
  const next = inputsPanel(page);
  await expect(next.getByText("Week ending 16 Oct 2026: Monday 12 Oct 2026 to Friday.")).toBeVisible();
  const bulletin = next.locator("li", { hasText: "CBK Weekly Bulletin" }).first();
  await bulletin.getByRole("button", { name: "Fetch from CBK" }).click();
  await expect(next.getByRole("alert")).toContainText("E2E: no bulletin is saved for 2026-10-16. Upload the bulletin once CBK has published it.");
  await expect(bulletin).toContainText("Not received");
});

test("T35 Replace an uploaded report with a file; the slot keeps it as this week’s", async ({ page }) => {
  await openStart(page, "Equities");
  const panel = inputsPanel(page);
  const weekly = panel.locator("li", { hasText: "KCB IB weekly trading report" }).first();
  await expect(weekly.getByRole("button", { name: /^Replace/ })).toBeVisible();
  await weekly.locator('input[type="file"]').setInputFiles(join(REPO, "backend", "data", "demo", "inputs", "SYNTHETIC_KCB_weekly_2026-10-09.pdf"));
  await expect(weekly).toContainText("Received, this week’s");
  await expect(weekly).toContainText("SYNTHETIC_KCB_weekly_2026-10-09.pdf");
  await expect(panel.getByRole("alert")).toHaveCount(0);
});

test("T36 Universe of Coverage grid: add a company, remove it unsaved, add and save one, clear the typed values", async ({ page }) => {
  await openStart(page, "Equities");
  const panel = analystPanel(page);
  const grid = panel.locator("div.space-y-2", { has: page.getByRole("heading", { name: "Universe of Coverage", exact: true }) }).first();
  await expect(grid.getByRole("row", { name: /^Family Bank/ })).toBeVisible(); // the workbook's rows are listed
  const rowsBefore = await grid.locator("tbody tr").count();
  await grid.getByRole("button", { name: "Add company" }).click();
  await expect(grid.locator("tbody tr")).toHaveCount(rowsBefore + 1);
  await grid.getByRole("button", { name: "Remove new company" }).click();
  await expect(grid.locator("tbody tr")).toHaveCount(rowsBefore);
  await expect(grid.getByText("Not saved yet.")).toHaveCount(0);

  await grid.getByRole("button", { name: "Add company" }).click();
  await grid.getByLabel("Universe of Coverage: Company").last().fill("Zeta Bank");
  for (const [column, value] of [["Price, last Friday", "40"], ["Price, this Friday", "41"], ["Price, previous month end", "39"], ["Year open", "30"], ["Target price", "55"]]) {
    await grid.getByLabel(new RegExp(`^Zeta Bank: ${column}`)).fill(value);
  }
  await expect(grid.getByText("Not saved yet.")).toBeVisible();
  await grid.getByRole("button", { name: "Save", exact: true }).click();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(grid.getByText(/^Typed/).first()).toBeVisible();
  await expect(grid.getByText("Not saved yet.")).toHaveCount(0);
  await grid.getByRole("button", { name: "Clear typed values" }).click();
  await expect(grid.getByRole("button", { name: "Clear typed values" })).toHaveCount(0);
  await expect(grid.locator("tbody tr")).toHaveCount(rowsBefore);
});
