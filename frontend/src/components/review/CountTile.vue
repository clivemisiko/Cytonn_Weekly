<script setup lang="ts">
import { useId } from "vue";
import { STATUS_META } from "@/lib/format";
import type { Status } from "@/lib/types";

const props = withDefaults(defineProps<{ status: Status; value: number; sub?: string; pressed?: boolean }>(), { sub: undefined, pressed: undefined });
// On the review's strip the tile is one compact row; what its lines said is its description and its tooltip.
const descId = useId();
</script>

<template>
  <button
    v-if="pressed !== undefined"
    type="button"
    :aria-pressed="pressed"
    :aria-describedby="descId"
    :title="`${props.sub ? `${props.sub}. ` : ''}${STATUS_META[status].hint}`"
    class="flex items-center gap-2.5 rounded-md px-4 py-2 text-left outline-none transition-colors duration-150 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
    :class="[`state-${status}`, pressed && 'bg-(--hue)/15 hover:bg-(--hue)/20']"
  >
    <span class="font-mono text-xl leading-none font-bold text-(--hue-fg)">{{ value }}</span>
    <span class="text-sm font-medium text-foreground">{{ STATUS_META[status].label }}</span>
    <span :id="descId" class="sr-only">{{ props.sub ? `${props.sub}. ` : "" }}{{ STATUS_META[status].hint }}</span>
  </button>
  <div v-else class="surface-state flex flex-col gap-1.5 px-4 py-3" :class="`state-${status}`">
    <div class="flex items-center gap-2">
      <span class="glyph" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
      <span class="eyebrow text-(--hue-fg)">{{ STATUS_META[status].label }}</span>
    </div>
    <div v-if="sub !== undefined" class="flex items-baseline gap-3">
      <span class="font-mono text-xl leading-none font-bold tracking-tight text-foreground">{{ value }}</span>
      <span class="relative min-h-5 text-sm text-muted-foreground"><span class="block">{{ sub }}</span></span>
    </div>
    <span v-else class="font-mono text-xl leading-none font-bold tracking-tight text-foreground">{{ value }}</span>
    <p class="text-xs leading-relaxed text-muted-foreground">{{ STATUS_META[status].hint }}</p>
  </div>
</template>
