import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, card, draftAndApprove, hold, overviewUrl, release, startRun } from "./helpers";

/**
 * "Draft again": a section that already has a review (in review, approved or rejected) can be drafted over from its
 * overview card, after a confirmation. Digital Payments is used throughout: the test instance drafts it from fixed rows,
 * with no network. This file has its own run on a freshly restored test backend (`playwright test draftagain`), and each
 * test uses its own week, so none sees another's runs.
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });
test.afterEach(() => void release());

const json = { "Content-Type": "application/json" };
const HEADING = { name: "Digital Payments: analyst review", level: 1 } as const;
const UNRESOLVED = /\d+ unresolved · 0 of \d+ resolved/;

/** Digital Payments drafted through the API for that week; the run's id. */
async function draftPayments(request: APIRequestContext, period: string): Promise<number> {
  const res = await request.post(`${API}/api/sections/digital_payments/draft`, { headers: json, data: { report_type: "weekly", period }, timeout: 120_000 });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).run_id;
}

/** The section's newest run of that week, as the overview reads it. */
async function latest(request: APIRequestContext, period: string, slug: string): Promise<{ run_id: number; decision: string | null }> {
  const res = await request.get(`${API}/api/sections?report_type=weekly&period=${encodeURIComponent(period)}`);
  expect(res.ok()).toBe(true);
  return (await res.json()).sections.find((s: { slug: string }) => s.slug === slug).latest;
}

/** From the overview card's "Draft again" to a started draft: the start screen, the draft button, the confirmation. */
async function draftAgain(page: Page, period: string) {
  await page.goto(overviewUrl(period));
  await card(page, "Digital Payments").getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await page.getByRole("button", { name: `Draft the ${period} section` }).click();
  return page.getByRole("dialog", { name: "Draft Digital Payments again?" });
}

test("T42 an approved section: Draft again asks first, the new run is undecided and current, the old one stays approved", async ({ page, request }) => {
  const period = "Week ending 2026-11-06";
  await draftAndApprove(request, "digital_payments", period, "weekly");
  const old = (await latest(request, period, "digital_payments")).run_id;

  await page.goto(overviewUrl(period));
  const payments = card(page, "Digital Payments");
  await expect(payments).toContainText("Approved");
  await expect(payments.getByRole("button", { name: "View review" })).toBeVisible();
  await expect(payments.getByRole("button", { name: "Draft again" })).toBeEnabled();

  const dialog = await draftAgain(page, period);
  await expect(page.getByText(/review \(run \d+\) was approved/)).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${old}, approved) stays saved and read-only.`);
  await expect(dialog).toContainText("The new draft becomes the current one and starts undecided.");
  await expect(dialog).toContainText("This section is approved now. The weekly export needs it approved again.");

  // Cancelling drafts nothing.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect((await latest(request, period, "digital_payments")).run_id).toBe(old);

  await page.getByRole("button", { name: `Draft the ${period} section` }).click();
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  const fresh = await latest(request, period, "digital_payments");
  expect(fresh.run_id).toBeGreaterThan(old);
  expect(fresh.decision).toBeNull();

  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await expect(page.getByText(UNRESOLVED)).toBeVisible();

  // The earlier run is untouched: still approved, still locked, still readable.
  const earlier = await (await request.get(`${API}/api/reviews/${old}`)).json();
  expect([earlier.decision, earlier.locked]).toEqual(["approved", true]);
  await page.goto(`${overviewUrl(period)}&review=${old}`);
  await expect(page.getByText("Approved and locked")).toBeVisible();
});

test("T43 a rejected section: Draft again shows the notes of the rejected draft on the new review", async ({ page, request }) => {
  const period = "Week ending 2026-11-13";
  const first = await draftPayments(request, period);
  await page.goto(`${overviewUrl(period)}&review=${first}`);
  await expect(page.getByRole("heading", HEADING)).toBeVisible();
  await page.getByRole("radio", { name: "Fix needed" }).first().click();
  const note = page.getByLabel(/^Note for /).first();
  await note.fill("SYNTHETIC e2e: the hospitality line is missing.");
  await note.press("Enter");
  await expect(page.getByText("Saved as run")).toBeVisible();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog", { name: "Reject this section?" }).getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Rejected and locked")).toBeVisible();
  await page.getByRole("button", { name: "Back to all sections" }).last().click();
  await expect(card(page, "Digital Payments")).toContainText("Rejected");

  const dialog = await draftAgain(page, period);
  await expect(page.getByText(/review \(run \d+\) was rejected/)).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${first}, rejected) stays saved and read-only.`);
  await expect(dialog).not.toContainText("needs it approved again"); // nothing was approved
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();

  const panel = page.getByRole("region", { name: `Notes from the rejected draft (run ${first})` });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("SYNTHETIC e2e: the hospitality line is missing.");
  await expect(page.getByText(UNRESOLVED)).toBeVisible(); // nothing was copied onto the new items
});

test("T44 a section in review: Draft again leaves the unfinished review as it is and makes the new draft current", async ({ page, request }) => {
  const period = "Week ending 2026-11-20";
  const old = await draftPayments(request, period);

  await page.goto(overviewUrl(period));
  const payments = card(page, "Digital Payments");
  await expect(payments.getByRole("button", { name: "Resume review" })).toBeVisible();
  const dialog = await draftAgain(page, period);
  await expect(page.getByText(new RegExp(`review is in progress \\(run ${old}`))).toBeVisible();
  await expect(dialog).toContainText(`The earlier review (run ${old}) was still in review. It stays saved as it is, undecided`);
  await expect(dialog).not.toContainText("needs it approved again");
  await dialog.getByRole("button", { name: "Draft again" }).click();
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible();

  const fresh = await latest(request, period, "digital_payments");
  expect(fresh.run_id).toBeGreaterThan(old);
  const earlier = await (await request.get(`${API}/api/reviews/${old}`)).json();
  expect([earlier.decision, earlier.locked]).toEqual([null, false]);
  await page.goto(overviewUrl(period));
  await expect(card(page, "Digital Payments")).toContainText(`Run ${fresh.run_id}`);
});

test("T45 Draft again is off, with the reason, only while that section is itself drafting; another section drafting does not turn it off", async ({ page, request }) => {
  const period = "Week ending 2026-11-27";
  await draftPayments(request, period);

  hold();
  const running = await startRun(request, "real_estate", period);
  await page.goto(overviewUrl(period));
  const payments = card(page, "Digital Payments");
  await expect(payments.getByRole("button", { name: "Resume review" })).toBeEnabled();
  // Real Estate is drafting; Digital Payments is a different section, so its button stays on.
  await expect(payments.getByRole("button", { name: "Draft again" })).toBeEnabled();
  await expect(payments).not.toContainText("Being drafted now");

  // The section that is drafting has its own button off, with the reason.
  const own = card(page, "Real Estate").getByRole("button", { name: "Draft again" });
  if (await own.count()) {
    await expect(own).toBeDisabled();
    await expect(own).toHaveAccessibleDescription(/Being drafted now/);
  }

  release();
  await expect.poll(async () => (await (await request.get(`${API}/api/runs/${running}`)).json()).status).not.toBe("running");
});

test("T46 a section never drafted for the week still shows only Draft section, and no Draft again anywhere", async ({ page }) => {
  await page.goto(overviewUrl("Week ending 2026-12-04"));
  await expect(card(page, "Fixed Income")).toBeVisible();
  await expect(page.getByRole("button", { name: "Draft again" })).toHaveCount(0);
  for (const title of ["Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"]) {
    await expect(card(page, title).getByRole("button")).toHaveText(["Draft section"]);
  }
});
