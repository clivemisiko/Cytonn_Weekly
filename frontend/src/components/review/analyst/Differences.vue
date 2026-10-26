<script setup lang="ts">
import Notice from "../Notice.vue";

defineProps<{ lines: string[] }>();
</script>

<template>
  <Notice v-if="lines.length" tone="warn" role="status">
    <ul class="space-y-1">
      <li v-for="line in lines" :key="line">{{ line }}</li>
    </ul>
    <p class="mt-1 font-medium">The reviewer is shown each difference.</p>
  </Notice>
</template>
