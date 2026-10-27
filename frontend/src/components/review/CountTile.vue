<script setup lang="ts">
import { STATUS_META } from "@/lib/format";
import type { Status } from "@/lib/types";

defineProps<{ status: Status; value: number; sub?: string }>();
</script>

<template>
  <div class="surface-state flex flex-col gap-2 p-4.5 shadow-xs transition-shadow duration-200 hover:shadow-sm" :class="`state-${status}`">
    <div class="flex items-center gap-2">
      <span class="glyph shadow-2xs" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
      <span class="eyebrow text-(--hue-fg)">{{ STATUS_META[status].label }}</span>
    </div>
    <div v-if="sub !== undefined" class="flex items-baseline gap-3">
      <span class="text-3xl leading-none font-bold tracking-tight text-foreground">{{ value }}</span>
      <span class="relative min-h-5 text-sm text-muted-foreground"><span class="block">{{ sub }}</span></span>
    </div>
    <span v-else class="text-3xl leading-none font-bold tracking-tight text-foreground">{{ value }}</span>
    <p class="text-xs leading-relaxed text-muted-foreground">{{ STATUS_META[status].hint }}</p>
  </div>
</template>
