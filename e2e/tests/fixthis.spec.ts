import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, VARIANT, screenUrl } from "./helpers";

/**
 * T152 to T155: "Add this input" on a review item (fix_inputs, weekly/recheck.fix_inputs) goes to the section's start
 * screen and highlights the input named, and items that need a check have "Open source". The test instance cannot draft
 * Fixed Income, Equities or Real Estate offline, so one Digital Payments review is drafted and its item is stood in for
 * with page.route, carrying each section's own fix_inputs entry (made-up demo values only).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const PERIOD = "Week ending 2026-12-18"; // this file's own week
const json = { "Content-Type": "application/json" };

type Fix = { panel: string; key: string };
const SECTIONS: { slug: string; title: string; fix: Fix | null }[] = [
  { slug: "fixed_income", title: "Fixed Income", fix: { panel: "analyst-form", key: "placements" } },
  { slug: "equities", title: "Equities", fix: { panel: "analyst-form", key: "pe" } },
  { slug: "real_estate", title: "Real Estate", fix: { panel: "snips", key: "land" } },
  { slug: "digital_payments", title: "Digital Payments", fix: { panel: "inputs-panel", key: "dp_workbook" } },
  { slug: "focus", title: "Focus of the Week", fix: null },
];

let runId = 0;
async function demoReview(request: APIRequestContext): Promise<Record<string, unknown>> {
  if (!runId) {
    const res = await request.post(`${API}/api/sections/digital_payments/draft`, { headers: json, data: { report_type: "weekly", period: PERIOD }, timeout: 120_000 });
    expect(res.status(), await res.text()).toBe(200);
    runId = (await res.json()).run_id;
  }
  return (await request.get(`${API}/api/reviews/${runId}`)).json();
}

/** The demo review shown as `slug`'s, with one flagged item whose fix_inputs (and context) are given. */
async function standIn(page: Page, request: APIRequestContext, slug: string, title: string, item: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  const base = await demoReview(request);
  const first = (base.review_items as Record<string, unknown>[])[0];
  const body = { ...base, ...extra, section_slug: slug, section_title: title, review_items: [{ ...first, status: "flagged", fix_slots: [], ...item }] };
  await page.route(`**/api/reviews/${runId}`, (route) => (route.request().method() === "GET" ? route.fulfill({ json: body }) : route.fallback()));
  await page.goto(`${screenUrl(PERIOD)}&review=${runId}`);
  return page.getByRole("region", { name: "Selected review item" });
}

for (const s of SECTIONS) {
  test(`T152 ${s.title}: Add this input goes to the start screen and highlights the input it names, or there is no button`, async ({ page, request }) => {
    const detail = await standIn(page, request, s.slug, s.title, { fix_inputs: s.fix ? [s.fix] : [] });
    const button = detail.getByRole("button", { name: "Add this input" });
    if (!s.fix) {
      await expect(detail).toBeVisible();
      await expect(button).toHaveCount(0);
      return;
    }
    await button.click();
    await expect(page).toHaveURL(new RegExp(`section=${s.slug}.*focus=${encodeURIComponent(`${s.fix.panel}:${s.fix.key}`)}`));
    const target = page.locator(`[data-attention="${s.fix.panel}"] [data-attention-key="${s.fix.key}"]`);
    await expect(target).toHaveAttribute("data-attention-on", "");
    await expect(target).toBeInViewport();
  });
}

test("T153 Add this input on an approved review says the run stays as it is, and Draft again goes through the existing dialog", async ({ page, request }) => {
  const detail = await standIn(page, request, "digital_payments", "Digital Payments", { fix_inputs: [{ panel: "inputs-panel", key: "dp_workbook" }] },
    { decision: "approved", locked: true });
  await expect(detail.getByText("This review is decided, and that run stays as it is. Drafting again makes a new run, and the section needs approving again.")).toBeVisible();
  await detail.getByRole("button", { name: "Add this input" }).click();
  await expect(page.locator('[data-attention="inputs-panel"] [data-attention-key="dp_workbook"]')).toHaveAttribute("data-attention-on", "");
  await expect(page.getByRole("button", { name: `Draft the ${PERIOD} section` })).toBeVisible();
});

test("T154 an OCR-only figure and a claim show Open source; an item with an input to add does not", async ({ page, request }) => {
  const ocr = { value: 1.0, origin: "ocr", source: "Demo price list", check: "Open the demo page (https://example.org/demo.pdf) and read it" };
  let detail = await standIn(page, request, "equities", "Equities", { fix_inputs: [], context: { inputs: { demo: ocr } } });
  await expect(detail.getByTestId("item-open-source")).toHaveAttribute("href", "https://example.org/demo.pdf");
  await expect(detail.getByRole("button", { name: "Add this input" })).toHaveCount(0);

  detail = await standIn(page, request, "equities", "Equities", { fix_inputs: [{ panel: "analyst-form", key: "pe" }], context: { inputs: { demo: ocr } } });
  await expect(detail.getByTestId("item-open-source")).toHaveCount(0);

  // A non-http address in a hint is never a link.
  detail = await standIn(page, request, "equities", "Equities", { fix_inputs: [], context: { inputs: { demo: { ...ocr, check: "see javascript:alert(1)" } } } });
  await expect(detail.getByTestId("item-open-source")).toHaveCount(0);
});

test("T155 the read-only archive view of a review has no Add this input", async ({ page, request }) => {
  const base = await demoReview(request);
  const first = (base.review_items as Record<string, unknown>[])[0];
  const body = { ...base, review_items: [{ ...first, status: "flagged", fix_inputs: [{ panel: "inputs-panel", key: "dp_workbook" }] }] };
  await page.route(`**/api/reviews/${runId}`, (route) => (route.request().method() === "GET" ? route.fulfill({ json: body }) : route.fallback()));
  await page.goto(`/previous?period=${encodeURIComponent(PERIOD)}&review=${runId}`);
  await expect(page.getByRole("region", { name: "Selected review item" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add this input" })).toHaveCount(0);
});
