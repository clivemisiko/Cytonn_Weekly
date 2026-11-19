<script setup lang="ts">
import { PhX } from "@phosphor-icons/vue";
import { computed, onMounted, provide, ref, shallowRef } from "vue";
import ItemsPane from "@/components/review/ItemsPane.vue";
import Notice from "@/components/review/Notice.vue";
import ReviewItemCard from "@/components/review/ReviewItemCard.vue";
import * as api from "@/lib/api";
import { READ_ONLY } from "@/lib/previous";
import type { Review } from "@/lib/types";

const props = defineProps<{ reviewId: number; index: number | null }>();
const emit = defineEmits<{ close: [] }>();

// Read-only: the review's own components hide every control that changes something. The only button here closes the view.
provide(READ_ONLY, true);
const review = shallowRef<Review | null>(null);
const problem = ref<string | null>(null);
const item = computed(() => (props.index === null ? null : (review.value?.review_items.find((i) => i.index === props.index) ?? null)));

onMounted(async () => {
  try {
    review.value = await api.getReview(props.reviewId);
  } catch (err) {
    problem.value = (err as Error).message;
  }
});
</script>

<template>
  <section aria-label="Full view" class="space-y-3" data-card="full_view">
    <div class="flex items-center justify-between gap-2">
      <h2 class="panel-title">Full view, read only</h2>
      <button
        type="button"
        class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Close the full view"
        @click="emit('close')"
      >
        <PhX weight="bold" class="size-4" aria-hidden="true" />
      </button>
    </div>
    <p v-if="!review && !problem" role="status" class="text-sm text-muted-foreground">Reading the review…</p>
    <Notice v-if="problem" role="alert" class="font-medium">{{ problem }}</Notice>
    <template v-if="review">
      <p class="text-xs text-muted-foreground">{{ review.section_title }}, run {{ review.run_id }}. Nothing can be changed here.</p>
      <ul v-if="item" class="space-y-3"><ReviewItemCard :item="item" :review="review" :open="true" /></ul>
      <p v-else-if="index !== null" class="text-sm text-muted-foreground">That item is no longer in this review.</p>
      <ItemsPane v-else :review="review" />
    </template>
  </section>
</template>
