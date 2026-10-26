<script setup lang="ts">
withDefaults(defineProps<{ title?: string; wide?: boolean; flush?: boolean }>(), { title: "Digital Payments: coordinator review", wide: false, flush: false });
</script>

<template>
  <header :class="!flush && 'border-b bg-card'">
    <div :class="!flush && ['mx-auto w-full px-4 py-6 sm:px-6', wide ? 'max-w-375' : 'max-w-275']">
      <p v-if="!flush" class="eyebrow flex items-center gap-2">
        <span aria-hidden="true" class="brand-dot size-2 rounded-full bg-primary" />
        Cytonn Weekly
      </p>
      <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-1" :class="!flush && 'mt-2'">
        <h1 class="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">{{ title }}</h1>
        <p v-if="$slots.meta" class="text-sm font-medium text-muted-foreground"><slot name="meta" /></p>
      </div>
      <p v-if="$slots.default" class="mt-1.5 text-sm leading-relaxed text-muted-foreground"><slot /></p>
    </div>
  </header>
</template>
