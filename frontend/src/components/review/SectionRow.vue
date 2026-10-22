<script setup lang="ts">
import { PhArrowsClockwise, PhCaretRight, PhCircleNotch, PhLockSimple } from "@phosphor-icons/vue";
import { computed } from "vue";
import Button from "@/components/ui/Button.vue";
import { CHIP as CHIP_BASE } from "@/components/ui/button";
import { type SectionState, stateOf, useLiveElapsed, when } from "@/lib/drafting";
import { elapsed, friendlyDate, plural, weekRange } from "@/lib/format";
import type { Drafting, SectionSummary } from "@/lib/types";

const CHIP: Record<SectionState, { label: string; className: string; glyph?: string; stateClass?: string }> = {
  approved: { label: "Approved", className: "border-ok/40 bg-ok/10 text-ok-fg", glyph: "✓", stateClass: "state-clean" },
  rejected: { label: "Rejected", className: "border-flag/40 bg-flag/10 text-flag-fg", glyph: "!", stateClass: "state-flagged" },
  in_review: { label: "In review", className: "border-input bg-muted text-foreground" },
  not_drafted: { label: "Not drafted this week", className: "border-input text-muted-foreground" },
  unavailable: { label: "Not available yet", className: "border-input bg-muted text-muted-foreground" },
};
const RING = 2 * Math.PI * 18; // the progress ring's circumference (radius 18 in a 44-unit box)

/**
 * One section's card on the overview, in the issue's order: the section's number in a round badge outside the card, then
 * its title, its state and what is known about its latest run, a summary line, what is flagged and how many charts
 * the real issue carries, and the actions. Everything shown comes from the overview's payload for the section; nothing
 * here is worked out or fetched. What a person must act on is never cut: the reason a section is unavailable, what
 * unblocks it, the sentence about the last review, and the flagged count are always shown in full. "Show more" only
 * opens the section's own headings, its charts and what is already built.
 */
const props = defineProps<{
  s: SectionSummary;
  index: number;
  period: string;
  /** Set only on the card of the section being drafted right now. */
  drafting: Drafting | null;
  /** Why "Draft again" is off (another draft holds the slot, the provider cannot run), or null when it is on. */
  draftAgainOff: string | null;
}>();
const emit = defineEmits<{ open: [slug: string, resume: boolean]; redraft: [slug: string] }>();

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
// A section that already has a review (in review, approved or rejected) can be drafted again; the start screen asks first.
const canRedraft = computed(() => state.value === "in_review" || state.value === "approved" || state.value === "rejected");
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

const fraction = computed(() => (run.value && run.value.progress.total ? run.value.progress.resolved / run.value.progress.total : 0));
/** The flagged items of the section's current review, as the overview's payload counts them (0 with no current review). */
const flagged = computed(() => (run.value && current.value ? run.value.counts.flagged.total : 0));
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
    <div class="grid grid-cols-1 gap-x-3 @md:grid-cols-[2.5rem_minmax(0,1fr)]">
      <span class="hidden size-10 place-items-center rounded-full bg-muted font-mono text-sm font-semibold text-foreground @md:grid" aria-hidden="true">
        {{ index + 1 }}
      </span>

      <div class="min-w-0 space-y-3 rounded-lg border bg-card p-4 @lg:p-6" :class="state === 'unavailable' && 'bg-muted/50'">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0 space-y-2">
            <h2 :id="`sec-${s.slug}`" class="text-lg font-semibold">{{ s.title }}</h2>
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span :class="[CHIP_BASE, chip.className, chip.stateClass]">
                <span v-if="chip.glyph" class="glyph size-4 text-xs" aria-hidden="true">{{ chip.glyph }}</span>
                <PhLockSimple v-if="state === 'unavailable'" weight="bold" class="size-3" aria-hidden="true" />
                {{ chipLabel }}
              </span>
              <!-- Small chip on the drafting section's own card. -->
              <span
                v-if="drafting"
                :class="[CHIP_BASE, drafting.stale ? 'border-warn/40 bg-warn/10 text-warn-fg' : 'border-input bg-muted text-foreground']"
              >
                <PhCircleNotch weight="bold" class="size-3" :class="!drafting.stale && 'animate-spin motion-reduce:animate-none'" aria-hidden="true" />
                {{ drafting.stale ? "Looks stuck" : "Drafting now" }}
                <span class="font-mono font-medium tabular-nums">{{ elapsed(seconds) }}</span>
              </span>
              <span v-if="current && run?.is_dev_draft" class="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-dev-ink">DEV DRAFT</span>
              <p v-if="run && current && state !== 'unavailable'" class="text-xs text-muted-foreground">
                Run <span class="font-mono">{{ run.run_id }}</span
                >{{ run.week_start && run.week_end ? `, ${period ? "period" : "report week"} ${weekRange(run.week_start, run.week_end)}` : ""
                }}{{ run.topic ? `. Topic: ${run.topic}` : "" }}
              </p>
            </div>
          </div>

          <!-- The thumbnail's place: how far the review is, as a ring. -->
          <div
            v-if="state !== 'unavailable' && run && current"
            role="progressbar"
            :aria-label="`${s.title}: items resolved`"
            aria-valuemin="0"
            :aria-valuemax="run.progress.total"
            :aria-valuenow="run.progress.resolved"
            class="relative hidden size-12 shrink-0 @md:block"
          >
            <svg viewBox="0 0 44 44" class="size-12 -rotate-90" aria-hidden="true">
              <circle cx="22" cy="22" r="18" fill="none" stroke-width="4" class="stroke-border" />
              <circle
                cx="22"
                cy="22"
                r="18"
                fill="none"
                stroke-width="4"
                stroke-linecap="round"
                class="stroke-foreground"
                :stroke-dasharray="RING"
                :stroke-dashoffset="RING * (1 - fraction)"
              />
            </svg>
            <span class="absolute inset-0 grid place-items-center font-mono text-xs font-semibold" aria-hidden="true">{{ run.progress.resolved }}/{{ run.progress.total }}</span>
          </div>
        </div>

        <div class="space-y-2 text-sm">
          <template v-if="state === 'unavailable'">
            <p>{{ s.reason }}</p>
            <p class="text-muted-foreground"><span class="font-semibold text-foreground">Unblocked by:</span> {{ s.unblock }}</p>
          </template>
          <p v-else-if="run && current">
            <span class="font-mono font-semibold">{{ run.progress.resolved }}</span> of
            <span class="font-mono font-semibold">{{ run.progress.total }}</span> items resolved
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

        <div v-if="action || flagged > 0 || s.charts.length > 0" class="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t pt-3">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span v-if="flagged > 0" class="state-flagged inline-flex items-center gap-1 text-xs font-semibold text-(--hue-fg)">
              <span class="glyph size-4 text-xs" aria-hidden="true">!</span>
              {{ flagged }} flagged
            </span>
            <span v-if="s.charts.length > 0" :class="[CHIP_BASE, 'border-input font-medium text-muted-foreground']">{{ plural(s.charts.length, "chart") }} to add by hand</span>
          </div>
          <div v-if="action" class="flex min-w-0 flex-col gap-2 @md:items-end">
            <div class="flex flex-wrap gap-2 @md:justify-end">
              <Button size="lg" :variant="action.primary ? 'default' : 'outline'" @click="emit('open', s.slug, action.resume)">
                {{ action.label }}
                <PhCaretRight weight="bold" data-icon="inline-end" aria-hidden="true" />
              </Button>
              <Button
                v-if="canRedraft"
                size="lg"
                variant="outline"
                :disabled="draftAgainOff !== null"
                :aria-describedby="draftAgainOff ? `redraft-off-${s.slug}` : undefined"
                @click="emit('redraft', s.slug)"
              >
                <PhArrowsClockwise weight="bold" data-icon="inline-start" aria-hidden="true" />
                Draft again
              </Button>
            </div>
            <p v-if="canRedraft && draftAgainOff" :id="`redraft-off-${s.slug}`" class="max-w-72 text-xs text-muted-foreground @md:text-right">
              {{ draftAgainOff }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </li>
</template>
