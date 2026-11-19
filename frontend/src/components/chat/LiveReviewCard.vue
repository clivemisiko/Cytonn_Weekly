<script setup lang="ts">
import { PhArrowSquareOut, PhLockSimple } from "@phosphor-icons/vue";
import { computed, watch } from "vue";
import DecisionControls from "@/components/review/DecisionControls.vue";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { flaggedOf } from "@/lib/chatcards";
import { friendlyTime, plural } from "@/lib/format";
import { useReviewSession } from "@/lib/session";
import type { Review } from "@/lib/types";

const props = defineProps<{ initial: Review }>();
const emit = defineEmits<{ full: [reviewId: number, index: number | null]; decided: []; close: [] }>();

// The same session the review page uses, so a decision goes through the same queue and the same route: the server's own check of the
// flagged count, and its refusals, are what the analyst sees.
const session = useReviewSession(props.initial);
const review = session.review;
const flagged = computed(() => flaggedOf(review.value));
const counts = computed(() => review.value.counts);
const dev = computed(() => review.value.is_dev_draft);

watch(
  () => review.value.decision,
  (now, before) => now && now !== before && emit("decided"),
);
</script>

<template>
  <!-- data-attention is the name the review page's status bar has, so a refused decision's "Show me" goes to the sentence below, as it does there. -->
  <section :aria-label="`Review of ${review.section_title}`" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="review" data-attention="review-status-bar">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 class="text-sm font-semibold">Review of {{ review.section_title }}, run {{ review.run_id }}</h3>
      <span v-if="dev" class="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-dev-ink">DEV DRAFT</span>
    </div>
    <p class="text-sm">
      <span class="font-mono font-semibold">{{ counts.flagged.total }}</span> flagged,
      <span class="font-mono font-semibold">{{ counts.not_auto_verified.total }}</span> not auto-verified,
      <span class="font-mono font-semibold">{{ counts.clean.total }}</span> clean.
    </p>
    <p v-if="review.decision" role="status" class="flex items-center gap-1.5 text-sm font-semibold">
      <PhLockSimple weight="bold" class="size-4 shrink-0" aria-hidden="true" />
      {{ review.decision === "approved" ? "Approved" : "Rejected" }} and locked{{ review.decided_at ? `, ${friendlyTime(review.decided_at)}` : "" }}.
    </p>

    <div v-if="flagged.length" class="space-y-2">
      <p class="eyebrow">{{ plural(flagged.length, "flagged item") }}: read {{ flagged.length === 1 ? "it" : "them" }} before you decide</p>
      <ul class="space-y-2">
        <li v-for="f in flagged" :key="f.item.index" class="state-flagged space-y-1 rounded-md border px-3 py-2" data-card="flagged_item">
          <p class="flex items-start gap-1.5 text-sm font-semibold [overflow-wrap:anywhere]">
            <span class="glyph size-4 shrink-0 text-xs" aria-hidden="true">!</span>
            <span><span class="sr-only">Flagged: </span>{{ f.item.ref }}</span>
          </p>
          <p v-if="f.why" class="text-sm [overflow-wrap:anywhere]">{{ f.why }}</p>
          <Button variant="outline" size="sm" @click="emit('full', review.run_id, f.item.index)">
            <PhArrowSquareOut weight="bold" data-icon="inline-start" aria-hidden="true" />
            Open full view<span class="sr-only"> of {{ f.item.ref }}</span>
          </Button>
        </li>
      </ul>
    </div>

    <Button variant="outline" size="sm" @click="emit('full', review.run_id, null)">
      <PhArrowSquareOut weight="bold" data-icon="inline-start" aria-hidden="true" />
      Open full view<span class="sr-only"> of the whole review</span>
    </Button>

    <DecisionControls :review="review" :deciding="session.deciding.value" :on-decide="session.decide" @close="emit('close')" />
    <Notice v-if="session.decisionError.value" data-problem role="alert" class="font-medium">{{ session.decisionError.value }}</Notice>
  </section>
</template>
