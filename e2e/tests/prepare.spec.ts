import { expect, test, type Page } from "@playwright/test";
import { API } from "./helpers";

// The prepare page, which every section shows while it has no draft. Every figure here is invented, and each test takes
// its own Friday so a save in one never shows in another. The test backend is in dev mode: the sources step appears only
// where the API is stood in for as Bedrock.
const url = (section: string, friday: string, extra = "") => `/chat?section=${section}&period=${encodeURIComponent(`Week ending ${friday}`)}${extra}`;
const prepare = (page: Page) => page.locator('[data-card="prepare"]');
const inputs = (page: Page) => page.getByRole("region", { name: /Report inputs$/ });
const banner = (page: Page) => prepare(page).locator("[data-banner]");
// A 1x1 PNG: an image the snip store takes, and nothing real.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");

const SECTIONS = [
  { slug: "fixed_income", title: "Fixed Income", friday: "2027-03-05" },
  { slug: "equities", title: "Equities", friday: "2027-03-12" },
  { slug: "real_estate", title: "Real Estate", friday: "2027-03-19" },
  { slug: "digital_payments", title: "Digital Payments", friday: "2027-03-26" },
  { slug: "focus", title: "Focus of the Week", friday: "2027-04-02" },
];

/** Stand in for the API's config as Bedrock, so the sources step shows; the backend itself stays in dev mode. */
async function asBedrock(page: Page) {
  await page.route("**/api/config", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), provider: "bedrock", provider_valid: true, dev_mode: false, provider_problem: null } });
  });
}

for (const s of SECTIONS) {
  test(`T140 ${s.title}: the same page as every section, three numbered cards and no way to an old page`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    const opened: string[] = [];
    page.on("request", (r) => r.method() === "POST" && r.url().endsWith("/api/jobs") && opened.push(r.url()));
    await page.goto(url(s.slug, s.friday));
    const p = prepare(page);
    await expect(p.getByRole("heading", { name: s.title, level: 2 })).toBeVisible();
    await expect(p.locator("[data-pill]")).toHaveText("Not drafted");
    await expect(p.getByText(`Week ending ${s.friday} · Prepare your sources and inputs, then create a draft.`)).toBeVisible();
    await expect(banner(page)).toHaveText(/^(\d+ required items? missing|Everything required is in place)/);
    await expect(banner(page)).toHaveAttribute("aria-live", "polite");
    await expect(p.getByRole("heading", { level: 3, name: /^\d/ })).toHaveText(["1Source documents", "2Report inputs", "3Create draft"]);
    await expect(p.getByRole("button", { name: /Create draft/ })).toBeVisible();
    await expect(p.locator("[data-caption]")).toHaveText(/still missing$|^Everything required is in place$|^Still needed: /);
    for (const href of await p.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) expect(href).not.toMatch(/^\/(overview|sources|previous)/);
    await expect(page.getByRole("log", { name: "Conversation" })).toHaveCount(0);
    expect(opened).toEqual([]); // the page opened no conversation
  });

  test(`T141 ${s.title}: with a search engine, sources are the last step, and the address can open on them`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await asBedrock(page);
    await page.goto(url(s.slug, s.friday, "&step=sources"));
    await expect(inputs(page).getByRole("heading", { name: "Sources", level: 2 })).toBeVisible();
    await expect(inputs(page).getByText(/^Step (\d+) of \1$/)).toBeVisible();
    await expect(inputs(page).getByRole("button", { name: "Done" })).toBeVisible();
  });
}

test("T142 Fixed Income: every input is a step; a saved value shows filled in and can be changed; the fund table is a step", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("fixed_income", "2027-04-09"));
  const card = inputs(page);
  await expect(card.getByText("Step 1 of 11", { exact: true })).toBeVisible();
  const before = await banner(page).textContent();
  await card.getByLabel("3-month bank placements").fill("4.44");
  await card.getByLabel("3-month bank placements").press("Enter");
  await expect(card.getByText("Step 2 of 11", { exact: true })).toBeVisible();
  await expect(card.getByLabel("Cytonn Money Market Fund yield, previous week")).toBeFocused(); // focus moved after the save
  await expect(banner(page)).not.toHaveText(before ?? "");

  await page.goto(url("fixed_income", "2027-04-09", "&step=placements")); // a saved value is shown, filled in, with its mark
  await expect(card.getByLabel("3-month bank placements")).toHaveValue("4.44");
  await expect(card.getByText("Saved: 4.44")).toBeVisible();
  await card.getByLabel("3-month bank placements").fill("5.55");
  await card.getByRole("button", { name: /^Save\s*: 3-month bank placements$/ }).click();
  await card.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(card.getByText("Saved: 5.55")).toBeVisible();

  for (const [step, what] of [["fund", "Money market fund table"], ["mmf_published", "Fund table published on"], ["mmf_source", "Fund table source label"]] as const) {
    await page.goto(url("fixed_income", "2027-04-09", `&step=${step}`));
    await expect(step === "fund" ? card.getByRole("region", { name: what }) : card.getByLabel(what)).toBeVisible();
  }
  await page.goto(url("fixed_income", "2027-04-09", "&step=mmf_published"));
  await expect(card.getByLabel("Fund table published on")).toHaveAttribute("type", "date");
  await card.getByLabel("Fund table published on").fill("2027-04-08");
  await card.getByRole("button", { name: /^Save\s*: Fund table published on$/ }).click();
  await expect(card.getByText("Step 11 of 11", { exact: true })).toBeVisible();
  await card.getByLabel("Fund table source label").fill("Fake Paper");
  await card.getByRole("button", { name: /^Save\s*: Fund table source label$/ }).click();
  await page.goto(url("fixed_income", "2027-04-09", "&step=mmf_source"));
  await expect(card.getByText("Saved: Fake Paper")).toBeVisible();
});

test("T143 Fixed Income: a carried value is a step with a Confirm button that names it, and confirming clears it", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const put = await request.put(`${API}/api/inputs/weekly/2027-04-16/analyst?section=fixed_income`, { data: { fields: { placements: "7.77" } } });
  expect(put.ok()).toBeTruthy();
  expect((await request.post(`${API}/api/inputs/weekly/2027-04-23/analyst/carry?section=fixed_income`)).ok()).toBeTruthy();
  await page.goto(url("fixed_income", "2027-04-23", "&step=placements"));
  const card = inputs(page);
  const confirm = card.getByRole("button", { name: /^Confirm 7\.77 for 3-month bank placements/ });
  await expect(confirm).toBeVisible();
  await expect(card.getByText(/Carried from last week, not yet confirmed: 7\.77/)).toBeVisible();
  await confirm.click();
  await page.goto(url("fixed_income", "2027-04-23", "&step=placements"));
  await expect(card.getByText("Saved: 7.77")).toBeVisible();
  await expect(card.getByRole("button", { name: /^Confirm 7\.77/ })).toHaveCount(0);
});

test("T144 Equities: the large-cap list is a names box, one per line; a saved figure can be changed", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("equities", "2027-04-30"));
  const card = inputs(page);
  const names = card.getByLabel("Large-cap list");
  await expect(card.getByText("Step 1 of", { exact: false })).toBeVisible();
  await expect(card.getByText("One per line.")).toBeVisible();
  await names.fill("Fake Bank\nFake Brewer");
  await card.getByRole("button", { name: /^Save\s*: Large-cap list$/ }).click();
  await expect(card.getByLabel("Year-to-date equities turnover")).toBeFocused();
  await card.getByLabel("Year-to-date equities turnover").fill("11.1");
  await card.getByLabel("Year-to-date equities turnover").press("Enter");

  await page.goto(url("equities", "2027-04-30", "&step=large_caps"));
  await expect(card.getByText("Saved: Fake Bank, Fake Brewer")).toBeVisible();
  await expect(card.getByLabel("Large-cap list")).toHaveValue("Fake Bank\nFake Brewer");
  await page.goto(url("equities", "2027-04-30", "&step=turnover_ytd"));
  await expect(card.getByLabel("Year-to-date equities turnover")).toHaveValue("11.1");
  await card.getByLabel("Year-to-date equities turnover").fill("22.2");
  await card.getByLabel("Year-to-date equities turnover").press("Enter");
  await card.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(card.getByText("Saved: 22.2")).toBeVisible();
});

test("T145 Digital Payments: the optional workbook is a card 1 row, and card 2 says there is nothing to type", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("digital_payments", "2027-05-07"));
  const p = prepare(page);
  await expect(p.getByRole("row", { name: /Digital Payments workbook/ })).toContainText("Optional, not uploaded");
  await expect(p.getByLabel("Upload Digital Payments workbook")).toBeAttached();
  await expect(inputs(page).getByText("Nothing to type for this section.")).toBeVisible();
  await expect(banner(page)).toHaveText(/^Everything required is in place/);
});

test("T146 Real Estate: each sector is a step; an uploaded snip counts until confirmed; its sector and date can be changed", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("real_estate", "2027-05-14"));
  const p = prepare(page);
  const card = inputs(page);
  await expect(p.getByText("Nothing to upload here. The snips are added in the next card.")).toBeVisible();
  await expect(card.getByText("Step 1 of 4", { exact: true })).toBeVisible();
  await expect(card.getByRole("heading", { name: "Industry reports", level: 3 })).toBeVisible();
  await expect(banner(page)).toHaveText(/^Everything required is in place/);

  await card.getByLabel("Add a snip or a PDF for Industry reports").setInputFiles({ name: "fake-snip.png", mimeType: "image/png", buffer: PNG });
  await expect(card.getByRole("list", { name: "Industry reports snips" })).toContainText("fake-snip.png");
  await expect(banner(page)).toHaveText(/^1 required item missing/); // uploaded, not confirmed

  const snip = card.getByRole("list", { name: "Industry reports snips" }).getByRole("listitem").first();
  await snip.getByLabel("Date of the page (optional)").fill("2027-05-12");
  await snip.getByLabel("Date of the page (optional)").blur();
  await expect(snip.getByLabel("Date of the page (optional)")).toHaveValue("2027-05-12");
  await snip.getByLabel("Sector").selectOption({ label: "Land" });
  await expect(card.getByRole("list", { name: "Industry reports snips" })).toHaveCount(0); // it moved
  await card.getByRole("button", { name: "Next" }).click();
  await card.getByRole("button", { name: "Next" }).click();
  await expect(card.getByRole("list", { name: "Land snips" })).toContainText("fake-snip.png");
  await page.reload();
  await expect(prepare(page).getByRole("button", { name: "View checklist" })).toBeVisible();
  await prepare(page).getByRole("button", { name: "View checklist" }).click();
  await expect(prepare(page).locator("#prepare-checklist")).toContainText("Land: 1 snip not confirmed");
});

test("T147 Focus of the Week: Create draft waits for the topic, the caption names it, a reload keeps it, and the draft carries it", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("focus", "2027-05-21"));
  const p = prepare(page);
  const card = inputs(page);
  const create = p.getByRole("button", { name: /Create draft/ });
  await expect(p.getByText("Nothing to upload here. The topic and section titles are typed in the next card.")).toBeVisible();
  await expect(create).toBeDisabled();
  await expect(p.locator("[data-caption]")).toHaveText("Still needed: the topic");
  await expect(banner(page)).toHaveText(/^1 required item missing/);

  await card.getByLabel("This week’s topic").fill("A fake topic about invented bonds");
  await expect(create).toBeEnabled();
  await expect(p.locator("[data-caption]")).toHaveText("Everything required is in place");
  await card.getByLabel("This week’s topic").press("Enter");
  await expect(card.getByLabel("Section titles")).toBeFocused();
  await expect(card.getByText("One per line.")).toBeVisible();
  await card.getByLabel("Section titles").fill("Fake one\nFake two");

  await page.reload(); // kept in session storage for the visit
  await expect(card.getByLabel("This week’s topic")).toHaveValue("A fake topic about invented bonds");
  await card.getByRole("button", { name: "Next" }).click();
  await expect(card.getByLabel("Section titles")).toHaveValue("Fake one\nFake two");

  const started = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/api/runs"));
  await create.click();
  const ask = page.getByRole("dialog", { name: "Draft this section?" });
  if (await ask.isVisible().catch(() => false)) await ask.getByRole("button", { name: "Draft anyway" }).click();
  const body = (await started).postDataJSON();
  expect([body.topic, body.sections]).toEqual(["A fake topic about invented bonds", "Fake one\nFake two"]);
  await expect(page).toHaveURL(/view=conversation/);
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0); // cleared once the draft started
});

test("T148 Create draft opens the conversation and starts the draft; a drafted section shows the conversation with a way back", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "2026-09-04"; // a demo Friday the test backend drafts Equities for with no outside source
  await page.goto(url("equities", period));
  await prepare(page).getByRole("button", { name: /Create draft/ }).click();
  const ask = page.getByRole("dialog", { name: "Draft this section?" });
  await expect(ask.or(page.getByRole("log", { name: "Conversation" }))).toBeVisible();
  if (await ask.isVisible()) await ask.getByRole("button", { name: "Draft anyway" }).click();
  await expect(page).toHaveURL(/view=conversation/);
  await expect(page.getByRole("region", { name: "What you can do now" }).getByRole("region", { name: /^Review of Equities/ })).toBeVisible({ timeout: 180_000 });

  await page.goto(url("equities", period)); // no flag: the section has a draft, so the conversation view
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
  await expect(prepare(page)).toHaveCount(0);
  await page.getByRole("link", { name: "Back to sources and inputs" }).first().click();
  await expect(prepare(page).locator("[data-pill]")).toHaveText("In review");
});

test("T149 the prepare page offers the conversation when one already holds more than its snapshot, and only then", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(url("equities", "2027-05-28"));
  await expect(inputs(page)).toBeVisible();
  await expect(prepare(page).getByRole("link", { name: "Open the conversation" })).toHaveCount(0);
  await page.route("**/api/sections/equities/readiness*", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), conversation: true } });
  });
  await page.reload();
  const link = prepare(page).getByRole("link", { name: "Open the conversation" });
  await expect(link).toHaveAttribute("href", /view=conversation/);
  await link.click();
  await expect(page.getByRole("log", { name: "Conversation" })).toBeVisible();
});
