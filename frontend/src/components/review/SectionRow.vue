<script setup lang="ts">
import { PhArrowsClockwise, PhCaretRight, PhCircleNotch, PhLockSimple } from "@phosphor-icons/vue";
import { computed } from "vue";
import { RouterLink } from "vue-router";
import Button from "@/components/ui/Button.vue";
import { CHIP as CHIP_BASE } from "@/components/ui/button";
import { type SectionState, canRedraft, draftingStatus, flaggedOf, sectionAction, stateOf, useLiveElapsed, when } from "@/lib/drafting";
import { elapsed, friendlyDate, plural, weekRange } from "@/lib/format";
import { textOf } from "@/lib/run";
import type { Drafting, SectionSummary } from "@/lib/types";

const CHIP: Record<SectionState, { label: string; className: string; glyph?: string; stateClass?: string }> = {
  approved: { label: "Approved", className: "border-ok/40 bg-ok/10 text-ok-fg", glyph: "✓", stateClass: "state-clean" },
  rejected: { label: "Rejected", className: "border-flag/40 bg-flag/10 text-flag-fg", glyph: "!", stateClass: "state-flagged" },
  in_review: { label: "In review", className: "border-input bg-muted text-foreground" },
  not_drafted: { label: "Not drafted this week", className: "border-input text-muted-foreground" },
  unavailable: { label: "Not available yet", className: "border-input bg-muted text-muted-foreground" },
};

const props = defineProps<{
  s: SectionSummary;
  index: number;
  period: string;
  /** This section's entry from the server: running, queued, or its newest run's failure; null when it has none. */
  drafting: Drafting | null;
  /** Why "Draft again" is off (this section is running or queued, the provider cannot run), or null when it is on. */
  draftAgainOff: string | null;
}>();
const emit = defineEmits<{ open: [slug: string, resume: boolean]; redraft: [slug: string] }>();

const state = computed(() => stateOf(props.s));
const run = computed(() => props.s.latest);
const current = computed(() => Boolean(run.value && (run.value.current ?? run.value.this_week)));
const chip = computed(() => CHIP[state.value]);
const chipLabel = computed(() => (state.value === "not_drafted" ? `Not drafted ${when(props.period)}` : chip.value.label));
const action = computed(() => sectionAction(props.s));
const canRedraftIt = computed(() => canRedraft(props.s));
const seconds = useLiveElapsed(() => props.drafting);
const failed = computed(() => props.drafting?.state === "failed");
const queued = computed(() => props.drafting?.state === "queued");
// The step a running draft reported last, in the run view's own wording.
const step = computed(() => (props.drafting?.step ? textOf(props.drafting.step) : null));
const nothing = computed(() => {
  const r = run.value;
  const d = props.drafting;
  const first = failed.value
    ? `The last draft stopped. ${d?.reason ?? ""}`.trim()
    : d
      ? d.stale
        ? "This draft has exceeded normal runtime and may have stalled. Drafting again will replace it."
        : queued.value
          ? "Queued for drafting; processing will begin automatically once a worker is available."
          : "Drafting now; the review shows here when it finishes."
      : `No draft generated yet ${when(props.period)}.`;
  return (
    first +
    (r ? ` The last review (run ${r.run_id}, ${friendlyDate(r.run_date)}) was ${r.decision ?? "left in progress"}.` : "") +
    (props.s.needs_topic ? " Drafting asks for this week’s topic." : "") +
    (props.s.requires_approved ? " Compiled from the other report sections once all five are approved." : "")
  );
});

const flagged = computed(() => flaggedOf(props.s));
const hasMore = computed(() => props.s.built_parts.length > 0 || props.s.subsections.length > 0 || props.s.charts.length > 0);
const lists = computed(() =>
  [
    { title: "Already built", items: props.s.built_parts },
    { title: "In the real report", items: props.s.subsections },
    { title: "Charts to add by hand", items: props.s.charts },
  ].filter((l) => l.items.length > 0),
);
</script>

<template>
  <li class="@container" :aria-labelledby="`sec-${s.slug}`">
    <div class="grid grid-cols-1 gap-x-3 @md:grid-cols-[1.75rem_minmax(0,1fr)]">
      <span class="mt-3 ml-3 hidden size-7 place-items-center font-mono text-xs font-semibold text-muted-foreground @md:grid" aria-hidden="true">
        {{ String(index + 1).padStart(2, "0") }}
      </span>

      <div
        class="min-w-0 space-y-2.5 px-4 py-3"
        :class="state === 'unavailable' && 'bg-muted/40'"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0 space-y-2">
            <h2 :id="`sec-${s.slug}`" tabindex="-1" class="outline-none text-base font-semibold tracking-tight text-foreground">{{ s.title }}</h2>
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span :class="[CHIP_BASE, chip.className, chip.stateClass, 'rounded-sm border-transparent text-[0.6875rem] tracking-wider uppercase']">
                <span v-if="chip.glyph" class="glyph size-4 text-xs" aria-hidden="true">{{ chip.glyph }}</span>
                <PhLockSimple v-if="state === 'unavailable'" weight="bold" class="size-3" aria-hidden="true" />
                {{ chipLabel }}
              </span>
              <!-- Small chip on the drafting section's own card. -->
              <span
                v-if="drafting && failed"
                :class="[CHIP_BASE, 'border-flag/40 bg-flag/10 text-flag-fg', 'state-flagged', 'shadow-2xs']"
              >
                <span class="glyph size-4 text-xs" aria-hidden="true">!</span>
                Draft failed
              </span>
              <span
                v-else-if="drafting"
                :class="[CHIP_BASE, drafting.stale ? 'border-warn/40 bg-warn/10 text-warn-fg' : 'border-input bg-muted text-foreground', 'shadow-2xs']"
              >
                <PhCircleNotch weight="bold" class="size-3" :class="!drafting.stale && !queued && 'animate-spin motion-reduce:animate-none'" aria-hidden="true" />
                {{ drafting.stale ? "Stalled" : draftingStatus(drafting) }}
                <span v-if="!queued" class="font-mono font-medium tabular-nums">{{ elapsed(seconds) }}</span>
              </span>
              <p v-if="drafting && !failed && !queued && step" class="text-xs text-muted-foreground">{{ step }}</p>
              <p v-if="drafting && failed" class="text-xs text-muted-foreground">
                {{ drafting.reason ?? "The draft stopped." }}
                <RouterLink v-if="drafting.run_id" :to="`/runs/${drafting.run_id}`" class="underline">See the run</RouterLink>
              </p>
              <span v-if="current && run?.is_dev_draft" class="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-dev-ink shadow-2xs">DEV DRAFT</span>
              <p v-if="run && current && state !== 'unavailable'" class="text-xs text-muted-foreground">
                Run <span class="font-mono font-medium">{{ run.run_id }}</span
                >{{ run.week_start && run.week_end ? `, ${period ? "period" : "report week"} ${weekRange(run.week_start, run.week_end)}` : ""
                }}{{ run.topic ? `. Topic: ${run.topic}` : "" }}
              </p>
            </div>
          </div>
        </div>

        <div class="space-y-2 text-sm">
          <template v-if="state === 'unavailable'">
            <p>{{ s.reason }}</p>
            <p class="text-muted-foreground"><span class="font-semibold text-foreground">Unblocked by:</span> {{ s.unblock }}</p>
          </template>
          <p v-else-if="run && current">
            <span class="font-mono font-semibold">{{ run.progress.total }}</span> review items
          </p>
          <p v-else class="text-muted-foreground">{{ nothing }}</p>

          <!-- A native disclosure: keyboard and screen-reader support with no script, and it is not a second button on
               the card (a section never drafted has one button, its action). -->
          <details v-if="hasMore" class="group">
            <summary
              class="inline-block cursor-pointer rounded-sm text-sm font-semibold text-link underline decoration-link/40 underline-offset-2 outline-none marker:hidden hover:decoration-link focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"
            >
              <span class="group-open:hidden">Show more</span><span class="hidden group-open:inline">Show less</span
              ><span class="sr-only">: {{ s.title }}</span>
            </summary>
            <div class="mt-3 space-y-3 border-t pt-3">
              <div v-for="l in lists" :key="l.title" class="space-y-1">
                <p class="eyebrow">{{ l.title }}</p>
                <ul class="list-disc space-y-1 pl-5 text-muted-foreground marker:text-input">
                  <li v-for="item in l.items" :key="item">{{ item }}</li>
                </ul>
              </div>
            </div>
          </details>
        </div>

        <div v-if="action || flagged > 0 || s.charts.length > 0" class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t pt-2.5">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span v-if="flagged > 0" class="state-flagged inline-flex items-center gap-1 text-xs font-semibold text-(--hue-fg)">
              <span class="glyph size-4 text-xs" aria-hidden="true">!</span>
              {{ flagged }} flagged
            </span>
            <span v-if="s.charts.length > 0" :class="[CHIP_BASE, 'border-input font-medium text-muted-foreground']">{{ plural(s.charts.length, "chart") }} to add by hand</span>
          </div>
          <div v-if="action" class="flex min-w-0 flex-col gap-2 @md:items-end">
            <div class="flex flex-wrap gap-2 @md:justify-end">
              <Button :variant="action.primary ? 'default' : 'outline'" @click="emit('open', s.slug, action.resume)">
                {{ action.label }}
                <PhCaretRight weight="bold" data-icon="inline-end" aria-hidden="true" />
              </Button>
              <Button
                v-if="canRedraftIt"
                variant="outline"
                :disabled="draftAgainOff !== null"
                :aria-describedby="draftAgainOff ? `redraft-off-${s.slug}` : undefined"
                @click="emit('redraft', s.slug)"
              >
                <PhArrowsClockwise weight="bold" data-icon="inline-start" aria-hidden="true" />
                Draft again
              </Button>
            </div>
            <p v-if="canRedraftIt && draftAgainOff" :id="`redraft-off-${s.slug}`" class="max-w-72 text-xs text-muted-foreground @md:text-right">
              {{ draftAgainOff }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </li>
</template>
