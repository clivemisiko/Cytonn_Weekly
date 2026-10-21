<script setup lang="ts">
/**
 * The dev-mode ribbon, directly under the top bar on the whole width of the page: a local-model draft can never be
 * mistaken for a production one. It sticks under the top bar as the page scrolls, and it is in the page's flow, so
 * nothing needs to be padded to clear it. The shell draws it (components/nav/AppShell.vue) for whichever screen says so.
 */
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
