import { type MaybeRefOrGetter, computed, ref, toValue, watch, watchEffect } from "vue";
import * as api from "./api";
import { friendlyDate, plural } from "./format";
import type { AppConfig, Drafting, Overview, ReportChoice, SectionSummary } from "./types";

const POLL_MS = 5_000;

/** Every draft the server reports (running, queued, or a section's newest failure); an older API sends the one only. */
export const draftingList = (o: Pick<Overview, "drafting" | "drafting_list">): Drafting[] =>
  o.drafting_list ?? (o.drafting ? [o.drafting] : []);

/** Whether the entry is a draft that has not ended (a failed entry only explains why a section has no new draft). */
export const isLive = (d: Drafting | null): d is Drafting => d !== null && d.state !== "failed";

/**
 * Re-reads the overview of the report on screen every few seconds while a draft is running or queued on the server, so
 * the screen shows it start, move up the queue and finish (and the run it saved) without a reload. Stops as soon as
 * nothing is live; a failed poll is simply retried.
 */
export function useDraftingPoll(
  drafting: MaybeRefOrGetter<Drafting[]>,
  onOverview: (next: Overview) => void,
  report: MaybeRefOrGetter<ReportChoice>,
  enabled: MaybeRefOrGetter<boolean> = true,
) {
  // A boolean, so a fresh list from each poll does not restart the timer.
  const active = computed(() => toValue(enabled) && toValue(drafting).some(isLive));
  const key = computed(() => JSON.stringify([toValue(report).type, toValue(report).period, toValue(report).kind]));
  watchEffect((onCleanup) => {
    if (!active.value) return;
    const [type, period, kind] = JSON.parse(key.value) as [ReportChoice["type"], string, string | null];
    let live = true;
    const id = setInterval(async () => {
      try {
        const next = await api.getOverview({ type, period, kind });
        if (live) onOverview(next);
      } catch {
        /* the API blinked: try again next tick */
      }
    }, POLL_MS);
    onCleanup(() => {
      live = false;
      clearInterval(id);
    });
  });
}

/** Whether the running draft is this section of this report (the same slug drafts in several report types). */
export const isDraftingThis = (drafting: Drafting | null, slug: string, report: ReportChoice) =>
  drafting !== null &&
  drafting.slug === slug &&
  (drafting.report_type ?? "weekly") === report.type &&
  (drafting.period ?? "") === report.period;

/** The entry for this section of this report that is running or queued, or the newest failure, or null. A live entry wins. */
export function draftingFor(list: Drafting[], slug: string, report: ReportChoice): Drafting | null {
  const mine = list.filter((d) => isDraftingThis(d, slug, report));
  return mine.find(isLive) ?? mine[0] ?? null;
}

/** "Queued, 2 ahead" (position 1 is next in line). */
export function queueText(position: number | null | undefined): string {
  const ahead = Math.max(0, (position ?? 1) - 1);
  return ahead === 0 ? "Queued, next in line" : `Queued, ${ahead} ahead`;
}

/** "Being drafted now" or "Queued, 2 ahead". */
export const draftingStatus = (d: Drafting): string => (d.state === "queued" ? queueText(d.position) : "Being drafted now");

/**
 * The two checks every draft button makes, in one place: a section that calls the LLM waits only while it is itself
 * running or queued (unless that draft looks stuck, which a new draft replaces), and while the provider cannot run.
 * Another section drafting never holds it up. A section that calls no provider (the Executive Summary)
 * is never held up by either.
 */
export const ownBusy = (llm: boolean, mine: Drafting | null) => llm && isLive(mine) && !mine.stale;
export const providerOff = (llm: boolean, config: AppConfig) => llm && !!config.provider_problem;

/** Why "Draft again" is off on this section's card (the same checks as the start screen's draft button), or null. */
export function draftAgainOff(s: SectionSummary, mine: Drafting | null, config: AppConfig): string | null {
  if (providerOff(s.uses_provider, config)) return `${config.provider_problem} Drafting is off until then.`;
  if (!ownBusy(s.uses_provider, mine)) return null;
  return `${draftingStatus(mine!)}.`;
}

/** The page of a running draft (its steps and counter), or null when the server named no run for it. */
export const runHref = (drafting: Drafting | null) => (drafting?.run_id ? `/runs/${drafting.run_id}` : null);

/** Where a section's screen goes when its own draft is already running: the run's page, unless that draft looks stuck. */
export const reattachHref = (drafting: Drafting | null, slug: string, report: ReportChoice) =>
  isLive(drafting) && !drafting.stale && isDraftingThis(drafting, slug, report) ? runHref(drafting) : null;

/**
 * The server's elapsed seconds as of the last read, counted on locally from then (never from when the page mounted, so
 * it is right after leaving and coming back, or a reload). A stuck draft is not counted on: its count stays where the
 * server put it.
 */
export function useLiveElapsed(drafting: MaybeRefOrGetter<{ elapsed_seconds: number; stale?: boolean } | null>) {
  const extra = ref(0);
  watch(
    () => toValue(drafting),
    (now, _before, onCleanup) => {
      extra.value = 0; // each poll brings a fresh server count; count on from that
      if (!now || now.stale) return;
      const received = Date.now();
      const id = setInterval(() => (extra.value = Math.floor((Date.now() - received) / 1000)), 1000);
      onCleanup(() => clearInterval(id));
    },
    { immediate: true },
  );
  return computed(() => (toValue(drafting)?.elapsed_seconds ?? 0) + extra.value);
}

/** A section's state on the overview, from its latest run of the report on screen. */
export type SectionState = "approved" | "rejected" | "in_review" | "not_drafted" | "unavailable";

export function stateOf(s: SectionSummary): SectionState {
  if (!s.available) return "unavailable";
  const run = s.latest;
  if (!run || !(run.current ?? run.this_week)) return "not_drafted";
  if (run.decision === "approved") return "approved";
  if (run.decision === "rejected") return "rejected";
  return "in_review";
}

/** "for Q3'2026", "this week", or (a weekly period naming its Friday) the short "for w/e 2 Oct 2026". */
export const when = (period: string) =>
  period.startsWith("Week ending ") ? `for w/e ${friendlyDate(period.slice(12))}` : period ? `for ${period}` : "this week";

/** The button a section's row offers for its state (the overview card and the chooser's list); null when unavailable. */
export function sectionAction(s: SectionSummary): { label: string; resume: boolean; primary: boolean } | null {
  const state = stateOf(s);
  if (state === "unavailable") return null;
  if (state === "in_review") return { label: "Resume review", resume: true, primary: true };
  if (state === "not_drafted") return { label: s.requires_approved ? "Compose summary" : "Draft section", resume: false, primary: true };
  return { label: "View review", resume: true, primary: false };
}

/** A section that already has a review (in review, approved or rejected) can be drafted again; the start screen asks first. */
export const canRedraft = (s: SectionSummary) => ["in_review", "approved", "rejected"].includes(stateOf(s));

/** The flagged items of a section's current review, as the overview's payload counts them (0 with no current review). */
export const flaggedOf = (s: SectionSummary) => (s.latest && (s.latest.current ?? s.latest.this_week) ? s.latest.counts.flagged.total : 0);

/** How many sections are in each state, in the overview's tally order. */
export function stateTally(o: Overview): [string, number][] {
  const states = o.sections.map(stateOf);
  const n = (st: SectionState) => states.filter((x) => x === st).length;
  return [
    ["Approved", n("approved")],
    ["In review", n("in_review")],
    ["Not drafted", n("not_drafted")],
    ["Rejected", n("rejected")],
    ["Not available yet", n("unavailable")],
  ];
}

/** The report's four figures, counted from the overview's payload (a section's current review only). */
export function reportCounts(o: Overview) {
  const states = o.sections.map(stateOf);
  return {
    approved: states.filter((x) => x === "approved").length,
    inReview: states.filter((x) => x === "in_review").length,
    flagged: o.sections.reduce((n, s) => n + flaggedOf(s), 0),
    drafting: draftingList(o).filter(isLive).length,
  };
}

export interface AttentionItem {
  slug: string;
  title: string;
  why: string;
  flag: boolean;
}

/**
 * Each section waiting on the analyst, worded from the payload: a stopped draft, a rejection, a review, or no draft yet,
 * ordered a stopped draft, a rejection, flagged items, ready for a decision, not drafted (then the issue's order).
 */
export function attentionList(o: Overview, report: ReportChoice): AttentionItem[] {
  const list = draftingList(o);
  return o.sections
    .flatMap((s, i) => {
      const state = stateOf(s);
      const d = draftingFor(list, s.slug, report);
      if (d?.state === "failed") return [{ slug: s.slug, title: s.title, why: "The last draft stopped", flag: true, rank: 0, i }];
      if (isLive(d)) return [];
      if (state === "rejected") return [{ slug: s.slug, title: s.title, why: "Rejected: draft it again", flag: true, rank: 1, i }];
      if (state === "in_review") {
        const f = flaggedOf(s);
        return [{ slug: s.slug, title: s.title, why: f ? `${plural(f, "item")} flagged` : "Ready for a decision", flag: f > 0, rank: f > 0 ? 2 : 4, i }];
      }
      if (state === "not_drafted") return [{ slug: s.slug, title: s.title, why: s.requires_approved ? "Not composed yet" : "Not drafted yet", flag: false, rank: 5, i }];
      return [];
    })
    .sort((a, b) => a.rank - b.rank || a.i - b.i)
    .map(({ slug, title, why, flag }) => ({ slug, title, why, flag }));
}
