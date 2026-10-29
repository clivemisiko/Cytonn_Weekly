<script setup lang="ts">
import { PhCaretDown } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, ref } from "vue";
import PageGrid from "@/components/nav/PageGrid.vue";
import { exportChartsNote } from "@/lib/charts";
import { type SectionState, draftAgainOff, isDraftingThis, stateOf, useDraftingPoll } from "@/lib/drafting";
import { friendlyDate, plural, reportName } from "@/lib/format";
import { useShellRibbon } from "@/lib/shell";
import type { AppConfig, ExportStatus, Overview, ReportChoice } from "@/lib/types";
import DraftingBanner from "./DraftingBanner.vue";
import ExportBar from "./ExportBar.vue";
import Masthead from "./Masthead.vue";
import Notice from "./Notice.vue";
import ReportPicker from "./ReportPicker.vue";
import SectionRow from "./SectionRow.vue";

const props = defineProps<{
  overview: Overview;
  config: AppConfig;
  /** The report on screen, as the API normalized it. */
  report: ReportChoice;
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
const drafting = computed(() => props.overview.drafting);
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
const groupLabel = computed(() => {
  const period = props.overview.report.period;
  return period.startsWith("Week ending ") ? `Week ending ${friendlyDate(period.slice(12))}` : period || "This week";
});
const approved = computed(() => props.overview.sections.filter((s) => stateOf(s) === "approved").length);
const flagged = computed(() =>
  props.overview.sections.reduce((n, s) => (s.latest && (s.latest.current ?? s.latest.this_week) ? n + s.latest.counts.flagged.total : n), 0),
);
</script>

<template>
  <PageGrid aside-title="Report status" storage-key="overview">
    <Masthead flush title="Coordinator review">
      <template #meta>Today {{ friendlyDate(overview.today) }}</template>
      {{ kind ? `${kind.title}: ` : `${name}: ` }}{{ plural(overview.sections.length, "report section") }}. Each is drafted, checked and approved or rejected on its own.
    </Masthead>

    <div class="mt-6 space-y-6">
      <ReportPicker
        :key="`${report.type}|${report.period}|${report.kind ?? ''}`"
        :current="report"
        :types="overview.report_types"
        :kinds="overview.companion_kinds"
        :on-apply="onReport"
      />
      <Notice v-if="config.dev_mode" role="alert" class="font-semibold">
        CYTONN_LLM_PROVIDER=local: DEV MODE. Drafts from the local model are NOT FOR PUBLICATION.
      </Notice>
      <Notice v-if="exportStatus?.is_dev_draft" role="alert" class="font-semibold">
        {{ exportStatus.dev_mode_label }} The export carries a DEV MODE watermark on every page and must not be sent or published ({{ exportStatus.dev_sections.join(", ") }}).
      </Notice>
      <!-- In the feed, not the foldable panel beside the export button: a note there could be folded away. -->
      <Notice v-if="exportChartsNote(exportStatus?.charts_missing ?? 0)" tone="info" role="status">
        {{ exportChartsNote(exportStatus?.charts_missing ?? 0) }}
      </Notice>
      <div v-if="exportError" data-attention="export-bar">
        <Notice role="alert" data-problem class="font-medium">{{ exportError }}</Notice>
      </div>
      <DraftingBanner v-if="drafting" :drafting="drafting" />
      <Notice v-if="overview.report.type === 'companion'" tone="info">
        Companion research reports ride inside a weekly issue as its Focus of the Week. Every section below is Cytonn’s own
        analysis, so none can be drafted yet; the weekly Focus of the Week can still draft a cited piece on the same topic.
      </Notice>

      <!-- Visual Pipeline Progress Stepper -->
      <div class="rounded-xl border border-border bg-card p-4.5 shadow-xs">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="eyebrow">Publication Pipeline</span>
            <span
              class="rounded-full px-2 py-0.5 text-xs font-semibold"
              :class="approved === overview.sections.length ? 'bg-ok/15 text-ok-fg' : 'bg-primary/10 text-primary-fg'"
            >
              {{ approved }} of {{ overview.sections.length }} approved
            </span>
          </div>
          <span class="font-mono text-xs text-muted-foreground">
            {{ approved === overview.sections.length ? '✓ Ready for Word Export' : `${overview.sections.length - approved} section${overview.sections.length - approved === 1 ? '' : 's'} remaining` }}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-2 text-xs font-medium sm:grid-cols-4">
          <div class="flex items-center gap-2 rounded-lg border border-border/80 bg-muted/40 p-2.5">
            <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-foreground font-mono text-[10px] font-bold text-background">1</span>
            <span class="truncate">Inputs & Data</span>
          </div>
          <div class="flex items-center gap-2 rounded-lg border border-border/80 bg-muted/40 p-2.5">
            <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-foreground font-mono text-[10px] font-bold text-background">2</span>
            <span class="truncate">AI Research & Draft</span>
          </div>
          <div class="flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 p-2.5 text-primary-fg">
            <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary font-mono text-[10px] font-bold text-primary-invert">3</span>
            <span class="truncate font-semibold">Review & Verify</span>
          </div>
          <div
            class="flex items-center gap-2 rounded-lg border p-2.5"
            :class="exportStatus?.ready ? 'border-ok/40 bg-ok/10 text-ok-fg' : 'border-border/80 bg-muted/20 text-muted-foreground'"
          >
            <span
              class="flex size-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] font-bold"
              :class="exportStatus?.ready ? 'bg-ok text-ok-invert' : 'bg-muted-foreground/30 text-foreground'"
            >4</span>
            <span class="truncate">Word Export</span>
          </div>
        </div>
      </div>

      <CollapsibleRoot v-model:open="groupOpen" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <h2 class="text-base font-semibold">
            <CollapsibleTrigger class="flex items-center gap-2 rounded-md py-1 text-left outline-none hover:text-link focus-visible:ring-2 focus-visible:ring-ring">
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
          <ol class="space-y-4">
            <SectionRow
              v-for="(s, i) in overview.sections"
              :key="s.slug"
              :s="s"
              :index="i"
              :period="overview.report.period"
              :drafting="isDraftingThis(drafting, s.slug, report) ? drafting : null"
              :draft-again-off="draftAgainOff(s, drafting, config, report)"
              @open="(slug, resume) => emit('open', slug, resume)"
              @redraft="(slug) => emit('redraft', slug)"
            />
          </ol>
        </CollapsibleContent>
      </CollapsibleRoot>
    </div>

    <template #aside>
      <dl role="group" aria-label="Sections by state" class="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-xs @xl:grid-cols-5">
        <div v-for="[label, value] in tally" :key="label" class="flex flex-col gap-1.5 bg-card px-4 py-3.5 transition-colors hover:bg-muted/30 last:col-span-2 @xl:last:col-span-1">
          <dt class="eyebrow">{{ label }}</dt>
          <dd class="font-mono text-xl font-bold tracking-tight text-foreground">{{ value }}<span class="text-xs font-normal text-muted-foreground"> / {{ overview.sections.length }}</span></dd>
        </div>
      </dl>
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
