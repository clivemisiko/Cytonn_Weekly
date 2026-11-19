<script setup lang="ts">
defineProps<{ title: string; id: string }>();
</script>

<template>
  <section :aria-labelledby="id" class="rounded-lg border bg-card">
    <div class="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b px-4 py-2">
      <h2 :id="id" class="panel-title">{{ title }}</h2>
      <slot name="action" />
    </div>
    <div class="p-2"><slot /></div>
  </section>
</template>
