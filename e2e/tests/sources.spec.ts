import { expect, test, type Page } from "@playwright/test";
import { API, DRAFT, PERIOD, VARIANT, openStart } from "./helpers";

// The Sources panel of a Bedrock draft. Runs only on the "bedrock" start of the test API (E2E_VARIANT=bedrock, see
// e2e/serve_e2e.py): the provider is Bedrock with invented settings, the model is a fake client that quotes the first
// sentence of the first saved source it is shown (and adds one claim that is in no page), and an approved-site fetch is
// answered by one fixed page. Nothing is searched, fetched or sent anywhere.
test.skip(VARIANT !== "bedrock", "needs E2E_VARIANT=bedrock");
test.describe.configure({ mode: "serial" });

const TITLES = "Overview of the topic\nMarket performance\nRecommendations and Conclusion";
const PASTED = "The invented regulator said private sector credit grew by 8.75% in the year to September 2026. Lending to households rose faster than lending to firms.";
const group = (page: Page, subject: string) => page.getByRole("group", { name: `Sources for ${subject}` });

async function openFocus(page: Page) {
  await openStart(page, "Focus of the Week");
  await page.getByLabel("This week’s topic").fill("SYNTHETIC bedrock topic");
  await page.getByLabel("Sections (optional)").fill(TITLES);
}

async function paste(page: Page, subject: string, over: { url?: string; date?: string; text?: string } = {}) {
  const piece = group(page, subject);
  await piece.getByText("Add a source", { exact: true }).click();
  await piece.getByLabel("Address (URL) the text came from").fill(over.url ?? "https://www.centralbank.go.ke/press/e2e");
  await piece.getByLabel("Date of the page").fill(over.date ?? "2026-10-08");
  await piece.getByLabel("Pasted text").fill(over.text ?? PASTED);
  await piece.getByRole("button", { name: "Save pasted text" }).click();
}

test("T107 a Bedrock start screen: the mode is production, not dev, and the Sources panel needs the typed titles first", async ({ page, request }) => {
  const config = await (await request.get(`${API}/api/config`)).json();
  expect(config).toMatchObject({ provider: "bedrock", dev_mode: false, provider_problem: null });
  await page.setViewportSize({ width: 1366, height: 800 });
  await openStart(page, "Focus of the Week");
  await expect(page.getByText("Production · bedrock")).toBeVisible();
  await expect(page.getByText("DEV MODE", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Nothing is searched: each piece is written only from the sources supplied for it.", { exact: false })).toBeVisible();
  await expect(page.getByText("web search and tokens", { exact: false })).toHaveCount(0);

  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByText("Type the section titles in the form below.", { exact: false })).toBeVisible();
  await page.getByLabel("This week’s topic").fill("SYNTHETIC bedrock topic");
  // Bedrock has nothing to search, so it does not propose titles: the draft waits for typed ones, and says why.
  await expect(page.getByRole("button", { name: DRAFT })).toBeDisabled();
  await expect(page.getByText("Amazon Bedrock does not propose section titles", { exact: false })).toBeVisible();

  await page.getByLabel("Sections (optional)").fill(TITLES);
  await expect(page.getByRole("button", { name: DRAFT })).toBeEnabled();
  // One piece per typed title; the closing part is written from the others and takes no sources.
  await expect(group(page, "Overview of the topic")).toBeVisible();
  await expect(group(page, "Market performance")).toBeVisible();
  await expect(page.getByRole("group", { name: /Recommendations and Conclusion/ })).toHaveCount(0);
  await expect(sources.getByText("Approved sites (", { exact: false })).toBeVisible();
});

test("T108 a pasted source is listed with its host, date, size, origin and fingerprint, and its saved text is one link away", async ({ page }) => {
  await openFocus(page);
  await paste(page, "Market performance");
  const piece = group(page, "Market performance");
  await expect(piece.getByRole("status")).toContainText("Saved");
  await expect(piece).toContainText("1 source");
  await expect(piece).toContainText("www.centralbank.go.ke");
  await expect(piece).toContainText("8 Oct 2026");
  await expect(piece).toContainText(`${PASTED.length.toLocaleString("en-GB")} characters`);
  await expect(piece).toContainText(/pasted \d+ \w+ 2026, \d\d:\d\d EAT/); // times are East Africa Time, never UTC
  await expect(piece).toContainText(/fingerprint [0-9a-f]{8}\b/);
  await expect(piece).not.toContainText("host not on the approved list");
  await expect(piece.getByText("No sources yet", { exact: false })).toHaveCount(0);

  const href = await piece.getByRole("link", { name: /View saved text/ }).getAttribute("href");
  expect(href).toMatch(/^.*\/api\/sources\/[0-9a-f]{8}\/text$/);
  const text = await page.request.get(`${API}${new URL(href!, "http://x").pathname}`);
  expect(text.headers()["content-type"]).toContain("text/plain");
  expect(await text.text()).toBe(PASTED); // kept exactly as pasted

  await page.reload();
  await page.getByLabel("This week’s topic").fill("SYNTHETIC bedrock topic");
  await page.getByLabel("Sections (optional)").fill(TITLES);
  await expect(group(page, "Market performance")).toContainText("www.centralbank.go.ke"); // saved on the server, not in the page
});

test("T109 a fetch from an approved site is kept as fetched, and a refused fetch shows the API's sentence and keeps nothing", async ({ page }) => {
  await openFocus(page);
  const piece = group(page, "Overview of the topic");
  await piece.getByText("Add a source", { exact: true }).click();
  const address = piece.getByLabel("Address (URL) to fetch");

  for (const [url, sentence] of [
    ["https://blog.example.com/post", "blog.example.com is not on the approved list of sites, so it is not fetched"],
    ["https://x.com/someone/status/1", "x.com is a social media site, and social media is never used as a source"],
    ["http://www.centralbank.go.ke/press/1", "Only https addresses are fetched"],
  ]) {
    await address.fill(url);
    await piece.getByRole("button", { name: "Fetch page" }).click();
    await expect(piece.getByRole("alert")).toContainText(sentence);
    await expect(piece).toContainText("No sources yet");
  }

  await address.fill("https://www.imf.org/en/news/e2e");
  await piece.getByRole("button", { name: "Fetch page" }).click();
  await expect(piece.getByRole("status")).toContainText("Saved E2E fetched statement (www.imf.org)");
  await expect(piece).toContainText("fetched");
  await expect(piece).toContainText("8 Oct 2026"); // the page's own date, read from its meta tag
  await expect(piece.getByRole("alert")).toHaveCount(0);
});

test("T110 a pasted source with no date is refused in the API's words, and one from a site off the list is kept and marked", async ({ page }) => {
  await openFocus(page);
  const piece = group(page, "Market performance");
  await piece.getByText("Add a source", { exact: true }).click();
  await piece.getByLabel("Address (URL) the text came from").fill("https://blog.example.com/post");
  await piece.getByLabel("Pasted text").fill(PASTED);
  await expect(piece.getByRole("button", { name: "Save pasted text" })).toBeDisabled(); // the date is needed first
  await piece.getByLabel("Date of the page").fill("2026-10-07");
  await piece.getByRole("button", { name: "Save pasted text" }).click();
  await expect(piece).toContainText("blog.example.com");
  await expect(piece).toContainText("host not on the approved list");
});

test("T111 a removed source goes back to the no-sources notice", async ({ page }) => {
  await openFocus(page);
  const piece = group(page, "Market performance");
  await expect(piece.getByText("No sources yet: this piece will come back unavailable")).toBeVisible();
  await paste(page, "Market performance", { url: "https://www.knbs.or.ke/e2e", text: PASTED + " More text follows." });
  await expect(piece).toContainText("1 source");
  await piece.getByRole("button", { name: /^Remove .* from Market performance$/ }).first().click();
  await expect(piece.getByText("No sources yet: this piece will come back unavailable")).toBeVisible();
  await expect(piece).toContainText("0 sources");
});

test("T112 a piece with no sources says so, the draft button stays on, and the confirmation names the pieces without sources", async ({ page }) => {
  await openFocus(page);
  await paste(page, "Market performance", { url: "https://www.nse.co.ke/e2e", text: PASTED });
  await expect(group(page, "Overview of the topic").getByText("No sources yet: this piece will come back unavailable")).toBeVisible();
  await expect(group(page, "Market performance").getByText("No sources yet", { exact: false })).toHaveCount(0);
  await expect(page.getByText("1 of 2 pieces have none yet", { exact: false })).toBeVisible();

  await expect(page.getByRole("button", { name: DRAFT })).toBeEnabled(); // the coordinator decides
  await page.getByRole("button", { name: DRAFT }).click();
  const dialog = page.getByRole("dialog", { name: "Some pieces have no sources" });
  await expect(dialog).toContainText("“Overview of the topic” has no sources, so it will come back unavailable.");
  await expect(dialog).not.toContainText("Market performance");
  await dialog.getByRole("button", { name: "Go back" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/overview/); // nothing started
});

test("T113 a drafted piece shows its source host, date and verified quote, and a quote that is in no page was dropped", async ({ page, request }) => {
  await openFocus(page);
  await paste(page, "Market performance", { url: "https://blog.example.com/e2e", date: "2026-10-07", text: PASTED });
  await page.getByRole("button", { name: DRAFT }).click();
  await page.getByRole("dialog", { name: "Some pieces have no sources" }).getByRole("button", { name: "Draft anyway" }).click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByRole("heading", { name: "Draft ready for review", level: 2 })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open review" }).click();
  await expect(page.getByRole("heading", { name: "Focus of the Week: coordinator review", level: 1 })).toBeVisible();
  await expect(page.getByText("DEV MODE", { exact: false })).toHaveCount(0); // a Bedrock draft is a production draft

  await page.getByRole("button", { name: "Expand all" }).click();
  const claims = page.getByTestId("claim-source");
  await expect(claims).toHaveCount(1); // the second claim's quote is in no page, so only one survived
  const claim = claims.first();
  await expect(claim).toContainText("blog.example.com");
  await expect(claim).toContainText("7 Oct 2026");
  await expect(claim).toContainText("“The invented regulator said private sector credit grew by 8.75% in the year to September 2026”");
  await expect(claim).toContainText("checked word for word against the saved text");
  await expect(claim).toContainText("Pasted");
  await expect(claim).toContainText(/fingerprint [0-9a-f]{8}\b/);
  await expect(claim.getByRole("link", { name: "View saved text" })).toHaveAttribute("href", /\/api\/sources\/[0-9a-f]{8}\/text$/);
  // The host is not on the approved list: said on the item itself, in words (not by colour alone).
  await expect(page.locator("li[data-status]", { has: claims.first() }).getByText("host not on the approved list").first()).toBeVisible();

  // The claim that was dropped is named in the piece's warnings, with the reason.
  const run = new URL(page.url()).searchParams.get("review");
  const review = await (await request.get(`${API}/api/reviews/${run}`)).json();
  expect(JSON.stringify(review.section.blocks)).toContain("claim dropped, its quote is not in the saved text of source");
  // The section the page had no source for came back unavailable, in plain words.
  expect(JSON.stringify(review.section.blocks)).toContain("No sources were supplied for this piece, so nothing was drafted.");
});

test("T114 the Sources panel does not scroll the page sideways at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openFocus(page);
  await paste(page, "Market performance", { url: "https://www.worldbank.org/en/country/kenya/e2e-" + "a".repeat(80), text: PASTED });
  await expect(group(page, "Market performance")).toContainText("www.worldbank.org");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
