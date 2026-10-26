<script setup lang="ts">
import { truncateId } from "@/lib/format";

defineProps<{ value: string }>();
</script>

<template>
  <span :title="value" :aria-label="value" tabindex="0" class="font-mono text-[0.9em] whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-ring">{{ truncateId(value) }}</span>
</template>
