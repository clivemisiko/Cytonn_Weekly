<script setup lang="ts">
import { PhArrowBendDownRight, PhCheck, PhFile, PhQuestion, PhWarning } from "@phosphor-icons/vue";
import { CHIP } from "@/components/ui/button";
import type { Origin } from "@/lib/analyst";

const ORIGIN = {
  typed: { icon: PhCheck, box: "border-ok/40 bg-ok/10 text-ok-fg" },
  carried: { icon: PhArrowBendDownRight, box: "border-input bg-muted text-foreground" },
  unconfirmed: { icon: PhWarning, box: "border-warn/40 bg-warn/10 text-warn-fg" },
  differs: { icon: PhWarning, box: "border-warn/40 bg-warn/10 text-warn-fg" },
  workbook: { icon: PhFile, box: "border-input bg-muted text-foreground" },
  empty: { icon: PhQuestion, box: "border-dashed border-input text-muted-foreground" },
} as const;

defineProps<{ origin: Origin }>();
</script>

<template>
  <span :class="[CHIP, ORIGIN[origin].box]">
    <component :is="ORIGIN[origin].icon" weight="bold" class="size-3" aria-hidden="true" />
    <slot />
  </span>
</template>
