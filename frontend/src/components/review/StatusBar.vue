<script setup lang="ts">
import { PhCheckCircle, PhInfo, PhWarning } from "@phosphor-icons/vue";
import { computed, inject } from "vue";
import { plural } from "@/lib/format";
import { READ_ONLY } from "@/lib/previous";
import type { Decision, Review } from "@/lib/types";
import DecisionControls from "./DecisionControls.vue";
import Notice from "./Notice.vue";

const props = defineProps<{
  review: Review;
  saving: boolean;
  saveError: string | null;
  hasDevRibbon: boolean;
  deciding: boolean;
  decisionError: string | null;
  onDecide: (decision: Decision) => Promise<boolean>;
}>();
const emit = defineEmits<{ close: [] }>();

const readOnly = inject(READ_ONLY, false);
const counts = computed(() => props.review.counts);
</script>

<template>
  <div
    data-attention="review-status-bar"
    class="sticky z-30 border-b border-border/80 bg-background/95 px-4 py-3.5 shadow-xs backdrop-blur supports-backdrop-filter:bg-background/85 sm:px-6"
    :class="hasDevRibbon ? 'top-[calc(var(--topbar-h)+1.75rem)]' : 'top-(--topbar-h)'"
  >
    <div class="w-full">
      <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div class="min-w-55 flex-1 sm:max-w-sm">
          <div class="flex items-baseline justify-between gap-3 text-sm">
            <span>
              <span class="font-semibold"><span class="font-mono">{{ counts.flagged.total }}</span> flagged</span>
              <span class="text-muted-foreground">
                · <span class="font-mono">{{ counts.not_auto_verified.total }}</span> not auto-verified · <span class="font-mono">{{ counts.clean.total }}</span> clean
              </span>
            </span>
            <span class="text-xs text-muted-foreground" aria-live="polite">
              {{ saving ? "Saving…" : saveError ? "Not saved" : `Saved as run ${review.run_id}` }}
            </span>
          </div>
        </div>
        <div class="relative min-h-6 basis-full text-sm font-medium sm:flex-1 sm:basis-0" aria-live="polite">
          <span v-if="review.decision" class="flex items-center gap-2 text-foreground">
            <PhInfo weight="bold" class="size-4 shrink-0 text-link" aria-hidden="true" />
            <span>Decision recorded: <strong class="font-semibold">{{ review.decision }}</strong>.</span>
          </span>
          <span v-else-if="counts.flagged.total" class="flex items-center gap-2 text-warn-fg">
            <PhWarning weight="bold" class="size-4 shrink-0" aria-hidden="true" />
            <span>{{ plural(counts.flagged.total, "flagged item") }}: read {{ counts.flagged.total === 1 ? "it" : "them" }} before you approve or reject.</span>
          </span>
          <span v-else-if="review.is_approvable" class="flex items-center gap-2 text-ok-fg">
            <PhCheckCircle weight="bold" class="size-4 shrink-0" aria-hidden="true" />
            <span>Ready for a decision: nothing is flagged.</span>
          </span>
        </div>
        <div v-if="!readOnly" class="basis-full lg:basis-auto">
          <DecisionControls :review="review" :deciding="deciding" :on-decide="onDecide" @close="emit('close')" />
        </div>
      </div>
      <div v-if="decisionError" role="alert" class="rise-in overflow-hidden">
        <Notice data-problem class="mt-3 font-medium">{{ decisionError }}</Notice>
      </div>
      <div v-if="saveError" role="alert" class="rise-in overflow-hidden">
        <Notice data-problem class="mt-3 font-medium">Changes could not be saved: {{ saveError }}. The section has been restored to the last saved version. Please re-enter your changes.</Notice>
      </div>
    </div>
  </div>
</template>
