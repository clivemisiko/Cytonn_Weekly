<script setup lang="ts">
import { PhCaretDown, PhCheckCircle } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, reactive, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import { STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Resolution, Review, Status } from "@/lib/types";
import ReviewItemCard from "./ReviewItemCard.vue";

const props = defineProps<{
  review: Review;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
  onAcceptClean: () => Promise<boolean>;
}>();

type Filter = "all" | "unresolved" | "flagged" | "fix_needed";
const filter = ref<Filter>("all");

const open = reactive<Record<Status, boolean>>({ flagged: true, not_auto_verified: true, clean: false });
// Which cards show their evidence. Collapsed by default; Expand all / Collapse all act on every item with something to show.
const expanded = reactive<Record<number, boolean>>({});
const setAll = (on: boolean) => {
  for (const i of props.review.review_items) expanded[i.index] = on;
  for (const k of Object.keys(open) as Status[]) if (on) open[k] = true;
};

const totalOf = (status: Status) => props.review.review_items.filter((i) => i.status === status).length;

const itemsOf = (status: Status) => {
  const items = props.review.review_items.filter((i) => i.status === status);
  if (filter.value === "all") return items;
  if (filter.value === "unresolved") return items.filter((i) => i.resolution === null);
  if (filter.value === "fix_needed") return items.filter((i) => i.resolution === "fix_needed");
  if (filter.value === "flagged") return items;
  return items;
};

function setFilter(next: Filter) {
  filter.value = next;
  if (next === "unresolved" || next === "flagged" || next === "fix_needed") {
    open.flagged = true;
    open.not_auto_verified = true;
    open.clean = true;
  }
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
        <p class="text-xs text-muted-foreground">Resolve every item below to approve this section.</p>
      </div>
      <div class="flex gap-1.5">
        <Button size="sm" variant="outline" class="h-8 px-2.5 text-xs" @click="setAll(true)">Expand all</Button>
        <Button size="sm" variant="outline" class="h-8 px-2.5 text-xs" @click="setAll(false)">Collapse all</Button>
      </div>
    </div>

    <!-- Quick filter pill bar: lets coordinator jump straight to what needs their attention -->
    <div class="flex flex-wrap items-center gap-1.5 rounded-lg border border-border/80 bg-muted/50 p-1 text-xs">
      <button
        type="button"
        :class="[
          'rounded-md px-2.5 py-1 font-medium transition-all outline-none',
          filter === 'all'
            ? 'bg-card font-semibold text-foreground shadow-2xs'
            : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="setFilter('all')"
      >
        All ({{ review.review_items.length }})
      </button>
      <button
        type="button"
        :class="[
          'flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-all outline-none',
          filter === 'unresolved'
            ? 'bg-card font-semibold text-foreground shadow-2xs'
            : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="setFilter('unresolved')"
      >
        <span>Unresolved</span>
        <span
          v-if="review.progress.unresolved > 0"
          class="rounded-full px-1.5 py-0.5 font-mono text-[10px] font-bold"
          :class="filter === 'unresolved' ? 'bg-primary/20 text-primary-fg' : 'bg-muted-foreground/20 text-foreground'"
        >
          {{ review.progress.unresolved }}
        </span>
      </button>
      <button
        v-if="review.counts.flagged.total > 0"
        type="button"
        :class="[
          'flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-all outline-none',
          filter === 'flagged'
            ? 'bg-card font-semibold text-foreground shadow-2xs'
            : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="setFilter('flagged')"
      >
        <span>Flagged</span>
        <span class="rounded-full bg-flag/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-flag-fg">
          {{ review.counts.flagged.total }}
        </span>
      </button>
      <button
        v-if="review.progress.fix_needed > 0"
        type="button"
        :class="[
          'flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium transition-all outline-none',
          filter === 'fix_needed'
            ? 'bg-card font-semibold text-foreground shadow-2xs'
            : 'text-muted-foreground hover:text-foreground',
        ]"
        @click="setFilter('fix_needed')"
      >
        <span>Fix needed</span>
        <span class="rounded-full bg-flag/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-flag-fg">
          {{ review.progress.fix_needed }}
        </span>
      </button>
    </div>

    <!-- Quick action: One-click accept clean items without digging into collapsed folder -->
    <div
      v-if="!locked && review.counts.clean.unresolved > 0"
      class="flex items-center justify-between gap-3 rounded-lg border border-ok/30 bg-ok/10 p-3 text-xs"
    >
      <div class="min-w-0">
        <p class="font-semibold text-ok-fg">{{ review.counts.clean.unresolved }} clean items pending</p>
        <p class="text-muted-foreground">Passed automated verification with zero flags.</p>
      </div>
      <Button size="sm" class="h-8 shrink-0 font-medium shadow-2xs" @click="onAcceptClean()">
        Accept all clean ({{ review.counts.clean.unresolved }})
      </Button>
    </div>

    <!-- Approveness banner when all items are resolved -->
    <div
      v-if="review.is_approvable && !review.decision"
      class="flex items-center gap-2.5 rounded-lg border border-ok/40 bg-ok/15 p-3 text-xs font-medium text-ok-fg"
    >
      <PhCheckCircle weight="bold" class="size-4.5 shrink-0" />
      <span>All items resolved! Use the <strong>Approve</strong> button in the top bar to finalize this section.</span>
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
          <p v-if="itemsOf(status).length === 0" class="pt-3 text-sm text-muted-foreground">
            {{ filter !== 'all' ? 'No items match the current filter.' : 'None.' }}
          </p>
          <ul v-else class="space-y-3 pt-3">
            <ReviewItemCard
              v-for="item in itemsOf(status)"
              :key="item.index"
              :item="item"
              :review="review"
              :locked="locked"
              :on-resolve="onResolve"
              v-model:open="expanded[item.index]"
              :shared-detail="status === 'not_auto_verified' ? shared?.text : null"
            />
          </ul>
        </CollapsibleContent>
      </CollapsibleRoot>
    </section>
  </section>
</template>
