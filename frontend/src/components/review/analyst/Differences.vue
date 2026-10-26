<script setup lang="ts">
import { computed } from "vue";
import Notice from "../Notice.vue";

/** Where a typed value and the uploaded workbook disagree, line by line. */
const props = defineProps<{ lines: string[] }>();

// Every line ends with the same sentence; it is said once, in the heading.
const SUFFIX = / The typed value is used\.$/;
const rows = computed(() => props.lines.map((l) => l.replace(SUFFIX, "")));
// A long list is folded, but its count and the rule stay in view.
const FOLD_AFTER = 3;
</script>

<template>
  <Notice v-if="lines.length" tone="warn" role="status">
    <p class="font-medium">
      {{ lines.length }} {{ lines.length === 1 ? "value differs" : "values differ" }} from the uploaded workbook. The typed value is used.
    </p>
    <details :open="lines.length <= FOLD_AFTER" class="mt-1">
      <summary v-if="lines.length > FOLD_AFTER" class="cursor-pointer">Show the {{ lines.length }} differences</summary>
      <ul class="mt-1 space-y-1">
        <li v-for="line in rows" :key="line">{{ line }}</li>
      </ul>
    </details>
    <p class="mt-1 font-medium">The reviewer is shown each difference.</p>
  </Notice>
</template>
