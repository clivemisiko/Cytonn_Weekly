<script setup lang="ts">
import { PhCaretRight, PhCircleNotch, PhLockSimple } from "@phosphor-icons/vue";
import { computed } from "vue";
import Button from "@/components/ui/Button.vue";
import { CHIP as CHIP_BASE } from "@/components/ui/button";
import { type SectionState, stateOf, useLiveElapsed, when } from "@/lib/drafting";
import { elapsed, friendlyDate, weekRange } from "@/lib/format";
import type { Drafting, SectionSummary } from "@/lib/types";

const CHIP: Record<SectionState, { label: string; className: string; glyph?: string; stateClass?: string }> = {
  approved: { label: "Approved", className: "border-ok/40 bg-ok/10 text-ok-fg", glyph: "✓", stateClass: "state-clean" },
  rejected: { label: "Rejected", className: "border-flag/40 bg-flag/10 text-flag-fg", glyph: "!", stateClass: "state-flagged" },
  in_review: { label: "In review", className: "border-primary/40 bg-primary/10 text-foreground" },
  not_drafted: { label: "Not drafted this week", className: "border-input text-muted-foreground" },
  unavailable: { label: "Not available yet", className: "border-input bg-muted text-muted-foreground" },
};

/** One section's card on the overview: its state, its progress or why nothing is there, and the one action. */
const props = defineProps<{
  s: SectionSummary;
  index: number;
  period: string;
  /** Set only on the card of the section being drafted right now. */
  drafting: Drafting | null;
}>();
const emit = defineEmits<{ open: [slug: string, resume: boolean] }>();

const state = computed(() => stateOf(props.s));
const run = computed(() => props.s.latest);
const current = computed(() => Boolean(run.value && (run.value.current ?? run.value.this_week)));
const chip = computed(() => CHIP[state.value]);
const chipLabel = computed(() => (state.value === "not_drafted" ? `Not drafted ${when(props.period)}` : chip.value.label));
const action = computed(() => {
  const draftLabel = props.s.needs_text ? "Add your text" : props.s.requires_approved ? "Compose summary" : "Draft section";
  if (state.value === "unavailable") return null;
  if (state.value === "in_review") return { label: "Resume review", resume: true, primary: true };
  if (state.value === "not_drafted") return { label: draftLabel, resume: false, primary: true };
  return { label: "View review", resume: true, primary: false };
});
const seconds = useLiveElapsed(() => props.drafting);
const nothing = computed(() => {
  const r = run.value;
  const first = props.drafting
    ? props.drafting.stale
      ? "A draft has run far longer than it should and looks stuck. Drafting again replaces it."
      : "Drafting now; the review shows here when it finishes."
    : `Nothing drafted ${when(props.period)}.`;
  return (
    first +
    (r ? ` The last review (run ${r.run_id}, ${friendlyDate(r.run_date)}) was ${r.decision ?? "left in progress"}.` : "") +
    (props.s.needs_topic ? " Drafting asks for this week’s topic." : "") +
    (props.s.needs_text ? " You paste this section’s text; the tool never drafts Cytonn’s own copy." : "") +
    (props.s.requires_approved ? " Composed from the other sections once every one of them is approved." : "")
  );
});
</script>

<template>
  <li
    class="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-4 gap-y-3 rounded-lg border bg-card p-4 sm:p-6 md:grid-cols-[2rem_minmax(0,14rem)_minmax(0,1fr)_auto] md:items-start"
    :class="state === 'unavailable' && 'bg-muted/50'"
    :aria-labelledby="`sec-${s.slug}`"
  >
    <span class="inline-grid h-6 w-8 place-items-center rounded-sm bg-primary font-mono text-xs font-semibold text-primary-foreground" aria-hidden="true">
      {{ index + 1 }}
    </span>

    <div class="min-w-0 space-y-2">
      <h2 :id="`sec-${s.slug}`" class="text-base font-semibold">{{ s.title }}</h2>
      <div class="flex flex-wrap items-center gap-2">
        <span :class="[CHIP_BASE, chip.className, chip.stateClass]">
          <span v-if="chip.glyph" class="glyph size-4 text-xs" aria-hidden="true">{{ chip.glyph }}</span>
          <PhLockSimple v-if="state === 'unavailable'" weight="bold" class="size-3" aria-hidden="true" />
          {{ chipLabel }}
        </span>
        <!-- Small chip on the drafting section's own card. -->
        <span
          v-if="drafting"
          :class="[CHIP_BASE, drafting.stale ? 'border-warn/40 bg-warn/10 text-warn-fg' : 'border-primary/40 bg-primary/10 text-foreground']"
        >
          <PhCircleNotch weight="bold" class="size-3" :class="!drafting.stale && 'animate-spin motion-reduce:animate-none'" aria-hidden="true" />
          {{ drafting.stale ? "Looks stuck" : "Drafting now" }}
          <span class="font-mono font-medium tabular-nums">{{ elapsed(seconds) }}</span>
        </span>
        <span v-if="current && run?.is_dev_draft" class="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-dev-ink">DEV DRAFT</span>
      </div>
    </div>

    <div class="col-start-2 min-w-0 md:col-start-3">
      <div v-if="state === 'unavailable'" class="space-y-2 text-sm">
        <p>{{ s.reason }}</p>
        <p class="text-muted-foreground"><span class="font-semibold text-foreground">Unblocked by:</span> {{ s.unblock }}</p>
        <div v-if="s.built_parts.length > 0">
          <p class="eyebrow pb-1">Already built</p>
          <ul class="list-disc space-y-1 pl-5 text-muted-foreground marker:text-input">
            <li v-for="p in s.built_parts" :key="p">{{ p }}</li>
          </ul>
        </div>
      </div>
      <div v-else-if="run && current" class="space-y-2">
        <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
          <span>
            <span class="font-mono font-semibold">{{ run.progress.resolved }}</span> of
            <span class="font-mono font-semibold">{{ run.progress.total }}</span> items resolved
          </span>
          <span v-if="run.counts.flagged.total > 0" class="state-flagged inline-flex items-center gap-1 text-xs font-semibold text-(--hue-fg)">
            <span class="glyph size-4 text-xs" aria-hidden="true">!</span>
            {{ run.counts.flagged.total }} flagged
          </span>
        </div>
        <div
          role="progressbar"
          :aria-label="`${s.title}: items resolved`"
          aria-valuemin="0"
          :aria-valuemax="run.progress.total"
          :aria-valuenow="run.progress.resolved"
          class="h-2 overflow-hidden rounded-full bg-border"
        >
          <div class="h-full rounded-full bg-primary" :style="{ width: `${run.progress.total ? (run.progress.resolved / run.progress.total) * 100 : 0}%` }" />
        </div>
        <p class="text-xs text-muted-foreground">
          Run <span class="font-mono">{{ run.run_id }}</span
          >{{ run.week_start && run.week_end ? `, ${period ? "period" : "report week"} ${weekRange(run.week_start, run.week_end)}` : ""
          }}{{ run.topic ? `. Topic: ${run.topic}` : "" }}
        </p>
      </div>
      <p v-else class="text-sm text-muted-foreground">{{ nothing }}</p>
    </div>

    <div v-if="action" class="col-start-2 md:col-start-4 md:justify-self-end">
      <Button size="lg" :variant="action.primary ? 'default' : 'outline'" @click="emit('open', s.slug, action.resume)">
        {{ action.label }}
        <PhCaretRight weight="bold" data-icon="inline-end" aria-hidden="true" />
      </Button>
    </div>
  </li>
</template>
