import type { ReportType, RunEvent, RunEventKind } from "./types";

/** How one step line is marked. `working` is only ever a step that started and has not ended. */
export type StepMark = "working" | "done" | "skipped" | "failed";

export interface StepLine {
  /** The seq of the event that created the line: stable while a later event replaces its text in place. */
  key: number;
  text: string;
  mark: StepMark;
  /** True for the one line that is the latest unfinished step of a run still under way. */
  active: boolean;
}

const TERMINAL: RunEventKind[] = ["run_finished", "run_failed"];

export const isTerminal = (e: RunEvent) => TERMINAL.includes(e.kind);

/** `label` then a full stop, unless the label already ends a sentence (a headline ending in "?"). */
const stop = (label: string) => (/[.!?…]$/.test(label) ? label : `${label}.`);

/** `detail` after a sentence, or nothing when the event carries none. */
const then = (detail: string | null) => (detail ? ` ${detail}` : "");

/** The fixed wording of each event kind. Every word after the template comes from the event itself. */
function textOf(e: RunEvent): string {
  switch (e.kind) {
    case "run_started":
      return "Starting the draft.";
    case "source_started":
      return `Fetching ${stop(e.label)}`;
    case "source_finished":
      return `Fetched ${stop(e.label)}`;
    case "source_failed":
      return `Could not fetch ${stop(e.label)}${then(e.detail)}`;
    case "piece_started":
      return `Drafting ${stop(e.label)}`;
    case "piece_finished":
      return `Drafted ${stop(e.label)}`;
    case "part_skipped":
      return `Skipped ${stop(e.label)}${then(e.detail)}`;
    case "check_started":
      return `Checking ${stop(e.label)}`;
    case "check_finished": {
      const c = e.counts ?? { clean: 0, flagged: 0, not_auto_verified: 0 };
      return `Checked ${e.label}: ${c.clean} clean, ${c.flagged} flagged, ${c.not_auto_verified} not auto-verified.`;
    }
    case "run_finished":
      return "Draft ready for review.";
    case "run_failed":
      return `The draft stopped.${then(e.detail)}`;
  }
}

/** Which started kind an event closes, and how the closed line is marked. */
const CLOSES: Partial<Record<RunEventKind, { opens: RunEventKind; mark: StepMark }>> = {
  source_finished: { opens: "source_started", mark: "done" },
  source_failed: { opens: "source_started", mark: "failed" },
  piece_finished: { opens: "piece_started", mark: "done" },
  // A stub part is skipped outright; a piece whose search found nothing closes its own "Drafting" line the same way.
  part_skipped: { opens: "piece_started", mark: "skipped" },
  check_finished: { opens: "check_started", mark: "done" },
};
const OPENS: RunEventKind[] = ["source_started", "piece_started", "check_started"];

/**
 * The step list: one line per event, in arrival order, except that a step's closing event replaces its own
 * "started" line in place (matched on kind and label) instead of adding a second line.
 *
 * Nothing here is timed or guessed. A line is `working` only because its start arrived and its end has not; it is
 * `active` (the spinner) only while it is the latest such line of a run that has not ended. If the run failed with a
 * step still open, that step is where it stopped, so it is marked failed.
 */
export function stepLines(events: RunEvent[]): StepLine[] {
  const lines: StepLine[] = [];
  const open = new Map<string, number>(); // "<started kind>|<label>" -> index in `lines`
  let failed = false;
  let ended = false;
  for (const e of events) {
    if (isTerminal(e)) {
      ended = true;
      failed = e.kind === "run_failed";
    }
    const closes = CLOSES[e.kind];
    const at = closes ? open.get(`${closes.opens}|${e.label}`) : undefined;
    if (closes && at !== undefined) {
      lines[at] = { ...lines[at], text: textOf(e), mark: closes.mark };
      open.delete(`${closes.opens}|${e.label}`);
      continue;
    }
    const opening = OPENS.includes(e.kind);
    lines.push({
      key: e.seq,
      text: textOf(e),
      mark: opening ? "working" : e.kind === "run_failed" || e.kind === "source_failed" ? "failed" : closes?.mark ?? "done",
      active: false,
    });
    if (opening) open.set(`${e.kind}|${e.label}`, lines.length - 1);
  }
  const stillOpen = [...open.values()].sort((a, b) => a - b);
  if (failed) for (const i of stillOpen) lines[i] = { ...lines[i], mark: "failed" };
  else if (!ended && stillOpen.length) {
    const latest = stillOpen[stillOpen.length - 1];
    lines[latest] = { ...lines[latest], active: true };
  }
  return lines;
}

/** Events merged by seq, in order: the stream replays from the start, and a poll returns the whole list. */
export function mergeEvents(have: RunEvent[], more: RunEvent[]): RunEvent[] {
  if (more.length === 0) return have;
  const bySeq = new Map(have.map((e) => [e.seq, e]));
  let changed = false;
  for (const e of more) {
    if (!bySeq.has(e.seq)) {
      bySeq.set(e.seq, e);
      changed = true;
    }
  }
  return changed ? [...bySeq.values()].sort((a, b) => a.seq - b.seq) : have;
}

/** The overview of one report, optionally opening one saved review on it (how a finished run hands over). */
export function overviewHref(type: ReportType, period: string, reviewId?: number | null): string {
  const q = new URLSearchParams();
  if (type !== "weekly" || period) {
    q.set("report", type);
    if (period) q.set("period", period);
  }
  if (reviewId != null) q.set("review", String(reviewId));
  const search = q.toString();
  return search ? `/overview?${search}` : "/overview";
}
