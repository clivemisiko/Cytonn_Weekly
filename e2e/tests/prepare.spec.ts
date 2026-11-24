import { expect, test, type Page, type Route } from "@playwright/test";
import { SHOW_CHAT } from "../../frontend/src/lib/features";
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
  // `sources`: whether the section has a sources step with a search engine. Real Estate has none: it is written from
  // the snips the analyst uploads, and the API refuses a source for it (the old start screen leaves it out too).
  { slug: "fixed_income", title: "Fixed Income", friday: "2027-03-05", sources: true },
  { slug: "equities", title: "Equities", friday: "2027-03-12", sources: true },
  { slug: "real_estate", title: "Real Estate", friday: "2027-03-19", sources: false },
  { slug: "digital_payments", title: "Digital Payments", friday: "2027-03-26", sources: true },
  { slug: "focus", title: "Focus of the Week", friday: "2027-04-02", sources: true },
];

/** The links rule: no link to an old form, the overview or previous reports; a link to a /sources/{id} record only, opening
 *  in a new tab with rel noopener; anything else stays inside the chat. */
async function linksFollowTheRule(where: ReturnType<Page["locator"]>) {
  const links = await where.locator("a[href]").evaluateAll((as) => as.map((a) => ({ href: a.getAttribute("href") ?? "", target: a.getAttribute("target"), rel: a.getAttribute("rel") ?? "" })));
  for (const l of links) {
    expect(l.href, l.href).not.toMatch(/^\/(overview|previous)/);
    if (l.href.startsWith("/sources")) {
      expect(l.href, l.href).toMatch(/^\/sources\/[^/?]+(\?|$)/);
      expect([l.target, l.rel.includes("noopener")], l.href).toEqual(["_blank", true]);
    } else if (l.href.startsWith("/")) expect(l.href, l.href).toMatch(/^\/chat\?/);
  }
  return links;
}

/** Stand in for the API's config as Bedrock, so the sources step shows; the backend itself stays in dev mode. */
async function asBedrock(page: Page) {
  await page.route("**/api/config", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), provider: "bedrock", provider_valid: true, dev_mode: false, provider_problem: null } });
  });
}

for (const s of SECTIONS) {
  test(`T140 ${s.title}: the same page as every section, three numbered cards, and links only to /sources/{id} records in a new tab, never to an old form, the overview or previous reports`, async ({ page }) => {
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
    await linksFollowTheRule(p);
    await expect(page.getByRole("log", { name: "Conversation" })).toHaveCount(0);
    expect(opened).toEqual([]); // the page opened no conversation
  });

  test(`T141 ${s.title}: with a search engine, ${s.sources ? "sources are the last step, and the address can open on them" : "there is no sources step, because the section is written from snips and takes no source"}`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await asBedrock(page);
    await page.goto(url(s.slug, s.friday, "&step=sources"));
    if (!s.sources) {
      await expect(inputs(page).getByText(/^Step 1 of \d+$/)).toBeVisible();
      await expect(inputs(page).getByRole("heading", { name: "Sources", level: 2 })).toHaveCount(0);
      return;
    }
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
  await expect(card.getByText("Step 1 of 6", { exact: true })).toBeVisible();
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
  // Off but focusable, so a keyboard user meets it and hears why; pressing it starts nothing.
  await expect(create).toHaveAttribute("aria-disabled", "true");
  await expect(create).not.toHaveAttribute("disabled");
  await expect(create).toHaveAttribute("aria-describedby", "prepare-draft-caption");
  await expect(p.locator("[data-caption]")).toHaveText("Still needed: the topic");
  let runs = 0;
  page.on("request", (r) => r.method() === "POST" && r.url().includes("/api/runs") && runs++);
  await create.focus();
  await expect(create).toBeFocused();
  await page.keyboard.press("Enter");
  await create.click({ force: true });
  expect(runs).toBe(0);
  await expect(banner(page)).toHaveText(/^1 required item missing/);

  await card.getByLabel("This week’s topic").fill("A fake topic about invented bonds");
  await expect(create).not.toHaveAttribute("aria-disabled");
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
  await expect(ask.or(page.getByRole("region", { name: "What you can do now" }))).toBeVisible();
  if (await ask.isVisible()) await ask.getByRole("button", { name: "Draft anyway" }).click();
  await expect(page).toHaveURL(/view=conversation/);
  await expect(page.locator('[data-card="live"]')).toBeVisible(); // the draft's own cards, never a page with only a back link
  await expect(prepare(page)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "What you can do now" }).getByRole("region", { name: /^Review of Equities/ })).toBeVisible({ timeout: 180_000 });

  if (!SHOW_CHAT) {
    // The chat hidden, a drafted section still opens on its prepare page, and the draft is one link away.
    await page.goto(url("equities", period));
    await expect(prepare(page).locator("[data-pill]")).toHaveText("In review");
    await prepare(page).getByRole("link", { name: "Open the draft" }).click();
    await expect(page.getByRole("region", { name: "What you can do now" }).getByRole("region", { name: /^Review of Equities/ })).toBeVisible();
    await page.getByRole("link", { name: "Back to sources and inputs" }).first().click();
    await expect(prepare(page).locator("[data-pill]")).toHaveText("In review");
    return;
  }
  await page.goto(url("equities", period)); // no flag: the section has a draft, so the conversation view
  await expect(page.getByRole("region", { name: "What you can do now" })).toBeVisible();
  await expect(page.getByRole("log", { name: "Conversation" })).toHaveCount(SHOW_CHAT ? 1 : 0);
  await expect(prepare(page)).toHaveCount(0);
  await page.getByRole("link", { name: "Back to sources and inputs" }).first().click();
  await expect(prepare(page).locator("[data-pill]")).toHaveText("In review");
});

test("T149 the prepare page offers the conversation when one already holds more than its snapshot, and only then", async ({ page }) => {
  test.skip(!SHOW_CHAT, "the chat is hidden");
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

test("T150 a saved source is a link to its /sources/{id} record in a new tab, on the prepare page and in the conversation view; nothing else leaves the chat", async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const period = "Week ending 2027-06-04";
  const titles = "Fake section one";
  const q = new URLSearchParams({ report_type: "weekly", period, section: "focus", sections: titles });
  const listing = await (await request.get(`${API}/api/sources?${q}`)).json();
  const subject = listing.pieces[0].subject as string;
  const added = await request.post(`${API}/api/sources`, {
    data: { section: "focus", subject, report_type: "weekly", period, sections: titles, url: "https://example.com/fake-record", date: "2027-06-02", title: "A fake record", text: "An invented sentence for the test, about nothing real." },
  });
  expect(added.ok(), await added.text()).toBeTruthy();

  // The titles the page keeps for the visit name the piece the source was saved under.
  await page.addInitScript(([key, value]) => sessionStorage.setItem(key, value), [`cw-focus:${period}:focus`, JSON.stringify({ topic: "A fake topic", titles })]);
  await asBedrock(page);
  await page.goto(url("focus", "2027-06-04", "&step=sources"));
  await expect(inputs(page).locator('a[href^="/sources/"]').first()).toBeVisible();
  const onPrepare = await linksFollowTheRule(prepare(page));
  expect(onPrepare.some((l) => l.href.startsWith("/sources/"))).toBe(true); // the rule was checked against a real record link

  await page.goto(url("focus", "2027-06-04", "&view=conversation"));
  if (!SHOW_CHAT) {
    // No draft, so nothing for the conversation view to show: the address is turned into the prepare page.
    await expect(page).toHaveURL(/view=prepare/);
    await expect(prepare(page)).toBeVisible();
    return;
  }
  await expect(page.getByRole("region", { name: "What you can do now" })).toBeVisible();
  await expect(page.getByRole("region", { name: "What you can do now" }).getByText(/^1 saved/)).toBeVisible();
  await linksFollowTheRule(page.getByRole("main"));
});

test("T151 with the chat hidden, the section list opens a section on its prepare page, with no message box and no way into the conversation", async ({ page }) => {
  test.skip(SHOW_CHAT, "the chat is shown");
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(`/chat?period=${encodeURIComponent("Week ending 2027-07-02")}`);
  await page.getByRole("button", { name: "Equities", exact: true }).click();
  await expect(page).toHaveURL(/section=equities/);
  await expect(prepare(page)).toBeVisible();
  await expect(inputs(page)).toBeVisible();
  await expect(prepare(page).getByRole("button", { name: /Create draft/ })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open the conversation" })).toHaveCount(0);
  await expect(page.getByRole("log", { name: "Conversation" })).toHaveCount(0);
});

for (const s of SECTIONS) {
  test(`T152 ${s.title}: with the chat hidden, the section list opens it on its prepare page with no click needed`, async ({ page }) => {
    test.skip(SHOW_CHAT, "the chat is shown");
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto(`/chat?period=${encodeURIComponent("Week ending 2027-08-06")}`); // opening a section saves nothing
    await page.getByRole("button", { name: s.title, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`section=${s.slug}`));
    await expect(page).not.toHaveURL(/view=conversation/);
    await expect(prepare(page)).toBeVisible();
    await expect(prepare(page).getByRole("button", { name: /Create draft/ })).toBeVisible();
  });
}

for (const s of SECTIONS) {
  test(`T153 ${s.title}: a failed read shows a notice with Try again beside that part only, and Try again repeats only that read`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    const calls: Record<string, number> = { readiness: 0, analyst: 0 };
    const failOnce = (name: string) => async (route: Route) => {
      calls[name] += 1;
      if (calls[name] === 1) await route.fulfill({ status: 503, json: { detail: `Fake ${name} failure.` } });
      else await route.fallback();
    };
    await page.route(/\/api\/sections\/[^/]+\/readiness/, failOnce("readiness"));
    await page.route(/\/api\/inputs\/weekly\/[^/]+\/analyst\?/, failOnce("analyst"));
    await page.goto(url(s.slug, s.friday));

    const readinessProblem = prepare(page).locator('[data-part-problem="readiness"]');
    await expect(readinessProblem).toContainText("Fake readiness failure.");
    await readinessProblem.getByRole("button", { name: "Try again" }).click();
    await expect(banner(page)).toBeVisible();
    await expect(readinessProblem).toHaveCount(0);

    const formProblem = prepare(page).locator('[data-part-problem="form"]');
    if (calls.analyst === 0) {
      await expect(inputs(page)).toBeVisible(); // no form for this section: nothing else to fail
      expect(calls).toEqual({ readiness: 2, analyst: 0 });
      return;
    }
    await expect(formProblem).toContainText("Fake analyst failure.");
    await expect(prepare(page).locator('[data-card="prepare_sources"]')).toBeVisible(); // what loaded stays
    await expect(banner(page)).toBeVisible();
    await formProblem.getByRole("button", { name: "Try again" }).click();
    await expect(inputs(page)).toBeVisible();
    await expect(formProblem).toHaveCount(0);
    expect(calls).toEqual({ readiness: 2, analyst: 2 });
  });
}
