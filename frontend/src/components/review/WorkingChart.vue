<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { friendlyDate } from "@/lib/format";
import { chartGeometry } from "@/lib/notable";
import type { Suggestion } from "@/lib/types";

/**
 * The working's points as a line, drawn from `working.points` and nothing else: each point's value places it, each point's
 * display string is the only number printed (the highest and lowest at the left as the scale, the latest beside its dot).
 * Dates are to scale, so a missing week is a visible gap. The drawing is as wide as its box so the 12px labels are never
 * shrunk; where the labels leave too little room it is wider and the box scrolls sideways. Colours are the app's tokens.
 */
const props = defineProps<{ working: Suggestion["working"] }>();

const box = ref<HTMLElement | null>(null);
const width = ref(320);
let observer: ResizeObserver | null = null;

onMounted(() => {
  if (!box.value) return;
  width.value = box.value.clientWidth || width.value;
  if (typeof ResizeObserver === "undefined") return;
  observer = new ResizeObserver(([entry]) => {
    width.value = Math.floor(entry.contentRect.width) || width.value;
  });
  observer.observe(box.value);
});
onBeforeUnmount(() => observer?.disconnect());

const g = computed(() => chartGeometry(props.working.points, width.value));
const line = computed(() => g.value?.dots.map((d) => `${d.x},${d.y}`).join(" ") ?? "");
const summary = computed(() => {
  const c = g.value;
  if (!c) return "";
  const n = c.dots.length;
  const latest = `${friendlyDate(c.latest.date)}, ${c.latest.display}`;
  return n === 1
    ? `${props.working.series}: one point, ${latest}`
    : `${props.working.series}: ${n} points from ${friendlyDate(c.oldest.date)}, ${c.oldest.display}, to ${latest}`;
});
</script>

<template>
  <div ref="box" class="overflow-x-auto">
    <svg v-if="g" :width="g.width" :height="g.height" :viewBox="`0 0 ${g.width} ${g.height}`" role="img" :aria-label="summary">
      <!-- the scale's two heights, as hairlines from the labels to the latest point -->
      <g class="stroke-border" stroke-width="1">
        <line v-for="s in g.scale" :key="s.y" :x1="g.left" :x2="g.right" :y1="s.y" :y2="s.y" />
      </g>
      <polyline
        v-if="g.dots.length > 1"
        :points="line"
        class="fill-none stroke-foreground"
        stroke-width="1.5"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      <circle v-for="d in g.dots.slice(0, -1)" :key="d.date" :cx="d.x" :cy="d.y" r="3" class="fill-card stroke-foreground" stroke-width="1.5" />
      <circle :cx="g.latest.x" :cy="g.latest.y" r="5" class="fill-primary stroke-primary" stroke-width="1.5" />

      <text v-for="s in g.scale" :key="s.y" x="0" :y="s.y + 4" class="fill-muted-foreground font-mono text-xs">{{ s.text }}</text>
      <text :x="g.latest.x + 10" :y="g.latest.y + 4" class="fill-foreground font-mono text-xs font-semibold">{{ g.latest.display }}</text>
      <text v-if="g.dots.length > 1" :x="g.oldest.x" :y="g.height - 8" class="fill-muted-foreground text-xs">{{ friendlyDate(g.oldest.date) }}</text>
      <text :x="g.latest.x" :y="g.height - 8" text-anchor="end" class="fill-muted-foreground text-xs">{{ friendlyDate(g.latest.date) }}</text>
    </svg>
  </div>
</template>
