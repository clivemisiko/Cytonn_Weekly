<script setup lang="ts">
import { PhArrowLeft, PhLockSimple } from "@phosphor-icons/vue";
import { computed, provide, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import { OPEN_REVIEW, lastRecheck } from "@/lib/fixfile";
import { lastSentence } from "@/lib/sentence";
import { STATUS_ORDER, friendlyTime, weekRange } from "@/lib/format";
import { weekOfReview } from "@/lib/notable";
import { READ_ONLY } from "@/lib/previous";
import { useReviewSession } from "@/lib/session";
import { shell, useShellRibbon } from "@/lib/shell";
import { isBlocksSection, type Review, type Status } from "@/lib/types";
import BlocksPane from "./BlocksPane.vue";
import CountTile from "./CountTile.vue";
import DraftPane from "./DraftPane.vue";
import ItemsPane from "./ItemsPane.vue";
import Masthead from "./Masthead.vue";
import NotablePanel from "./NotablePanel.vue";
import RecheckResult from "./RecheckResult.vue";
import RejectedDraftNotes from "./RejectedDraftNotes.vue";
import SentenceResult from "./SentenceResult.vue";
import StatusBar from "./StatusBar.vue";

const props = defineProps<{ initial: Review; readOnly?: boolean }>();
const emit = defineEmits<{ close: []; open: [review: Review]; redraft: [slug: string] }>();
// A card that fixed an item from a file hands the new review up, and the page shows it in this one's place.
provide(OPEN_REVIEW, (next: Review) => emit("open", next));
provide(READ_ONLY, props.readOnly ?? false);
const recheck = computed(() => (lastRecheck.value?.runId === props.initial.run_id ? lastRecheck.value.result : null));
const sentence = computed(() => (lastSentence.value?.runId === props.initial.run_id ? lastSentence.value.result : null));

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

// The strip filters the review items: one status, or every item when no tile is pressed.
// It opens on the first status that has items: Flagged, then Not auto-verified, then Clean.
const filter = ref<"all" | Status>(STATUS_ORDER.find((s) => props.initial.counts[s].total > 0) ?? "all");
const SUBLINES: Record<Status, string> = { flagged: "Read before approving", not_auto_verified: "Check by hand", clean: "Checked, no flag" };

// Pieces the reviewer took out of the draft, and whether any drafted finding is left.
const removed = computed(() => review.value.section.removed_findings ?? []);
const findingsLeft = computed(() => {
  const s = review.value.section;
  return isBlocksSection(s)
    ? s.blocks.some((b) => b.kind === "narrative" && b.role !== "lead" && b.role !== "conclusion")
    : s.items.some((i) => i.kind === "highlight");
});
</script>

<template>
  <div>
    <Masthead wide :title="`${review.section_title} review`" :crumbs="['Reports', review.report_title, review.section_title]">
      <template #actions>
        <Button size="sm" variant="outline" @click="emit('close')"><PhArrowLeft weight="bold" aria-hidden="true" />All sections</Button>
      </template>
      <template v-if="review.decision" #meta>
        <div class="flex flex-col items-start gap-1 sm:items-end">
          <span
            role="status"
            class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm font-semibold"
            :class="approved ? 'border-ok/40 bg-ok/10 text-ok-fg' : 'border-flag/40 bg-flag/10 text-flag-fg'"
          >
            <PhLockSimple weight="bold" class="size-4" aria-hidden="true" />{{ approved ? "Approved" : "Rejected" }} and locked
          </span>
          <span class="text-xs">{{ review.decided_at ? `${friendlyTime(review.decided_at)} · ` : "" }}Read-only</span>
        </div>
      </template>
      <template v-if="review.period && review.report_type !== 'weekly'">
        {{ review.report_title }}, <span class="font-mono">{{ review.period }}</span
        >, run <span class="font-mono">{{ review.run_id }}</span>
      </template>
      <template v-else>
        <span v-if="review.period" class="font-mono">{{ review.period }}</span
        ><template v-else>Report week {{ weekRange(review.section.week_start, review.section.week_end) }}</template> · Run
        <span class="font-mono">{{ review.run_id }}</span>
      </template>
    </Masthead>
    <!-- The status bar sticks under the top bar across both columns: the counts and the decision never scroll out of reach. -->
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

    <!-- The review items (list and detail) come first, then the draft at full width. -->
    <div class="@container w-full min-w-0 px-4 pt-4 pb-16 sm:px-6">
      <div class="space-y-6">
        <RecheckResult v-if="recheck" :result="recheck" @redraft="emit('redraft', review.section_slug)" />
        <SentenceResult v-if="sentence" :result="sentence" />
        <RejectedDraftNotes :run-id="review.run_id" />
        <!-- Three counts, one per status, in the item cards' colour, glyph and border: each one filters the review items, and
             pressing it again shows every item. -->
        <div role="group" aria-label="Review items by status" class="flex flex-wrap items-center gap-1 rounded-lg border bg-card p-1.5">
            <CountTile
              v-for="s in STATUS_ORDER"
              :key="s"
              :status="s"
              :value="review.counts[s].total"
              :sub="review.counts[s].total ? SUBLINES[s] : 'None in this draft'"
              :pressed="filter === s"
              @click="filter = filter === s ? 'all' : s"
            />
          <p class="ml-auto px-3 text-xs text-muted-foreground">Not auto-verified is not the same as incorrect</p>
        </div>
        <ItemsPane v-model:filter="filter" :review="review" />
        <details v-if="removed.length" class="rounded-lg border bg-card px-4 py-2.5 text-sm">
          <summary class="cursor-pointer font-medium">Removed findings ({{ removed.length }})</summary>
          <ul class="mt-2 space-y-1 text-muted-foreground">
            <li v-for="(f, i) in removed" :key="i" class="[overflow-wrap:anywhere]">
              <span class="text-foreground">{{ f.headline || "Untitled finding" }}</span>. Removed by you, {{ friendlyTime(f.at) }}.
            </li>
          </ul>
          <p v-if="!findingsLeft" class="mt-2">This section has no drafted findings.</p>
        </details>
        <BlocksPane
          v-if="isBlocksSection(review.section)"
          :review="review"
          :section="review.section"
          :on-team-chart="session.setTeamChart"
        />
        <DraftPane v-else :review="review" :section="review.section" />
        <!-- The analyst's worklist for this week: separate from the review above, which it never changes. -->
        <NotablePanel
          v-if="week && !readOnly"
          :key="`notable-${review.section_slug}-${week}`"
          :section="review.section_slug"
          :section-title="review.section_title"
          :week="week"
        />
      </div>
    </div>
  </div>
</template>
