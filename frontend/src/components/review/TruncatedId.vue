<script setup lang="ts">
import { truncateId } from "@/lib/format";

/** A long hash or id in monospace, shortened to first 8 + last 4; the full value is the tooltip and the screen-reader label. */
defineProps<{ value: string }>();
</script>

<template>
  <span :title="value" :aria-label="value" tabindex="0" class="font-mono text-[0.9em] whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-ring">{{ truncateId(value) }}</span>
</template>
