import { describe, expect, it } from "vitest";
import {
  DISMISS_REASONS,
  TOP_N,
  CHAR_W,
  checkEdit,
  chartGeometry,
  figureLine,
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

describe("figureLine", () => {
  const fig = (label: string, display: string) => ({ label, value: 0, display, unit: "" });
  it("puts one separator between a figure's label and its value, however the label is built", () => {
    // the library builds some labels as "<series>: <what>"; joining them with another colon read "...: latest: 9.05%"
    const line = figureLine([fig("Weeks in a row", "9"), fig("Invented 91-day yield: latest", "9.05%")]);
    expect(line).toBe("Weeks in a row = 9; Invented 91-day yield: latest = 9.05%");
    expect(line).not.toContain("latest: 9.05%");
  });
  it("is empty when there are no figures", () => {
    expect(figureLine([])).toBe("");
  });
});

describe("chartGeometry", () => {
  const pt = (date: string, value: number, display = `${value.toFixed(2)}%`) => ({ date, value, display });
  const WEEKLY = [
    pt("2026-09-11", 8.1),
    pt("2026-09-18", 8.4),
    pt("2026-09-25", 8.2),
    pt("2026-10-02", 9.0),
    pt("2026-10-09", 9.05),
  ];

  it("is null when there are no points", () => {
    expect(chartGeometry([], 400)).toBeNull();
  });

  it("puts the oldest point on the left edge of the plot and the latest on the right edge, in the order given", () => {
    const g = chartGeometry(WEEKLY, 400)!;
    expect(g.dots.map((d) => d.date)).toEqual(WEEKLY.map((p) => p.date));
    expect(g.oldest).toBe(g.dots[0]);
    expect(g.latest).toBe(g.dots[4]);
    expect(g.oldest.x).toBeCloseTo(g.left, 5);
    expect(g.latest.x).toBeCloseTo(g.right, 5);
    expect(g.right).toBeGreaterThan(g.left);
    expect(g.right).toBeLessThan(400);
  });

  it("spaces points by the days between their dates, so a gap looks like a gap", () => {
    const g = chartGeometry([pt("2026-09-11", 8), pt("2026-09-18", 8.1), pt("2026-10-09", 8.2), pt("2026-10-16", 8.3)], 500)!;
    const [a, b, c, d] = g.dots.map((x) => x.x);
    const week = b - a;
    expect(week).toBeGreaterThan(0);
    expect(c - b).toBeCloseTo(3 * week, 1); // 21 days after a 7-day step
    expect(d - c).toBeCloseTo(week, 1);
  });

  it("puts a higher value higher up (a smaller y), the lowest at the foot of the scale and the highest at its head", () => {
    const g = chartGeometry(WEEKLY, 400)!;
    const ys = g.dots.map((d) => d.y);
    expect(Math.min(...ys)).toBeCloseTo(g.top, 5); // 9.05
    expect(Math.max(...ys)).toBeCloseTo(g.bottom, 5); // 8.1
    expect(ys[4]).toBeLessThan(ys[0]);
    expect(ys[3]).toBeLessThan(ys[2]);
    expect(g.top).toBeGreaterThan(0); // padding above the highest point and below the lowest, inside the drawing
    expect(g.bottom).toBeLessThan(g.height);
    // y is linear in the value
    const frac = (v: number) => (g.bottom - ((v - 8.1) / (9.05 - 8.1)) * (g.bottom - g.top));
    expect(g.dots[1].y).toBeCloseTo(frac(8.4), 1);
  });

  it("labels the scale with the display strings of the lowest and the highest points, never a number it made itself", () => {
    const g = chartGeometry([pt("2026-09-25", 3, "Kshs 3.0 bn"), pt("2026-10-02", 1, "Kshs 1.0 bn"), pt("2026-10-09", 2, "Kshs 2.0 bn")], 400)!;
    expect(g.scale).toEqual([
      { y: g.top, text: "Kshs 3.0 bn" },
      { y: g.bottom, text: "Kshs 1.0 bn" },
    ]);
  });

  it("makes room at the left for the longest scale label and at the right for the latest point's own label", () => {
    const g = chartGeometry([pt("2026-09-25", 3, "Kshs 1,000.0 bn"), pt("2026-10-09", 1, "Kshs 9.0 bn")], 600)!;
    expect(g.left).toBeGreaterThanOrEqual("Kshs 1,000.0 bn".length * CHAR_W);
    expect(600 - g.right).toBeGreaterThanOrEqual("Kshs 9.0 bn".length * CHAR_W);
  });

  it("works with negative values", () => {
    const g = chartGeometry([pt("2026-10-02", -0.2, "(0.20%)"), pt("2026-10-09", -0.5, "(0.50%)")], 400)!;
    expect(g.dots[0].y).toBeCloseTo(g.top, 5);
    expect(g.dots[1].y).toBeCloseTo(g.bottom, 5);
    expect(g.scale.map((s) => s.text)).toEqual(["(0.20%)", "(0.50%)"]);
  });

  it("draws a flat series as a flat line through the middle, with one scale label", () => {
    const g = chartGeometry([pt("2026-09-25", 9), pt("2026-10-02", 9), pt("2026-10-09", 9)], 400)!;
    const mid = (g.top + g.bottom) / 2;
    expect(g.dots.map((d) => d.y)).toEqual([mid, mid, mid]);
    expect(g.scale).toEqual([{ y: mid, text: "9.00%" }]);
  });

  it("draws one point as one dot at the right end, centred, with one scale label", () => {
    const g = chartGeometry([pt("2026-10-09", 9.05)], 400)!;
    expect(g.dots).toHaveLength(1);
    expect(g.oldest).toBe(g.latest);
    expect(g.latest.x).toBeCloseTo(g.right, 5);
    expect(g.latest.y).toBeCloseTo((g.top + g.bottom) / 2, 5);
    expect(g.scale).toEqual([{ y: g.latest.y, text: "9.05%" }]);
  });

  it("keeps a usable plot when the width is very small: the drawing is widened, never inverted", () => {
    const g = chartGeometry(WEEKLY, 60)!;
    expect(g.right - g.left).toBeGreaterThanOrEqual(160); // room for the oldest and the latest date under the two ends
    expect(g.width).toBeGreaterThanOrEqual(g.right);
  });

  it("rounds every coordinate to two decimals", () => {
    const g = chartGeometry(WEEKLY, 333)!;
    for (const n of [g.left, g.right, g.top, g.bottom, ...g.dots.flatMap((d) => [d.x, d.y])]) {
      expect(Math.abs(n * 100 - Math.round(n * 100))).toBeLessThan(1e-6);
    }
  });
});
