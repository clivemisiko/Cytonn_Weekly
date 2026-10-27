<script setup lang="ts">
import { PhInfo, PhWarning, PhWarningCircle } from "@phosphor-icons/vue";
import { cn } from "cn";
import { useAttrs } from "vue";

const TONES = {
  flag: { box: "border-flag/40 bg-flag/10 text-flag-fg", icon: PhWarningCircle },
  warn: { box: "border-warn/40 bg-warn/10 text-warn-fg", icon: PhWarning },
  info: { box: "border-border bg-muted text-foreground", icon: PhInfo },
} as const;

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{ tone?: keyof typeof TONES }>(), { tone: "flag" });
const attrs = useAttrs();
</script>

<template>
  <div v-bind="attrs" :class="cn('flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm leading-relaxed shadow-2xs', TONES[props.tone].box, attrs.class as string)">
    <component :is="TONES[props.tone].icon" weight="bold" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    <span class="min-w-0"><slot /></span>
  </div>
</template>
