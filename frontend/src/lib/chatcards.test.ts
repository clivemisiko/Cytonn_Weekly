import { describe, expect, it } from "vitest";
import { FOCUS_ON_OLD_PAGE, GROUPS, NOT_JUDGED, draftCard, flaggedOf, hasNeeds, needsYou, parseReadiness, parseReviewSnapshot, snipLine, sourcesLine, weekOf } from "./chatcards";
import type { AppConfig, Drafting, Review, SectionSummary } from "./types";

const entry = (key: string, over: Record<string, unknown> = {}) => ({ kind: "upload", key, label: key.toUpperCase(), why: "not uploaded", ...over });
const data = (over: Record<string, unknown> = {}) => ({
  section: "fixed_income",
  week_ending: "2026-10-09",
  groups: { needs_analyst: [], carried_or_suggested: [], fetched: [], in_place: [], optional: [] },
  ...over,
});
const section = (over: Partial<SectionSummary> = {}) => ({ slug: "fixed_income", title: "Fixed Income", available: true, needs_topic: false, uses_provider: true, requires_approved: false, reason: null, latest: null, ...over }) as SectionSummary;
const config = (over: Partial<AppConfig> = {}): AppConfig => ({ provider: "bedrock", provider_valid: true, dev_mode: false, dev_mode_label: "", spends_api_budget: true, provider_problem: null, ...over });
const drafting = (over: Partial<Drafting> = {}) => ({ slug: "fixed_income", state: "running", title: "Fixed Income", started_at: "", elapsed_seconds: 3, stale: false, stale_after_seconds: 900, ...over }) as Drafting;

describe("the readiness card", () => {
  it("reads all five groups, in the order they are shown", () => {
    expect(GROUPS.map((g) => g.key)).toEqual(["needs_analyst", "carried_or_suggested", "fetched", "in_place", "optional"]);
    const r = parseReadiness(
      data({ groups: { needs_analyst: [entry("a")], carried_or_suggested: [entry("b", { kind: "number", why: "carried from last week, not yet confirmed" })], fetched: [entry("c")], in_place: [entry("d"), entry("e")], optional: [entry("f")] } }),
    );
    expect(r?.weekEnding).toBe("2026-10-09");
    expect(GROUPS.map((g) => r?.groups[g.key].length)).toEqual([1, 1, 1, 2, 1]);
    expect(r?.snips).toBeNull();
    expect(r?.sources).toBeNull();
    expect(r?.note).toBeNull();
  });

  it("keeps Real Estate snip counts and Focus source counts as they are, with the fixed not-judged note", () => {
    const r = parseReadiness(data({ section: "real_estate", snips: [{ sector: "Land", uploaded: 3, read: 2, confirmed: 1 }], sources: { total: 5, in_week: 4, outside_week: 1 } }));
    expect(snipLine(r!.snips![0])).toBe("Land: 3 uploaded, 2 read, 1 confirmed");
    expect(sourcesLine(r!.sources!)).toBe("5 saved, 4 dated inside the week, 1 outside it");
    expect(r?.note).toBe(NOT_JUDGED);
    expect(parseReadiness(data({ sources: { total: 0, in_week: 0, outside_week: 0 }, note: "The API's own words." }))?.note).toBe("The API's own words.");
  });

  it("refuses an answer that is not a readiness check and survives odd entries", () => {
    expect(parseReadiness(null)).toBeNull();
    expect(parseReadiness({ groups: {} })).toBeNull();
    expect(parseReadiness(data({ groups: { needs_analyst: [5, null, { key: 1 }] } }))?.groups.needs_analyst).toHaveLength(1);
  });

  it("names a week from a period label", () => {
    expect(weekOf("Week ending 2026-10-09")).toBe("2026-10-09");
  });
});

describe("the needs you card", () => {
  it("splits what is missing by the button each takes, and offers Fetch only for the bulletin", () => {
    const r = parseReadiness(
      data({
        groups: {
          needs_analyst: [entry("cbk_bulletin"), entry("fi_workbook"), entry("bidding_range", { kind: "text", why: "nothing typed" })],
          carried_or_suggested: [entry("target", { kind: "number", why: "carried from last week, not yet confirmed" })],
        },
      }),
    )!;
    const n = needsYou(r);
    expect(n.uploads.map((u) => [u.key, u.fetchable])).toEqual([["cbk_bulletin", true], ["fi_workbook", false]]);
    expect(n.typed.map((e) => e.key)).toEqual(["bidding_range"]);
    expect(n.fetch).toEqual([]);
    expect(n.confirm.map((e) => e.key)).toEqual(["target"]);
    expect(hasNeeds(n)).toBe(true);
  });

  it("offers a fetch button for a fetchable table, needed or optional, and not for anything else", () => {
    const r = parseReadiness(
      data({
        groups: {
          needs_analyst: [entry("remarks", { kind: "table" })],
          optional: [entry("interbank", { kind: "table", why: "not filled" }), entry("eurobond_yields", { kind: "table" })],
        },
      }),
    )!;
    const n = needsYou(r);
    expect(n.fetch.map((e) => e.key)).toEqual(["interbank", "eurobond_yields"]);
    expect(n.typed.map((e) => e.key)).toEqual(["remarks"]);
    expect(hasNeeds(needsYou(parseReadiness(data({ groups: { optional: [entry("interbank", { kind: "table" })] } }))!))).toBe(true);
  });

  it("has nothing to offer when only in-place, fetched and optional items are left", () => {
    const n = needsYou(parseReadiness(data({ groups: { in_place: [entry("a")], optional: [entry("b")], fetched: [entry("c")] } }))!);
    expect(hasNeeds(n)).toBe(false);
  });
});

describe("the review summary card", () => {
  const card = { type: "review_summary", review_id: 12, is_dev_draft: true, data: { decision: null, counts: { flagged: 1, not_auto_verified: 2, clean: 3 }, items: [{ index: 4, ref: "yield", status: "flagged" }] } };

  it("reads the counts, the dev mark and the items to look at", () => {
    expect(parseReviewSnapshot(card)).toEqual({ reviewId: 12, isDev: true, decision: null, counts: { flagged: 1, notAuto: 2, clean: 3 }, items: [{ index: 4, ref: "yield", status: "flagged" }] });
    expect(parseReviewSnapshot({ ...card, is_dev_draft: false })?.isDev).toBe(false);
  });

  it("refuses a card with no review number or no counts", () => {
    expect(parseReviewSnapshot({ ...card, review_id: "12" })).toBeNull();
    expect(parseReviewSnapshot({ type: "review_summary", review_id: 1, data: {} })).toBeNull();
  });
});

describe("the flagged item card", () => {
  const review = {
    review_items: [
      { index: 0, ref: "clean one", status: "clean", detail: null },
      { index: 1, ref: "91-day yield", status: "flagged", detail: [{ message: "Drafted 8.9, expected 8.8" }] },
      { index: 2, ref: "a claim", status: "flagged", detail: "Check by hand." },
      { index: 3, ref: "unchecked", status: "not_auto_verified", detail: "Not yet checked." },
    ],
  } as unknown as Review;

  it("lists only the flagged items, each with the first thing the checker said", () => {
    expect(flaggedOf(review).map((f) => [f.item.index, f.why])).toEqual([[1, "Drafted 8.9, expected 8.8"], [2, "Check by hand."]]);
  });
});

describe("the draft card", () => {
  it("is ready when nothing blocks it, and offers a new draft over an earlier review", () => {
    expect(draftCard(section(), null, config())).toEqual({ kind: "ready", again: false });
    expect(draftCard(section({ latest: { run_id: 1 } as SectionSummary["latest"] }), null, config())).toEqual({ kind: "ready", again: true });
  });

  it("shows a running or queued draft instead of the button", () => {
    expect(draftCard(section(), drafting(), config()).kind).toBe("running");
    expect(draftCard(section(), drafting({ state: "queued", position: 2 }), config()).kind).toBe("queued");
  });

  it("is blocked, with the reason, for a provider problem and for Focus, and not offered for a section that is not available", () => {
    expect(draftCard(section(), null, config({ provider_problem: "No AWS settings." }))).toEqual({ kind: "blocked", why: "No AWS settings." });
    expect(draftCard(section({ needs_topic: true }), null, config())).toEqual({ kind: "blocked", why: FOCUS_ON_OLD_PAGE });
    expect(draftCard(section({ available: false, reason: "Waiting on CBK." }), null, config())).toEqual({ kind: "none", why: "Waiting on CBK." });
  });

  it("does not block a section that calls no model on a provider problem", () => {
    expect(draftCard(section({ uses_provider: false }), null, config({ provider_problem: "No AWS settings." })).kind).toBe("ready");
  });

  it("offers a failed draft again with the failure", () => {
    expect(draftCard(section(), drafting({ state: "failed", reason: "The source site was down." }), config())).toEqual({ kind: "failed", why: "The source site was down." });
  });
});
