<script setup lang="ts">
import { RadioGroupItem, RadioGroupRoot } from "reka-ui";
import { computed } from "vue";
import { RESOLUTION_LABELS, resolutionKey } from "@/lib/format";
import type { Resolution } from "@/lib/types";

const OPTIONS = ["none", "accept", "fix_needed"] as const;
type Option = (typeof OPTIONS)[number];

// Fill behind the selected option: neutral for "unresolved", the state colours for the other two.
const THUMB: Record<Option, string> = { none: "bg-foreground/10", accept: "bg-ok", fix_needed: "bg-flag" };
const SELECTED_TEXT: Record<Option, string> = { none: "text-foreground", accept: "text-ok-on", fix_needed: "text-flag-on" };

const props = defineProps<{ label: string; value: Resolution; disabled: boolean }>();
const emit = defineEmits<{ change: [next: Resolution] }>();
const current = computed(() => resolutionKey(props.value));
</script>

<template>
  <RadioGroupRoot
    :model-value="current"
    :disabled="disabled"
    :aria-label="`Resolution for ${label}`"
    class="relative inline-flex w-fit flex-col overflow-hidden rounded-md border border-input bg-card @min-[17rem]:flex-row"
    :class="disabled && 'border-border bg-muted' /* locked: a muted frame, not a fade, so the recorded choice keeps its full contrast */"
    @update:model-value="(v) => emit('change', v === 'none' ? null : (v as Resolution))"
  >
    <RadioGroupItem
      v-for="opt in OPTIONS"
      :key="opt"
      :value="opt"
      class="relative h-8 shrink-0 px-2 text-sm whitespace-nowrap transition-[color,background-color,transform] duration-150 ease-out outline-none not-first:border-t not-first:border-border @min-[17rem]:not-first:border-t-0 @min-[17rem]:not-first:border-l focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset disabled:cursor-not-allowed"
      :class="
        current === opt
          ? ['font-semibold', SELECTED_TEXT[opt]]
          : 'font-medium text-muted-foreground not-disabled:hover:bg-muted not-disabled:hover:text-foreground'
      "
    >
      <span v-if="current === opt" aria-hidden="true" class="absolute inset-0" :class="THUMB[opt]" />
      <span class="relative">{{ RESOLUTION_LABELS[opt] }}</span>
    </RadioGroupItem>
  </RadioGroupRoot>
</template>
