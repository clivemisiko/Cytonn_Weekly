import type { InjectionKey } from "vue";
import { friendlyDate, friendlyTime } from "./format";
import type { Overview, PreviousWeek, PreviousWeeks, ReportChoice, WeekChoice } from "./types";

export const APPROVED_BANNER = "All six sections of this week are approved. The read-only archive and the Word export are under Previous reports.";
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

/** The report the overview opens on when the address names none and no week was chosen here: the API's default week
 *  (the latest Friday), always labelled. Null (the route could not be read) falls back to the weekly report with no label. */
export function defaultReport(weekEnding: string | null): ReportChoice {
  return { type: "weekly", period: weekEnding ? `Week ending ${weekEnding}` : "", kind: null };
}

const WEEK_KEY = "cytonn-week";
const WEEK_PERIOD = /^Week ending \d{4}-\d{2}-\d{2}$/;

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // even touching it can throw
  }
}

/** The week this browser last chose, or null when none was or storage cannot be read. */
export function rememberedWeek(storage: Pick<Storage, "getItem"> | null = browserStorage()): string | null {
  try {
    const value = storage?.getItem(WEEK_KEY) ?? null;
    return value !== null && WEEK_PERIOD.test(value) ? value : null;
  } catch {
    return null;
  }
}

export function rememberWeek(period: string, storage: Pick<Storage, "setItem"> | null = browserStorage()): void {
  if (!WEEK_PERIOD.test(period)) return;
  try {
    storage?.setItem(WEEK_KEY, period);
  } catch {
    // Not remembered: the next visit opens on the latest Friday.
  }
}

/** The opening report: the week this browser last chose, else the API's default week; a failed read is the unlabelled report. */
export async function openingReport(read: () => Promise<PreviousWeeks>, remembered: string | null = rememberedWeek()): Promise<ReportChoice> {
  if (remembered) return { type: "weekly", period: remembered, kind: null };
  try {
    return defaultReport((await read()).default_week_ending);
  } catch {
    return defaultReport(null); // the overview read that follows says whether the API is reachable
  }
}

/** One week of the selector in words, so its state is never colour alone. */
export function weekChoiceLabel(c: WeekChoice): string {
  const state = c.status === "approved" ? "all six approved" : c.status === "in_progress" ? `${c.approved} of ${c.total} approved` : "not started";
  return `${friendlyDate(c.week_ending)}, ${state}`;
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
