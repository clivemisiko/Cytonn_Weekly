<script setup lang="ts">
import { PhCaretDown } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, reactive, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import { STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Review, Status } from "@/lib/types";
import ReviewItemCard from "./ReviewItemCard.vue";

const props = defineProps<{ review: Review }>();

type Filter = "all" | "flagged";
const filter = ref<Filter>("all");

const open = reactive<Record<Status, boolean>>({ flagged: true, not_auto_verified: true, clean: false });
// Which cards show their evidence. Collapsed by default; Expand all / Collapse all act on every item with something to show.
const expanded = reactive<Record<number, boolean>>({});
const setAll = (on: boolean) => {
  for (const i of props.review.review_items) expanded[i.index] = on;
  for (const k of Object.keys(open) as Status[]) if (on) open[k] = true;
};

const filters = computed(() =>
  (
    [
      { key: "all", label: "All", count: props.review.review_items.length, flag: false, show: true },
      { key: "flagged", label: "Flagged", count: props.review.counts.flagged.total, flag: true, show: props.review.counts.flagged.total > 0 },
    ] as { key: Filter; label: string; count: number | null; flag: boolean; show: boolean }[]
  ).filter((f) => f.show),
);

const totalOf = (status: Status) => props.review.review_items.filter((i) => i.status === status).length;

const itemsOf = (status: Status) => {
  const items = props.review.review_items.filter((i) => i.status === status);
  return filter.value === "flagged" && status !== "flagged" ? [] : items;
};

function setFilter(next: Filter) {
  filter.value = next;
  if (next === "flagged") open.flagged = true;
}

// The explanation two or more not-auto-verified items share (the claims' "Not yet automatically checked..." note) is shown
// once under the group header instead of on every card; each card keeps its "Not auto-verified" chip.
const shared = computed(() => {
  const allNotAuto = props.review.review_items.filter((i) => i.status === "not_auto_verified");
  const counts = new Map<string, number>();
  for (const i of allNotAuto) if (typeof i.detail === "string") counts.set(i.detail, (counts.get(i.detail) ?? 0) + 1);
  let best: [string, number] | null = null;
  for (const e of counts) if (e[1] > 1 && (!best || e[1] > best[1])) best = e;
  return best && { text: best[0], count: best[1], of: allNotAuto.length };
});
</script>

<template>
  <section aria-labelledby="items-title" class="min-w-0 space-y-5 [overflow-wrap:anywhere]">
    <div class="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
      <div>
        <h2 id="items-title" class="text-lg font-semibold tracking-tight text-foreground">Review items</h2>
        <p class="text-xs text-muted-foreground">Read the items below, then approve or reject the section as a whole.</p>
      </div>
      <div class="flex gap-1.5">
        <Button size="sm" variant="outline" class="h-8 px-2.5 text-xs" @click="setAll(true)">Expand all</Button>
        <Button size="sm" variant="outline" class="h-8 px-2.5 text-xs" @click="setAll(false)">Collapse all</Button>
      </div>
    </div>

    <!-- Filters: a toggle group, so the one pressed is announced. Counts are from the review itself. -->
    <div role="group" aria-label="Show items" class="flex flex-wrap items-center gap-1 rounded-lg border bg-muted/50 p-1 text-sm">
      <button
        v-for="f in filters"
        :key="f.key"
        type="button"
        :aria-pressed="filter === f.key"
        :class="[
          'flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring',
          filter === f.key ? 'bg-card font-semibold text-foreground shadow-2xs' : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="setFilter(f.key)"
      >
        <span>{{ f.label }}</span>
        <span v-if="f.count !== null" class="count-badge" :class="f.flag && 'state-flagged'">{{ f.count }}</span>
      </button>
    </div>

    <section v-for="status in STATUS_ORDER" :key="status" :class="`state-${status}`" :aria-labelledby="`group-${status}-title`">
      <CollapsibleRoot v-model:open="open[status]">
        <h3 :id="`group-${status}-title`" class="text-base font-semibold">
          <CollapsibleTrigger
            class="state-rule flex w-full items-center gap-2 border-b py-2 text-left transition-colors outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <span class="glyph size-4 text-xs" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
            <span>
              {{ STATUS_META[status].title }} <span class="font-mono text-sm font-medium text-muted-foreground">({{ totalOf(status) }})</span>
            </span>
            <span v-if="filter !== 'all' && itemsOf(status).length !== totalOf(status)" class="text-xs font-normal text-muted-foreground">
              · {{ itemsOf(status).length }} shown
            </span>
            <PhCaretDown
              weight="bold"
              aria-hidden="true"
              class="ml-auto size-4 text-muted-foreground transition-transform duration-200 ease-out"
              :class="open[status] && 'rotate-180'"
            />
          </CollapsibleTrigger>
        </h3>

        <p v-if="status === 'clean'" class="pt-3 text-xs text-muted-foreground">Checked with no flag. Listed so you can see full coverage.</p>

        <CollapsibleContent class="collapsible -m-1 overflow-hidden p-1">
          <p v-if="status === 'not_auto_verified' && shared" class="pt-3 text-xs whitespace-pre-line text-muted-foreground">
            <span v-if="shared.count < shared.of" class="font-medium">For {{ shared.count }} of these {{ shared.of }} items: </span>{{ shared.text }}
          </p>
          <p v-if="itemsOf(status).length === 0" class="pt-3 text-sm text-muted-foreground">
            {{ filter !== 'all' ? 'No items match the current filter.' : 'No items in this category.' }}
          </p>
          <ul v-else class="space-y-3 pt-3">
            <ReviewItemCard
              v-for="item in itemsOf(status)"
              :key="item.index"
              :item="item"
              :review="review"
              v-model:open="expanded[item.index]"
            />
          </ul>
        </CollapsibleContent>
      </CollapsibleRoot>
    </section>
  </section>
</template>
