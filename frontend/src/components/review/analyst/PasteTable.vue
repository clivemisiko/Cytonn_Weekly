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
const emit = defineEmits<{ save: [text: string | null]; dirty: [dirty: boolean]; confirm: []; retire: [point_id: number, reason: string] }>();

const text = ref(props.item.text);
const dirty = computed(() => text.value.trim() !== props.item.text.trim());
watch(dirty, (now) => emit("dirty", now));
const typed = computed(() => !!props.item.rows?.length);
const rows = computed(() => props.item.rows ?? props.item.workbook_rows ?? []);
const id = `analyst-${props.item.key}`;

const retiringId = ref<number | null>(null);
const retireReason = ref<string>("");

function startRetire(pointId: number) {
  retiringId.value = pointId;
  retireReason.value = "";
}

function cancelRetire() {
  retiringId.value = null;
  retireReason.value = "";
}

function submitRetire(pointId: number) {
  if (!retireReason.value.trim()) return;
  emit("retire", pointId, retireReason.value.trim());
  cancelRetire();
}
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

    <!-- Active redemptions from the history store -->
    <div v-if="item.stored_rows && item.stored_rows.length > 0" class="space-y-2 rounded-md border p-3 bg-muted/30">
      <div class="flex items-center justify-between">
        <h4 class="text-xs font-semibold">Active redemptions from the history store (all weeks in fiscal year)</h4>
        <span class="text-[11px] text-muted-foreground">{{ item.stored_rows.length }} stored</span>
      </div>
      <p class="text-[11px] text-muted-foreground">
        Retiring an entry removes it from future drafts in this fiscal year; past saved runs are unchanged.
      </p>
      <div class="space-y-2">
        <div v-for="s in item.stored_rows" :key="s.point_id" class="flex flex-col gap-1.5 rounded border bg-background p-2 text-xs">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span class="font-mono font-medium">{{ s.date }}</span>
              <span class="font-semibold">{{ s.bond }}</span>
              <span class="tabular-nums font-mono">{{ s.kes_m.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }} Kshs mn</span>
              <span class="text-muted-foreground">Source: {{ s.source }}</span>
              <span class="text-muted-foreground">Confirmed by {{ s.confirmed_by }}{{ s.confirmed_on ? ` on ${s.confirmed_on}` : "" }}</span>
            </div>
            <Button
              v-if="retiringId !== s.point_id"
              size="sm"
              variant="outline"
              :disabled="disabled"
              :aria-label="`Retire ${s.bond} on ${s.date}`"
              @click="startRetire(s.point_id)"
            >
              Retire
            </Button>
          </div>
          <div v-if="retiringId === s.point_id" class="flex flex-col gap-2 pt-1 border-t mt-1">
            <label :for="`retire-reason-${s.point_id}`" class="text-[11px] font-medium text-warn-fg">
              Reason for retiring this redemption:
            </label>
            <div class="flex items-center gap-2">
              <input
                :id="`retire-reason-${s.point_id}`"
                v-model="retireReason"
                type="text"
                maxlength="200"
                placeholder="Give the reason for retiring this redemption..."
                class="flex-1 rounded border px-2 py-1 text-xs"
                :disabled="disabled"
                @keydown.enter.prevent="submitRetire(s.point_id)"
              />
              <Button
                size="sm"
                :disabled="disabled || !retireReason.trim()"
                @click="submitRetire(s.point_id)"
              >
                Confirm retire
              </Button>
              <Button size="sm" variant="outline" :disabled="disabled" @click="cancelRetire">
                Cancel
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <ConfirmBox v-if="item.needs_confirmation && !dirty" :carried="item.carried" :label="item.label" :disabled="disabled" @confirm="emit('confirm')" />
  </TableFrame>
</template>
