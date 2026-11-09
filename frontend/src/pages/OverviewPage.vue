<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef } from "vue";
import { type LocationQuery, useRoute, useRouter } from "vue-router";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import OverviewScreen from "@/components/review/OverviewScreen.vue";
import OverviewSkeleton from "@/components/review/OverviewSkeleton.vue";
import ReviewScreen from "@/components/review/ReviewScreen.vue";
import ReviewSkeleton from "@/components/review/ReviewSkeleton.vue";
import StartScreen from "@/components/review/StartScreen.vue";
import StartSkeleton from "@/components/review/StartSkeleton.vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { draftingList } from "@/lib/drafting";
import { BACK_NONE, type BackTarget, useBack } from "@/lib/nav";
import { openingReport, rememberWeek } from "@/lib/previous";
import { shell, useShellActions, useShellHere } from "@/lib/shell";
import { type AppConfig, type Drafting, type Overview, REPORT_TYPES, type ReportChoice, type ReportType, type Review, type SectionSummary, type WeekChoice } from "@/lib/types";

type Phase =
  | { name: "booting"; target?: "overview" | "review" | "start" }
  | { name: "unreachable"; message: string }
  | { name: "overview"; config: AppConfig; overview: Overview }
  | { name: "start"; config: AppConfig; section: SectionSummary; saved: Review | null; drafting: Drafting[]; week: string | null }
  | { name: "review"; review: Review };

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));
const one = (value: LocationQuery[string] | undefined) => (Array.isArray(value) ? value[0] : value) ?? null;

const route = useRoute();
const router = useRouter();
const phase = shallowRef<Phase>({
  name: "booting",
  target: reviewFromUrl() ? "review" : sectionFromUrl() ? "start" : "overview",
});
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

/** A section slug in the address bar (?section=fixed_income). */
function sectionFromUrl(): string | null {
  const slug = one(route.query.section);
  return typeof slug === "string" && slug.trim() ? slug.trim() : null;
}

/** The chosen report in the address bar, without a history entry. */
function reportToUrl(next: ReportChoice, reviewId: number | null = null, sectionSlug: string | null = null) {
  // The report is always written, the unlabelled weekly one as ?report=weekly: an address with none opens the default week.
  const query: Record<string, string> = { report: next.type };
  if (next.period) query.period = next.period;
  if (next.kind) query.kind = next.kind;
  if (reviewId !== null) {
    query.review = String(reviewId);
  } else if (sectionSlug !== null) {
    query.section = sectionSlug;
  }
  void router.replace({ path: route.path, query });
}

/** The weeks the selector lists, read with every overview shown; empty when the route cannot be read. */
const weekChoices = shallowRef<WeekChoice[]>([]);
async function loadWeekChoices() {
  try {
    const next = (await api.getPreviousWeeks()).choices ?? [];
    if (live) weekChoices.value = next;
  } catch {
    if (live) weekChoices.value = [];
  }
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
    void loadWeekChoices();
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
    return { name: "start", config, section, saved, drafting: draftingList(overview), week };
  } catch (err) {
    return { name: "unreachable", message: messageOf(err) };
  }
}

/** Show another phase without touching the address bar (a start screen, an open review). */
const set = (next: Phase) => {
  if (live) phase.value = next;
};

onMounted(async () => {
  let wanted = reportFromUrl();
  // No report in the address bar: open on the API's labelled default week (the unlabelled report if it cannot be read).
  if (route.query.report === undefined) wanted = await openingReport(api.getPreviousWeeks);
  const reviewId = reviewFromUrl();
  const sectionSlug = sectionFromUrl();
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
  if (sectionSlug) {
    report.value = wanted;
    try {
      const startPhase = await fetchStart(sectionSlug);
      if (startPhase.name === "start") {
        set(startPhase);
        return;
      }
    } catch {
      /* fall through to the overview */
    }
  }
  show(await fetchOverview(wanted));
});

function home() {
  reportToUrl(report.value, null, null);
  shell.invalidate(); // the overview is read again below, which then hands the rail its payload
  set({ name: "booting", target: "overview" });
  void fetchOverview(report.value).then(show);
}

// The top bar's Back: from a section's start screen or an open review, to this report's list of sections.
// From the list of sections itself, Back is disabled as overview is the top-level workspace.
const TO_SECTIONS: BackTarget = { kind: "go", to: "all sections", go: home };
useBack(() => (phase.value.name === "start" || phase.value.name === "review" ? TO_SECTIONS : BACK_NONE));

/** Switch the overview to another report. A period the API rejects stays in the picker with the API's reason. */
async function chooseReport(next: ReportChoice): Promise<string | null> {
  const now = phase.value;
  if (now.name !== "overview") return null;
  try {
    show({ ...now, overview: await api.getOverview(next) });
    rememberWeek(report.value.type === "weekly" ? report.value.period : "");
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
    set({ name: "booting", target: "review" });
    try {
      const review = await api.getReview(run.run_id);
      reportToUrl(report.value, review.run_id, null);
      set({ name: "review", review });
    } catch (err) {
      set({ name: "unreachable", message: messageOf(err) });
    }
    return;
  }
  set({ name: "booting", target: "start" });
  reportToUrl(report.value, null, slug);
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
    set({ name: "booting", target: "review" });
    try {
      const review = await api.getReview(run.run_id);
      reportToUrl(report.value, review.run_id, null);
      set({ name: "review", review });
    } catch (err) {
      set({ name: "unreachable", message: messageOf(err) });
    }
    return;
  }
  set({ name: "booting", target: "start" });
  reportToUrl(report.value, null, slug);
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
  rememberWeek(report.value.period);
  reportToUrl(report.value, null, slug);
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
  return p.name === "review"
    ? `review-${p.review.run_id}`
    : p.name === "start"
      ? `start-${p.section.slug}`
      : p.name === "booting"
        ? `booting-${p.target ?? "overview"}`
        : p.name;
});
</script>

<template>
  <Transition name="phase" mode="out-in">
    <main id="main" :key="key" tabindex="-1">
      <template v-if="phase.name === 'booting'">
        <ReviewSkeleton v-if="phase.target === 'review'" />
        <StartSkeleton v-else-if="phase.target === 'start'" />
        <OverviewSkeleton v-else />
      </template>

      <template v-else-if="phase.name === 'unreachable'">
        <Masthead title="Analyst review" />
        <div class="mx-auto w-full max-w-275 px-4 py-8 sm:px-6">
          <div class="max-w-xl">
            <h2 class="text-lg font-semibold">Unable to connect to the report review service</h2>
            <Notice role="alert" class="mt-4 font-medium">{{ phase.message }}</Notice>
            <p class="mt-4 text-sm text-muted-foreground">
              Please check your network connection or verify that the backend server is running. If this issue persists, please contact your system administrator.
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
        :weeks="weekChoices"
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
        @open="(review) => (reportToUrl(report, review.run_id), set({ name: 'review', review }))"
        @home="home"
      />

      <ReviewScreen
        v-else-if="phase.name === 'review'"
        :initial="phase.review"
        @close="home"
        @open="(next) => (reportToUrl(report, next.run_id), set({ name: 'review', review: next }))"
        @redraft="async (slug) => (reportToUrl(report, null, slug), set(await fetchStart(slug)))"
      />
    </main>
  </Transition>
</template>
