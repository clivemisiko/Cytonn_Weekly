import { type MaybeRefOrGetter, computed, onUnmounted, ref, shallowRef, toValue, watchEffect } from "vue";
import * as api from "./api";
import { type SectionState, isDraftingThis, stateOf } from "./drafting";
import type { AppConfig, Overview, ReportChoice, ReportType } from "./types";

/** What the side rail shows for a section: its state on the overview, "drafting" while it is being drafted, or null (unknown). */
export type RailState = SectionState | "drafting";

export interface RailSection {
  slug: string;
  title: string;
  /** null: not known to be current (not read yet, being re-read, or the last read failed). Never a guess. */
  state: RailState | null;
}

/** Where the person is, as far as the rail needs to know. */
export type Here = { view: "overview" } | { view: "section"; slug: string } | null;

const reportOf = (o: Overview): ReportChoice => ({ type: o.report.type, period: o.report.period, kind: o.report.kind });

/**
 * What the side rail knows, kept in one place so the rail can never say something the overview does not.
 *
 * The rail's sections and their states come from the overview payload itself (the same object the overview's cards are
 * built from), either handed over by the page that just read it (`setOverview`) or read again here (`refresh`) with the
 * same call. A state is shown only while it is known to be current: `invalidate` makes every state unknown at once (after an
 * approval, a rejection, a draft started), a failed read leaves them unknown, and a response that arrives after a newer one is
 * dropped. Nothing is cached across those events, defaulted or guessed.
 *
 * `load` is the overview call; the app's instance uses the API's, a test passes its own.
 */
export function createShell(load: (report: ReportChoice) => Promise<Overview>) {
  const held = shallowRef<Overview | null>(null);
  const known = ref(false);
  const config = shallowRef<AppConfig | null>(null);
  const here = shallowRef<Here>(null);
  const ribbon = ref<string | null>(null);
  /** Opens a section on the page that owns the sections (the overview page); null where nothing can (the run view). */
  const opener = shallowRef<((slug: string) => void) | null>(null);
  /** Goes to the overview's list of sections from within the overview page; null elsewhere. */
  const toOverview = shallowRef<(() => void) | null>(null);
  let latest = 0;

  /** Take the payload a page has just read. It is the newest, so any read still in flight is dropped. */
  function setOverview(overview: Overview) {
    latest++;
    held.value = overview;
    known.value = true;
  }

  /** Every state is unknown from now until the next payload arrives, and a read already in flight is dropped (it began
   *  before whatever made the states stale). The sections stay listed. */
  function invalidate() {
    latest++;
    known.value = false;
  }

  /** Read the report's overview again. Only the newest read counts; a failed one leaves the states unknown. */
  async function refresh(report: ReportChoice): Promise<void> {
    const mine = ++latest;
    try {
      const overview = await load(report);
      if (mine !== latest) return;
      held.value = overview;
      known.value = true;
    } catch {
      if (mine === latest) known.value = false;
    }
  }

  /** Read again the overview of the report a review or a run names, keeping the companion kind when it is the one held. */
  function refreshFor(type: ReportType, period: string): Promise<void> {
    const have = held.value?.report;
    return refresh({ type, period, kind: have && have.type === type && have.period === period ? have.kind : null });
  }

  const sections = computed<RailSection[]>(() => {
    const overview = held.value;
    if (!overview) return [];
    const report = reportOf(overview);
    return overview.sections.map((s) => ({
      slug: s.slug,
      title: s.title,
      state: !known.value ? null : isDraftingThis(overview.drafting, s.slug, report) ? "drafting" : stateOf(s),
    }));
  });
  /** How many sections are approved, counted as the overview's own tally counts them; null when not known. */
  const approved = computed(() => (known.value && held.value ? held.value.sections.filter((s) => stateOf(s) === "approved").length : null));
  const total = computed(() => held.value?.sections.length ?? null);
  const report = computed(() => (held.value ? { ...reportOf(held.value), title: held.value.report.title } : null));

  return { held, known, config, here, ribbon, opener, toOverview, sections, approved, total, report, setOverview, invalidate, refresh, refreshFor };
}

/** The app's one rail store, fed by the API's overview call. */
export const shell = createShell(api.getOverview);

/** Set a value in the store for as long as the calling component lives, and undo it only if it is still this one's. */
function useShellValue<T>(slot: { value: T }, value: MaybeRefOrGetter<T>, none: T) {
  let mine: T | undefined;
  watchEffect(() => {
    mine = toValue(value);
    slot.value = mine;
  });
  onUnmounted(() => {
    if (slot.value === mine) slot.value = none;
  });
}

/** The dev-mode ribbon's label while this page is on screen (null for none). The shell draws it under the top bar. */
export const useShellRibbon = (label: MaybeRefOrGetter<string | null>) => useShellValue(shell.ribbon, label, null);

/** Which screen of the overview page is showing, so the rail can mark it. */
export const useShellHere = (here: MaybeRefOrGetter<Here>) => useShellValue(shell.here, here, null);

/** What the rail's items do on the overview page. Cleared when the page goes away, so the rail is inactive elsewhere. */
export function useShellActions(actions: { openSection: (slug: string) => void; toOverview: () => void }) {
  shell.opener.value = actions.openSection;
  shell.toOverview.value = actions.toOverview;
  onUnmounted(() => {
    if (shell.opener.value === actions.openSection) shell.opener.value = null;
    if (shell.toOverview.value === actions.toOverview) shell.toOverview.value = null;
  });
}
