<script setup lang="ts">
import { computed } from "vue";
import { type SectionState, draftAgainOff, isDraftingThis, stateOf, useDraftingPoll } from "@/lib/drafting";
import { friendlyDate, plural, reportName } from "@/lib/format";
import type { AppConfig, Overview, ReportChoice } from "@/lib/types";
import DevRibbon from "./DevRibbon.vue";
import DraftingBanner from "./DraftingBanner.vue";
import ExportBar from "./ExportBar.vue";
import Masthead from "./Masthead.vue";
import Notice from "./Notice.vue";
import ReportPicker from "./ReportPicker.vue";
import SectionRow from "./SectionRow.vue";

/** Every section of the chosen report at a glance; each one is reviewed and decided on its own. */
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
</script>

<template>
  <DevRibbon v-if="config.dev_mode" :label="config.dev_mode_label" />
  <div :class="config.dev_mode && 'pt-7'">
    <Masthead title="Coordinator review">
      <template #meta>Today {{ friendlyDate(overview.today) }}</template>
      {{ kind ? `${kind.title}: ` : `${name}: ` }}{{ plural(overview.sections.length, "report section") }}. Each is drafted, checked and approved or rejected on its own.
    </Masthead>
    <div class="mx-auto w-full max-w-275 space-y-6 px-4 pt-8 pb-16 sm:px-6">
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
      <DraftingBanner v-if="drafting" :drafting="drafting" />
      <Notice v-if="overview.report.type === 'companion'" tone="info">
        Companion research reports ride inside a weekly issue as its Focus of the Week. Every section below is Cytonn’s own
        analysis, so none can be drafted yet; the weekly Focus of the Week can still draft a cited piece on the same topic.
      </Notice>
      <dl role="group" aria-label="Sections by state" class="grid grid-cols-2 divide-border rounded-lg border bg-card sm:grid-cols-5 sm:divide-x">
        <div v-for="[label, value] in tally" :key="label" class="flex flex-col gap-1 px-4 py-3 last:col-span-2 sm:last:col-span-1">
          <dt class="eyebrow">{{ label }}</dt>
          <dd class="font-mono text-xl font-semibold">{{ value }}<span class="text-sm font-medium text-muted-foreground"> / {{ overview.sections.length }}</span></dd>
        </div>
      </dl>
      <ExportBar
        v-if="overview.report.type === 'weekly'"
        :period="overview.report.period"
        :refresh-key="overview.sections.map((s) => `${s.latest?.run_id ?? ''}:${s.latest?.decision ?? ''}`).join('|')"
      />
      <ol class="space-y-3">
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
    </div>
  </div>
</template>
