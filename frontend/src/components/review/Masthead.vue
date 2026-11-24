<script setup lang="ts">
withDefaults(defineProps<{ title?: string; wide?: boolean; flush?: boolean; crumbs?: string[] }>(), { title: "Digital Payments: analyst review", wide: false, flush: false, crumbs: undefined });
</script>

<template>
  <header :class="!flush && 'border-b bg-card'">
    <div :class="!flush && 'w-full px-4 py-3.5 sm:px-6'">
      <div v-if="!flush" class="flex items-center justify-between gap-3">
        <nav v-if="crumbs" aria-label="Breadcrumb">
          <ol class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <li v-for="(c, i) in crumbs" :key="i" class="flex items-center gap-1.5" :aria-current="i === crumbs.length - 1 ? 'page' : undefined">
              {{ c }}<span v-if="i < crumbs.length - 1" aria-hidden="true">/</span>
            </li>
          </ol>
        </nav>
        <p v-else class="eyebrow flex items-center gap-2">
          <span aria-hidden="true" class="size-1.5 rounded-full bg-primary" />
          Cytonn Weekly
        </p>
        <slot name="actions" />
      </div>
      <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-1" :class="!flush && 'mt-1'">
        <h1 class="text-xl font-bold tracking-tight text-foreground">{{ title }}</h1>
        <div v-if="$slots.meta" class="text-sm font-medium text-muted-foreground"><slot name="meta" /></div>
      </div>
      <p v-if="$slots.default" class="mt-1 text-xs leading-relaxed text-muted-foreground"><slot /></p>
    </div>
  </header>
</template>
