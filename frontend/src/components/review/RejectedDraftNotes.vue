<script setup lang="ts">
import { PhClockCounterClockwise } from "@phosphor-icons/vue";
import { onMounted, ref } from "vue";
import * as api from "@/lib/api";
import { RESOLUTION_LABELS, friendlyTime, resolutionKey } from "@/lib/format";
import type { RejectedDraftNotes } from "@/lib/types";
import Notice from "./Notice.vue";

/**
 * What the coordinator said about the rejected draft just before this one: its fix-needed items and notes. Read-only, and
 * never copied onto this review's items: the labels can differ between drafts, and approval follows this review alone.
 * Shown only when the API returns something (the run before was rejected and holds a fix-needed item or a note).
 */
const props = defineProps<{ runId: number }>();

const CHIP = {
  none: "border-border text-muted-foreground",
  accept: "border-ok/40 bg-ok/10 text-ok-fg",
  fix_needed: "border-flag/40 bg-flag/10 text-flag-fg",
} as const;

const notes = ref<RejectedDraftNotes | null>(null);
const error = ref<string | null>(null);
onMounted(() => {
  api
    .getRejectedDraftNotes(props.runId)
    .then((n) => (notes.value = n))
    .catch((err: Error) => (error.value = err.message));
});
const title = (n: RejectedDraftNotes) => `Notes from the rejected draft (run ${n.run_id})`;
</script>

<template>
  <section
    v-if="notes"
    aria-labelledby="rejected-notes-title"
    class="rise-in space-y-3 rounded-lg border border-l-[6px] border-border border-l-primary bg-card px-4 py-3"
  >
    <div class="space-y-1">
      <h2 id="rejected-notes-title" class="flex items-center gap-2 text-base font-semibold">
        <PhClockCounterClockwise weight="bold" class="size-4 shrink-0" aria-hidden="true" />{{ title(notes) }}
      </h2>
      <p class="text-xs text-muted-foreground">
        Item labels can differ between drafts; these notes were not carried onto the new items.<template v-if="notes.decided_at">
          Rejected on {{ friendlyTime(notes.decided_at) }}.</template
        >
      </p>
    </div>
    <ul class="divide-y rounded-md border">
      <li v-for="(e, n) in notes.entries" :key="n" class="space-y-1 px-3 py-2">
        <p class="flex flex-wrap items-center gap-2 text-sm font-medium">
          <span class="[overflow-wrap:anywhere]">{{ e.ref }}</span>
          <span class="rounded-sm border px-1.5 py-0.5 text-xs font-semibold" :class="CHIP[resolutionKey(e.resolution)]">
            {{ RESOLUTION_LABELS[resolutionKey(e.resolution)] }}
          </span>
        </p>
        <p v-if="e.note" class="text-sm whitespace-pre-line [overflow-wrap:anywhere]">{{ e.note }}</p>
        <p v-else class="text-xs text-muted-foreground">No note.</p>
      </li>
    </ul>
  </section>
  <Notice v-else-if="error" tone="warn" role="status">The notes from the earlier draft could not be read: {{ error }}</Notice>
</template>
