<script setup lang="ts">
import { PhCheck, PhQuestion, PhWarning } from "@phosphor-icons/vue";
import { CHIP } from "@/components/ui/button";

/** Received and this week's, received but dated another week, or not received: by shape as well as colour. */
defineProps<{ tone: "ok" | "warn" | "none" }>();
</script>

<template>
  <span
    :class="[
      CHIP,
      tone === 'ok' && 'border-ok/40 bg-ok/10 text-ok-fg',
      tone === 'warn' && 'border-warn/40 bg-warn/10 text-warn-fg',
      tone === 'none' && 'border-dashed border-input text-muted-foreground',
    ]"
  >
    <component :is="tone === 'ok' ? PhCheck : tone === 'warn' ? PhWarning : PhQuestion" weight="bold" class="size-3" aria-hidden="true" />
    <slot />
  </span>
</template>
