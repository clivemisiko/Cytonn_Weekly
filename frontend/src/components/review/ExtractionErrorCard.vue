<script setup lang="ts">
import { PhWarning } from "@phosphor-icons/vue";
import TruncatedId from "./TruncatedId.vue";

defineProps<{
  /** The file it came from; left out when a group header already names it. */
  source?: string;
  location: string;
  reason: string;
  consequence: string;
  nextStep?: string;
  rawDetail?: string;
  fileId?: string;
}>();
</script>

<template>
  <li class="space-y-2 rounded-md border bg-muted/50 px-3 py-2 text-sm">
    <p class="flex items-center gap-2 font-semibold text-warn-fg">
      <PhWarning weight="bold" class="size-4 shrink-0" aria-hidden="true" />
      {{ location }}: left out of this draft
    </p>
    <dl class="grid gap-x-3 gap-y-1 @min-[30rem]:grid-cols-[9rem_1fr]">
      <template v-if="source">
        <dt class="text-xs text-muted-foreground">Source</dt>
        <dd>{{ source }}</dd>
      </template>
      <dt class="text-xs text-muted-foreground">What went wrong</dt>
      <dd class="[overflow-wrap:anywhere]">{{ reason }}</dd>
      <dt class="text-xs text-muted-foreground">What this means</dt>
      <dd>{{ consequence }}</dd>
    </dl>
    <p v-if="nextStep" class="font-semibold"><span class="text-xs font-normal text-muted-foreground">Next step </span>{{ nextStep }}</p>
    <details v-if="rawDetail || fileId" class="text-xs">
      <summary class="cursor-pointer text-muted-foreground">Show technical detail</summary>
      <div class="mt-1 space-y-1 [overflow-wrap:anywhere]">
        <p v-if="rawDetail" class="font-mono whitespace-pre-line">{{ rawDetail }}</p>
        <p v-if="fileId">File id: <TruncatedId :value="fileId" /></p>
      </div>
    </details>
  </li>
</template>
