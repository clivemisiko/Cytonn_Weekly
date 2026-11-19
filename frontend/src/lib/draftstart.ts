import { computed, ref, toValue, type MaybeRefOrGetter } from "vue";
import * as api from "./api";
import { weekOf } from "./chatcards";
import { draftChartsNote } from "./charts";
import { redraftNotes } from "./redraft";
import { missingSourcesNote, piecesNothingFoundFor, usesSources } from "./sources";
import type { AppConfig, ReportChoice, SectionSummary } from "./types";

/** Starting a draft as the chat's draft card does: the old start screen's questions asked together in one dialog (`asking`),
 *  then POST /api/runs. The draft card and the prepare page share it, so the two can never start a draft differently. */
export function useDraftStart(
  opts: { section: MaybeRefOrGetter<SectionSummary>; report: MaybeRefOrGetter<ReportChoice>; config: MaybeRefOrGetter<AppConfig | null> },
  after: () => void,
) {
  const starting = ref(false);
  const problem = ref<string | null>(null);
  const asking = ref<string[] | null>(null);
  const startedRun = ref<string | null>(null);
  const week = computed(() => weekOf(toValue(opts.report).period));

  /** Charts with no image, pieces a search found nothing for, and what a new draft does to an earlier review. */
  async function notes(): Promise<string[]> {
    const section = toValue(opts.section);
    const report = toValue(opts.report);
    const config = toValue(opts.config);
    const out: string[] = [];
    const slug = section.slug;
    if (slug === "fixed_income" || slug === "equities") {
      try {
        const note = draftChartsNote((await api.getInputs(week.value)).charts ?? [], slug);
        if (note) out.push(note);
      } catch {
        /* a failed read never stops a draft */
      }
    }
    if (config && usesSources(config, section) && slug !== "real_estate") {
      try {
        const note = missingSourcesNote(piecesNothingFoundFor((await api.getSources(slug, report)).pieces));
        if (note) out.push(note);
      } catch {
        /* the same */
      }
    }
    const earlier = section.latest;
    if (earlier && (earlier.current ?? earlier.this_week)) out.push(...redraftNotes(earlier, report.type, section.requires_approved));
    return out;
  }

  async function start() {
    problem.value = null;
    starting.value = true;
    try {
      const found = await notes();
      if (found.length) asking.value = found;
      else await draft();
    } finally {
      starting.value = false;
    }
  }

  async function draft() {
    asking.value = null;
    starting.value = true;
    problem.value = null;
    const section = toValue(opts.section);
    try {
      const started = await api.startRun(section.slug, toValue(opts.report), { provider: section.uses_provider ? toValue(opts.config)?.provider : undefined });
      startedRun.value = started.run_id;
    } catch (err) {
      problem.value = (err as Error).message;
    } finally {
      starting.value = false;
      after();
    }
  }

  return { starting, problem, asking, startedRun, start, draft };
}
