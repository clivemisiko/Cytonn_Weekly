<script setup lang="ts">
import { computed, inject, nextTick, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { OPEN_REVIEW } from "@/lib/fixfile";
import { APPROVED_SENTENCE_NOTE, REMOVE_FINDING_NOTE, lastSentence } from "@/lib/sentence";
import { shell } from "@/lib/shell";
import type { Review, ReviewItem } from "@/lib/types";
import RedraftDialog from "./RedraftDialog.vue";

const props = defineProps<{ review: Review; item: ReviewItem }>();
const openReview = inject(OPEN_REVIEW, null);

const phase = ref<"idle" | "confirming" | "working">("idle");
const error = ref<string | null>(null);
const errorEl = ref<HTMLElement | null>(null);
const notes = computed(() => (props.review.decision === "approved" ? [REMOVE_FINDING_NOTE, APPROVED_SENTENCE_NOTE] : [REMOVE_FINDING_NOTE]));

async function send() {
  phase.value = "working";
  error.value = null;
  try {
    const out = await api.removeFinding(props.review.run_id, props.item.index);
    lastSentence.value = { runId: out.review.run_id, result: out.result };
    shell.invalidate(); // the section's newest review is now an undecided one
    void shell.refreshFor(out.review.report_type, out.review.period);
    openReview?.(out.review);
  } catch (err) {
    error.value = (err as Error).message;
    phase.value = "idle";
    await nextTick();
    errorEl.value?.focus();
  }
}
</script>

<template>
  <div v-if="item.remove_finding" class="contents">
    <Button variant="outline" size="sm" :disabled="phase === 'working'" :aria-label="`Remove this finding: ${item.ref}`" @click="phase = 'confirming'">
      Remove this finding
    </Button>
    <span v-if="phase === 'working'" role="status" class="text-xs text-muted-foreground">Saving a new version without this finding…</span>
    <p v-if="error" ref="errorEl" tabindex="-1" role="alert" data-problem class="basis-full text-sm font-medium text-flag-fg [overflow-wrap:anywhere]">{{ error }}</p>
    <RedraftDialog
      :open="phase === 'confirming'"
      title="Remove this finding?"
      :notes="notes"
      confirm-label="Remove the finding"
      @confirm="send"
      @cancel="phase = 'idle'"
    />
  </div>
</template>
