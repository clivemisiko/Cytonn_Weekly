<script setup lang="ts">
import { STATUS_META } from "@/lib/format";
import type { Status } from "@/lib/types";

withDefaults(defineProps<{ status: Status; value: number; sub?: string; pressed?: boolean }>(), { sub: undefined, pressed: undefined });
</script>

<template>
  <component
    :is="pressed === undefined ? 'div' : 'button'"
    :type="pressed === undefined ? undefined : 'button'"
    :aria-pressed="pressed"
    class="surface-state flex flex-col gap-1.5 px-4 py-3 text-left"
    :class="[`state-${status}`, pressed !== undefined && 'cursor-pointer outline-none transition-shadow duration-150 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring', pressed && 'ring-2 ring-(--hue)']"
  >
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
  </component>
</template>
