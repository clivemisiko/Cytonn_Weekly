<script setup lang="ts">
withDefaults(defineProps<{ title?: string; wide?: boolean; flush?: boolean }>(), { title: "Digital Payments: analyst review", wide: false, flush: false });
</script>

<template>
  <header :class="!flush && 'border-b bg-card'">
    <div :class="!flush && 'w-full px-4 py-3.5 sm:px-6'">
      <p v-if="!flush" class="eyebrow flex items-center gap-2">
        <span aria-hidden="true" class="size-1.5 rounded-full bg-primary" />
        Cytonn Weekly
      </p>
      <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-1" :class="!flush && 'mt-1'">
        <h1 class="text-xl font-bold tracking-tight text-foreground">{{ title }}</h1>
        <p v-if="$slots.meta" class="text-sm font-medium text-muted-foreground"><slot name="meta" /></p>
      </div>
      <p v-if="$slots.default" class="mt-1 text-xs leading-relaxed text-muted-foreground"><slot /></p>
    </div>
  </header>
</template>
