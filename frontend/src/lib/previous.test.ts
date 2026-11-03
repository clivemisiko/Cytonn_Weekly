import { describe, expect, it } from "vitest";
import { APPROVED_BANNER, DEV_LABEL, NO_WEEKS, defaultReport, fullyApproved, openingReport, weekRow } from "./previous";
import type { LatestRun, Overview, PreviousWeek } from "./types";

const SLUGS = ["company_updates", "fixed_income", "equities", "real_estate", "digital_payments", "focus"];
const counts = { total: 0, unresolved: 0, fix_needed: 0 };

function run(decision: "approved" | "rejected" | null, current = true): LatestRun {
  return {
    run_id: 1, run_date: "2026-10-09", this_week: current, current, decision,
    decided_at: decision ? "2026-10-09T10:00:00+00:00" : null,
    progress: { total: 1, resolved: 1, unresolved: 0, fix_needed: 0 },
    counts: { flagged: counts, not_auto_verified: counts, clean: counts },
    is_dev_draft: false, week_start: "2026-10-05", week_end: "2026-10-09", topic: null,
  };
}

function overview(latest: (slug: string) => LatestRun | null, type: "weekly" | "quarterly" = "weekly"): Overview {
  return {
    today: "2026-10-12",
    drafting: null,
    report: { type, title: "Weekly", period: "Week ending 2026-10-09", kind: null, published_as: "" },
    report_types: [],
    companion_kinds: [],
    sections: SLUGS.map((slug) => ({
      slug, title: slug, available: true, needs_topic: false, needs_text: false, requires_approved: false, uses_provider: false,
      reason: null, unblock: null, built_parts: [], subsections: [], charts: [], steps: [], latest: latest(slug),
    })),
  } as Overview;
}

const week = (over: Partial<PreviousWeek> = {}): PreviousWeek => ({
  period: "Week ending 2026-10-09", week_ending: "2026-10-09", approved_at: "2026-10-12T07:30:00+00:00",
  is_dev_draft: false, can_export: true, sections: [], ...over,
});

describe("the approved-week banner", () => {
  it("shows when every section's newest run is approved", () => {
    expect(fullyApproved(overview(() => run("approved")))).toBe(true);
    expect(APPROVED_BANNER).toBe("This week is fully approved. Find it under Previous reports.");
  });

  it("does not show when one section is in review, rejected or not drafted", () => {
    expect(fullyApproved(overview((s) => run(s === "focus" ? null : "approved")))).toBe(false);
    expect(fullyApproved(overview((s) => run(s === "equities" ? "rejected" : "approved")))).toBe(false);
    expect(fullyApproved(overview((s) => (s === "focus" ? null : run("approved"))))).toBe(false);
  });

  it("does not show for an old unlabelled run or another report type", () => {
    expect(fullyApproved(overview((s) => run("approved", s !== "focus")))).toBe(false);
    expect(fullyApproved(overview(() => run("approved"), "quarterly"))).toBe(false);
  });
});

describe("the overview's default week", () => {
  const weeks = { weeks: [], next_week_ending: null, default_week_ending: "2026-10-16" };

  it("is the API's default week, labelled", async () => {
    expect(defaultReport("2026-10-16")).toEqual({ type: "weekly", period: "Week ending 2026-10-16", kind: null });
    expect(await openingReport(() => Promise.resolve(weeks))).toEqual({ type: "weekly", period: "Week ending 2026-10-16", kind: null });
  });

  it("falls back to the unlabelled weekly report when the route cannot be read", async () => {
    expect(await openingReport(() => Promise.reject(new Error("unreachable")))).toEqual({ type: "weekly", period: "", kind: null });
  });
});

describe("the Previous reports list", () => {
  it("says each row's state in words", () => {
    const row = weekRow(week());
    expect(row.title).toBe("Week ending 9 Oct 2026");
    expect(row.status).toBe("All six approved");
    expect(row.approved).toBe("Last approved 12 Oct 2026, 10:30 EAT");
    expect(row.dev).toBeNull();
  });

  it("labels a dev-draft week in text, not colour alone", () => {
    expect(weekRow(week({ is_dev_draft: true })).dev).toBe(DEV_LABEL);
  });

  it("has an empty state", () => {
    expect(NO_WEEKS).toBe("No approved weeks yet.");
  });
});
