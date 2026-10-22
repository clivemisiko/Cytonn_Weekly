import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import { API, REPO, VARIANT, startRun } from "./helpers";

/**
 * The chart card on the Equities review: the picture, its facts, "Show points", the choice to use the team's own chart, and what
 * each state says. Every figure is invented: the demo instance stores invented equities workbooks for four Fridays (e2e/chart_demo.py)
 * and drafts those weeks without any outside source. This file has its own run on a freshly restored test backend
 * (`playwright test chartcard`).
 *
 *   2026-09-25  complete workbook: both charts drawn      2026-09-11  workbook not yet updated: both stale, not drawn
 *   2026-09-18  rows left out of the P/E series           2026-09-04  no workbook: information only
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const DATA = process.env.E2E_DATA_DIR ?? join(REPO, "backend", "data", "demo-e2e", "data");
const CLEAN = "2026-09-25";
const DEFECTS = "2026-09-18";
const STALE = "2026-09-11";
const NONE = "2026-09-04";
const PE_CAPTION = "The charts below indicate the historical P/E and dividend yields of the market (P/E chart)";
const YIELD_CAPTION = "The charts below indicate the historical P/E and dividend yields of the market (dividend yield chart)";
const json = { "Content-Type": "application/json" };

type Item = { index: number; ref: string; status: string; kind: string; resolution: string | null; resolution_note: string | null };
const reviewOf = async (request: APIRequestContext, id: number) => (await (await request.get(`${API}/api/reviews/${id}`)).json()) as {
  review_items: Item[];
  section: { blocks: { chart_id?: string; use_team_chart?: boolean; status?: string }[]; chart_notes: string[] };
};
const chartItems = (items: Item[], title: string) => items.filter((i) => i.ref.startsWith(`${title}:`));

/** Draft the Equities section of a demo Friday through the API and return the saved review's id. */
async function draft(request: APIRequestContext, friday: string): Promise<number> {
  const run = await startRun(request, "equities", `Week ending ${friday}`);
  for (let n = 0; n < 240; n++) {
    const state = await (await request.get(`${API}/api/runs/${run}`)).json();
    if (state.status === "finished") return state.review_id as number;
    if (state.status === "failed") throw new Error(`the draft failed: ${JSON.stringify(state.events.at(-1))}`);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("the draft did not finish");
}

async function open(page: Page, id: number) {
  await page.goto(`/overview?review=${id}`);
  await expect(page.getByRole("heading", { name: "Equities: coordinator review", level: 1 })).toBeVisible();
}

const cards = (page: Page) => page.locator("[data-chart-block]");
const peCard = (page: Page) => cards(page).filter({ has: page.getByRole("heading", { name: /NASI P\/E chart/ }) });
const yieldCard = (page: Page) => cards(page).filter({ has: page.getByRole("heading", { name: /NASI dividend yield chart/ }) });
const panel = (page: Page) => page.getByRole("complementary", { name: "Review items" });
const itemsOf = (page: Page, title: string) => panel(page).locator("li[data-status]").filter({ hasText: `${title}:` });
const notesList = (page: Page) => page.getByRole("heading", { name: /^Charts to add by hand/ });
// The list itself; a review item repeats the caption as its context, so list items are looked for only here.
const notes = (page: Page) => page.locator('section[aria-labelledby="charts-title"]').getByRole("listitem");
const loaded = (img: Locator) => expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBe(1200);

let clean = 0;
let defectsId = 0;

test("T78 a complete workbook: both charts are drawn, with the picture, the facts they rest on and the provenance line", async ({ page, request }) => {
  clean = await draft(request, CLEAN);
  await open(page, clean);
  await expect(cards(page)).toHaveCount(2);
  const card = peCard(page);
  await expect(card.getByText("Drawn by the tool", { exact: true })).toBeVisible();
  await expect(card.getByText(PE_CAPTION, { exact: true })).toBeVisible();

  const img = card.getByRole("img", { name: new RegExp(`^${PE_CAPTION.replace(/[()/]/g, "\\$&")}\\. Line chart of `) });
  await expect(img).toBeVisible();
  await loaded(img);
  await expect(img).toHaveAttribute("src", new RegExp(`/api/reviews/${clean}/charts/nasi_pe\\.png$`));

  const facts = card.getByLabel("What the chart rests on");
  // September is "Sep" or "Sept" depending on the browser's locale data; the app formats dates by that.
  for (const [label, value] of [["Points read", "60"], ["Window", "Up to 5 years"], ["Newest point", /25 Sept? 2026/], ["Last value", "8.0x"], ["Average", "points since"]] as [string, string | RegExp][]) {
    await expect(facts.locator("div", { hasText: label }).first()).toContainText(value);
  }
  await expect(card.getByText(/^From the analyst workbook, not verified \(Equities workbook, 'NASI-PE & Dividend Yield'!B8:B67\)\.$/)).toBeVisible();
  const fullSize = card.getByRole("link", { name: /Open full size/ });
  await expect(fullSize).toHaveAttribute("href", new RegExp(`/api/reviews/${clean}/charts/nasi_pe\\.png$`));
  await expect(fullSize).toHaveAttribute("target", "_blank");
  await expect(fullSize).toHaveAttribute("rel", /noopener/);

  // The yield chart is drawn in its own unit, and the review items for both charts sit in the panel, none flagged.
  await expect(yieldCard(page).locator("div", { hasText: "Last value" }).first()).toContainText("6.0%");
  // The panel opens its Not auto-verified group and keeps Clean collapsed (coverage, not work): each chart has three items that
  // rest on the analyst workbook, and the freshness and rows checks that found nothing are in Clean.
  for (const title of ["NASI P/E chart", "NASI dividend yield chart"]) {
    expect(await itemsOf(page, title).evaluateAll((all) => all.map((el) => el.getAttribute("data-status")))).toEqual(Array(3).fill("not_auto_verified"));
  }
  await panel(page).getByRole("button", { name: /^Clean \(\d+\)$/ }).click();
  for (const title of ["NASI P/E chart", "NASI dividend yield chart"]) {
    const rows = itemsOf(page, title);
    await expect(rows).toHaveCount(5);
    expect(await rows.evaluateAll((all) => all.map((el) => el.getAttribute("data-status")))).not.toContain("flagged");
  }
  // Both are drawn, so neither is left in the list of charts to add by hand.
  await expect(notesList(page)).toHaveCount(0);
});

test("T79 Show points: a collapsed table of the plotted points, read on request from the stored series", async ({ page }) => {
  await open(page, clean);
  const card = peCard(page);
  const toggle = card.getByRole("button", { name: "Show points" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(card.getByRole("region", { name: /^Plotted points of NASI P\/E chart/ })).toHaveCount(0);

  await toggle.click();
  await expect(card.getByRole("button", { name: "Hide points" })).toHaveAttribute("aria-expanded", "true");
  const region = card.getByRole("region", { name: "Plotted points of NASI P/E chart, newest first" });
  await expect(region).toBeVisible();
  await expect(region.locator("tbody tr")).toHaveCount(60);
  const first = region.locator("tbody tr").first();
  await expect(first).toContainText(/25 Sept? 2026/);
  await expect(first).toContainText("8.0x");
  await expect(first).toContainText("B8");
  await region.focus();
  await expect(region).toBeFocused(); // a keyboard can scroll it

  await card.getByRole("button", { name: "Hide points" }).click();
  await expect(region).toHaveCount(0);
});

test("T80 Use the team's own chart: reachable by keyboard, named in the feed, saved with the review, and taken back", async ({ page, request }) => {
  await open(page, clean);
  const card = peCard(page);
  await card.getByRole("button", { name: "Show points" }).focus();
  await page.keyboard.press("Tab");
  const button = card.getByRole("button", { name: "Use the team's own chart" });
  await expect(button).toBeFocused(); // the next stop after "Show points"
  await expect(button).toHaveAccessibleDescription(/Word file keeps the placeholder/);
  await page.keyboard.press("Enter");

  // Named in the feed (the draft's column), on the card, and the other chart is untouched.
  await expect(card.getByText("Using the team's own chart", { exact: true })).toBeVisible();
  await expect(card.getByRole("status").filter({ hasText: "Using the team's own chart." })).toBeVisible();
  await expect(card.getByRole("button", { name: "Use the tool's chart again" })).toBeVisible();
  await expect(yieldCard(page).getByText("Drawn by the tool", { exact: true })).toBeVisible();
  await expect(notesList(page)).toHaveText("Charts to add by hand (1)");
  await expect(notes(page).filter({ hasText: PE_CAPTION })).toBeVisible();
  await expect(notes(page).filter({ hasText: YIELD_CAPTION })).toHaveCount(0);

  // Saved with the review: in the database, not only on the screen.
  const saved = await reviewOf(request, clean);
  const mine = chartItems(saved.review_items, "NASI P/E chart");
  expect(mine).toHaveLength(5);
  expect(mine.map((i) => i.resolution)).toEqual(Array(5).fill("accept"));
  expect(mine.every((i) => i.resolution_note?.startsWith("Using the team's own chart"))).toBe(true);
  expect(chartItems(saved.review_items, "NASI dividend yield chart").map((i) => i.resolution)).toEqual(Array(5).fill(null));
  const chosen = Object.fromEntries(saved.section.blocks.filter((b) => b.chart_id).map((b) => [b.chart_id, b.use_team_chart]));
  expect(chosen).toEqual({ nasi_pe: true, nasi_yield: false });
  expect(saved.section.chart_notes).toEqual([PE_CAPTION]);

  await page.reload();
  await expect(peCard(page).getByText("Using the team's own chart", { exact: true })).toBeVisible();
  await expect(notesList(page)).toHaveText("Charts to add by hand (1)");

  // Taken back: the items are unresolved again and the chart is listed no more.
  await peCard(page).getByRole("button", { name: "Use the tool's chart again" }).click();
  await expect(peCard(page).getByText("Drawn by the tool", { exact: true })).toBeVisible();
  await expect(notesList(page)).toHaveCount(0);
  expect(chartItems((await reviewOf(request, clean)).review_items, "NASI P/E chart").map((i) => i.resolution)).toEqual(Array(5).fill(null));
});

test("T81 rows left out of the series are listed by cell on the card and are a flagged item beside the draft; a decided review freezes the choice", async ({ page, request }) => {
  const id = (defectsId = await draft(request, DEFECTS));
  await open(page, id);
  const card = peCard(page);
  await expect(card.getByText("Drawn by the tool", { exact: true })).toBeVisible();
  await expect(card.getByText(/Empty value cells inside the table.*: B20/)).toBeVisible();
  await expect(card.getByText(/Rows that share a date.*: B11, B12/)).toBeVisible();
  await expect(yieldCard(page).getByText(/Empty value cells|Rows that share a date/)).toHaveCount(0);

  // The same defects are one flagged item in the Review items panel (not in anything that folds), unresolved, so approval waits.
  const rows = itemsOf(page, "NASI P/E chart").filter({ hasText: "rows of the series" });
  await expect(rows).toHaveCount(1);
  await expect(rows).toHaveAttribute("data-status", "flagged");
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();

  // Once decided, the review is frozen and so is the choice.
  const items = (await reviewOf(request, id)).review_items;
  for (const i of items) {
    const res = await request.patch(`${API}/api/reviews/${id}/items/${i.index}`, { headers: json, data: { resolution: "accept" } });
    expect(res.ok()).toBe(true);
  }
  expect((await request.post(`${API}/api/reviews/${id}/decide`, { headers: json, data: { decision: "approved" } })).status()).toBe(200);
  await open(page, id);
  await expect(peCard(page).getByRole("button", { name: "Use the team's own chart" })).toBeDisabled();
  await expect(peCard(page).getByText("This review is decided, so the choice is frozen.")).toBeVisible();
});

test("T82 a workbook not yet updated: both charts are not drawn, the reason is in the feed and the items stay flagged until the choice is made", async ({ page, request }) => {
  const id = await draft(request, STALE);
  await open(page, id);
  for (const card of [peCard(page), yieldCard(page)]) {
    await expect(card.getByText("Not drawn", { exact: true }).first()).toBeVisible();
    await expect(card.getByRole("img")).toHaveCount(0);
    await expect(card.getByText(/The newest point is dated 2026-09-04; for the week ending 2026-09-11 it should be dated 2026-09-11 or later\./)).toBeVisible();
    await expect(card.getByRole("button", { name: "Show points" })).toHaveCount(0);
    // A stale series still carries a last value and an average, but the card does not present them as the chart's.
    await expect(card.getByLabel("What the chart rests on")).toHaveCount(0);
    await expect(card.getByText(/From the analyst workbook, not verified/)).toHaveCount(0);
  }
  await expect(notesList(page)).toHaveText("Charts to add by hand (2)");
  const flagged = itemsOf(page, "NASI P/E chart");
  await expect(flagged).toHaveCount(2); // the newest point, and the chart not drawn
  expect(await flagged.evaluateAll((all) => all.map((el) => el.getAttribute("data-status")))).toEqual(["flagged", "flagged"]);

  // The team's own chart settles it: both items accepted, and the placeholder stays.
  await peCard(page).getByRole("button", { name: "Use the team's own chart" }).click();
  await expect(peCard(page).getByText("Using the team's own chart", { exact: true })).toBeVisible();
  expect(chartItems((await reviewOf(request, id)).review_items, "NASI P/E chart").map((i) => i.resolution)).toEqual(["accept", "accept"]);
  await expect(notesList(page)).toHaveText("Charts to add by hand (2)");
});

test("T83 no workbook uploaded: the charts are information only, with nothing to resolve and nothing flagged", async ({ page, request }) => {
  const id = await draft(request, NONE);
  await open(page, id);
  for (const card of [peCard(page), yieldCard(page)]) {
    await expect(card.getByText("No workbook uploaded", { exact: true })).toBeVisible();
    await expect(card.getByRole("status").filter({ hasText: "equities workbook for this week is not among this week's inputs" })).toBeVisible();
    await expect(card.getByText(/Nothing here needs resolving\./)).toBeVisible();
    await expect(card.getByRole("button")).toHaveCount(0); // nothing to show or to set aside
    await expect(card.getByRole("img")).toHaveCount(0);
  }
  const saved = await reviewOf(request, id);
  expect(saved.review_items.filter((i) => i.kind === "chart")).toEqual([]);
  expect(saved.section.chart_notes).toEqual([PE_CAPTION, YIELD_CAPTION]);
  await expect(notesList(page)).toHaveText("Charts to add by hand (2)");
  await expect(panel(page).getByText(/NASI (P\/E|dividend yield) chart/)).toHaveCount(0); // no item about them in the panel either
});

test("T84 at 390px the card has nothing to scroll sideways and its buttons are reachable; in dark mode the picture keeps a white frame", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, clean);
  const card = peCard(page);
  const img = card.getByRole("img");
  await img.scrollIntoViewIfNeeded();
  await loaded(img);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const box = (await img.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.width).toBeGreaterThan(280);
  for (const name of ["Show points", "Use the team's own chart"]) {
    const b = (await card.getByRole("button", { name }).boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(390);
    expect(b.height).toBeGreaterThanOrEqual(28);
  }
  await card.getByRole("button", { name: "Show points" }).click();
  const region = card.getByRole("region", { name: /^Plotted points/ });
  await expect(region).toBeVisible();
  expect(await region.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe("rgb(243, 243, 243)");
  const frame = await img.evaluate((el) => getComputedStyle(el.parentElement!).backgroundColor);
  expect(frame).toBe("rgb(255, 255, 255)");
});

test("T85 screenshots of the chart card at 1280px and 390px, light and dark (only with E2E_SHOTS=<folder>)", async ({ page, request }) => {
  const dir = process.env.E2E_SHOTS;
  test.skip(!dir, "set E2E_SHOTS to a folder to write them");
  mkdirSync(dir!, { recursive: true });
  const notDrawn = await draft(request, STALE); // a fresh draft: T82 set the earlier one's choice
  const none = await draft(request, NONE);
  const states: [string, number, boolean][] = [
    ["drawn-with-points", clean, true],
    ["rows-left-out", defectsId, false],
    ["not-drawn", notDrawn, false],
    ["no-workbook", none, false],
  ];
  for (const [theme, width] of [["light", 1280], ["dark", 1280], ["light", 390], ["dark", 390]] as const) {
    // Tall enough that the card is not scrolled into view: the page's sticky bars would be drawn over an element screenshot.
    await page.setViewportSize({ width, height: width === 390 ? 3400 : 2400 });
    await page.emulateMedia({ colorScheme: theme });
    for (const [state, id, points] of states) {
      await open(page, id);
      const card = peCard(page);
      if (points) await card.getByRole("button", { name: "Show points" }).click();
      await card.scrollIntoViewIfNeeded();
      if (state === "drawn-with-points") await loaded(card.getByRole("img"));
      await card.screenshot({ path: join(dir!, `chart-${state}-${theme}-${width}.png`) });
    }
    await open(page, clean);
    await peCard(page).getByRole("button", { name: "Use the team's own chart" }).click();
    await expect(peCard(page).getByText("Using the team's own chart", { exact: true })).toBeVisible();
    await peCard(page).screenshot({ path: join(dir!, `chart-team-chart-${theme}-${width}.png`) });
    await peCard(page).getByRole("button", { name: "Use the tool's chart again" }).click();
    await expect(peCard(page).getByText("Drawn by the tool", { exact: true })).toBeVisible();
    await open(page, clean);
    await page.screenshot({ path: join(dir!, `review-top-${theme}-${width}.png`) });
  }
});

test("T86 a picture or a series file that changed after the draft is said on the card, not shown as a broken image", async ({ page }) => {
  const folder = join(DATA, "charts", String(clean));
  appendFileSync(join(folder, "nasi_pe.png"), Buffer.from([0]));
  writeFileSync(join(folder, "nasi_pe.json"), readFileSync(join(folder, "nasi_pe.json"), "utf8").replace("B8", "B9"));
  await open(page, clean);
  const card = peCard(page);
  await expect(card.getByRole("alert").filter({ hasText: "The picture is not shown: the stored file was changed after the draft" })).toBeVisible();
  await expect(card.getByRole("img")).toHaveCount(0);
  await card.getByRole("button", { name: "Show points" }).click();
  await expect(card.getByRole("alert").filter({ hasText: "The plotted points are not shown: the stored file was changed after the draft" })).toBeVisible();
  // The other chart is untouched.
  await loaded(yieldCard(page).getByRole("img"));
});
