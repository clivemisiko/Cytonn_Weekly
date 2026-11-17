import { expect, test, type Page } from "@playwright/test";
import { PERIOD, VARIANT, card, overviewUrl } from "./helpers";

test.skip(!!VARIANT, "runs on the default test backend");

const TITLES = ["Fixed Income", "Equities", "Real Estate", "Digital Payments", "Focus of the Week"];
const NOW = "2026-10-09T08:00:00+00:00";
const job = (status: string, extra: Record<string, unknown> = {}) => ({
  job_id: 5, report_type: "weekly", period: PERIOD, section: "fixed_income", status, paused_reason: null, calls_used: 1, call_budget: 20,
  input_tokens: 100, output_tokens: 50, token_budget: 200000, max_tool_calls: 8, budget_raises: 0, created_at: NOW, ...extra,
});
const answer = (seq: number, content: string) => ({ seq, role: "assistant", content, tool_name: null, cards: null, created_at: NOW });

/** The test backend is in local mode, where the assistant cannot answer: say the config is Bedrock, and stand in for the job routes. */
async function stubChat(page: Page, handle: (method: string) => { status?: number; json: unknown }) {
  await page.route("**/api/config", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ json: { ...(await res.json()), provider: "bedrock", provider_problem: null } });
  });
  await page.route("**/api/jobs", (route) => route.fulfill({ json: { job: job("idle"), created: false } }));
  await page.route("**/api/jobs/5/**", (route) => route.fulfill(handle(route.request().method())));
}

test("T116 the chat opens on a section picker with the week, a section opens its conversation with the readiness card, and the old page is one link away", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(`/chat?period=${encodeURIComponent(PERIOD)}`);
  await expect(page.getByRole("heading", { name: "Choose what to talk about" })).toBeVisible();
  await expect(page.getByLabel("Week", { exact: true })).toBeVisible();
  const main = page.getByRole("main");
  await expect(main.getByRole("button", { name: "Whole report" })).toBeVisible();
  for (const title of TITLES) {
    await expect(main.getByRole("button", { name: title, exact: true })).toBeVisible();
    await expect(main.getByRole("link", { name: `Old page for ${title}` })).toHaveAttribute("href", /\/overview\?report=weekly&period=.*&section=/);
  }

  await main.getByRole("button", { name: "Whole report" }).click();
  await expect(page).toHaveURL(/section=fixed_income/);
  await expect(page.getByRole("heading", { name: "Fixed Income", level: 2 })).toBeVisible();
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log.getByRole("region", { name: /What fixed income needs for the week ending 2026-10-09/ })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Report sections" }).getByRole("button", { name: /^Fixed Income/ })).toHaveAttribute("aria-current", "page");

  // This copy is in local mode, so the assistant cannot answer: the box is off and says why in words.
  await expect(page.getByLabel("Message")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await expect(page.getByText(/not set up for it \(local\)/)).toBeVisible();

  await page.setViewportSize({ width: 390, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "Old page for this section" }).click();
  await expect(page).toHaveURL(/\/overview\?.*section=fixed_income/);
});

test("T117 an answer arrives by polling as plain text, and polling stops once the job is idle", async ({ page }) => {
  let polls = 0;
  let state = "idle";
  await stubChat(page, (method) => {
    if (method === "POST") {
      state = "working";
      return { status: 202, json: { seq: 2, job: job("working") } };
    }
    polls++;
    if (state === "working" && polls >= 3) {
      state = "idle";
      return { json: { job: job("idle"), messages: [answer(3, "Two things are missing. See [the bulletin](https://example.com) and **bold**.")] } };
    }
    return { json: { job: job(state), messages: [] } };
  });
  await page.goto(`/chat?section=fixed_income&period=${encodeURIComponent(PERIOD)}`);
  await page.getByLabel("Message").fill("What is missing?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("The assistant is answering.", { exact: true })).toBeVisible();
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log.getByText("What is missing?")).toBeVisible();
  await expect(log.getByText("Two things are missing. See [the bulletin](https://example.com) and **bold**.")).toBeVisible();
  await expect(page.getByText("The assistant is answering.", { exact: true })).toHaveCount(0);
  await expect(log.locator("a, strong")).toHaveCount(0);

  const settled = polls;
  await page.waitForTimeout(3000);
  expect(polls).toBe(settled);
});

test("T118 a refusal shows in words, and a budget stop shows the raise button and keeps the box off until it is used", async ({ page }) => {
  let state = "paused";
  let refuse = true;
  await stubChat(page, (method) => {
    if (method === "POST" && refuse) return { status: 409, json: { detail: "The assistant is still answering the last message." } };
    if (method === "POST") return { json: { job: job("idle") } }; // the raise
    return { json: { job: state === "paused" ? job("paused", { paused_reason: "call_budget", calls_used: 20 }) : job("idle", { call_budget: 30 }), messages: [] } };
  });
  await page.goto(`/chat?section=fixed_income&period=${encodeURIComponent(PERIOD)}`);
  await expect(page.getByText(/Paused\. This conversation has used 20 of its 20 model calls/)).toBeVisible();
  await expect(page.getByText("Raise the budget first, then send your message.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();

  refuse = false;
  state = "idle";
  await page.getByRole("button", { name: "Raise the budget" }).click();
  await expect(page.getByRole("button", { name: "Raise the budget" })).toHaveCount(0);
  await expect(page.getByText("Raise the budget first, then send your message.")).toHaveCount(0);

  refuse = true;
  await page.getByLabel("Message").fill("Hello");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The assistant is still answering the last message." })).toBeVisible();
});

test("T119 each weekly section card on the overview has a Chat link that opens that section's conversation", async ({ page }) => {
  await page.goto(overviewUrl());
  await card(page, "Fixed Income").getByRole("link", { name: "Chat about Fixed Income" }).click();
  await expect(page).toHaveURL(new RegExp(`/chat\\?section=fixed_income&period=${encodeURIComponent(PERIOD).replace(/%/g, "%")}`));
  await expect(page.getByRole("heading", { name: "Fixed Income", level: 2 })).toBeVisible();
  await expect(page.getByLabel("Week", { exact: true })).toHaveValue(PERIOD);
});
