<script setup lang="ts">
import { computed } from "vue";
import { groupNotices } from "@/lib/extraction";
import type { ExtractionNotice } from "@/lib/types";
import ExtractionErrorCard from "./ExtractionErrorCard.vue";

const props = defineProps<{ notices: ExtractionNotice[] }>();
const groups = computed(() => groupNotices(props.notices));
</script>

<template>
  <div v-if="groups.length" class="@container space-y-3">
    <details v-for="g in groups" :key="g.key" open class="space-y-2">
      <summary class="cursor-pointer text-sm font-semibold">
        Source: {{ g.title }}
        <span class="font-normal text-muted-foreground"> · {{ g.cards.length }} {{ g.cards.length === 1 ? "part" : "parts" }} left out</span>
      </summary>
      <ul class="mt-2 space-y-2">
        <ExtractionErrorCard v-for="c in g.cards" :key="c.location" v-bind="c" />
      </ul>
    </details>
  </div>
</template>
