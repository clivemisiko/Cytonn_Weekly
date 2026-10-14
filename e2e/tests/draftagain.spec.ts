import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, card, draftAndApprove, hold, overviewUrl, release, startRun } from "./helpers";

/**
 * "Draft again": a section that already has a review (in review, approved or rejected) can be drafted over from its
 * overview card, after a confirmation. Company Updates is used where a provider is not needed (the test instance drafts it
 * with no model, as T23 and T37 do); the disabled button needs a section that calls the provider, so that one uses Digital
 * Payments. This file has its own run on a freshly restored test backend (`playwright test draftagain`), and each test uses
 * its own week, so none sees another's runs.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const json = { "Content-Type": "application/json" };
const HEADING = { name: "Company Updates: coordinator review", level: 1 } as const;

/** Company Updates drafted through the API for that week; the run's id. */
async function draftCompanyUpdates(request: APIRequestContext, period: string, text: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/company_updates/draft`, { headers: json, data: { report_type: "weekly", period, text } });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

/** The section's newest run of that week, as the overview reads it. */
async function latest(request: APIRequestContext, period: string, slug: string): Promise<{ run_id: number; decision: string | null }> {
  const res = await request.get(`${API}/api/sections?report_type=weekly&period=${encodeURIComponent(period)}`);
  expect(res.ok()).toBe(true);
  return (await res.json()).sections.find((s: { slug: string }) => s.slug === slug).latest;
}

/** From the overview card's "Draft again" to a drafted Company Updates: the text, the confirmation, the run view. */
async function draftAgain(page: Page, period: string, text: string) {
  await page.goto(overviewUrl(period));
  await card(page, "Company Updates").getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await page.getByLabel("Your Company Updates text").fill(text);
  await page.getByRole("button", { name: "Save your text as the section" }).click();
  return page.getByRole("dialog", { name: "Draft Company Updates again?" });
}

test("T42 an approved section: Draft again asks first, the new run is undecided and current, the old one stays approved", async ({ page, request }) => {
  const period = "Week ending 2026-11-06";
  await draftAndApprove(request, "company_updates", period, "weekly", "Investment Updates:\nSYNTHETIC e2e text, approved.");
  const old = (await latest(request, period, "company_updates")).run_id;

  await page.goto(overviewUrl(period));
  const cu = card(page, "Company Updates");
  await expect(cu).toContainText("Approved");
  await expect(cu.getByRole("button", { name: "View review" })).toBeVisible();
  await expect(cu.getByRole("button", { name: "Draft again" })).toBeEnabled();

  const dialog = await draftAgain(page, period, "Investment Updates:\nSYNTHETIC e2e text, drafted again.");
  await expect(page.getByText(/review \(run \d+\) was approved/)).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${old}, approved) stays saved and read-only.`);
  await expect(dialog).toContainText("The new draft becomes the current one and starts undecided.");
  await expect(dialog).toContainText("This section is approved now. The weekly export needs it approved again.");

  // Cancelling drafts nothing.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect((await latest(request, period, "company_updates")).run_id).toBe(old);

  await page.getByRole("button", { name: "Save your text as the section" }).click();
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  const fresh = await latest(request, period, "company_updates");
  expect(fresh.run_id).toBeGreaterThan(old);
  expect(fresh.decision).toBeNull();

  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible();

  // The earlier run is untouched: still approved, still locked, still readable.
  const earlier = await (await request.get(`${API}/api/reviews/${old}`)).json();
  expect([earlier.decision, earlier.locked]).toEqual(["approved", true]);
  await page.goto(`${overviewUrl(period)}&review=${old}`);
  await expect(page.getByText("Approved and locked")).toBeVisible();
});

test("T43 a rejected section: Draft again shows the notes of the rejected draft on the new review", async ({ page, request }) => {
  const period = "Week ending 2026-11-13";
  const first = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, first draft.");
  await page.goto(`${overviewUrl(period)}&review=${first}`);
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await page.getByRole("radio", { name: "Fix needed" }).click();
  const note = page.getByLabel(/^Note for /);
  await note.fill("SYNTHETIC e2e: the hospitality line is missing.");
  await note.press("Enter");
  await expect(page.getByText("Saved as run")).toBeVisible();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog", { name: "Reject this section?" }).getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Rejected and locked")).toBeVisible();
  await page.getByRole("button", { name: "Back to all sections" }).last().click();
  await expect(card(page, "Company Updates")).toContainText("Rejected");

  const dialog = await draftAgain(page, period, "Investment Updates:\nSYNTHETIC e2e text, second draft.");
  await expect(page.getByText(/review \(run \d+\) was rejected/)).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${first}, rejected) stays saved and read-only.`);
  await expect(dialog).not.toContainText("needs it approved again"); // nothing was approved
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();

  const panel = page.getByRole("region", { name: `Notes from the rejected draft (run ${first})` });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("SYNTHETIC e2e: the hospitality line is missing.");
  await expect(page.getByText("1 unresolved · 0 of 1 resolved")).toBeVisible(); // nothing was copied onto the new item
});

test("T44 a section in review: Draft again leaves the unfinished review as it is and makes the new draft current", async ({ page, request }) => {
  const period = "Week ending 2026-11-20";
  const old = await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text, left in review.");

  await page.goto(overviewUrl(period));
  const cu = card(page, "Company Updates");
  await expect(cu.getByRole("button", { name: "Resume review" })).toBeVisible();
  const dialog = await draftAgain(page, period, "Investment Updates:\nSYNTHETIC e2e text, drafted again.");
  await expect(page.getByText(new RegExp(`review is in progress \\(run ${old}`))).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${old}) was still in review. It stays saved as it is, undecided`);
  await expect(dialog).not.toContainText("needs it approved again");
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();

  const fresh = await latest(request, period, "company_updates");
  expect(fresh.run_id).toBeGreaterThan(old);
  const earlier = await (await request.get(`${API}/api/reviews/${old}`)).json();
  expect([earlier.decision, earlier.locked]).toEqual([null, false]);
  await page.goto(overviewUrl(period));
  await expect(card(page, "Company Updates")).toContainText(`Run ${fresh.run_id}`);
});

test("T45 Draft again is off, with the reason, while another draft holds the one draft slot", async ({ page, request }) => {
  const period = "Week ending 2026-11-27";
  await draftCompanyUpdates(request, period, "Investment Updates:\nSYNTHETIC e2e text.");
  const dp = await request.post(`${API}/api/sections/digital_payments/draft`, { headers: json, data: { report_type: "weekly", period }, timeout: 120_000 });
  expect(dp.status(), await dp.text()).toBe(200);

  hold();
  const running = await startRun(request, "real_estate", period);
  await page.goto(overviewUrl(period));
  const payments = card(page, "Digital Payments");
  await expect(payments.getByRole("button", { name: "Resume review" })).toBeEnabled();
  const again = payments.getByRole("button", { name: "Draft again" });
  await expect(again).toBeDisabled();
  await expect(payments).toContainText(`Real Estate (${period}) is drafting now. Only one draft runs at a time, across every section.`);
  await expect(again).toHaveAccessibleDescription(/is drafting now/);
  // A section that calls no provider takes no slot, so it is not held up.
  await expect(card(page, "Company Updates").getByRole("button", { name: "Draft again" })).toBeEnabled();

  // Once the run ends the slot is free and the button is on again.
  release();
  await expect.poll(async () => (await (await request.get(`${API}/api/runs/${running}`)).json()).status).not.toBe("running");
  await page.reload();
  await expect(card(page, "Digital Payments").getByRole("button", { name: "Draft again" })).toBeEnabled();
  await expect(card(page, "Digital Payments")).not.toContainText("is drafting now");
});

test("T46 a section never drafted for the week still shows only Draft section, and no Draft again anywhere", async ({ page }) => {
  await page.goto(overviewUrl("Week ending 2026-12-04"));
  await expect(card(page, "Company Updates")).toBeVisible();
  await expect(page.getByRole("button", { name: "Draft again" })).toHaveCount(0);
  const only = (title: string, name: string) => expect(card(page, title).getByRole("button")).toHaveText([name]);
  await only("Company Updates", "Add your text");
  for (const title of ["Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"]) await only(title, "Draft section");
});
