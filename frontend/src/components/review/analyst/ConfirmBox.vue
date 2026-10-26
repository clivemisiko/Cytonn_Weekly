<script setup lang="ts">
import { PhCheck } from "@phosphor-icons/vue";
import Button from "@/components/ui/Button.vue";
import type { AnalystCarried } from "@/lib/types";

defineProps<{ carried: AnalystCarried | null; label: string; disabled: boolean }>();
const emit = defineEmits<{ confirm: [] }>();
</script>

<template>
  <div class="space-y-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2">
    <p class="text-xs font-medium text-warn-fg">
      {{
        carried?.from === "suggested"
          ? "A suggestion only. It is not used in a draft until you confirm it or type the figure yourself."
          : "This changes every week. Last week’s value is not used in a draft until you confirm it for this week or type this week’s."
      }}
    </p>
    <p v-if="carried?.note" class="text-xs [overflow-wrap:anywhere]">{{ carried.note }}</p>
    <Button size="sm" variant="outline" :disabled="disabled" @click="emit('confirm')">
      <PhCheck weight="bold" data-icon="inline-start" aria-hidden="true" />
      Confirm for this week<span class="sr-only">: {{ label }}</span>
    </Button>
  </div>
</template>
