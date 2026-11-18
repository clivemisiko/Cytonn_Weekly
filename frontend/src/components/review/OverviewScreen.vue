<script setup lang="ts">
import { PhArrowRight, PhCaretDown, PhCaretRight, PhListChecks, PhPulse, PhSealCheck, PhWarningCircle } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, nextTick, ref, watch } from "vue";
import PageGrid from "@/components/nav/PageGrid.vue";
import { LINK } from "@/components/ui/button";
import { exportChartsNote } from "@/lib/charts";
import { type SectionState, draftAgainOff, draftingFor, draftingList, isLive, stateOf, useDraftingPoll } from "@/lib/drafting";
import { friendlyDate, plural, reportName } from "@/lib/format";
import { APPROVED_BANNER, fullyApproved } from "@/lib/previous";
import { useShellRibbon } from "@/lib/shell";
import type { AppConfig, ExportStatus, Overview, ReportChoice, WeekChoice } from "@/lib/types";
import DraftingBanner from "./DraftingBanner.vue";
import Button from "@/components/ui/Button.vue";
import MetricCard from "@/components/ui/MetricCard.vue";
import Panel from "@/components/ui/Panel.vue";
import ActivityPanel from "./ActivityPanel.vue";
import ExportBar from "./ExportBar.vue";
import Notice from "./Notice.vue";
import ReportPicker from "./ReportPicker.vue";
import SectionRow from "./SectionRow.vue";

const props = defineProps<{
  overview: Overview;
  config: AppConfig;
  /** The report on screen, as the API normalized it. */
  report: ReportChoice;
  /** The weeks the selector lists; empty until read, or when the route cannot be read. */
  weeks?: WeekChoice[];
  /** Switch to another report: resolves to an error to show in the picker, or null once switched. */
  onReport: (next: ReportChoice) => Promise<string | null>;
}>();
const emit = defineEmits<{
  open: [slug: string, resume: boolean];
  /** "Draft again" on a section that already has a review: its start screen, with the saved review beside it. */
  redraft: [slug: string];
  /** A fresher overview, from polling while a draft runs on the server. */
  overview: [next: Overview];
}>();

useShellRibbon(() => (props.config.dev_mode ? props.config.dev_mode_label : null)); // the shell draws it under the top bar
const drafting = computed(() => draftingList(props.overview));
const live = computed(() => drafting.value.filter(isLive));
useDraftingPoll(drafting, (next) => emit("overview", next), () => props.report);
const name = computed(() => reportName(props.overview.report.title, props.overview.report.period));
const kind = computed(() => props.overview.companion_kinds.find((k) => k.slug === props.overview.report.kind));
const tally = computed<[string, number][]>(() => {
  const states = props.overview.sections.map(stateOf);
  const n = (st: SectionState) => states.filter((x) => x === st).length;
  return [
    ["Approved", n("approved")],
    ["In review", n("in_review")],
    ["Not drafted", n("not_drafted")],
    ["Rejected", n("rejected")],
    ["Not available yet", n("unavailable")],
  ];
});

// The group of cards: named by its week or period, with how many are approved and (always shown, even when the group
// is folded) how many items the checker flagged across the sections' current reviews, as the payload counts them.
const groupOpen = ref(true);

// What the export bar in the panel last read. Whether the export would carry the dev-mode watermark is shown in the feed,
// beside the dev-mode notice, because the panel can be folded and a warning must not fold away with it.
const exportStatus = ref<ExportStatus | null>(null);
// The export's error, in the feed so it is seen with the Report status panel folded; "Show me" goes here.
const exportError = ref<string | null>(null);
// The screen stays mounted when the picker changes report, and ExportBar never clears what it sent when it unmounts.
watch(
  () => props.overview.report.type,
  (type) => {
    if (type !== "weekly") {
      exportStatus.value = null;
      exportError.value = null;
    }
  },
  { immediate: true },
);
const groupLabel = computed(() => {
  const period = props.overview.report.period;
  return period.startsWith("Week ending ") ? `Week ending ${friendlyDate(period.slice(12))}` : period || "This week";
});
const approved = computed(() => props.overview.sections.filter((s) => stateOf(s) === "approved").length);

// Each section waiting on the analyst, worded from the payload: a stopped draft, a rejection, a review, or no draft yet.
// rank orders the queue (lower first): a stopped draft, a rejection, flagged items, ready for a decision, not drafted.
const attentionAll = computed(() =>
  props.overview.sections
    .flatMap((s, i) => {
      const state = stateOf(s);
      const d = draftingFor(drafting.value, s.slug, props.report);
      if (d?.state === "failed") return [{ slug: s.slug, title: s.title, why: "The last draft stopped", flag: true, rank: 0, i }];
      if (isLive(d)) return [];
      if (state === "rejected") return [{ slug: s.slug, title: s.title, why: "Rejected: draft it again", flag: true, rank: 1, i }];
      if (state === "in_review" && s.latest) {
        const f = s.latest.counts.flagged.total;
        return [{ slug: s.slug, title: s.title, why: f ? `${plural(f, "item")} flagged` : "Ready for a decision", flag: f > 0, rank: f > 0 ? 2 : 4, i }];
      }
      if (state === "not_drafted") return [{ slug: s.slug, title: s.title, why: s.requires_approved ? "Not composed yet" : "Not drafted yet", flag: false, rank: 5, i }];
      return [];
    })
    .sort((a, b) => a.rank - b.rank || a.i - b.i),
);
const ATTENTION_SHOWN = 4;
const attention = computed(() => attentionAll.value.slice(0, ATTENTION_SHOWN));
const inReview = computed(() => props.overview.sections.filter((s) => stateOf(s) === "in_review").length);
// A review waiting on the analyst comes first, then a section with no draft (or whose draft stopped); a rejected one is
// left to its card, where "Draft again" asks first.
const next = computed(() => {
  const review = props.overview.sections.find((s) => stateOf(s) === "in_review");
  if (review) return { label: `Continue reviewing ${review.title}`, go: () => emit("open", review.slug, true) };
  const fresh = props.overview.sections.find((s) => stateOf(s) === "not_drafted" && !isLive(draftingFor(drafting.value, s.slug, props.report)));
  if (fresh) return { label: `${fresh.requires_approved ? "Compose" : "Draft"} ${fresh.title}`, go: () => emit("open", fresh.slug, false) };
  return null;
});
async function goToCard(slug: string) {
  groupOpen.value = true;
  await nextTick();
  const el = document.getElementById(`sec-${slug}`);
  el?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  el?.focus({ preventScroll: true });
}
const flagged = computed(() =>
  props.overview.sections.reduce((n, s) => (s.latest && (s.latest.current ?? s.latest.this_week) ? n + s.latest.counts.flagged.total : n), 0),
);
</script>

<template>
  <PageGrid aside-title="Report status" storage-key="overview">
    <!-- Identity and the one way on: the report and its date at the left, the first section waiting on the analyst at the
         right, opened exactly as its card's own button opens it. -->
    <div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div class="min-w-0 flex-1">
        <p class="eyebrow flex flex-wrap items-center gap-x-2">
          <span>{{ overview.report.title }}</span>
          <span aria-hidden="true">·</span>
          <span class="font-mono normal-case tracking-normal">Today {{ friendlyDate(overview.today) }}</span>
        </p>
        <h1 class="mt-1 text-xl font-bold tracking-tight">Analyst review</h1>
        <p class="mt-1 text-xs text-muted-foreground">
          {{ kind ? `${kind.title}: ` : `${name}: ` }}{{ plural(overview.sections.length, "report section") }}. Each is drafted, checked and approved or rejected on its own.
        </p>
      </div>
      <Button v-if="next" size="lg" class="max-w-full whitespace-normal" @click="next.go()">
        {{ next.label }}
        <PhArrowRight weight="bold" data-icon="inline-end" aria-hidden="true" />
      </Button>
    </div>

    <div class="mt-4 space-y-4">
      <ReportPicker
        :key="`${report.type}|${report.period}|${report.kind ?? ''}`"
        :current="report"
        :types="overview.report_types"
        :kinds="overview.companion_kinds"
        :weeks="weeks"
        :on-apply="onReport"
      />

      <!-- Four figures in one strip, each counted from the overview's payload (a section's current review only). -->
      <div role="group" aria-label="This report in figures" class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border @2xl:grid-cols-4">
        <MetricCard label="Approved" :value="approved" :sub="` / ${overview.sections.length}`" :icon="PhSealCheck" :tone="approved === overview.sections.length ? 'ok' : 'neutral'" />
        <MetricCard label="In review" :value="inReview" :icon="PhListChecks" />
        <MetricCard label="Flagged" :value="flagged" :icon="PhWarningCircle" :tone="flagged > 0 ? 'flag' : 'neutral'" />
        <MetricCard label="Drafting" :value="live.length" :icon="PhPulse" />
      </div>

      <!-- Standing cautions: always present and announced, but quiet, so they never become the page's focus. -->
      <Notice v-if="config.dev_mode" quiet role="alert">
        <span class="font-semibold">Development Mode Active (Local Model):</span> Drafts generated in this mode are for testing purposes only and are not approved for publication.
      </Notice>
      <Notice v-if="exportStatus?.is_dev_draft" quiet role="alert">
        Export Notice: This document contains test content ({{ exportStatus.dev_sections.join(", ") }}) and includes a developer watermark on every page. It cannot be circulated or published externally.
      </Notice>
      <!-- In the feed, not the foldable panel beside the export button: a note there could be folded away. -->
      <Notice v-if="exportChartsNote(exportStatus?.charts_missing ?? 0)" tone="info" quiet role="status">
        {{ exportChartsNote(exportStatus?.charts_missing ?? 0) }}
      </Notice>
      <div v-if="exportError" data-attention="export-bar">
        <Notice role="alert" data-problem class="font-medium">{{ exportError }}</Notice>
      </div>
      <DraftingBanner v-for="d in live" :key="d.run_id ?? `${d.report_type}${d.period}${d.slug}`" :drafting="d" />
      <Notice v-if="fullyApproved(overview)" tone="info" role="status">
        <span>{{ APPROVED_BANNER }} <RouterLink to="/previous" :class="LINK">Previous reports</RouterLink></span>
      </Notice>
      <Notice v-if="overview.report.type === 'companion'" tone="info">
        Companion research reports ride inside a weekly issue as its Focus of the Week. Every section below is Cytonn’s own
        analysis, so none can be drafted yet; the weekly Focus of the Week can still draft a cited piece on the same topic.
      </Notice>


      <!-- The queue: the few sections most in need of the analyst, highest first; every section stays listed below. -->
      <Panel v-if="attention.length" id="attention-title" title="Needs your attention">
        <template #action>
          <span class="text-xs text-muted-foreground">
            <span class="font-mono">{{ attention.length }}</span> of <span class="font-mono">{{ attentionAll.length }}</span>
          </span>
        </template>
        <ul class="divide-y">
          <li v-for="a in attention" :key="a.slug">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
              @click="goToCard(a.slug)"
            >
              <span class="glyph" :class="a.flag ? 'state-flagged' : 'state-not_auto_verified'" aria-hidden="true">{{ a.flag ? "!" : "?" }}</span>
              <span class="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                <span class="mr-auto text-sm font-semibold">{{ a.title }}</span>
                <span class="rounded-sm px-2 py-0.5 text-xs font-bold tracking-wide uppercase" :class="a.flag ? 'bg-flag/12 text-flag-fg' : 'bg-muted text-muted-foreground'">{{ a.why }}</span>
              </span>
              <PhCaretRight weight="bold" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </Panel>
      <p v-else-if="approved === overview.sections.length" class="text-sm text-muted-foreground">Every section is approved.</p>

      <CollapsibleRoot v-model:open="groupOpen" class="space-y-3 pt-2">
        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b pb-2">
          <h2 class="panel-title">
            <CollapsibleTrigger class="flex items-center gap-2 rounded-md py-1 text-left uppercase outline-none hover:text-link focus-visible:ring-2 focus-visible:ring-ring">
              <PhCaretDown weight="bold" class="size-4 shrink-0 text-muted-foreground transition-transform duration-200" :class="!groupOpen && '-rotate-90'" aria-hidden="true" />
              {{ groupLabel }} · {{ approved }} of {{ overview.sections.length }} approved
            </CollapsibleTrigger>
          </h2>
          <span v-if="flagged > 0" class="state-flagged inline-flex items-center gap-1 text-sm font-semibold text-(--hue-fg)">
            <span class="glyph size-4 text-xs" aria-hidden="true">!</span>
            {{ flagged }} flagged
          </span>
        </div>
        <CollapsibleContent class="collapsible -m-1 overflow-hidden p-1">
          <ol class="space-y-2">
            <SectionRow
              v-for="(s, i) in overview.sections"
              :key="s.slug"
              :s="s"
              :index="i"
              :period="overview.report.period"
              :drafting="draftingFor(drafting, s.slug, report)"
              :draft-again-off="draftAgainOff(s, draftingFor(drafting, s.slug, report), config)"
              @open="(slug, resume) => emit('open', slug, resume)"
              @redraft="(slug) => emit('redraft', slug)"
            />
          </ol>
        </CollapsibleContent>
      </CollapsibleRoot>
    </div>

    <template #aside>
      <!-- Report status first, then drafting activity (only while a run is live or has stopped), then the export. -->
      <div class="space-y-3">
        <div class="space-y-1.5">
          <div class="flex items-baseline justify-between text-xs">
            <span class="font-semibold">{{ groupLabel }}</span>
            <span class="font-mono text-muted-foreground">{{ approved }}/{{ overview.sections.length }} approved</span>
          </div>
          <div class="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div class="h-full bg-ok-fg" :style="{ width: `${overview.sections.length ? (approved / overview.sections.length) * 100 : 0}%` }" />
          </div>
        </div>
        <dl role="group" aria-label="Sections by state" class="divide-y text-sm">
          <div v-for="[label, value] in tally" :key="label" class="flex items-baseline justify-between gap-3 py-1.5" :class="value === 0 && 'text-muted-foreground'">
            <dt>{{ label }}</dt>
            <dd class="font-mono font-semibold">{{ value }}<span class="text-xs font-normal text-muted-foreground"> / {{ overview.sections.length }}</span></dd>
          </div>
        </dl>
      </div>
      <ActivityPanel :drafting="drafting" :report="report" />
      <ExportBar
        v-if="overview.report.type === 'weekly'"
        :period="overview.report.period"
        :refresh-key="overview.sections.map((s) => `${s.latest?.run_id ?? ''}:${s.latest?.decision ?? ''}`).join('|')"
        @status="(status) => (exportStatus = status)"
        @error="(message) => (exportError = message)"
      />
    </template>
  </PageGrid>
</template>
