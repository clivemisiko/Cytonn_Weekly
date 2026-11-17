<script setup lang="ts">
import { PhArrowsClockwise, PhCheckCircle, PhDownloadSimple, PhMinusCircle, PhWarningCircle } from "@phosphor-icons/vue";
import { friendlyTime } from "@/lib/format";
import { GROUPS, type GroupKey, type Readiness, sourcesLine, snipLine } from "@/lib/chatcards";

defineProps<{ readiness: Readiness; title: string; at: string }>();

const ICONS = { needs_analyst: PhWarningCircle, carried_or_suggested: PhArrowsClockwise, fetched: PhDownloadSimple, in_place: PhCheckCircle, optional: PhMinusCircle } satisfies Record<GroupKey, unknown>;
</script>

<template>
  <section :aria-label="`What ${title} needs for the week ending ${readiness.weekEnding}`" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="readiness">
    <div class="space-y-0.5">
      <h3 class="text-sm font-semibold">What {{ title }} needs for the week ending {{ readiness.weekEnding }}</h3>
      <p class="text-xs text-muted-foreground">As it was when this conversation opened, {{ friendlyTime(at) }}. What can be done now is under “What you can do now”.</p>
    </div>
    <template v-for="g in GROUPS" :key="g.key">
      <div v-if="readiness.groups[g.key].length" class="space-y-1">
        <p class="flex items-center gap-1.5 text-sm font-semibold">
          <component :is="ICONS[g.key]" weight="bold" class="size-4 shrink-0" aria-hidden="true" />
          {{ g.heading }} ({{ readiness.groups[g.key].length }})
        </p>
        <p class="text-xs text-muted-foreground">{{ g.meaning }}</p>
        <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
          <li v-for="e in readiness.groups[g.key]" :key="e.key">{{ e.label }}: {{ e.why }}</li>
        </ul>
      </div>
    </template>
    <div v-if="readiness.snips" class="space-y-1">
      <p class="text-sm font-semibold">Snips</p>
      <ul class="list-disc space-y-0.5 pl-5 text-sm">
        <li v-for="s in readiness.snips" :key="s.sector">{{ snipLine(s) }}</li>
      </ul>
    </div>
    <div v-if="readiness.sources" class="space-y-1">
      <p class="text-sm font-semibold">Sources</p>
      <p class="text-sm">{{ sourcesLine(readiness.sources) }}</p>
    </div>
    <p v-if="readiness.note" class="text-sm text-muted-foreground">{{ readiness.note }}</p>
  </section>
</template>
