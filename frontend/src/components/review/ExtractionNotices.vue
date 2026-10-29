<script setup lang="ts">
import { computed } from "vue";
import { groupNotices } from "@/lib/extraction";
import type { ExtractionNotice } from "@/lib/types";
import ExtractionErrorCard from "./ExtractionErrorCard.vue";
import Notice from "./Notice.vue";

const props = defineProps<{ notices: ExtractionNotice[] }>();
// A "source" notice says where a figure came from; the others are tables a file could not give.
const sources = computed(() => props.notices.filter((n) => n.kind === "source"));
const groups = computed(() => groupNotices(props.notices.filter((n) => n.kind !== "source")));
const safeUrl = (url: string | null | undefined) => (url && /^https?:\/\//.test(url) ? url : null);
</script>

<template>
  <div v-if="sources.length" class="space-y-2">
    <Notice v-for="n in sources" :key="n.text" :tone="n.level === 'warning' ? 'warn' : 'info'" role="status">
      {{ n.text }}
      <a v-if="safeUrl(n.link)" :href="safeUrl(n.link)!" target="_blank" rel="noopener noreferrer"
         class="text-link underline underline-offset-2">Open the source</a>
    </Notice>
  </div>
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
