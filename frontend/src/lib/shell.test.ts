import { describe, expect, it } from "vitest";
import { createShell } from "./shell";
import type { Drafting, LatestRun, Overview, ReportChoice, SectionSummary } from "./types";

const TITLES: Record<string, string> = {
  company_updates: "Company Updates",
  fixed_income: "Fixed Income",
  equities: "Equities",
  real_estate: "Real Estate",
};
const WEEK = "Week ending 2026-10-09";
const counts = { total: 0, unresolved: 0, fix_needed: 0 };

function run(decision: "approved" | "rejected" | null): LatestRun {
  return {
    run_id: 1,
    run_date: "2026-10-09",
    this_week: true,
    current: true,
    decision,
    decided_at: decision ? "2026-10-09T10:00:00+00:00" : null,
    progress: { total: 3, resolved: 3, unresolved: 0, fix_needed: 0 },
    counts: { flagged: counts, not_auto_verified: counts, clean: counts },
    is_dev_draft: false,
    week_start: "2026-10-05",
    week_end: "2026-10-09",
    topic: null,
  };
}

function section(slug: string, latest: LatestRun | null = null, available = true): SectionSummary {
  return {
    slug,
    title: TITLES[slug],
    available,
    needs_topic: false,
    needs_text: false,
    requires_approved: false,
    uses_provider: true,
    reason: null,
    unblock: null,
    built_parts: [],
    subsections: [],
    charts: [],
    steps: [],
    latest,
  };
}

/** A weekly overview whose sections hold the given decisions (undefined: not drafted; "open": drafted, undecided). */
function overview(decisions: Record<string, "approved" | "rejected" | "open">, drafting: Drafting | null = null, type: "weekly" | "quarterly" = "weekly"): Overview {
  return {
    today: "2026-10-12",
    drafting,
    report: { type, title: type === "weekly" ? "Weekly" : "Quarterly Markets Review", period: WEEK, kind: null, published_as: "" },
    report_types: [],
    companion_kinds: [],
    sections: Object.keys(TITLES).map((slug) => {
      const d = decisions[slug];
      return section(slug, d === undefined ? null : run(d === "open" ? null : d));
    }),
  };
}

const states = (shell: ReturnType<typeof createShell>) => Object.fromEntries(shell.sections.value.map((s) => [s.slug, s.state]));
const never = () => Promise.reject(new Error("not called"));

describe("shell store", () => {
  it("knows nothing before it has read anything: no sections, no count", () => {
    const shell = createShell(never);
    expect(shell.sections.value).toEqual([]);
    expect(shell.approved.value).toBeNull();
    expect(shell.total.value).toBeNull();
  });

  it("takes each section's state and the approved count from the overview payload, as the overview's own tally does", () => {
    const shell = createShell(never);
    shell.setOverview(overview({ company_updates: "approved", fixed_income: "open", equities: "rejected" }));
    expect(states(shell)).toEqual({ company_updates: "approved", fixed_income: "in_review", equities: "rejected", real_estate: "not_drafted" });
    expect(shell.approved.value).toBe(1);
    expect(shell.total.value).toBe(4);
  });

  it("marks an unavailable section as such, and a section being drafted as drafting, only in the report it is drafting for", () => {
    const shell = createShell(never);
    const o = overview({}, { slug: "fixed_income", title: "Fixed Income", report_type: "weekly", period: WEEK, started_at: "", elapsed_seconds: 5, stale: false, stale_after_seconds: 3600 });
    o.sections[3] = section("real_estate", null, false);
    shell.setOverview(o);
    expect(states(shell)).toEqual({ company_updates: "not_drafted", fixed_income: "drafting", equities: "not_drafted", real_estate: "unavailable" });
    const other = overview({}, { slug: "fixed_income", title: "Fixed Income", report_type: "quarterly", period: "Q3'2026", started_at: "", elapsed_seconds: 5, stale: false, stale_after_seconds: 3600 });
    shell.setOverview(other);
    expect(states(shell).fixed_income).toBe("not_drafted");
  });

  it("updates after a rejection: unknown at once, then the rejected state, with the approved count unchanged", async () => {
    const reads: ReportChoice[] = [];
    let served = overview({ company_updates: "approved", fixed_income: "open" });
    const shell = createShell(async (report) => {
      reads.push(report);
      return served;
    });
    shell.setOverview(served);
    expect(states(shell).fixed_income).toBe("in_review");
    expect(shell.approved.value).toBe(1);

    // The coordinator rejects Fixed Income: the screen says every state is unknown until the payload is read again.
    served = overview({ company_updates: "approved", fixed_income: "rejected" });
    shell.invalidate();
    expect(states(shell)).toEqual({ company_updates: null, fixed_income: null, equities: null, real_estate: null });
    expect(shell.approved.value).toBeNull();
    expect(shell.sections.value.map((s) => s.title)).toEqual(["Company Updates", "Fixed Income", "Equities", "Real Estate"]); // still listed

    await shell.refreshFor("weekly", WEEK);
    expect(reads).toEqual([{ type: "weekly", period: WEEK, kind: null }]);
    expect(states(shell).fixed_income).toBe("rejected");
    expect(states(shell).company_updates).toBe("approved");
    expect(shell.approved.value).toBe(1); // a rejected section is not an approved one

    // Then it is drafted again and approved: the count follows.
    served = overview({ company_updates: "approved", fixed_income: "approved" });
    shell.invalidate();
    await shell.refreshFor("weekly", WEEK);
    expect(shell.approved.value).toBe(2);
  });

  it("leaves every state unknown when a read fails, never the earlier ones", async () => {
    const shell = createShell(() => Promise.reject(new Error("API down")));
    shell.setOverview(overview({ company_updates: "approved" }));
    await shell.refresh({ type: "weekly", period: WEEK, kind: null });
    expect(Object.values(states(shell))).toEqual([null, null, null, null]);
    expect(shell.approved.value).toBeNull();
  });

  it("drops a read that arrives after a newer one, and one begun before the states went stale", async () => {
    const pending: ((o: Overview) => void)[] = [];
    const shell = createShell(() => new Promise<Overview>((resolve) => pending.push(resolve)));
    const first = shell.refresh({ type: "weekly", period: WEEK, kind: null });
    const second = shell.refresh({ type: "weekly", period: WEEK, kind: null });
    pending[1](overview({ equities: "approved" }));
    await second;
    pending[0](overview({ equities: "rejected" })); // older answer, arriving late
    await first;
    expect(states(shell).equities).toBe("approved");

    const third = shell.refresh({ type: "weekly", period: WEEK, kind: null });
    shell.invalidate(); // something changed after that read began
    pending[2](overview({ equities: "rejected" }));
    await third;
    expect(states(shell).equities).toBeNull();
  });

  it("keeps a companion report's kind when it re-reads the report it already holds, and no kind for another", async () => {
    const reads: ReportChoice[] = [];
    const shell = createShell(async (report) => {
      reads.push(report);
      return overview({});
    });
    const o = overview({});
    o.report = { ...o.report, type: "companion", period: "#37.2026", kind: "kenya-listed-banks" };
    shell.setOverview(o);
    await shell.refreshFor("companion", "#37.2026");
    await shell.refreshFor("quarterly", "Q3'2026");
    expect(reads).toEqual([
      { type: "companion", period: "#37.2026", kind: "kenya-listed-banks" },
      { type: "quarterly", period: "Q3'2026", kind: null },
    ]);
  });
});
