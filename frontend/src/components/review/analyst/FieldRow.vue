<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { FIELD } from "@/components/ui/button";
import { asText, fieldOrigin, originLabel, range } from "@/lib/analyst";
import { friendlyDate } from "@/lib/format";
import type { AnalystField } from "@/lib/types";
import ConfirmBox from "./ConfirmBox.vue";
import Differences from "./Differences.vue";
import OriginChip from "./OriginChip.vue";
import SourceLine from "./SourceLine.vue";

/**
 * One typed field. It is saved when the cursor leaves it; emptied, the workbook's value (if any) is used again.
 * The panel keys it on the value the API holds, so a save that was kept starts it afresh and a refused one keeps the typing.
 */
const props = defineProps<{
  item: AnalystField;
  disabled: boolean;
  /** Why the API refused to work out a suggestion for this field, in its words. */
  error?: string | null;
}>();
const emit = defineEmits<{ save: [value: string]; dirty: [dirty: boolean]; confirm: []; suggest: [] }>();

const saved = asText(props.item.value);
const value = ref(saved);
const fromBook = computed(() => asText(props.item.workbook?.value));
const origin = computed(() => fieldOrigin(props.item));
const id = `analyst-${props.item.key}`;
const describedBy = computed(() => (props.error ? `${id}-error ${id}-hint` : `${id}-hint`));
watch(value, (next) => emit("dirty", next.trim() !== saved));
const commit = () => {
  if (value.value.trim() !== saved) emit("save", value.value);
};
</script>

<template>
  <div class="space-y-1">
    <div class="flex flex-wrap items-center gap-2">
      <label :for="id" class="text-sm font-semibold">{{ item.label }}</label>
      <OriginChip :origin="origin">{{ originLabel(origin, item.carried) }}</OriginChip>
    </div>
    <Textarea
      v-if="item.kind === 'names'"
      :id="id"
      v-model="value"
      :disabled="disabled"
      :aria-describedby="`${id}-hint`"
      rows="4"
      :placeholder="fromBook || 'Safaricom\nEquity Group\n…'"
      class="py-2 font-mono"
      @blur="commit"
    />
    <div v-else class="flex flex-wrap items-center gap-2">
      <input
        :id="id"
        v-model="value"
        :disabled="disabled"
        :aria-describedby="describedBy"
        :type="item.kind === 'date' ? 'date' : 'text'"
        :inputmode="item.kind === 'number' ? 'decimal' : undefined"
        autocomplete="off"
        :placeholder="fromBook ? `${fromBook} (workbook)` : undefined"
        :class="[FIELD, 'w-44 tabular-nums']"
        @blur="commit"
        @keydown.enter="($event.currentTarget as HTMLInputElement).blur()"
      />
      <span v-if="item.unit" class="text-sm text-muted-foreground">{{ item.unit }}</span>
      <Button v-if="item.suggestable && (!saved || item.needs_confirmation)" size="sm" variant="outline" :disabled="disabled" @click="emit('suggest')">
        Suggest from last week’s total<span class="sr-only">: {{ item.label }}</span>
      </Button>
      <span v-if="item.kind === 'date' && !value && fromBook" class="text-xs text-muted-foreground">
        Workbook: <span class="font-mono">{{ friendlyDate(fromBook) }}</span>
      </span>
      <span v-if="item.kind === 'date' && !value && !fromBook && item.default" class="text-xs text-muted-foreground">
        Used when empty: <span class="font-mono">{{ friendlyDate(item.default) }}</span>
      </span>
    </div>
    <p v-if="error" :id="`${id}-error`" role="alert" class="max-w-[72ch] text-xs font-medium whitespace-pre-line text-flag-fg">{{ error }}</p>
    <div :id="`${id}-hint`" class="space-y-1">
      <p v-if="item.help" class="text-xs text-muted-foreground">{{ item.help }}</p>
      <SourceLine :source="item.source" :used-in="item.used_in" :expected="range(item.min, item.max, item.unit)" />
      <p v-if="origin === 'workbook' && item.workbook" class="text-xs text-muted-foreground">
        Read from <span class="font-mono [overflow-wrap:anywhere]">{{ item.workbook.ref }}</span>. Type a value to use yours instead.
      </p>
      <p v-if="item.workbook_note && !saved" class="text-xs text-warn-fg">{{ item.workbook_note }}</p>
    </div>
    <ConfirmBox v-if="item.needs_confirmation" :carried="item.carried" :label="item.label" :disabled="disabled" @confirm="emit('confirm')" />
    <Differences :lines="item.differences" />
  </div>
</template>
