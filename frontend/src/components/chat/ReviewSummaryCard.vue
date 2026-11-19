<script setup lang="ts">
import { PhArrowSquareOut } from "@phosphor-icons/vue";
import Button from "@/components/ui/Button.vue";
import { friendlyTime } from "@/lib/format";
import { type ReviewSnapshot, STATUS_WORDS } from "@/lib/chatcards";

defineProps<{ snapshot: ReviewSnapshot; title: string; at: string }>();
const emit = defineEmits<{ full: [reviewId: number] }>();
</script>

<template>
  <section :aria-label="`${title} draft saved as review ${snapshot.reviewId}`" class="space-y-2 rounded-md border bg-background px-3 py-2.5" data-card="review_summary">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 class="text-sm font-semibold">Draft saved as review {{ snapshot.reviewId }}</h3>
      <span v-if="snapshot.isDev" class="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-dev-ink">DEV DRAFT</span>
    </div>
    <p class="text-xs text-muted-foreground">As it was when the draft finished, {{ friendlyTime(at) }}.</p>
    <p class="text-sm">
      <span class="font-mono font-semibold">{{ snapshot.counts.flagged }}</span> flagged,
      <span class="font-mono font-semibold">{{ snapshot.counts.notAuto }}</span> not auto-verified,
      <span class="font-mono font-semibold">{{ snapshot.counts.clean }}</span> clean.
    </p>
    <ul v-if="snapshot.items.length" class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]" aria-label="Items to look at">
      <li v-for="i in snapshot.items" :key="i.index">{{ STATUS_WORDS[i.status] ?? i.status }}: {{ i.ref }}</li>
    </ul>
    <Button variant="outline" size="sm" @click="emit('full', snapshot.reviewId)">
      <PhArrowSquareOut weight="bold" data-icon="inline-start" aria-hidden="true" />
      Open full view<span class="sr-only"> of review {{ snapshot.reviewId }}</span>
    </Button>
  </section>
</template>
