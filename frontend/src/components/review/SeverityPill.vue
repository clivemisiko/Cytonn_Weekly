<script setup lang="ts">
import { PhCheck, PhCircleDashed, PhWrench } from "@phosphor-icons/vue";
import { computed } from "vue";
import { RESOLUTION_CHIPS, STATUS_META } from "@/lib/format";
import type { Status } from "@/lib/types";

const props = defineProps<{ kind: Status | "none" | "accept" | "fix_needed" }>();
const status = computed(() => (props.kind in STATUS_META ? (props.kind as Status) : null));
const RES = {
  none: { icon: PhCircleDashed, cls: "border-dashed border-input text-muted-foreground" },
  accept: { icon: PhCheck, cls: "border-ok/40 bg-ok/10 text-ok-fg" },
  fix_needed: { icon: PhWrench, cls: "border-flag/40 bg-flag/10 text-flag-fg" },
} as const;
</script>

<template>
  <span
    v-if="status"
    :class="`state-${status}`"
    class="inline-flex items-center gap-1 rounded-full border py-0.5 pr-2 pl-0.5 text-xs font-semibold whitespace-nowrap text-(--hue-fg)"
    :style="{ borderColor: 'color-mix(in srgb, var(--hue) 55%, transparent)', background: 'color-mix(in srgb, var(--hue) 10%, transparent)', borderStyle: status === 'not_auto_verified' ? 'dashed' : 'solid' }"
  >
    <span class="glyph size-4 text-xs" aria-hidden="true">{{ STATUS_META[status].glyph }}</span>
    {{ STATUS_META[status].label }}
  </span>
  <span v-else class="inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs font-medium" :class="RES[kind as keyof typeof RES].cls">
    <component :is="RES[kind as keyof typeof RES].icon" weight="bold" class="size-3" aria-hidden="true" />
    {{ RESOLUTION_CHIPS[kind as keyof typeof RES] }}
  </span>
</template>
