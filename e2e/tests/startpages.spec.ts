import { expect, test } from "@playwright/test";
import { VARIANT } from "./helpers";

/**
 * The two pages that are not a report screen: the start page, one centred card with everything it said before, and the
 * page for an address the app does not have, a card in the shell's frame. This file has its own run on a freshly
 * restored test backend (`playwright test startpages`).
 */
test.skip(!!VARIANT, "runs on the default test backend");
test.describe.configure({ mode: "serial" });

const middleOfWindow = (page: import("@playwright/test").Page) => page.evaluate(() => document.documentElement.clientWidth / 2);

test("T76 the start page is one centred card holding what it always said, and nothing is wider than a phone's window", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Report generator", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Good (morning|afternoon|evening)\. Welcome to Cytonn Weekly\.$/, level: 2 })).toBeVisible();
  const card = page.locator("main > div");
  for (const part of [
    page.getByText("Ready. Nothing is drafted until you ask."),
    page.getByRole("button", { name: "Sign in with Cytonn SSO" }),
    page.getByText("Not connected yet.", { exact: true }),
    page.getByRole("link", { name: "Continue without signing in" }),
    page.getByText("this tool has no sign-in and should only be used by the team", { exact: false }),
  ]) {
    await expect(card.locator(part)).toBeVisible(); // everything is inside the one card
  }
  await expect(card.getByRole("heading", { name: "Report generator", level: 1 })).toBeVisible(); // the title block is in the card too
  const looks = await card.evaluate((el) => ({ border: getComputedStyle(el).borderTopWidth, card: getComputedStyle(el).backgroundColor, page: getComputedStyle(document.body).backgroundColor }));
  expect(looks.border).toBe("1px"); // a bordered white card on the pale page, not bare text
  expect(looks.card).not.toBe(looks.page);
  await expect(page.getByRole("navigation", { name: "Report sections" })).toHaveCount(0); // the start page stands alone, no rail
  const box = (await card.boundingBox())!;
  expect(Math.abs(box.x + box.width / 2 - (await middleOfWindow(page)))).toBeLessThan(2);

  await page.setViewportSize({ width: 390, height: 800 });
  const narrow = (await card.boundingBox())!;
  expect(narrow.x).toBeGreaterThanOrEqual(0);
  expect(narrow.x + narrow.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("T77 an address the app does not have shows a card in the shell's frame, centred, with the rail and no states it cannot know", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found", level: 1 })).toBeVisible();
  const text = page.getByText("This page could not be found.");
  await expect(text).toBeVisible();
  const rail = page.getByRole("navigation", { name: "Report sections" });
  await expect(rail).toBeVisible();
  await expect(rail.getByText("Open the overview to list this report’s sections.")).toBeVisible(); // no section state is guessed
  const card = page.locator("main > div > div", { has: text }).first();
  const railBox = (await rail.boundingBox())!;
  const box = (await card.boundingBox())!;
  const middle = railBox.x + railBox.width + ((await middleOfWindow(page)) * 2 - (railBox.x + railBox.width)) / 2;
  expect(Math.abs(box.x + box.width / 2 - middle)).toBeLessThan(40);
});
