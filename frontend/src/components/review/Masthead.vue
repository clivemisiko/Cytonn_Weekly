<script setup lang="ts">
/**
 * The one dark surface in the light theme, and the only place the brand shows: a teal-black band with
 * the report's name above the screen's title. Everything below it is paper, hairlines and the three state colours.
 * The way back is not here: Home and Back are on the top bar (components/nav/TopBar.vue), which never scrolls away.
 * Slots: `meta` for right-aligned facts about this screen, the default for one quiet line under the title.
 */
withDefaults(defineProps<{ title?: string; wide?: boolean }>(), { title: "Digital Payments: coordinator review", wide: false });
</script>

<template>
  <header class="border-b border-band-rule bg-band text-band-foreground">
    <div class="mx-auto w-full px-4 py-6 sm:px-6" :class="wide ? 'max-w-375' : 'max-w-275'">
      <p class="eyebrow flex items-center gap-2 text-band-muted">
        <span aria-hidden="true" class="block h-0.5 w-4 rounded-full bg-current" />
        Cytonn Weekly
      </p>
      <div class="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
        <h1 class="text-xl font-semibold sm:text-2xl">{{ title }}</h1>
        <p v-if="$slots.meta" class="text-sm text-band-muted"><slot name="meta" /></p>
      </div>
      <p v-if="$slots.default" class="mt-1 text-sm text-band-muted"><slot /></p>
    </div>
  </header>
</template>
