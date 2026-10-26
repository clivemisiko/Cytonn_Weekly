<script setup lang="ts">
import { PhArrowBendDownRight } from "@phosphor-icons/vue";
import { computed, onUnmounted, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { asText } from "@/lib/analyst";
import { friendlyDate, friendlyTime } from "@/lib/format";
import { useLeaveGuard } from "@/lib/nav";
import type { AnalystForm } from "@/lib/types";
import Notice from "../Notice.vue";
import FieldRow from "./FieldRow.vue";
import GridTable from "./GridTable.vue";
import PasteTable from "./PasteTable.vue";

const props = defineProps<{
  /** The Friday the report week ends on (ISO date). */
  week: string;
  /** The section whose inputs are shown: "fixed_income" or "equities". */
  section: string;
  disabled?: boolean;
  /** Changes when the week's uploads change, so the workbook's values are read again. */
  refresh: number;
}>();
/** True while something typed here is not saved yet (the draft button waits for it). */
const emit = defineEmits<{ pending: [pending: boolean] }>();

const form = ref<AnalystForm | null>(null);
const error = ref<string | null>(null);
/** A suggestion the API refused, shown under its own button rather than at the top of a long form. */
const fieldError = ref<{ key: string; text: string } | null>(null);
const busy = ref(false);
const dirty = ref<Record<string, boolean>>({});

watch(
  () => [props.week, props.section, props.refresh],
  (_now, _before, onCleanup) => {
    let live = true;
    onCleanup(() => (live = false));
    api
      .getAnalystInputs(props.week, props.section)
      .then((f) => live && (form.value = f))
      .catch((err: Error) => live && (error.value = err.message));
  },
  { immediate: true },
);

const waiting = computed(() => form.value?.unconfirmed ?? []);
const unsaved = computed(() => Object.values(dirty.value).some(Boolean));
const pending = computed(() => busy.value || unsaved.value || waiting.value.length > 0);
// Home and Back on the top bar ask before leaving while something typed here is not saved.
useLeaveGuard(unsaved, 'Something typed under "Weekly analyst inputs" is not saved yet. Leave this page and lose it?');
watch(pending, (now) => emit("pending", now), { immediate: true });
onUnmounted(() => emit("pending", false));

const mark = (key: string, value: boolean) => {
  if (dirty.value[key] !== value) dirty.value = { ...dirty.value, [key]: value };
};

async function save(key: string, changes: api.AnalystChanges) {
  busy.value = true;
  error.value = null;
  fieldError.value = null;
  try {
    form.value = await api.saveAnalystInputs(props.week, props.section, changes);
    mark(key, false);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

/** One change the API makes to the whole form (carry last week's, work out a suggestion, confirm a value). */
async function act(work: () => Promise<AnalystForm>, key?: string) {
  busy.value = true;
  error.value = null;
  fieldError.value = null;
  try {
    form.value = await work();
  } catch (err) {
    const text = (err as Error).message;
    if (key) fieldError.value = { key, text };
    else error.value = text;
  } finally {
    busy.value = false;
  }
}
const confirm = (key: string) => act(() => api.saveAnalystInputs(props.week, props.section, { confirm: [key] }));
const carry = () => act(() => api.carryAnalystInputs(props.week, props.section));
const suggest = (key: string) => act(() => api.suggestAnalystInput(props.week, props.section, key), key);

const locked = computed(() => busy.value || !!props.disabled);
const hasBook = computed(() => form.value?.workbooks[props.section] ?? false);
</script>

<template>
  <section data-attention="analyst-form" aria-labelledby="analyst-title" class="space-y-4 rounded-lg border bg-card p-6">
    <div class="space-y-1 border-b pb-4">
      <h2 id="analyst-title" class="text-lg font-semibold">Weekly analyst inputs</h2>
      <p class="max-w-[72ch] text-sm text-muted-foreground">
        The figures only the analysts hold, for the week ending <span class="font-mono">{{ friendlyDate(week) }}</span>. Type them
        here when no workbook is sent. Every value is carried into the draft as an analyst input for you to check. Nothing
        is filled in by itself: a value copied from last week or suggested by a button waits for you to confirm it, and
        anything left empty is marked as missing in the draft.
      </p>
      <template v-if="form">
        <p class="text-xs text-muted-foreground">
          {{
            hasBook
              ? "A workbook is uploaded for this week: its values are shown and used wherever you type nothing."
              : "No workbook is uploaded for this week: the draft uses only what is typed here."
          }}{{ form.saved_at ? ` Last saved ${friendlyTime(form.saved_at)}.` : "" }}
        </p>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2 pt-2">
          <Button variant="outline" size="sm" :disabled="locked || !form.can_carry" @click="carry">
            <PhArrowBendDownRight weight="bold" data-icon="inline-start" aria-hidden="true" />
            Start from last week’s form
          </Button>
          <p class="max-w-[60ch] text-xs text-muted-foreground">
            {{
              form.can_carry
                ? `Copies what was saved for the week ending ${friendlyDate(form.previous_week)} into every item still empty here, each marked as carried. Figures that change every week then wait for you to confirm them.`
                : `Nothing confirmed is saved for the week ending ${friendlyDate(form.previous_week)} to start from.`
            }}
          </p>
        </div>
      </template>
    </div>

    <Notice v-if="waiting.length > 0" tone="warn" role="status">
      <span class="font-semibold">{{ waiting.length }} {{ waiting.length === 1 ? "value needs" : "values need" }} confirming before a draft:</span>
      {{ waiting.map((w) => w.label).join("; ") }}.
    </Notice>

    <Notice v-if="error" role="alert" data-problem class="font-medium whitespace-pre-line">{{ error }}</Notice>

    <p v-if="form === null && !error" class="text-sm text-muted-foreground" aria-busy="true">Reading the form…</p>
    <!-- An item is keyed on what the API holds for it: one whose save was refused keeps what was typed, one that was
         kept re-reads it, and saving one item never resets another that is still being typed. -->
    <template v-else-if="form">
      <section
        v-for="group in form.groups"
        :key="group.key"
        :aria-labelledby="`analyst-group-${group.key}`"
        class="space-y-4 border-t pt-4 first-of-type:border-t-0 first-of-type:pt-0"
      >
        <h3 :id="`analyst-group-${group.key}`" class="eyebrow">{{ group.title }}</h3>
        <template v-for="item in group.items" :key="item.key">
          <FieldRow
            v-if="item.type === 'field'"
            :key="`${item.key}:${asText(item.value)}`"
            :item="item"
            :disabled="locked"
            :error="fieldError?.key === item.key ? fieldError.text : null"
            @confirm="confirm(item.key)"
            @suggest="suggest(item.key)"
            @dirty="(d) => mark(item.key, d)"
            @save="(value) => save(item.key, { fields: { [item.key]: value.trim() || null } })"
          />
          <PasteTable
            v-else-if="item.mode === 'paste'"
            :key="`${item.key}:${item.text}`"
            :item="item"
            :disabled="locked"
            @confirm="confirm(item.key)"
            @dirty="(d) => mark(item.key, d)"
            @save="(text) => save(item.key, { tables: { [item.key]: text === null ? null : { text } } })"
          />
          <GridTable
            v-else
            :key="`${item.key}:${JSON.stringify([item.rows, item.workbook_rows, item.auto_rows])}`"
            :item="item"
            :disabled="locked"
            @confirm="confirm(item.key)"
            @dirty="(d) => mark(item.key, d)"
            @save="(rows) => save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } })"
          />
        </template>
      </section>
    </template>
  </section>
</template>
