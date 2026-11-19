<script setup lang="ts">
import { RouterLink } from "vue-router";
import { LINK } from "@/components/ui/button";
import { type Readiness, snipLine, sourcesLine } from "@/lib/chatcards";

defineProps<{ readiness: Readiness; oldPage: string }>();
</script>

<template>
  <section aria-label="Sources and snips" class="space-y-2 rounded-md border bg-background px-3 py-2.5" data-card="sources">
    <h3 class="text-sm font-semibold">{{ readiness.snips ? "Snips and sources" : "Sources" }}</h3>
    <div v-if="readiness.snips" class="space-y-1">
      <p class="eyebrow">Snips</p>
      <ul class="list-disc space-y-0.5 pl-5 text-sm">
        <li v-for="s in readiness.snips" :key="s.sector">{{ snipLine(s) }}</li>
      </ul>
    </div>
    <div v-if="readiness.sources" class="space-y-1">
      <p class="eyebrow">Sources</p>
      <p class="text-sm">{{ sourcesLine(readiness.sources) }}</p>
    </div>
    <p v-if="readiness.note" class="text-sm text-muted-foreground">{{ readiness.note }}</p>
    <RouterLink :to="`${oldPage}&step=${readiness.snips ? 'snips' : 'sources'}`" :class="['inline-block text-sm', LINK]">Back to sources and inputs</RouterLink>
  </section>
</template>
