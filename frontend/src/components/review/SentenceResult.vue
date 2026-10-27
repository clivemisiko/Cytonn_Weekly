<script setup lang="ts">
import { onMounted, ref } from "vue";
import type { SentenceResult } from "@/lib/types";

defineProps<{ result: SentenceResult }>();

const root = ref<HTMLElement | null>(null);
onMounted(() => root.value?.focus());
</script>

<template>
  <section ref="root" tabindex="-1" aria-labelledby="sentence-title" class="rise-in space-y-3 rounded-lg border border-l-[6px] border-ok/40 border-l-ok bg-ok/10 px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <h2 id="sentence-title" role="status" class="text-base font-semibold text-ok-fg">
      {{ result.action === "paragraph" ? "Paragraph rewritten by you." : result.action === "edit" ? "Sentence edited. The figures were checked again." : "Sentence removed." }}
    </h2>
    <p v-if="result.action === 'paragraph'" class="text-sm text-muted-foreground">
      Nothing was checked against a source, because you wrote this paragraph. Read every figure in it against its source by hand.
      No model and no web search was used. Only that paragraph changed.
    </p>
    <p v-else class="text-sm text-muted-foreground">
      The check ran on this computer only: no model and no web search. Only that sentence changed. Nothing else in the draft was touched.
    </p>
    <p class="text-sm text-muted-foreground">
      This is a new version; the earlier one stays saved. {{ result.changed_items }} {{ result.changed_items === 1 ? "item starts" : "items start" }} undecided;
      notes and accepted marks on the other items were kept.
      <template v-if="result.was_approved">The earlier version was approved, so this one needs approving again.</template>
    </p>
  </section>
</template>
