<script setup lang="ts">
import { PhCircleNotch } from "@phosphor-icons/vue";
import { RouterLink } from "vue-router";
import { LINK } from "@/components/ui/button";
import { draftingStatus, runHref, useLiveElapsed } from "@/lib/drafting";
import { elapsed, friendlyTime } from "@/lib/format";
import type { Drafting } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{ drafting: Drafting }>();
const seconds = useLiveElapsed(() => props.drafting);
</script>

<template>
  <Notice v-if="drafting.stale" tone="warn" role="status">
    <span class="font-semibold">{{ drafting.title }} has been drafting for {{ elapsed(seconds) }}</span> (started
    {{ friendlyTime(drafting.started_at) }}), longer than any healthy draft takes. It looks stuck: a draft that finds every
    seat taken replaces it, and its result will be discarded.
    <RouterLink v-if="runHref(drafting)" :to="runHref(drafting)!" :class="LINK">View progress</RouterLink>
  </Notice>
  <div v-else role="status" class="flex flex-col gap-2 rounded-lg border border-input bg-muted px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
    <span class="flex shrink-0 items-center gap-2 text-sm font-semibold whitespace-nowrap">
      <PhCircleNotch weight="bold" class="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      {{ drafting.title }}: {{ draftingStatus(drafting) }}
      <span v-if="drafting.state !== 'queued'" class="font-mono font-medium tabular-nums text-muted-foreground">{{ elapsed(seconds) }}</span>
    </span>
    <span class="text-sm text-muted-foreground">
      <template v-if="drafting.state === 'queued'">Waiting for a free drafting seat; it starts by itself.</template>
      <template v-else>Started {{ friendlyTime(drafting.started_at) }}. It is saved and shows below when it finishes.</template>
    </span>
    <RouterLink v-if="runHref(drafting)" :to="runHref(drafting)!" :class="[LINK, 'shrink-0 text-sm font-semibold']">View progress</RouterLink>
  </div>
</template>
