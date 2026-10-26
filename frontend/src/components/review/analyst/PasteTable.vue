<script setup lang="ts">
import { PhTrash } from "@phosphor-icons/vue";
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { header } from "@/lib/analyst";
import type { AnalystTable } from "@/lib/types";
import ConfirmBox from "./ConfirmBox.vue";
import TableFrame from "./TableFrame.vue";

const props = defineProps<{ item: AnalystTable; disabled: boolean }>();
const emit = defineEmits<{ save: [text: string | null]; dirty: [dirty: boolean]; confirm: [] }>();

const text = ref(props.item.text);
const dirty = computed(() => text.value.trim() !== props.item.text.trim());
watch(dirty, (now) => emit("dirty", now));
const typed = computed(() => !!props.item.rows?.length);
const rows = computed(() => props.item.rows ?? props.item.workbook_rows ?? []);
const id = `analyst-${props.item.key}`;
</script>

<template>
  <TableFrame :item="item" :count="rows.length" :typed="typed">
    <label :for="id" class="sr-only">{{ item.label }}: paste the rows</label>
    <Textarea
      :id="id"
      v-model="text"
      rows="4"
      :disabled="disabled"
      spellcheck="false"
      :placeholder="`${item.columns.map((c) => c.label).join('   ')}\n${item.example}`"
      class="max-h-56 overflow-auto py-2 font-mono whitespace-pre"
    />
    <div class="flex flex-wrap items-center gap-2">
      <Button size="sm" :disabled="disabled || !dirty || !text.trim()" @click="emit('save', text)">Save table</Button>
      <Button v-if="dirty" size="sm" variant="outline" :disabled="disabled" @click="text = item.text">Discard changes</Button>
      <Button v-if="typed && !dirty" size="sm" variant="outline" :disabled="disabled" @click="emit('save', null)">
        <PhTrash weight="bold" data-icon="inline-start" aria-hidden="true" />
        Clear typed table
      </Button>
      <span v-if="dirty" class="text-xs font-medium text-warn-fg">Not saved yet.</span>
    </div>
    <!-- The rows in use, read-only: what was typed, else what the uploaded workbook holds. -->
    <div v-if="rows.length > 0" class="max-h-56 overflow-auto rounded-md border" tabindex="0" role="region" :aria-label="`${item.label}: rows in use`">
      <table class="w-full text-xs">
        <thead class="sticky top-0 bg-muted text-left">
          <tr>
            <th v-for="c in item.columns" :key="c.key" scope="col" class="px-2 py-1 font-semibold" :class="c.kind !== 'text' && 'text-right'">{{ header(c) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, n) in rows" :key="n" class="border-t">
            <td v-for="c in item.columns" :key="c.key" class="px-2 py-1" :class="c.kind !== 'text' && 'text-right tabular-nums'">{{ row[c.key] ?? "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <ConfirmBox v-if="item.needs_confirmation && !dirty" :carried="item.carried" :label="item.label" :disabled="disabled" @confirm="emit('confirm')" />
  </TableFrame>
</template>
