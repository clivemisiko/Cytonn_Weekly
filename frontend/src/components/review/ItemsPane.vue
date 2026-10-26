<script setup lang="ts">
import { PhCaretDown } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, reactive } from "vue";
import Button from "@/components/ui/Button.vue";
import { STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Resolution, Review, Status } from "@/lib/types";
import ReviewItemCard from "./ReviewItemCard.vue";

/** Review items grouped Flagged, Not auto-verified, Clean. Clean starts collapsed: it is coverage, not work. */
const props = defineProps<{
  review: Review;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
  onAcceptClean: () => Promise<boolean>;
}>();

const open = reactive<Record<Status, boolean>>({ flagged: true, not_auto_verified: true, clean: false });
const itemsOf = (status: Status) => props.review.review_items.filter((i) => i.status === status);

// The explanation two or more not-auto-verified items share (the claims' "Not yet automatically checked..." note) is shown
// once under the group header instead of on every card; each card keeps its "Not auto-verified" chip.
const shared = computed(() => {
  const counts = new Map<string, number>();
  for (const i of itemsOf("not_auto_verified")) if (typeof i.detail === "string") counts.set(i.detail, (counts.get(i.detail) ?? 0) + 1);
  let best: [string, number] | null = null;
  for (const e of counts) if (e[1] > 1 && (!best || e[1] > best[1])) best = e;
  return best && { text: best[0], count: best[1], of: itemsOf("not_auto_verified").length };
});
</script>

<template>
  <section aria-labelledby="items-title" class="min-w-0 space-y-6 [overflow-wrap:anywhere]">
    <h2 id="items-title" class="text-lg font-semibold">Review items</h2>
    <section v-for="status in STATUS_ORDER" :key="status" :class="`state-${status}`" :aria-labelledby="`group-${status}-title`">
      <CollapsibleRoot v-model:open="open[status]">
        <h3 :id="`group-${status}-title`" class="text-base font-semibold">
          <CollapsibleTrigger
            class="state-rule flex w-full items-center gap-2 border-b py-2 text-left transition-colors outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <span class="glyph size-4 text-xs" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
            <span>
              {{ STATUS_META[status].title }} <span class="font-mono text-sm font-medium text-muted-foreground">({{ itemsOf(status).length }})</span>
            </span>
            <PhCaretDown
              weight="bold"
              aria-hidden="true"
              class="ml-auto size-4 text-muted-foreground transition-transform duration-200 ease-out"
              :class="open[status] && 'rotate-180'"
            />
          </CollapsibleTrigger>
        </h3>

        <div v-if="status === 'clean'" class="flex flex-wrap items-center gap-x-4 gap-y-2 pt-3">
          <p class="text-xs text-muted-foreground">Checked with no flag. Listed so you can see full coverage.</p>
          <Button size="sm" :disabled="locked || review.counts.clean.unresolved === 0" @click="onAcceptClean()">
            Mark all clean as accepted ({{ review.counts.clean.unresolved }} unresolved)
          </Button>
        </div>

        <CollapsibleContent class="collapsible -m-1 overflow-hidden p-1">
          <p v-if="status === 'not_auto_verified' && shared" class="pt-3 text-xs whitespace-pre-line text-muted-foreground">
            <span v-if="shared.count < shared.of" class="font-medium">For {{ shared.count }} of these {{ shared.of }} items: </span>{{ shared.text }}
          </p>
          <p v-if="itemsOf(status).length === 0" class="pt-3 text-sm text-muted-foreground">None.</p>
          <ul v-else class="space-y-3 pt-3">
            <ReviewItemCard v-for="item in itemsOf(status)" :key="item.index" :item="item" :review="review":locked="locked" :on-resolve="onResolve" :shared-detail="status === 'not_auto_verified' ? shared?.text : null" />
          </ul>
        </CollapsibleContent>
      </CollapsibleRoot>
    </section>
  </section>
</template>
