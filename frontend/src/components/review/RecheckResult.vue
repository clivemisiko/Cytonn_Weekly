<script setup lang="ts">
import { onMounted, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import { changeLine, keptNames } from "@/lib/fixfile";
import type { FixResult } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{ result: FixResult }>();
defineEmits<{ redraft: [] }>();

const root = ref<HTMLElement | null>(null);
onMounted(() => root.value?.focus());
const changed = props.result.changes.length;
</script>

<template>
  <section ref="root" tabindex="-1" aria-labelledby="recheck-title" class="rise-in space-y-3 rounded-lg border border-l-[6px] border-ok/40 border-l-ok bg-ok/10 px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <h2 id="recheck-title" role="status" class="text-base font-semibold text-ok-fg">
      Figures re-checked. {{ changed === 0 ? "Nothing changed." : `${changed} changed.` }}
    </h2>
    <ul v-if="changed" class="list-disc space-y-1 pl-5 text-sm [overflow-wrap:anywhere]">
      <li v-for="c in result.changes" :key="`${c.block}|${c.label}`">{{ changeLine(c) }}</li>
    </ul>
    <p v-else class="text-sm">The new file gave the same figures as before, so no item changed.</p>
    <p class="text-sm text-muted-foreground">
      Kept from the earlier version: public sources and the written text<template v-if="result.kept.length"> ({{ keptNames(result.kept) }})</template>.
    </p>
    <p class="text-sm text-muted-foreground">
      This is a new version. {{ result.changed_items }} {{ result.changed_items === 1 ? "item starts" : "items start" }} undecided; notes and accepted marks on the other items were kept.
      <template v-if="result.was_approved">The earlier version was approved, so this one needs approving again.</template>
    </p>
    <Notice v-if="changed" tone="warn" class="items-center">
      <span class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span>The text around changed figures has not been rewritten. Draft the section again to update it.</span>
        <Button size="sm" variant="outline" @click="$emit('redraft')">Draft again</Button>
      </span>
    </Notice>
  </section>
</template>
