import type { InjectionKey } from "vue";
import { friendlyDate, friendlyTime } from "./format";
import { draftingList, isLive } from "./drafting";
import type { Drafting, Overview, PreviousWeek, PreviousWeeks, ReportChoice, WeekChoice } from "./types";

export const APPROVED_BANNER = "All five sections of this week are approved. The read-only archive and the Word export are under Previous reports.";
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

/** Only this many of the newest weeks can be "midway" (rule 1), so an abandoned old draft cannot hold the default. */
export const MIDWAY_WEEKS = 3;

/**
 * The week to open on when nothing names one. 1: the newest of the MIDWAY_WEEKS newest weeks with a section drafting
 * or queued, or drafted and not fully approved. 2: else the newest week with no draft at all. 3: else the newest week.
 * `drafting` null (the overview could not be read) applies the rules on the statuses alone. Null for an empty list.
 */
export function defaultWeek(choices: WeekChoice[], drafting: Drafting[] | null): string | null {
  const weeks = [...choices].sort((a, b) => b.week_ending.localeCompare(a.week_ending));
  const live = new Set((drafting ?? []).filter((d) => isLive(d) && (d.report_type ?? "weekly") === "weekly").map((d) => d.period ?? ""));
  const midway = weeks.slice(0, MIDWAY_WEEKS).find((w) => live.has(w.period) || w.status === "in_progress");
  const fresh = weeks.find((w) => w.status === "not_started" && !live.has(w.period));
  return (midway ?? fresh ?? weeks[0])?.period ?? null;
}

/** The default period, after both reads, so it settles once: the API's default_week_ending only when there are no choices. */
export async function openingWeek(weeks: PreviousWeeks, readOverview: () => Promise<Overview>): Promise<string> {
  let drafting: Drafting[] | null = null;
  try {
    drafting = draftingList(await readOverview());
  } catch {
    // the statuses alone decide
  }
  return defaultWeek(weeks.choices ?? [], drafting) ?? `Week ending ${weeks.default_week_ending}`;
}

/** The opening report when the address names none; a failed read of the weeks is the unlabelled report. */
export async function openingReport(read: () => Promise<PreviousWeeks>, readOverview: () => Promise<Overview>): Promise<ReportChoice> {
  try {
    return { type: "weekly", period: await openingWeek(await read(), readOverview), kind: null };
  } catch {
    return defaultReport(null); // the overview read that follows says whether the API is reachable
  }
}

/** One week of the selector in words, so its state is never colour alone. */
export function weekChoiceLabel(c: WeekChoice): string {
  const state = c.status === "approved" ? "all five approved" : c.status === "in_progress" ? `${c.approved} of ${c.total} approved` : "not started";
  return `${friendlyDate(c.week_ending)}, ${state}`;
}

/** What one row of the list says, in words, so no state is shown by colour alone. */
export function weekRow(w: PreviousWeek): { title: string; status: string; approved: string; dev: string | null } {
  return {
    title: `Week ending ${friendlyDate(w.week_ending)}`,
    status: "All five approved",
    approved: w.approved_at ? `Last approved ${friendlyTime(w.approved_at)}` : "",
    dev: w.is_dev_draft ? DEV_LABEL : null,
  };
}
