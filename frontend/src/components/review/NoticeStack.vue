<script setup lang="ts">
import Notice from "./Notice.vue";

/** A draft's warnings as one notice: the first line shows, the rest fold under "N more", so they do not pile up. */
defineProps<{ items: string[] }>();
</script>

<template>
  <Notice v-if="items.length === 1" tone="warn">{{ items[0] }}</Notice>
  <Notice v-else-if="items.length > 1" tone="warn">
    <details class="group">
      <summary class="cursor-pointer font-medium marker:text-warn-fg">{{ items[0] }} <span class="whitespace-nowrap underline underline-offset-2">+{{ items.length - 1 }} more</span></summary>
      <ul class="rise-in mt-2 list-disc space-y-1 pl-5">
        <li v-for="(w, i) in items.slice(1)" :key="`${i}-${w}`">{{ w }}</li>
      </ul>
    </details>
  </Notice>
</template>
