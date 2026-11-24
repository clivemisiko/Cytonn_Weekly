<script setup lang="ts">
import { PhArrowLeft, PhArrowRight } from "@phosphor-icons/vue";
import { computed, nextTick, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import { KIND_LABELS, STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Review, ReviewItem, Status } from "@/lib/types";
import ReviewItemCard from "./ReviewItemCard.vue";

const props = defineProps<{ review: Review }>();

// The review's counts strip sets it: one status, or "all" when no tile is pressed.
const filter = defineModel<"all" | Status>("filter", { default: "all" });

const items = computed(() => {
  const all = props.review.review_items;
  if (filter.value !== "all") return all.filter((i) => i.status === filter.value);
  return STATUS_ORDER.flatMap((s) => all.filter((i) => i.status === s));
});

// The row's tag, from a fixed table; anything not in it keeps the kind label.
function tagOf(item: ReviewItem): string {
  const flags = Array.isArray(item.detail) ? item.detail : [];
  if (item.kind === "unavailable_part") return "Missing content";
  if (flags.some((f) => f.kind === "missing")) return "Missing values";
  if (item.kind === "carried_text") return "Carried forward";
  if (item.status === "not_auto_verified" || Object.values(item.context.inputs ?? {}).some((i) => i.origin === "ocr")) return "Verify source";
  return KIND_LABELS[item.kind] ?? item.kind;
}
function summaryOf(item: ReviewItem): string {
  const first = Array.isArray(item.detail) ? item.detail[0]?.message : item.detail;
  return (first || item.context.text || "").trim();
}

const selected = ref<number | null>(null);
watch(
  items,
  (list) => {
    if (!list.some((i) => i.index === selected.value)) selected.value = list[0]?.index ?? null;
  },
  { immediate: true },
);
const pos = computed(() => items.value.findIndex((i) => i.index === selected.value));
const current = computed(() => items.value[pos.value] ?? null);
const pad = (n: number) => String(n).padStart(2, "0");

const rows = ref<HTMLElement | null>(null);
const detail = ref<HTMLElement | null>(null);
async function select(at: number, focus: "row" | "detail" | null = null) {
  const item = items.value[at];
  if (!item) return;
  selected.value = item.index;
  await nextTick();
  if (focus === "row") rows.value?.querySelector<HTMLElement>(`[data-index="${item.index}"] button`)?.focus();
  if (focus === "detail") detail.value?.focus();
}
function onKey(e: KeyboardEvent) {
  const last = items.value.length - 1;
  const to = { ArrowDown: pos.value + 1, ArrowUp: pos.value - 1, Home: 0, End: last }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  void select(Math.max(0, Math.min(last, to)), "row");
}
</script>

<template>
  <aside aria-label="Review items" class="grid min-w-0 gap-4 [overflow-wrap:anywhere] lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] lg:items-start">
    <section aria-labelledby="items-title" class="min-w-0 rounded-lg border bg-card">
      <div class="flex items-baseline justify-between gap-2 border-b px-4 py-3">
        <h2 id="items-title" class="eyebrow"><span class="sr-only">Review items: </span>{{ filter === "all" ? "All" : STATUS_META[filter].label }} items</h2>
        <span class="font-mono text-xs text-muted-foreground">{{ items.length }}</span>
      </div>
      <p v-if="filter === 'clean'" class="px-4 pt-3 text-xs text-muted-foreground">Checked with no flag. Listed so you can see full coverage.</p>
      <p v-if="items.length === 0" class="p-4 text-sm text-muted-foreground">No items in this category.</p>
      <!-- Arrow keys, Home and End move the selection; only the selected row is in the tab order. -->
      <ul v-else ref="rows" class="max-h-[70vh] space-y-1 overflow-y-auto overscroll-contain p-2" @keydown="onKey">
        <li v-for="(item, n) in items" :key="item.index" :class="`state-${item.status}`" :data-status="item.status" :data-index="item.index">
          <button
            type="button"
            :aria-current="item.index === selected ? 'true' : undefined"
            :tabindex="item.index === selected ? 0 : -1"
            class="w-full rounded-md border border-transparent px-3 py-2.5 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            :class="item.index === selected && 'border-(--hue)/50 bg-(--hue)/10 hover:bg-(--hue)/15'"
            @click="select(n)"
          >
            <span class="flex items-center gap-1.5 text-[0.6875rem] font-semibold tracking-wide uppercase">
              <span class="font-mono text-muted-foreground">{{ pad(n + 1) }} /</span>
              <span class="text-(--hue-fg)">{{ tagOf(item) }}</span>
              <span class="sr-only">, {{ KIND_LABELS[item.kind] ?? item.kind }}, {{ STATUS_META[item.status].label }}</span>
            </span>
            <span class="mt-1 block text-sm font-medium text-foreground">{{ item.ref }}</span>
            <span v-if="summaryOf(item)" class="mt-0.5 block truncate text-xs text-muted-foreground">{{ summaryOf(item) }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section v-if="current" ref="detail" tabindex="-1" aria-label="Selected review item" class="min-w-0 space-y-4 rounded-lg border bg-card p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-6">
      <Button size="sm" variant="outline" class="lg:hidden" @click="select(pos, 'row')"><PhArrowLeft weight="bold" aria-hidden="true" />Back to the list</Button>
      <ReviewItemCard :key="current.index" :item="current" :review="review" :position="`${pad(pos + 1)} / ${pad(items.length)}`" />
      <div class="flex flex-wrap items-end justify-between gap-3 border-t pt-4">
        <p v-if="review.decision" class="text-xs text-muted-foreground">Review controls are unavailable while this section is locked.</p>
        <Button v-if="pos < items.length - 1" size="sm" class="ml-auto" @click="select(pos + 1, 'detail')">Next issue<PhArrowRight weight="bold" aria-hidden="true" /></Button>
      </div>
    </section>
  </aside>
</template>
