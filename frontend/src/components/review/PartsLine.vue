<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ parts: { text: string; style?: "name" | "mono" }[] }>();
const shown = computed(() => props.parts.filter((p) => p.text));
</script>

<template>
  <ul class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground md:pl-11">
    <li v-for="(p, i) in shown" :key="`${i}-${p.text}`" class="flex items-center gap-2">
      <span v-if="i > 0" aria-hidden="true">·</span>
      <span :class="[p.style === 'name' && 'font-semibold text-foreground', p.style === 'mono' && 'font-mono']">{{ p.text }}</span>
    </li>
  </ul>
</template>
