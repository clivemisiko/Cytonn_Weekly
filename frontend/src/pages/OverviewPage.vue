<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef } from "vue";
import { type LocationQuery, useRoute, useRouter } from "vue-router";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import OverviewScreen from "@/components/review/OverviewScreen.vue";
import ReviewScreen from "@/components/review/ReviewScreen.vue";
import StartScreen from "@/components/review/StartScreen.vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { BACK_HOME, type BackTarget, useBack } from "@/lib/nav";
import { shell, useShellActions, useShellHere } from "@/lib/shell";
import type { AppConfig, Drafting, Overview, ReportChoice, ReportType, Review, SectionSummary } from "@/lib/types";

type Phase =
  | { name: "booting" }
  | { name: "unreachable"; message: string }
  | { name: "overview"; config: AppConfig; overview: Overview }
  | { name: "start"; config: AppConfig; section: SectionSummary; saved: Review | null; drafting: Drafting | null; week: string | null }
  | { name: "review"; review: Review };

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));
const REPORT_TYPES: ReportType[] = ["weekly", "quarterly", "half_year", "annual", "companion"];
const one = (value: LocationQuery[string] | undefined) => (Array.isArray(value) ? value[0] : value) ?? null;

/**
 * The overview of one report's sections, one section's start screen, or one open review. Only the chosen report is
 * remembered here (and in the address bar): the server holds every review, so going back to the overview re-reads it.
 */
const route = useRoute();
const router = useRouter();
const phase = shallowRef<Phase>({ name: "booting" });
const report = shallowRef<ReportChoice>(api.WEEKLY_REPORT);
let live = true;
onUnmounted(() => (live = false));
// The rail shows no section's state until this page has read the overview (or a review's report): nothing from before.
shell.invalidate();

/** The report in the address bar (?report=quarterly&period=Q3'2026), so a reload stays on it. Weekly when absent. */
function reportFromUrl(): ReportChoice {
  const type = one(route.query.report) as ReportType | null;
  if (!type || !REPORT_TYPES.includes(type)) return api.WEEKLY_REPORT;
  return { type, period: one(route.query.period) ?? "", kind: one(route.query.kind) };
}

/** A saved review to open straight away (?review=12): where a finished draft run's "Open review" lands. */
function reviewFromUrl(): number | null {
  const id = Number(one(route.query.review));
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** The chosen report in the address bar, without a history entry. */
function reportToUrl(next: ReportChoice) {
  const query: Record<string, string> = {};
  if (next.type !== "weekly" || next.period) {
    query.report = next.type;
    if (next.period) query.period = next.period;
    if (next.kind) query.kind = next.kind;
  }
  void router.replace({ path: route.path, query });
}

/** The report as the API normalized it ("q3 2026" comes back as "Q3'2026"). */
const normalized = (overview: Overview): ReportChoice => ({ type: overview.report.type, period: overview.report.period, kind: overview.report.kind });

/** The chosen report's overview. A report in the address bar that no longer fits falls back to the weekly one. */
async function fetchOverview(wanted: ReportChoice): Promise<Phase> {
  try {
    const config = await api.getConfig();
    try {
      return { name: "overview", config, overview: await api.getOverview(wanted) };
    } catch (err) {
      if ((err as api.ApiError).status !== 422) throw err;
      return { name: "overview", config, overview: await api.getOverview(api.WEEKLY_REPORT) };
    }
  } catch (err) {
    return { name: "unreachable", message: messageOf(err) };
  }
}

/** Show a phase; an overview also fixes the chosen report to what the API normalized, here and in the address bar. */
function show(next: Phase) {
  if (!live) return;
  if (next.name === "overview") {
    report.value = normalized(next.overview);
    reportToUrl(report.value);
    shell.config.value = next.config;
    shell.setOverview(next.overview); // the rail takes the very payload the cards are built from
  }
  phase.value = next;
}

/** A section's start screen, with its current saved review (if any) offered for resume. `known` is an overview just read. */
async function fetchStart(slug: string, known?: Overview): Promise<Phase> {
  try {
    const [config, overview] = await Promise.all([api.getConfig(), known ?? api.getOverview(report.value)]);
    shell.config.value = config;
    shell.setOverview(overview);
    const section = overview.sections.find((s) => s.slug === slug);
    if (!section) return { name: "overview", config, overview };
    const run = section.latest;
    const saved = run && (run.current ?? run.this_week) ? await api.getReview(run.run_id) : null;
    // The weekly report's week: the Friday its period names, else the latest Friday (what an unlabelled draft uses).
    const week = overview.report.type === "weekly" ? (overview.report.week_ending ?? overview.report.suggested_week_ending ?? null) : null;
    return { name: "start", config, section, saved, drafting: overview.drafting, week };
  } catch (err) {
    return { name: "unreachable", message: messageOf(err) };
  }
}

/** Show another phase without touching the address bar (a start screen, an open review). */
const set = (next: Phase) => {
  if (live) phase.value = next;
};

onMounted(async () => {
  const wanted = reportFromUrl();
  const reviewId = reviewFromUrl();
  // The review named in the address bar, or the overview if it cannot be read. Closing it goes to its own report.
  if (reviewId !== null) {
    try {
      const review = await api.getReview(reviewId);
      report.value = { type: review.report_type, period: review.period, kind: wanted.kind };
      set({ name: "review", review });
      void shell.refreshFor(review.report_type, review.period); // the rail's sections and states, read for this review's report
      return;
    } catch {
      /* fall through to the overview */
    }
  }
  show(await fetchOverview(wanted));
});

function home() {
  shell.invalidate(); // the overview is read again below, which then hands the rail its payload
  set({ name: "booting" });
  void fetchOverview(report.value).then(show);
}

// The top bar's Back: from a section's start screen or an open review, to this report's list of sections (as the
// masthead's own back link did before the bar); from the list itself, Home.
const TO_SECTIONS: BackTarget = { kind: "go", to: "all sections", go: home };
useBack(() => (phase.value.name === "start" || phase.value.name === "review" ? TO_SECTIONS : BACK_HOME));

/** Switch the overview to another report. A period the API rejects stays in the picker with the API's reason. */
async function chooseReport(next: ReportChoice): Promise<string | null> {
  const now = phase.value;
  if (now.name !== "overview") return null;
  try {
    show({ ...now, overview: await api.getOverview(next) });
    return null;
  } catch (err) {
    return messageOf(err);
  }
}

async function openSection(slug: string, resume: boolean) {
  const now = phase.value;
  if (now.name !== "overview") return;
  const run = now.overview.sections.find((s) => s.slug === slug)?.latest;
  if (resume && run) {
    try {
      set({ name: "review", review: await api.getReview(run.run_id) });
    } catch (err) {
      set({ name: "unreachable", message: messageOf(err) });
    }
    return;
  }
  set(await fetchStart(slug));
}

/**
 * A section opened from the rail, from any screen of this page. It goes where that section's own card button goes (its
 * review when it has a current one, else its start screen), decided on a fresh read of the report's sections, never on
 * what the rail was showing.
 */
async function goToSection(slug: string) {
  let overview: Overview;
  try {
    overview = await api.getOverview(report.value);
  } catch (err) {
    set({ name: "unreachable", message: messageOf(err) });
    return;
  }
  shell.setOverview(overview);
  const section = overview.sections.find((s) => s.slug === slug);
  if (!section || !section.available) return;
  const run = section.latest;
  if (run && (run.current ?? run.this_week)) {
    try {
      set({ name: "review", review: await api.getReview(run.run_id) });
    } catch (err) {
      set({ name: "unreachable", message: messageOf(err) });
    }
    return;
  }
  set(await fetchStart(slug, overview));
}

// What the rail's items do while this page is on screen, and which of its screens the rail marks.
useShellActions({ openSection: goToSection, toOverview: home });
useShellHere(() => {
  const p = phase.value;
  if (p.name === "overview") return { view: "overview" };
  if (p.name === "start") return { view: "section", slug: p.section.slug };
  if (p.name === "review") return { view: "section", slug: p.review.section_slug };
  return null;
});

/** On a start screen, switch the weekly report to the week ending on another Friday and show that week's section. */
async function chooseWeek(slug: string, weekEnding: string) {
  report.value = { type: "weekly", period: api.weekPeriod(weekEnding), kind: null };
  reportToUrl(report.value);
  set(await fetchStart(slug));
}

/** A polled overview replaces the shown one in place (same phase, so no screen transition). */
function refreshOverview(overview: Overview) {
  const now = phase.value;
  if (now.name === "overview") {
    set({ ...now, overview });
    shell.setOverview(overview);
  }
}

const key = computed(() => {
  const p = phase.value;
  return p.name === "review" ? `review-${p.review.run_id}` : p.name === "start" ? `start-${p.section.slug}` : p.name;
});
</script>

<template>
  <Transition name="phase" mode="out-in">
    <main id="main" :key="key" tabindex="-1">
      <div v-if="phase.name === 'booting'" aria-busy="true" aria-label="Loading">
        <div class="h-28 border-b bg-card" />
        <div class="mx-auto w-full max-w-275 space-y-3 px-4 pt-8 sm:px-6">
          <div data-slot="skeleton" class="h-16 w-full animate-pulse rounded-lg bg-border/60" />
          <div v-for="i in 5" :key="i" data-slot="skeleton" class="h-24 w-full animate-pulse rounded-lg bg-border/60" />
        </div>
      </div>

      <template v-else-if="phase.name === 'unreachable'">
        <Masthead title="Coordinator review" />
        <div class="mx-auto w-full max-w-275 px-4 py-8 sm:px-6">
          <div class="max-w-xl">
            <h2 class="text-lg font-semibold">The review API is not reachable</h2>
            <Notice role="alert" class="mt-4 font-medium">{{ phase.message }}</Notice>
            <p class="mt-4 text-sm text-muted-foreground">
              Start it from the repo root with <code class="rounded-sm bg-muted px-1 py-0.5 font-mono text-xs">uvicorn api.main:app --port 8000</code>.
              To point this app at another address, set <code class="rounded-sm bg-muted px-1 py-0.5 font-mono text-xs">VITE_API_TARGET</code>.
            </p>
            <Button class="mt-6" size="lg" @click="home">Try again</Button>
          </div>
        </div>
      </template>

      <OverviewScreen
        v-else-if="phase.name === 'overview'"
        :overview="phase.overview"
        :config="phase.config"
        :report="report"
        :on-report="chooseReport"
        @open="openSection"
        @redraft="(slug) => openSection(slug, false)"
        @overview="refreshOverview"
      />

      <StartScreen
        v-else-if="phase.name === 'start'"
        :section="phase.section"
        :config="phase.config"
        :report="report"
        :saved="phase.saved"
        :drafting="phase.drafting"
        :week="phase.week"
        :on-recheck="async () => set(await fetchStart((phase as Extract<Phase, { name: 'start' }>).section.slug))"
        @week="(weekEnding) => chooseWeek((phase as Extract<Phase, { name: 'start' }>).section.slug, weekEnding)"
        @open="(review) => set({ name: 'review', review })"
        @home="home"
      />

      <ReviewScreen v-else-if="phase.name === 'review'" :initial="phase.review" @close="home" />
    </main>
  </Transition>
</template>
