<script setup lang="ts">
import { PhLockSimple } from "@phosphor-icons/vue";
import { computed } from "vue";
import { STATUS_ORDER, friendlyTime, weekRange } from "@/lib/format";
import { useReviewSession } from "@/lib/session";
import { isBlocksSection, type Review, type StatusCounts } from "@/lib/types";
import BlocksPane from "./BlocksPane.vue";
import CountTile from "./CountTile.vue";
import DevRibbon from "./DevRibbon.vue";
import DraftPane from "./DraftPane.vue";
import ItemsPane from "./ItemsPane.vue";
import Masthead from "./Masthead.vue";
import StatusBar from "./StatusBar.vue";

/**
 * One open review: the sticky status bar (progress and the decision), the scorecard, and the drafted section beside its review items.
 * The tool never approves anything; this screen only records what the coordinator decides.
 */
const props = defineProps<{ initial: Review }>();
const emit = defineEmits<{ close: [] }>();

const session = useReviewSession(props.initial);
const review = session.review;
const dev = computed(() => (review.value.is_dev_draft && review.value.dev_mode_label ? review.value.dev_mode_label : null));
const approved = computed(() => review.value.decision === "approved");

function subline(c: StatusCounts): string {
  if (c.total === 0) return "None in this draft";
  const parts = [c.unresolved ? `${c.unresolved} unresolved` : "", c.fix_needed ? `${c.fix_needed} fix needed` : ""].filter(Boolean);
  return parts.length ? parts.join(", ") : "All accepted";
}
</script>

<template>
  <DevRibbon v-if="dev" :label="dev" />
  <div :class="dev && 'pt-7'">
    <Masthead wide :title="`${review.section_title}: coordinator review`">
      <template #meta>
        <template v-if="review.period && review.report_type !== 'weekly'">
          {{ review.report_title }}, <span class="font-mono">{{ review.period }}</span
          >, run <span class="font-mono">{{ review.run_id }}</span>
        </template>
        <template v-else>
          <span v-if="review.period" class="font-mono">{{ review.period }}</span
          ><template v-else>Report week</template> {{ weekRange(review.section.week_start, review.section.week_end) }}, run
          <span class="font-mono">{{ review.run_id }}</span>
        </template>
      </template>
    </Masthead>
    <div class="mx-auto w-full max-w-375 px-4 pb-16 sm:px-6">
      <StatusBar
        :review="review"
        :saving="session.saving.value"
        :save-error="session.saveError.value"
        :has-dev-ribbon="Boolean(dev)"
        :deciding="session.deciding.value"
        :decision-error="session.decisionError.value"
        :on-decide="session.decide"
        @close="emit('close')"
      />

      <div class="space-y-6 pt-6">
        <div
          v-if="review.decision"
          role="status"
          class="rise-in flex flex-col gap-1 rounded-lg border border-l-[6px] px-4 py-3"
          :class="approved ? 'border-ok/40 border-l-ok bg-ok/10' : 'border-flag/40 border-l-flag bg-flag/10'"
        >
          <span class="flex items-center gap-2 text-base font-semibold" :class="approved ? 'text-ok-fg' : 'text-flag-fg'">
            <PhLockSimple weight="bold" class="size-4" aria-hidden="true" />
            {{ approved ? "Approved" : "Rejected" }} and locked
          </span>
          <span class="text-sm text-muted-foreground">
            Decision recorded{{ review.decided_at ? ` on ${friendlyTime(review.decided_at)}` : "" }}. Every value below is frozen as drafted; nothing on
            this screen can be changed.
          </span>
        </div>
        <!-- Three counts, one per status, in the same colour, glyph and border style the item cards use. -->
        <div role="group" aria-label="Review items by status" class="grid grid-cols-1 gap-3 md:grid-cols-3">
          <CountTile v-for="s in STATUS_ORDER" :key="s" :status="s" :value="review.counts[s].total" :sub="subline(review.counts[s])" />
        </div>
        <div class="grid grid-cols-1 items-start gap-x-8 gap-y-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <BlocksPane v-if="isBlocksSection(review.section)" :review="review" :section="review.section" />
          <DraftPane v-else :review="review" :section="review.section" />
          <ItemsPane :review="review" :locked="review.locked" :on-resolve="session.resolve" :on-accept-clean="session.acceptClean" />
        </div>
      </div>
    </div>
  </div>
</template>
