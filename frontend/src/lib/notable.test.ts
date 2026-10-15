import { describe, expect, it } from "vitest";
import {
  DISMISS_REASONS,
  TOP_N,
  checkEdit,
  headlineOf,
  isEdited,
  partition,
  selectedText,
  shown,
  weekOfReview,
} from "./notable";
import type { Review, Suggestion, SuggestionDecision } from "./types";

const decision = (over: Partial<SuggestionDecision> = {}): SuggestionDecision => ({
  decision: "selected",
  edited_headline: null,
  dismiss_reason: null,
  decided_at: "2026-10-09T08:00:00Z",
  ...over,
});

function s(id: string, rank: number, over: Partial<Suggestion> = {}): Suggestion {
  return {
    id,
    kind: "streak",
    section: "fixed_income",
    week_ending: "2026-10-09",
    headline: `Headline ${id}.`,
    figures: [],
    working: { series: "91-day yield", rule: "Three rises in a row.", window: "last 12 weeks", points: [] },
    provenance: { kind: "demo", label: "invented demo item" },
    rank,
    version: 1,
    decision: null,
    ...over,
  };
}

describe("partition", () => {
  it("orders each list by rank, highest first, then by id, and splits on the decision", () => {
    const all = [
      s("c", 40),
      s("a", 90),
      s("b", 90),
      s("d", 10, { decision: decision() }),
      s("e", 70, { decision: decision({ decision: "selected", edited_headline: "Mine." }) }),
      s("f", 60, { decision: decision({ decision: "dismissed", dismiss_reason: "other" }) }),
    ];
    const p = partition(all);
    expect(p.open.map((x) => x.id)).toEqual(["a", "b", "c"]);
    expect(p.selected.map((x) => x.id)).toEqual(["e", "d"]);
    expect(p.dismissed.map((x) => x.id)).toEqual(["f"]);
  });

  it("does not change the list it is given", () => {
    const all = [s("a", 1), s("b", 2)];
    partition(all);
    expect(all.map((x) => x.id)).toEqual(["a", "b"]);
  });

  it("puts a restored item back among the open ones in rank order, and a selected one out of them", () => {
    const before = partition([s("a", 90), s("b", 50, { decision: decision({ decision: "dismissed" }) }), s("c", 20)]);
    expect(before.open.map((x) => x.id)).toEqual(["a", "c"]);
    const restored = partition([s("a", 90), s("b", 50), s("c", 20)]);
    expect(restored.open.map((x) => x.id)).toEqual(["a", "b", "c"]);
    expect(restored.dismissed).toEqual([]);
    const picked = partition([s("a", 90, { decision: decision() }), s("b", 50), s("c", 20)]);
    expect(picked.open.map((x) => x.id)).toEqual(["b", "c"]);
  });
});

describe("shown (top five, then show all)", () => {
  const seven = Array.from({ length: 7 }, (_, i) => s(`s${i}`, 100 - i));
  it("keeps to the top five until asked for all", () => {
    expect(TOP_N).toBe(5);
    expect(shown(seven, false).map((x) => x.id)).toEqual(["s0", "s1", "s2", "s3", "s4"]);
    expect(shown(seven, true)).toHaveLength(7);
  });
  it("shows everything when there are five or fewer", () => {
    expect(shown(seven.slice(0, 5), false)).toHaveLength(5);
    expect(shown([], false)).toEqual([]);
  });
});

describe("the analyst's wording", () => {
  it("prefers the edited headline and says when there is one", () => {
    const plain = s("a", 1);
    const edited = s("b", 1, { decision: decision({ edited_headline: "Reworded." }) });
    expect([headlineOf(plain), isEdited(plain)]).toEqual(["Headline a.", false]);
    expect([headlineOf(edited), isEdited(edited)]).toEqual(["Reworded.", true]);
    expect(isEdited(s("c", 1, { decision: decision({ decision: "dismissed" }) }))).toBe(false);
  });

  it("refuses an empty or over-long edit and accepts the rest, counted as the API counts", () => {
    expect(checkEdit("   ")).toMatch(/cannot be empty/);
    expect(checkEdit("x".repeat(301))).toMatch(/at most 300/);
    expect(checkEdit("x".repeat(300))).toBeNull();
    expect(checkEdit("  A reworded sentence. ")).toBeNull();
  });

  it("names every dismissal reason in plain words, in the API's keys", () => {
    expect(DISMISS_REASONS.map((r) => r.value)).toEqual(["not_relevant", "already_covered", "figures_look_wrong", "other"]);
    expect(DISMISS_REASONS.map((r) => r.label)).toEqual(["Not relevant", "Already covered", "Figures look wrong", "Other"]);
  });
});

describe("selectedText (the copyable worklist)", () => {
  const picked = [
    s("a", 90, { decision: decision(), provenance: { kind: "published", label: "CBK weekly bulletin" } }),
    s("b", 50, { decision: decision({ edited_headline: "Reworded." }) }),
  ];
  it("lists each selected item with its source, and the original beside an edit", () => {
    expect(selectedText(picked, "Fixed Income", "2026-10-09")).toBe(
      [
        "Selected for this week: Fixed Income, week ending 2026-10-09",
        "",
        "1. Headline a.",
        "   Source: CBK weekly bulletin",
        "2. Reworded.",
        "   Source: invented demo item",
        "   Original: Headline b.",
      ].join("\n"),
    );
  });
  it("is empty when nothing is selected", () => {
    expect(selectedText([], "Fixed Income", "2026-10-09")).toBe("");
  });
});

describe("weekOfReview", () => {
  const review = (over: Record<string, unknown>) => ({ report_type: "weekly", period: "", section: {}, ...over }) as unknown as Review;
  it("takes the week from a labelled weekly period", () => {
    expect(weekOfReview(review({ period: "Week ending 2026-10-09" }))).toBe("2026-10-09");
  });
  it("else from the section's week_ending, else from a week_end that is a Friday", () => {
    expect(weekOfReview(review({ section: { week_ending: "2026-10-02", week_end: "2026-10-03" } }))).toBe("2026-10-02");
    expect(weekOfReview(review({ section: { week_end: "2026-10-02" } }))).toBe("2026-10-02");
  });
  it("is null when no Friday is known, and for every report but the weekly", () => {
    expect(weekOfReview(review({ section: { week_end: "2026-10-03" } }))).toBeNull(); // a Saturday
    expect(weekOfReview(review({}))).toBeNull();
    expect(weekOfReview(review({ report_type: "quarterly", period: "Q3'2026", section: { week_end: "2026-10-02" } }))).toBeNull();
  });
});
