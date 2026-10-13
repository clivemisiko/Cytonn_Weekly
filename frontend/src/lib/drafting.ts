import { type MaybeRefOrGetter, computed, ref, toValue, watch, watchEffect } from "vue";
import * as api from "./api";
import { friendlyDate } from "./format";
import type { Drafting, Overview, ReportChoice, SectionSummary } from "./types";

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

/** The server's elapsed seconds, counted on locally between polls (the browser's clock never enters into it). */
export function useLiveElapsed(drafting: MaybeRefOrGetter<Drafting | null>) {
  const extra = ref(0);
  watch(
    () => toValue(drafting),
    (now, _before, onCleanup) => {
      extra.value = 0; // each poll brings a fresh server count; count on from that
      if (!now) return;
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
