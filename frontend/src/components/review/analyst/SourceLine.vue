<script setup lang="ts">
/** Source, where it is printed and the range the API accepts: the same three facts under every item. */
defineProps<{ source: string; usedIn: string; expected?: string }>();
</script>

<template>
  <p class="text-xs text-muted-foreground">
    Source: <span class="font-medium text-foreground">{{ source }}</span><span aria-hidden="true"> · </span>Used in: {{ usedIn }}<template v-if="expected"
      ><span aria-hidden="true"> · </span>Expected: <span class="font-mono">{{ expected }}</span></template
    >
  </p>
</template>
