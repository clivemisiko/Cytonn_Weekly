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

/**
 * The figures of a suggestion as the card prints them on one line. A label may hold a colon of its own ("<series>: latest"),
 * so the value is joined with " = " and not with another colon.
 */
export const figureLine = (figures: Suggestion["figures"]): string => figures.map((f) => `${f.label} = ${f.display}`).join("; ");

// -- the line chart in "Show working" ------------------------------------------------------------------------------------
// Geometry only: where each of the working's points and labels go in a drawing exactly as wide as its box. A point's value sets
// its position and its display string is the only text the chart prints for it; the chart works out no figure of its own.

type WorkingPoint = Suggestion["working"]["points"][number];

/** JetBrains Mono at 12px advances 0.6em, so a label is its length times this wide. */
export const CHAR_W = 7.2;
export const CHART_H = 150;
const TOP = 24; // above the highest point: its dot, and a label above it
const FOOT = 50; // below the lowest point: a label below it, then the dates
const MIN_PLOT = 160; // the line keeps at least this much; with less beside it the labels go above and below instead
const SIDE = 8; // beside the end dots when the labels are above and below: the dot's radius and a little over

export interface ChartDot extends WorkingPoint {
  x: number;
  y: number;
}
/** A line of text: where it is anchored and its baseline. */
export interface ChartLabel {
  text: string;
  x: number;
  y: number;
  anchor: "start" | "end";
}
/** One end of the scale: the height of its hairline, and its label. */
export interface ScaleMark {
  y: number;
  text: string;
  x: number;
  ty: number;
  anchor: "start";
}
export interface ChartGeometry {
  /** The drawing's width in pixels: always the width asked for, so the chart never scrolls. */
  width: number;
  height: number;
  /** The plot's edges: the x of the oldest and of the latest point, the y of the highest and of the lowest value. */
  left: number;
  right: number;
  top: number;
  bottom: number;
  /** True when the box is too narrow to keep 160px for the line beside the labels: the scale labels then sit above the top
   *  line and below the foot line, and the latest label above or below its dot. */
  compact: boolean;
  dots: ChartDot[];
  oldest: ChartDot;
  latest: ChartDot;
  /** The display strings of the highest and the lowest points, highest first; one when they coincide. */
  scale: ScaleMark[];
  latestLabel: ChartLabel;
  /** Where the dates go, under the ends; the text is the page's to format. The oldest is left out when it would crowd the latest. */
  dates: { oldest: { x: number; y: number; anchor: "start" } | null; latest: { x: number; y: number; anchor: "end" } };
}

const round2 = (n: number) => Math.round(n * 100) / 100;
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).getTime() / 86_400_000;

/**
 * Where the working's points go in a drawing `widthIn` pixels wide. X is proportional to the date, so a gap looks like a gap;
 * y runs from the lowest value to the highest with padding above and below; a flat series, and a single point, sit in the
 * middle. Wide: room is kept at the left for the longest scale label and at the right for the latest point's own label.
 * Compact (a phone): the plot takes the whole width, the scale labels go above the top line and below the foot line, and the
 * latest label goes above its dot, or below it when the line arrives from above, so it is always inside the box.
 */
export function chartGeometry(points: WorkingPoint[], widthIn: number): ChartGeometry | null {
  if (!points.length) return null;
  const width = Math.max(40, widthIn);
  const last = points[points.length - 1];
  const lo = points.reduce((a, p) => (p.value < a.value ? p : a));
  const hi = points.reduce((a, p) => (p.value > a.value ? p : a));
  const gutter = Math.max(lo.display.length, hi.display.length) * CHAR_W + 8;
  const reserve = last.display.length * CHAR_W + 14;
  const compact = width - reserve - gutter < MIN_PLOT;
  const left = round2(compact ? SIDE : gutter);
  const right = round2(compact ? width - SIDE : width - reserve);
  const top = TOP;
  const bottom = CHART_H - FOOT;
  const mid = round2((top + bottom) / 2);
  const t0 = day(points[0].date);
  const span = day(last.date) - t0;
  const spread = hi.value - lo.value;
  const dots: ChartDot[] = points.map((p) => ({
    ...p,
    x: round2(span > 0 ? left + ((day(p.date) - t0) / span) * (right - left) : right),
    y: round2(spread > 0 ? bottom - ((p.value - lo.value) / spread) * (bottom - top) : mid),
  }));
  const latest = dots[dots.length - 1];
  const before = dots.length > 1 ? dots[dots.length - 2] : null;

  const mark = (y: number, text: string, ty: number): ScaleMark => ({ y, text, x: 0, ty: round2(ty), anchor: "start" });
  const scale: ScaleMark[] =
    spread > 0
      ? compact
        ? [mark(top, hi.display, top - 7), mark(bottom, lo.display, bottom + 17)]
        : [mark(top, hi.display, top + 4), mark(bottom, lo.display, bottom + 4)]
      : [mark(mid, hi.display, compact ? mid - 7 : mid + 4)];

  const fromAbove = !!before && before.y < latest.y; // the line arrives from above: the label goes below the dot
  const latestLabel: ChartLabel = compact
    ? { text: last.display, x: round2(latest.x + 5), y: round2(fromAbove ? latest.y + 18 : latest.y - 10), anchor: "end" }
    : { text: last.display, x: round2(latest.x + 10), y: round2(latest.y + 4), anchor: "start" };

  const y = CHART_H - 8;
  return {
    width,
    height: CHART_H,
    left,
    right,
    top,
    bottom,
    compact,
    dots,
    oldest: dots[0],
    latest,
    scale,
    latestLabel,
    dates: {
      oldest: dots.length > 1 && right - left >= 150 ? { x: dots[0].x, y, anchor: "start" } : null,
      latest: { x: round2(compact ? latest.x + 5 : latest.x), y, anchor: "end" },
    },
  };
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
