<script setup lang="ts">
import { PhCircleNotch } from "@phosphor-icons/vue";
import { useLiveElapsed } from "@/lib/drafting";
import { elapsed, friendlyTime } from "@/lib/format";
import type { Drafting } from "@/lib/types";
import Notice from "./Notice.vue";

/** Overview-level notice: which section is drafting, since when, and whether it looks stuck. */
const props = defineProps<{ drafting: Drafting }>();
const seconds = useLiveElapsed(() => props.drafting);
</script>

<template>
  <Notice v-if="drafting.stale" tone="warn" role="status">
    <span class="font-semibold">{{ drafting.title }} has been drafting for {{ elapsed(seconds) }}</span> (started
    {{ friendlyTime(drafting.started_at) }}), longer than any healthy draft takes. It looks stuck: the next draft started, in
    any section, replaces it, and its result will be discarded.
  </Notice>
  <div v-else role="status" class="flex flex-col gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
    <span class="flex shrink-0 items-center gap-2 text-sm font-semibold whitespace-nowrap">
      <PhCircleNotch weight="bold" class="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      Drafting {{ drafting.title }}
      <span class="font-mono font-medium tabular-nums text-muted-foreground">{{ elapsed(seconds) }}</span>
    </span>
    <span class="text-sm text-muted-foreground">
      Started {{ friendlyTime(drafting.started_at) }}. One draft runs at a time, across every section; it is saved and shows
      below when it finishes.
    </span>
  </div>
</template>
