<script setup lang="ts">
import { PhCircleNotch } from "@phosphor-icons/vue";

defineProps<{ name: string }>();
</script>

<template>
  <span role="status" class="inline-flex items-center gap-1.5 text-xs font-medium text-foreground" data-uploading>
    <PhCircleNotch weight="bold" class="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
    <span class="[overflow-wrap:anywhere]">Uploading and reading {{ name }}…</span>
  </span>
</template>
