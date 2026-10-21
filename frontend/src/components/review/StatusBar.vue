<script setup lang="ts">
import { PhCheckCircle, PhInfo, PhWarning } from "@phosphor-icons/vue";
import { computed } from "vue";
import type { Decision, Review } from "@/lib/types";
import DecisionControls from "./DecisionControls.vue";
import Notice from "./Notice.vue";

/**
 * Sticky under the masthead for the whole review: how many items are left, whether the section can be approved,
 * and the decision itself, so the coordinator never has to scroll to the end of a long section to find either.
 */
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

const progress = computed(() => props.review.progress);
const fraction = computed(() => (progress.value.total ? progress.value.resolved / progress.value.total : 0));
</script>

<template>
  <div
    class="sticky z-30 border-b bg-background/95 px-4 py-3 backdrop-blur supports-backdrop-filter:bg-background/85 sm:px-6"
    :class="hasDevRibbon ? 'top-[calc(var(--topbar-h)+1.75rem)]' : 'top-(--topbar-h)'"
  >
    <div class="mx-auto w-full max-w-375">
      <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div class="min-w-55 flex-1 sm:max-w-sm">
          <div class="mb-2 flex items-baseline justify-between gap-3 text-sm">
            <span>
              <span class="font-semibold"><span class="font-mono">{{ progress.unresolved }}</span> unresolved</span>
              <span class="text-muted-foreground">
                · <span class="font-mono">{{ progress.resolved }}</span> of <span class="font-mono">{{ progress.total }}</span> resolved
              </span>
            </span>
            <span class="text-xs text-muted-foreground" aria-live="polite">
              {{ saving ? "Saving…" : saveError ? "Not saved" : `Saved as run ${review.run_id}` }}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Items resolved"
            aria-valuemin="0"
            :aria-valuemax="progress.total"
            :aria-valuenow="progress.resolved"
            class="h-2 overflow-hidden rounded-full bg-border"
          >
            <div class="h-full origin-left rounded-full bg-primary transition-transform duration-[240ms] ease-(--ease-out)" :style="{ transform: `scaleX(${fraction})` }" />
          </div>
        </div>
        <div class="relative min-h-6 basis-full text-sm font-medium sm:flex-1 sm:basis-0" aria-live="polite">
          <span v-if="review.decision" class="flex items-center gap-2 text-foreground">
            <PhInfo weight="bold" class="size-4 shrink-0 text-link" aria-hidden="true" />
            <span>Decision recorded: <strong class="font-semibold">{{ review.decision }}</strong>.</span>
          </span>
          <span v-else-if="review.is_approvable" class="flex items-center gap-2 text-ok-fg">
            <PhCheckCircle weight="bold" class="size-4 shrink-0" aria-hidden="true" />
            <span>Approvable: every item is resolved and none needs a fix.</span>
          </span>
          <!-- The unresolved count is the bar's headline, so this line says only what still stands in the way. -->
          <span v-else class="flex items-center gap-2 text-warn-fg">
            <PhWarning weight="bold" class="size-4 shrink-0" aria-hidden="true" />
            <span>
              {{
                progress.fix_needed
                  ? `Not approvable yet: ${progress.fix_needed} marked fix needed.`
                  : "Approve unlocks once every item is resolved and none needs a fix."
              }}
            </span>
          </span>
        </div>
        <div class="basis-full lg:basis-auto">
          <DecisionControls :review="review" :deciding="deciding" :on-decide="onDecide" @close="emit('close')" />
        </div>
      </div>
      <div v-if="decisionError" role="alert" class="rise-in overflow-hidden">
        <Notice class="mt-3 font-medium">{{ decisionError }}</Notice>
      </div>
      <div v-if="saveError" role="alert" class="rise-in overflow-hidden">
        <Notice class="mt-3 font-medium">NOT SAVED: {{ saveError }}. The last change did not reach the server; the screen shows what the server holds.</Notice>
      </div>
    </div>
  </div>
</template>
