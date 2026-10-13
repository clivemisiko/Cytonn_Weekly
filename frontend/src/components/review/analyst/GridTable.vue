<script setup lang="ts">
import { PhPlus, PhTrash } from "@phosphor-icons/vue";
import { cn } from "cn";
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import { FIELD } from "@/components/ui/button";
import { type Line, cameFrom, canonical, capital, header, isCarried, linesOf, rowsOf } from "@/lib/analyst";
import type { AnalystRow, AnalystTable } from "@/lib/types";
import ConfirmBox from "./ConfirmBox.vue";
import TableFrame from "./TableFrame.vue";

/** A grid typed cell by cell: the Universe of Coverage's inputs, the Eurobond issues. Empty cells show the workbook's value. */
const props = defineProps<{ item: AnalystTable; disabled: boolean }>();
const emit = defineEmits<{ save: [rows: AnalystRow[] | null]; dirty: [dirty: boolean]; confirm: [] }>();

const lines = ref<Line[]>(linesOf(props.item));
const fixed = props.item.fixed_rows.length > 0;
const name = props.item.columns[0];
const columns = fixed ? props.item.columns : props.item.columns.slice(1);
const saved = canonical(props.item, props.item.rows ?? []);
const dirty = computed(() => canonical(props.item, rowsOf(props.item, lines.value)) !== saved);
watch(dirty, (now) => emit("dirty", now));
const typedCount = props.item.rows?.length ?? 0;
const count = computed(() =>
  fixed ? typedCount || (props.item.workbook_rows?.length ?? 0) : lines.value.filter((l) => l.label || Object.keys(l.typed).length).length,
);

const setCell = (id: string, key: string, value: string) =>
  (lines.value = lines.value.map((l) => (l.id === id ? { ...l, typed: { ...l.typed, [key]: value } } : l)));
const rowName = (line: Line) => (fixed ? line.label : line.typed[name.key] || line.label || "new company");
const typedValue = (event: Event) => (event.target as HTMLInputElement).value;
const addLine = () => (lines.value = [...lines.value, { id: `new-${Date.now()}-${lines.value.length}`, label: "", typed: {}, book: {}, listed: false }]);
</script>

<template>
  <TableFrame :item="item" :count="count" :typed="typedCount > 0">
    <div class="overflow-x-auto rounded-md border">
      <table class="w-full text-xs">
        <thead class="bg-muted text-left">
          <tr>
            <th scope="col" class="px-2 py-2 font-semibold">{{ fixed ? "" : header(name) }}</th>
            <th v-for="c in columns" :key="c.key" scope="col" class="px-2 py-2 font-semibold">{{ header(c) }}</th>
            <th v-if="!fixed" scope="col" class="w-8" />
          </tr>
        </thead>
        <tbody>
          <tr v-for="line in lines" :key="line.id" class="border-t align-middle">
            <th scope="row" class="px-2 py-1 text-left font-medium">
              <span v-if="fixed || line.listed" class="whitespace-nowrap">{{ line.label }}</span>
              <input
                v-else
                type="text"
                autocomplete="off"
                :aria-label="`${item.label}: ${name.label}`"
                :value="line.typed[name.key] ?? ''"
                :disabled="disabled"
                placeholder="Company"
                :class="cn(FIELD, 'h-8 w-40 px-2 text-sm md:text-xs')"
                @input="setCell(line.id, name.key, typedValue($event))"
              />
            </th>
            <td v-for="c in columns" :key="c.key" class="px-2 py-1">
              <input
                :type="c.kind === 'date' ? 'date' : 'text'"
                :inputmode="c.kind === 'number' ? 'decimal' : undefined"
                autocomplete="off"
                :aria-label="`${rowName(line)}: ${header(c)}`"
                :value="line.typed[c.key] ?? ''"
                :disabled="disabled"
                :placeholder="line.book[c.key] ?? ''"
                :title="isCarried(item, line, c.key) && item.carried ? capital(cameFrom(item.carried)) : undefined"
                :class="
                  cn(
                    FIELD,
                    'h-8 px-2 font-mono text-sm tabular-nums md:text-xs',
                    c.kind === 'date' ? 'w-36' : 'w-24',
                    isCarried(item, line, c.key) && 'border-dashed bg-muted',
                  )
                "
                @input="setCell(line.id, c.key, typedValue($event))"
              />
            </td>
            <td v-if="!fixed" class="px-1">
              <button
                v-if="!line.listed"
                type="button"
                :disabled="disabled"
                :aria-label="`Remove ${rowName(line)}`"
                class="grid size-8 place-items-center rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                @click="lines = lines.filter((l) => l.id !== line.id)"
              >
                <PhTrash weight="bold" class="size-4" aria-hidden="true" />
              </button>
            </td>
          </tr>
          <tr v-if="lines.length === 0" class="border-t">
            <td :colspan="columns.length + 2" class="px-2 py-3 text-muted-foreground">No company yet. Add one, or upload the workbook to start from its rows.</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button v-if="!fixed" size="sm" variant="outline" :disabled="disabled" @click="addLine">
        <PhPlus weight="bold" data-icon="inline-start" aria-hidden="true" />
        Add company
      </Button>
      <Button size="sm" :disabled="disabled || !dirty" @click="emit('save', rowsOf(item, lines))">Save</Button>
      <Button v-if="dirty" size="sm" variant="outline" :disabled="disabled" @click="lines = linesOf(item)">Discard changes</Button>
      <Button v-if="typedCount > 0 && !dirty" size="sm" variant="outline" :disabled="disabled" @click="emit('save', null)">
        <PhTrash weight="bold" data-icon="inline-start" aria-hidden="true" />
        Clear typed values
      </Button>
      <span v-if="dirty" class="text-xs font-medium text-warn-fg">Not saved yet.</span>
    </div>
    <p v-if="(item.workbook_rows?.length ?? 0) > 0" class="text-xs text-muted-foreground">
      Grey figures are the uploaded workbook’s. A cell you type overrides it; a cell you leave empty uses it.
    </p>
    <p v-if="item.auto_note" class="text-xs text-muted-foreground">{{ item.auto_note }} They show in grey.</p>
    <p v-if="item.carried && !item.needs_confirmation" class="text-xs text-muted-foreground">
      Shaded cells with a dashed edge are {{ cameFrom(item.carried) }}. Type over any that changed.
    </p>
    <ConfirmBox v-if="item.needs_confirmation && !dirty" :carried="item.carried" :label="item.label" :disabled="disabled" @confirm="emit('confirm')" />
  </TableFrame>
</template>
