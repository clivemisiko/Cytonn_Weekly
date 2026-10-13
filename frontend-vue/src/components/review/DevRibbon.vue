<script setup lang="ts">
/** Fixed ribbon, directly under the top bar: a local-model draft can never be mistaken for a production one. */
defineProps<{ label: string }>();
</script>

<template>
  <div
    role="status"
    class="hatch-dev fixed inset-x-0 top-(--topbar-h) z-40 flex h-7 items-center justify-center border-b border-dev-rule px-4 font-mono text-xs font-semibold tracking-[0.06em] text-dev-ink"
  >
    <span class="truncate">{{ label }}</span>
  </div>
</template>
