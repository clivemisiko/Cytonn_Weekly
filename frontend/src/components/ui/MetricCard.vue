<script setup lang="ts">
import type { Component } from "vue";

// One cell of a metric strip. tone colours the icon only; the figure stays ink, so a number is never read by its colour.
withDefaults(defineProps<{ label: string; value: string | number; sub?: string; icon: Component; tone?: "ok" | "flag" | "neutral" }>(), {
  tone: "neutral",
});
const ICON = { ok: "text-ok-fg", flag: "text-flag-fg", neutral: "text-muted-foreground" } as const;
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5 bg-card px-4 py-3">
    <p class="eyebrow flex items-center gap-1.5 truncate">
      <component :is="icon" weight="bold" class="size-3.5 shrink-0" :class="ICON[tone]" aria-hidden="true" />
      {{ label }}
    </p>
    <p class="font-mono text-xl leading-none font-bold tracking-tight">
      {{ value }}<span v-if="sub" class="text-xs font-medium text-muted-foreground">{{ sub }}</span>
    </p>
  </div>
</template>
