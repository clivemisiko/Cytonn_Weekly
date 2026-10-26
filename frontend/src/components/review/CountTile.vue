<script setup lang="ts">
import { STATUS_META } from "@/lib/format";
import type { Status } from "@/lib/types";

/** One count for one status, in the colour, glyph and border style the item cards use. `sub` is the scorecard's second line. */
defineProps<{ status: Status; value: number; sub?: string }>();
</script>

<template>
  <div class="surface-state flex flex-col gap-2 p-4" :class="`state-${status}`">
    <div class="flex items-center gap-2">
      <span class="glyph" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
      <span class="eyebrow text-(--hue-fg)">{{ STATUS_META[status].label }}</span>
    </div>
    <div v-if="sub !== undefined" class="flex items-baseline gap-3">
      <span class="text-3xl leading-none font-bold tracking-tight">{{ value }}</span>
      <span class="relative min-h-5 text-sm text-muted-foreground"><span class="block">{{ sub }}</span></span>
    </div>
    <span v-else class="text-3xl leading-none font-bold tracking-tight">{{ value }}</span>
    <p class="text-xs text-muted-foreground">{{ STATUS_META[status].hint }}</p>
  </div>
</template>
