import type { DismissReason, Review, Suggestion, SuggestionKind } from "./types";

/** The panel shows this many open suggestions until the analyst asks for all of them. */
export const TOP_N = 5;
/** The API's limit on a headline, counted in characters after whitespace is normalized. */
export const MAX_HEADLINE = 300;

export const DISMISS_REASONS: { value: DismissReason; label: string }[] = [
  { value: "not_relevant", label: "Not relevant" },
  { value: "already_covered", label: "Already covered" },
  { value: "figures_look_wrong", label: "Figures look wrong" },
  { value: "other", label: "Other" },
];

export const reasonLabel = (reason: DismissReason | null): string => DISMISS_REASONS.find((r) => r.value === reason)?.label ?? "";

export const KIND_LABELS: Record<SuggestionKind, string> = {
  streak: "Streak",
  record: "Record",
  since: "Since",
  trailing_compare: "Against recent weeks",
  threshold_cross: "Threshold crossed",
  expected_range: "Expected range",
  pace: "Pace",
  drift: "Drift",
};

const byRank = (a: Suggestion, b: Suggestion) => b.rank - a.rank || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/**
 * The suggestions split by what the analyst has done with them, each list highest rank first (ties by id, so the order
 * never shuffles). An open one has no decision; a restored one is open again; a selected one leaves the open list.
 */
export function partition(all: Suggestion[]): { open: Suggestion[]; selected: Suggestion[]; dismissed: Suggestion[] } {
  const sorted = [...all].sort(byRank);
  return {
    open: sorted.filter((s) => !s.decision),
    selected: sorted.filter((s) => s.decision?.decision === "selected"),
    dismissed: sorted.filter((s) => s.decision?.decision === "dismissed"),
  };
}

/** The open suggestions to show: the top five, or all of them once asked. */
export const shown = (open: Suggestion[], showAll: boolean): Suggestion[] => (showAll ? open : open.slice(0, TOP_N));

/** The wording to show and copy: the analyst's rewording if there is one, else the original. */
export const headlineOf = (s: Suggestion): string => s.decision?.edited_headline ?? s.headline;
export const isEdited = (s: Suggestion): boolean => !!s.decision?.edited_headline;

const normalized = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");

/** Why a reworded headline cannot be saved, in the API's terms (whitespace normalized, length in characters); null if it can. */
export function checkEdit(text: string): string | null {
  const t = normalized(text);
  if (!t) return "The headline cannot be empty.";
  if ([...t].length > MAX_HEADLINE) return `The headline can be at most ${MAX_HEADLINE} characters.`;
  return null;
}

/** The selected items as plain text, for the analyst to paste into their own notes. Empty when nothing is selected. */
export function selectedText(selected: Suggestion[], sectionTitle: string, weekEnding: string): string {
  if (!selected.length) return "";
  const lines = [`Selected for this week: ${sectionTitle}, week ending ${weekEnding}`, ""];
  selected.forEach((s, i) => {
    lines.push(`${i + 1}. ${headlineOf(s)}`, `   Source: ${s.provenance.label}`);
    if (isEdited(s)) lines.push(`   Original: ${s.headline}`);
  });
  return lines.join("\n");
}

const isFriday = (iso: string) => /^\d{4}-\d{2}-\d{2}$/.test(iso) && new Date(`${iso}T00:00:00Z`).getUTCDay() === 5;

/**
 * The report week (the Friday it ends on) of an open review, or null when it has none the panel can use: the period
 * "Week ending 2026-10-09", else the section's own week_ending, else a week_end that is a Friday. Weekly reports only.
 */
export function weekOfReview(review: Review): string | null {
  if (review.report_type !== "weekly") return null;
  const labelled = /^Week ending (\d{4}-\d{2}-\d{2})$/.exec(review.period);
  if (labelled) return labelled[1];
  const section = review.section as { week_ending?: string | null; week_end?: string | null };
  return [section.week_ending, section.week_end].find((d): d is string => !!d && isFriday(d)) ?? null;
}
