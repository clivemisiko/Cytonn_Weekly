<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { friendlyDate } from "@/lib/format";
import { chartGeometry } from "@/lib/notable";
import type { Suggestion } from "@/lib/types";

/**
 * The working's points as a line, drawn from `working.points` and nothing else: each point's value places it, each point's
 * display string is the only number printed (the highest and lowest as the scale, the latest by its dot). Dates are to scale,
 * so a missing week is a visible gap. The drawing is exactly as wide as its box, so it never scrolls: with room it puts the
 * scale at the left and the latest label beside its dot, and in a narrow box (a phone) the scale labels go above and below the
 * plot and the latest label above or below its dot. The 12px labels are never shrunk. Colours are the app's tokens.
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
  <div ref="box" class="w-full overflow-hidden">
    <svg v-if="g" :width="g.width" :height="g.height" :viewBox="`0 0 ${g.width} ${g.height}`" role="img" :aria-label="summary" class="block">
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
      <circle data-part="latest-dot" :cx="g.latest.x" :cy="g.latest.y" r="5" class="fill-foreground stroke-background" stroke-width="1.5" />

      <text
        v-for="s in g.scale"
        :key="s.y"
        :x="s.x"
        :y="s.ty"
        :text-anchor="s.anchor"
        class="fill-muted-foreground font-mono text-xs"
      >{{ s.text }}</text>
      <text
        data-part="latest-label"
        :x="g.latestLabel.x"
        :y="g.latestLabel.y"
        :text-anchor="g.latestLabel.anchor"
        class="fill-foreground font-mono text-xs font-semibold"
      >{{ g.latestLabel.text }}</text>
      <text
        v-if="g.dates.oldest"
        :x="g.dates.oldest.x"
        :y="g.dates.oldest.y"
        :text-anchor="g.dates.oldest.anchor"
        class="fill-muted-foreground text-xs"
      >{{ friendlyDate(g.oldest.date) }}</text>
      <text :x="g.dates.latest.x" :y="g.dates.latest.y" :text-anchor="g.dates.latest.anchor" class="fill-muted-foreground text-xs">{{ friendlyDate(g.latest.date) }}</text>
    </svg>
  </div>
</template>
