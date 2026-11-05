import { type MaybeRefOrGetter, computed, ref, toValue, watch, watchEffect } from "vue";
import * as api from "./api";
import { friendlyDate } from "./format";
import type { AppConfig, Drafting, Overview, ReportChoice, SectionSummary } from "./types";

const POLL_MS = 5_000;

/**
 * Re-reads the overview of the report on screen every few seconds while a draft is running on the server, so the
 * screen shows it finishing (and the run it saved) without a reload. Stops as soon as nothing is drafting; a failed
 * poll is simply retried.
 */
export function useDraftingPoll(
  drafting: MaybeRefOrGetter<Drafting | null>,
  onOverview: (next: Overview) => void,
  report: MaybeRefOrGetter<ReportChoice>,
  enabled: MaybeRefOrGetter<boolean> = true,
) {
  // Booleans and strings, so a fresh `drafting` object from each poll does not restart the timer.
  const active = computed(() => toValue(enabled) && toValue(drafting) !== null);
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

/**
 * The two checks every draft button makes, in one place: a section that calls the LLM waits while another draft holds
 * the one draft slot (unless that draft looks stuck, which a new draft replaces), and while the provider cannot run.
 * A section that calls no provider (Company Updates, the Executive Summary) is never held up by either.
 */
export const slotTaken = (llm: boolean, drafting: Drafting | null) => llm && drafting !== null && !drafting.stale;
export const providerOff = (llm: boolean, config: AppConfig) => llm && !!config.provider_problem;

/** Why "Draft again" is off on this section's card (the same checks as the start screen's draft button), or null. */
export function draftAgainOff(s: SectionSummary, drafting: Drafting | null, config: AppConfig, report: ReportChoice): string | null {
  if (providerOff(s.uses_provider, config)) return `${config.provider_problem} Drafting is off until then.`;
  if (!slotTaken(s.uses_provider, drafting)) return null;
  return `${isDraftingThis(drafting, s.slug, report) ? "This section is" : `${drafting?.title} is`} drafting now. Only one draft runs at a time, across every section.`;
}

/** The page of a running draft (its steps and counter), or null when the server named no run for it. */
export const runHref = (drafting: Drafting | null) => (drafting?.run_id ? `/runs/${drafting.run_id}` : null);

/** Where a section's screen goes when its own draft is already running: the run's page, unless that draft looks stuck. */
export const reattachHref = (drafting: Drafting | null, slug: string, report: ReportChoice) =>
  drafting && !drafting.stale && isDraftingThis(drafting, slug, report) ? runHref(drafting) : null;

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
