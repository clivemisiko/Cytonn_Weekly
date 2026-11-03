import type { InjectionKey } from "vue";
import { friendlyDate, friendlyTime } from "./format";
import type { Overview, PreviousWeek, PreviousWeeks, ReportChoice } from "./types";

export const APPROVED_BANNER = "This week is fully approved. Find it under Previous reports.";
export const NO_WEEKS = "No approved weeks yet.";
export const DEV_LABEL = "Dev draft: watermarked, not for circulation";
/** Provided by a review shown under Previous reports: every decision and edit control is left out. */
export const READ_ONLY: InjectionKey<boolean> = Symbol("read-only-review");

/** Every section of a weekly overview has a current, approved newest run: the same rule as the export's. */
export function fullyApproved(overview: Overview): boolean {
  return (
    overview.report.type === "weekly" &&
    overview.sections.length > 0 &&
    overview.sections.every((s) => s.latest !== null && (s.latest.current ?? s.latest.this_week) && s.latest.decision === "approved")
  );
}

/** The report the overview opens on when the address names none: the API's default week, always labelled. Null (the
 *  route could not be read) falls back to the weekly report with no label. */
export function defaultReport(weekEnding: string | null): ReportChoice {
  return { type: "weekly", period: weekEnding ? `Week ending ${weekEnding}` : "", kind: null };
}

/** The opening report, read from GET /api/previous/weekly; a failed read is the unlabelled report and nothing else. */
export async function openingReport(read: () => Promise<PreviousWeeks>): Promise<ReportChoice> {
  try {
    return defaultReport((await read()).default_week_ending);
  } catch {
    return defaultReport(null); // the overview read that follows says whether the API is reachable
  }
}

/** What one row of the list says, in words, so no state is shown by colour alone. */
export function weekRow(w: PreviousWeek): { title: string; status: string; approved: string; dev: string | null } {
  return {
    title: `Week ending ${friendlyDate(w.week_ending)}`,
    status: "All six approved",
    approved: w.approved_at ? `Last approved ${friendlyTime(w.approved_at)}` : "",
    dev: w.is_dev_draft ? DEV_LABEL : null,
  };
}
