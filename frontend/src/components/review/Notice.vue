<script setup lang="ts">
import { PhInfo, PhWarning, PhWarningCircle } from "@phosphor-icons/vue";
import { cn } from "cn";
import { useAttrs } from "vue";

const TONES = {
  flag: { box: "border-flag/40 bg-flag/10 text-flag-fg", quiet: "border-l-flag", icon: PhWarningCircle },
  warn: { box: "border-warn/40 bg-warn/10 text-warn-fg", quiet: "border-l-warn", icon: PhWarning },
  info: { box: "border-border bg-muted text-foreground", quiet: "border-l-input", icon: PhInfo },
} as const;

defineOptions({ inheritAttrs: false });
// quiet: a standing caution (dev mode, the export's watermark) that must be read but must not be the screen's focus: a
// coloured edge and icon on the card's own fill, body-coloured text.
const props = withDefaults(defineProps<{ tone?: keyof typeof TONES; quiet?: boolean }>(), { tone: "flag", quiet: false });
const attrs = useAttrs();
</script>

<template>
  <div
    v-bind="attrs"
    :class="
      cn(
        'flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm leading-relaxed',
        props.quiet ? `border-l-[3px] bg-card py-2 text-xs text-foreground ${TONES[props.tone].quiet}` : TONES[props.tone].box,
        attrs.class as string,
      )
    "
  >
    <component
      :is="TONES[props.tone].icon"
      weight="bold"
      class="mt-0.5 size-4 shrink-0"
      :class="props.quiet && (props.tone === 'flag' ? 'text-flag-fg' : props.tone === 'warn' ? 'text-warn-fg' : 'text-muted-foreground')"
      aria-hidden="true"
    />
    <span class="min-w-0"><slot /></span>
  </div>
</template>
