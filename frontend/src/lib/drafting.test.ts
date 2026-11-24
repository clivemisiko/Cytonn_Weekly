import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, ref } from "vue";
import { attentionList, canRedraft, draftingFor, draftingList, draftingStatus, isDraftingThis, ownBusy, reattachHref, reportCounts, runHref, sectionAction, useLiveElapsed } from "./drafting";
import { elapsed } from "./format";
import type { Drafting, Overview, ReportChoice, SectionSummary } from "./types";

const WEEK = "Week ending 2026-10-09";
const weekly: ReportChoice = { type: "weekly", period: WEEK, kind: null };
const draft = (over: Partial<Drafting> = {}): Drafting => ({
  slug: "equities",
  title: "Equities",
  report_type: "weekly",
  period: WEEK,
  started_at: "2026-10-09T10:00:00+00:00",
  elapsed_seconds: 134,
  stale: false,
  stale_after_seconds: 3600,
  run_id: "abc123",
  ...over,
});

describe("the counter's text", () => {
  it("is m:ss under an hour and h:mm:ss after", () => {
    expect(elapsed(134)).toBe("2:14");
    expect(elapsed(9)).toBe("0:09");
    expect(elapsed(3599)).toBe("59:59");
    expect(elapsed(3600 + 125)).toBe("1:02:05");
  });
});

describe("useLiveElapsed", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("counts on from the server's figure, and a remount starts from the server's new figure, not from zero", () => {
    const first = effectScope();
    const a = ref<Drafting | null>(draft({ elapsed_seconds: 134 }));
    const one = first.run(() => useLiveElapsed(a))!;
    expect(one.value).toBe(134);
    vi.advanceTimersByTime(5_000);
    expect(one.value).toBe(139);
    first.stop(); // the page is left

    vi.advanceTimersByTime(60_000); // the draft keeps running meanwhile; coming back reads the server again
    const second = effectScope();
    const two = second.run(() => useLiveElapsed(ref<Drafting | null>(draft({ elapsed_seconds: 199 }))))!;
    expect(two.value).toBe(199);
    vi.advanceTimersByTime(3_000);
    expect(two.value).toBe(202);
    second.stop();
  });

  it("restarts from each fresh read while mounted", () => {
    const d = ref<Drafting | null>(draft({ elapsed_seconds: 10 }));
    const scope = effectScope();
    const seconds = scope.run(() => useLiveElapsed(d))!;
    vi.advanceTimersByTime(4_000);
    expect(seconds.value).toBe(14);
    d.value = draft({ elapsed_seconds: 30 });
    return Promise.resolve().then(() => {
      expect(seconds.value).toBe(30);
      scope.stop();
    });
  });

  it("does not count on for a draft the server calls stuck", () => {
    const scope = effectScope();
    const seconds = scope.run(() => useLiveElapsed(ref<Drafting | null>(draft({ elapsed_seconds: 4000, stale: true }))))!;
    vi.advanceTimersByTime(10_000);
    expect(seconds.value).toBe(4000);
    scope.stop();
  });
});

describe("where a draft that is running leads", () => {
  it("links the overview to the run's page, and to nothing when idle or when the server named no run", () => {
    expect(runHref(draft())).toBe("/runs/abc123");
    expect(runHref(null)).toBeNull();
    expect(runHref(draft({ run_id: null }))).toBeNull();
    expect(runHref(draft({ run_id: undefined }))).toBeNull();
  });

  it("reattaches a section to its own running draft (same section, week, type and period) and not to another's", () => {
    expect(reattachHref(draft(), "equities", weekly)).toBe("/runs/abc123");
    expect(reattachHref(draft(), "fixed_income", weekly)).toBeNull(); // another section: the screen links to it instead
    expect(reattachHref(draft(), "equities", { ...weekly, period: "Week ending 2026-10-02" })).toBeNull();
    expect(reattachHref(draft(), "equities", { type: "quarterly", period: "Q3'2026", kind: null })).toBeNull();
    expect(reattachHref(null, "equities", weekly)).toBeNull();
  });

  it("does not reattach to a stuck draft, and a new draft is then allowed, as the server allows it", () => {
    const stuck = draft({ stale: true, elapsed_seconds: 4000 });
    expect(isDraftingThis(stuck, "equities", weekly)).toBe(true);
    expect(reattachHref(stuck, "equities", weekly)).toBeNull();
    expect(ownBusy(true, stuck)).toBe(false);
    expect(ownBusy(true, draft())).toBe(true); // its own live draft still blocks it
    expect(ownBusy(true, draft({ state: "queued", position: 2 }))).toBe(true);
    expect(ownBusy(true, draft({ state: "failed" }))).toBe(false);
  });

  it("finds a section's own entry in the list; another section drafting never counts", () => {
    const list = [draft({ slug: "fixed_income" }), draft({ state: "queued", position: 2 })];
    expect(draftingFor(list, "equities", weekly)?.state).toBe("queued");
    expect(draftingFor(list, "real_estate", weekly)).toBeNull();
    expect(draftingFor([draft({ state: "failed" }), draft()], "equities", weekly)?.state).toBeUndefined(); // a live one wins
    expect(draftingList({ drafting: draft(), drafting_list: undefined })).toHaveLength(1); // an older API
    expect(draftingList({ drafting: null, drafting_list: undefined })).toEqual([]);
    expect(draftingStatus(draft({ state: "queued", position: 3 }))).toBe("Queued, 2 ahead");
    expect(draftingStatus(draft())).toBe("Being drafted now");
  });
});

describe("the report's figures, its attention list and each section's action (the overview and the chooser share them)", () => {
  const sec = (slug: string, decision: string | null | undefined, flagged = 0, over: Partial<SectionSummary> = {}) =>
    ({
      slug,
      title: slug,
      available: true,
      requires_approved: false,
      latest: decision === undefined ? null : { run_id: slug.length, current: true, this_week: true, decision, counts: { flagged: { total: flagged } } },
      ...over,
    }) as unknown as SectionSummary;
  const overview = (sections: SectionSummary[], drafting_list: Drafting[] = []) => ({ sections, drafting: null, drafting_list }) as unknown as Overview;

  it("counts approved, in review, flagged and drafting from the payload", () => {
    const o = overview([sec("a", "approved"), sec("bb", null, 3), sec("ccc", undefined), sec("dddd", null, 0, { available: false })], [draft({ slug: "ccc" })]);
    expect(reportCounts(o)).toEqual({ approved: 1, inReview: 1, flagged: 3, drafting: 1 });
  });

  it("orders the attention list: a stopped draft, a rejection, flagged, ready, not drafted; a running one is left out", () => {
    const o = overview(
      [sec("ready", null), sec("none", undefined), sec("flag", null, 2), sec("rej", "rejected"), sec("stop", undefined), sec("run", undefined), sec("ok", "approved")],
      [draft({ slug: "stop", state: "failed" }), draft({ slug: "run" })],
    );
    expect(attentionList(o, weekly).map((a) => [a.slug, a.why])).toEqual([
      ["stop", "The last draft stopped"],
      ["rej", "Rejected: draft it again"],
      ["flag", "2 items flagged"],
      ["ready", "Ready for a decision"],
      ["none", "Not drafted yet"],
    ]);
  });

  it("offers Resume review, Draft section, View review or nothing, and Draft again only once there is a review", () => {
    expect(sectionAction(sec("a", null))?.label).toBe("Resume review");
    expect(sectionAction(sec("a", undefined))?.label).toBe("Draft section");
    expect(sectionAction(sec("a", undefined, 0, { requires_approved: true }))?.label).toBe("Compose summary");
    expect(sectionAction(sec("a", "approved"))?.label).toBe("View review");
    expect(sectionAction(sec("a", undefined, 0, { available: false }))).toBeNull();
    expect([sec("a", null), sec("a", "approved"), sec("a", "rejected"), sec("a", undefined)].map(canRedraft)).toEqual([true, true, true, false]);
  });
});
