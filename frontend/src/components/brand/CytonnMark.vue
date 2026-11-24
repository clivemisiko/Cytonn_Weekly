<script setup lang="ts">
// Known limit: a placeholder drawn from the design artboards, not Cytonn's logo. Replace with Cytonn's official file once it is supplied.
withDefaults(defineProps<{ size?: number; avatar?: boolean; label?: string }>(), { size: 96, avatar: false, label: undefined });
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 96 96"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    class="shrink-0"
  >
    <template v-if="!avatar">
      <path d="M12 44a36 36 0 0 0 70 18" fill="none" stroke="var(--cw-logo-red)" stroke-width="7" stroke-linecap="round" />
      <path d="M30 84a36 36 0 0 0 46-10" fill="none" stroke="var(--cw-logo-purple)" stroke-width="7" stroke-linecap="round" />
      <path d="M54 86a36 36 0 0 0 30-26" fill="none" stroke="var(--cw-logo-blue)" stroke-width="7" stroke-linecap="round" />
      <path d="M22 22a36 36 0 0 0-10 22" fill="none" stroke="var(--cw-logo-green)" stroke-width="7" stroke-linecap="round" />
    </template>
    <circle :cx="avatar ? 48 : 52" :cy="avatar ? 48 : 40" :r="avatar ? 44 : 30" fill="var(--cw-accent)" />
    <g :transform="avatar ? 'translate(-4 8) scale(1)' : undefined">
      <path d="M52 24c1.6 9 5 12.4 14 14-9 1.6-12.4 5-14 14-1.6-9-5-12.4-14-14 9-1.6 12.4-5 14-14z" fill="var(--cw-button-fg)" />
      <circle cx="64" cy="26" r="1.6" fill="var(--cw-button-fg)" />
    </g>
  </svg>
</template>
