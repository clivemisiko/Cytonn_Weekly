<script setup lang="ts">
defineProps<{ label: string }>();
</script>

<template>
  <div
    role="status"
    class="hatch-dev sticky top-(--topbar-h) z-30 flex h-7 items-center justify-center border-b border-dev-rule px-4 font-mono text-xs font-semibold tracking-[0.06em] text-dev-ink"
  >
    <span class="truncate">{{ label }}</span>
  </div>
</template>
