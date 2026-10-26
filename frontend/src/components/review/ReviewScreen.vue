<script setup lang="ts">
import { PhLockSimple } from "@phosphor-icons/vue";
import { computed, provide, watch } from "vue";
import { OPEN_REVIEW, lastRecheck } from "@/lib/fixfile";
import { STATUS_ORDER, friendlyTime, weekRange } from "@/lib/format";
import PageGrid from "@/components/nav/PageGrid.vue";
import { weekOfReview } from "@/lib/notable";
import { useReviewSession } from "@/lib/session";
import { shell, useShellRibbon } from "@/lib/shell";
import { isBlocksSection, type Review, type StatusCounts } from "@/lib/types";
import BlocksPane from "./BlocksPane.vue";
import CountTile from "./CountTile.vue";
import DraftPane from "./DraftPane.vue";
import ItemsPane from "./ItemsPane.vue";
import Masthead from "./Masthead.vue";
import NotablePanel from "./NotablePanel.vue";
import RecheckResult from "./RecheckResult.vue";
import RejectedDraftNotes from "./RejectedDraftNotes.vue";
import StatusBar from "./StatusBar.vue";

/**
 * One open review: the sticky status bar (progress and the decision), the scorecard, and the drafted section beside its review items.
 * The tool never approves anything; this screen only records what the coordinator decides.
 */
const props = defineProps<{ initial: Review }>();
const emit = defineEmits<{ close: []; open: [review: Review]; redraft: [slug: string] }>();
// A card that fixed an item from a file hands the new review up, and the page shows it in this one's place.
provide(OPEN_REVIEW, (next: Review) => emit("open", next));
const recheck = computed(() => (lastRecheck.value?.runId === props.initial.run_id ? lastRecheck.value.result : null));

const session = useReviewSession(props.initial);
const review = session.review;
const dev = computed(() => (review.value.is_dev_draft && review.value.dev_mode_label ? review.value.dev_mode_label : null));
const approved = computed(() => review.value.decision === "approved");
const week = computed(() => weekOfReview(review.value));
useShellRibbon(dev); // the shell draws it under the top bar

// An approval or a rejection changes the section's state: the rail's states are unknown at once and read again.
watch(
  () => review.value.decision,
  (now, before) => {
    if (now && now !== before) {
      shell.invalidate();
      void shell.refreshFor(review.value.report_type, review.value.period);
    }
  },
);

function subline(c: StatusCounts): string {
  if (c.total === 0) return "None in this draft";
  const parts = [c.unresolved ? `${c.unresolved} unresolved` : "", c.fix_needed ? `${c.fix_needed} fix needed` : ""].filter(Boolean);
  return parts.length ? parts.join(", ") : "All accepted";
}
</script>

<template>
  <div>
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
    <!-- The status bar sticks under the top bar across both columns: the count of unresolved items, whether the section can be
         approved, and the decision never scroll out of reach. -->
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

    <!-- The draft is the content; the review items are the panel beside it. The panel is never folded (it is the work and it
         holds the flags) and, being as tall as the section, it is left in the flow. -->
    <PageGrid aside-title="Review items" hide-title wide-body :sticky="false">
      <div class="space-y-6">
        <RecheckResult v-if="recheck" :result="recheck" @redraft="emit('redraft', review.section_slug)" />
        <RejectedDraftNotes :run-id="review.run_id" />
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
        <div role="group" aria-label="Review items by status" class="grid grid-cols-1 gap-3 @min-[34rem]:grid-cols-3">
          <CountTile v-for="s in STATUS_ORDER" :key="s" :status="s" :value="review.counts[s].total" :sub="subline(review.counts[s])" />
        </div>
        <BlocksPane
          v-if="isBlocksSection(review.section)"
          :review="review"
          :section="review.section"
          :on-team-chart="session.setTeamChart"
        />
        <DraftPane v-else :review="review" :section="review.section" />
        <!-- The analyst's worklist for this week: separate from the review above, which it never changes. -->
        <NotablePanel
          v-if="week"
          :key="`notable-${review.section_slug}-${week}`"
          :section="review.section_slug"
          :section-title="review.section_title"
          :week="week"
        />
      </div>

      <template #aside>
        <ItemsPane :review="review" :locked="review.locked" :on-resolve="session.resolve" :on-accept-clean="session.acceptClean" />
      </template>
    </PageGrid>
  </div>
</template>
