import { describe, expect, it } from "vitest";
import { FOCUS_ON_OLD_PAGE, GROUPS, NOT_JUDGED, draftCard, hasDraftWork, openView, flaggedOf, hasNeeds, needsYou, parseReadiness, parseReviewSnapshot, snipLine, sourceRows, sourcesLine, typedProblem, captureSteps, unsavedSteps, weekOf } from "./chatcards";
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
    expect(n.inline.map((e) => e.key)).toEqual(["remarks"]);
    expect(n.typed).toEqual([]);
    expect(hasNeeds(needsYou(parseReadiness(data({ groups: { optional: [entry("interbank", { kind: "table" })] } }))!))).toBe(true);
  });

  it("takes form fields and tables inline, and leaves the fund table, its two lines and the large-cap list on the form", () => {
    const n = needsYou(
      parseReadiness(
        data({
          groups: {
            needs_analyst: [
              entry("fi_workbook"),
              entry("placements", { kind: "field" }),
              entry("eurobond_issues", { kind: "table" }),
              entry("mmf", { kind: "table" }),
              entry("mmf_published", { kind: "field" }),
              entry("mmf_source", { kind: "field" }),
              entry("large_caps", { kind: "field" }),
            ],
          },
        }),
      )!,
    );
    expect(n.inline.map((e) => e.key)).toEqual(["placements", "eurobond_issues"]);
    expect(n.typed.map((e) => e.key)).toEqual(["mmf", "mmf_published", "mmf_source", "large_caps"]);
    expect(hasNeeds({ uploads: [], fetch: [], inline: [entry("placements", { kind: "field" })], typed: [], confirm: [] })).toBe(true);
  });

  it("captures the steps once and keeps them in place when lines are saved", () => {
    const a = entry("placements", { kind: "field" });
    const b = entry("eurobond_issues", { kind: "table" });
    const c = entry("borrowing_redemptions", { kind: "table" });
    expect(captureSteps(null, [])).toBeNull();
    const steps = captureSteps(null, [a, b, c])!;
    expect(captureSteps(steps, [c])).toBe(steps); // a and b saved: still steps 1 and 2
    expect(captureSteps(steps, [])).toBe(steps);
    expect(unsavedSteps(steps, { eurobond_issues: "3 rows" })).toEqual([0, 2]);
    expect(unsavedSteps(steps, { placements: "1", eurobond_issues: "x", borrowing_redemptions: "y" })).toEqual([]);
  });

  it("refuses a blank value before saving and leaves every other check to the API", () => {
    expect(typedProblem("")).toBe("Type a value before saving.");
    expect(typedProblem("   ")).toBe("Type a value before saving.");
    expect(typedProblem("12.3")).toBeNull();
    expect(typedProblem("not a number")).toBeNull();
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

describe("the prepare page's source documents", () => {
  const r = () =>
    parseReadiness(
      data({
        groups: {
          needs_analyst: [entry("equities_workbook", { label: "Fake workbook", why: "not uploaded" }), entry("cbk_bulletin", { why: "not received; fetch it or upload it" }), entry("pe", { kind: "field" })],
          in_place: [entry("kcb_weekly", { why: "uploaded" })],
          optional: [entry("interbank", { kind: "table", why: "not filled" })],
        },
      }),
    )!;

  it("lists every upload and every fetchable table, with the check's own words capitalised, and counts what is added", () => {
    const rows = sourceRows(r());
    expect(rows.map((x) => [x.key, x.status, x.added, x.upload, x.fetch])).toEqual([
      ["equities_workbook", "Not uploaded", false, true, null],
      ["cbk_bulletin", "Not received; fetch it or upload it", false, true, "Fetch from CBK"],
      ["kcb_weekly", "Uploaded", true, true, null],
      ["interbank", "Optional, not filled", false, false, "Fetch interbank rates from CBK"],
    ]);
  });

  it("keeps the first-seen order when an upload moves a row to another group", () => {
    const order = sourceRows(r()).map((x) => x.key);
    const later = r();
    later.groups.in_place.push(later.groups.needs_analyst.shift()!);
    expect(sourceRows(later, order).map((x) => x.key)).toEqual(order);
  });
});

describe("openView: which view a section opens on", () => {
  // Each state as the page sees it. A reload, the browser's Back button, a typed address and coming back from the overview
  // or the review page all reach the page as one of these addresses (no view, view=prepare, view=conversation).
  const STATES = [
    { name: "no draft", state: "not_drafted", work: false },
    { name: "a draft running", state: "drafting", work: true },
    { name: "a draft queued", state: "queued", work: true },
    { name: "a draft finished, in review", state: "in_review", work: true },
    { name: "approved", state: "approved", work: true },
    { name: "rejected", state: "rejected", work: true },
    { name: "a failed draft, none before", state: "not_drafted", work: true },
    { name: "a draft from an earlier week only", state: "in_review", work: false },
  ];
  const shown = (view: string, s: { state: string; work: boolean }) => openView({ showChat: true, prepares: true, view, ...s });
  const hidden = (view: string, s: { state: string; work: boolean }) => openView({ showChat: false, prepares: true, view, ...s });

  for (const s of STATES) {
    it(`the chat hidden, ${s.name}: the prepare page unless the conversation view is asked for and has a draft card`, () => {
      expect(hidden("", s)).toBe("prepare");
      expect(hidden("prepare", s)).toBe("prepare");
      expect(hidden("conversation", s)).toBe(s.work ? "conversation" : "prepare");
    });
    it(`the chat shown, ${s.name}: as before`, () => {
      expect(shown("", s)).toBe(s.state === "not_drafted" ? "prepare" : "conversation");
      expect(shown("prepare", s)).toBe("prepare");
      expect(shown("conversation", s)).toBe("conversation");
    });
  }

  it("a section that is not a prepare section keeps the conversation view either way", () => {
    for (const showChat of [true, false]) expect(openView({ showChat, prepares: false, view: "", state: "not_drafted", work: false })).toBe("conversation");
  });

  it("hasDraftWork: a draft entry of any kind, or this week's review, and nothing else", () => {
    const base = { slug: "equities", latest: null } as unknown as SectionSummary;
    const latest = (current: boolean) => ({ ...base, latest: { current, this_week: current } }) as unknown as SectionSummary;
    expect(hasDraftWork(base, null)).toBe(false);
    expect(hasDraftWork(base, { slug: "equities", state: "failed" } as Drafting)).toBe(true);
    expect(hasDraftWork(base, { slug: "equities", state: "running" } as Drafting)).toBe(true);
    expect(hasDraftWork(latest(true), null)).toBe(true);
    expect(hasDraftWork(latest(false), null)).toBe(false);
  });
});
