<script setup lang="ts">
import { PhWarning } from "@phosphor-icons/vue";

defineProps<{ items: string[] }>();
</script>

<template>
  <ul v-if="items.length" class="space-y-1">
    <li v-for="(w, i) in items" :key="`${i}-${w}`" class="flex items-start gap-2 text-sm text-warn-fg">
      <PhWarning weight="bold" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {{ w }}
    </li>
  </ul>
</template>
