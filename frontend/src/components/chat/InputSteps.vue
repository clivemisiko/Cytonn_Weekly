<script setup lang="ts">
import { PhArrowLeft, PhArrowRight, PhCheck } from "@phosphor-icons/vue";
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import GridTable from "@/components/review/analyst/GridTable.vue";
import PasteTable from "@/components/review/analyst/PasteTable.vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { range } from "@/lib/analyst";
import { typedProblem } from "@/lib/chatcards";
import { NO_STEPS_LINE, type Step } from "@/lib/prepare";
import type { AnalystField, AnalystForm, AnalystItem } from "@/lib/types";

const props = defineProps<{
  steps: Step[];
  /** The section's analyst form, or null when it has none; a save hands the server's new form back through `form`. */
  form: AnalystForm | null;
  week: string;
  section: string;
  /** Keys still required or waiting to be confirmed: where "still to do" comes from. */
  missing: string[];
  /** The step it opens on. */
  start: number;
  heading: string;
  /** The card's number on the prepare page; none in the chat. */
  n?: number;
  dataCard: string;
}>();
const emit = defineEmits<{ changed: []; form: [form: AnalystForm]; done: [] }>();
defineSlots<{ step(props: { step: Step; next: () => void }): unknown }>();

const typed = ref<Record<string, string>>({});
const errors = ref<Record<string, string>>({});
const busy = ref<string | null>(null);
const at = ref(Math.min(props.start, Math.max(props.steps.length - 1, 0)));
const finished = ref(false);
const announce = ref("");
const body = useTemplateRef<HTMLElement>("body");
const id = (key: string, part = "") => `steps-${props.dataCard}-${key.replace(/[^a-z0-9_-]/gi, "-")}${part}`;

const shownOf = (v: string | string[] | null | undefined) => (Array.isArray(v) ? v.join(", ") : (v ?? ""));
const boxOf = (v: string | string[] | null | undefined) => (Array.isArray(v) ? v.join("\n") : (v ?? ""));
const byKey = computed(() => new Map<string, AnalystItem>((props.form?.groups ?? []).flatMap((g) => g.items.map((i) => [i.key, i] as const))));
// A saved value is shown in its box: the box is filled once, from the form, and what the analyst types is never overwritten.
watch(
  byKey,
  (items) => {
    for (const i of items.values()) if (i.type === "field" && !(i.key in typed.value)) typed.value[i.key] = boxOf(i.value);
  },
  { immediate: true },
);

/** What is saved for an item, in words, or null when nothing is. */
function savedOf(i: AnalystItem | undefined): string | null {
  if (!i || i.needs_confirmation) return null;
  if (i.type === "table") return i.rows?.length ? `${i.rows.length} row${i.rows.length === 1 ? "" : "s"}` : null;
  return shownOf(i.value) || null;
}
const carriedWord = (i: AnalystItem) => (i.carried?.from === "suggested" ? "Suggested" : i.carried?.from === "fetched" ? "Fetched" : "Carried from last week");

const left = computed(() => props.steps.flatMap((s, i) => (props.missing.includes(s.key) ? [i] : [])));
const last = computed(() => at.value === props.steps.length - 1);

async function go(i: number) {
  at.value = i;
  finished.value = false;
  announce.value = `Step ${i + 1} of ${props.steps.length}, ${props.steps[i].label}`;
  await nextTick();
  body.value?.querySelector<HTMLElement>(`[data-step="${i}"] :is(input:not([type=file]), textarea, select)`)?.focus();
}
function finish() {
  finished.value = true;
}
// What is still to do is the server's word after the last save is read back, so the end is announced when that arrives.
watch([finished, () => left.value.length], ([end, n]) => {
  if (!end) return;
  announce.value = n ? `Done: ${n} still to do` : "Done: everything required is in place";
  if (!n) emit("done");
});
const next = () => (last.value ? finish() : go(at.value + 1));

async function save(key: string, changes: api.AnalystChanges) {
  busy.value = key;
  errors.value = { ...errors.value, [key]: "" };
  try {
    emit("form", await api.saveAnalystInputs(props.week, props.section, changes));
    emit("changed");
  } catch (err) {
    errors.value = { ...errors.value, [key]: (err as Error).message };
    busy.value = null;
    return;
  }
  // The inputs are enabled again before focus moves: a disabled box cannot take focus, so the next step's box would not get it.
  busy.value = null;
  if (!last.value) await go(at.value + 1);
  else finish();
}
function saveField(i: AnalystField) {
  const text = typed.value[i.key] ?? "";
  const problem = typedProblem(text);
  if (problem) errors.value = { ...errors.value, [i.key]: problem };
  else void save(i.key, { fields: { [i.key]: text.trim() } });
}
const confirm = (key: string) => save(key, { confirm: [key] });
</script>

<template>
  <section :aria-labelledby="id('title')" class="space-y-4 rounded-lg border p-4 sm:p-6" :data-card="dataCard">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 :id="id('title')" class="text-lg font-semibold"><span v-if="n" class="mr-2 tabular-nums">{{ n }}</span>{{ heading }}</h3>
      <p v-if="steps.length && !finished" class="text-sm text-muted-foreground tabular-nums">Step {{ at + 1 }} of {{ steps.length }}</p>
    </div>
    <p aria-live="polite" class="sr-only">{{ announce }}</p>

    <p v-if="!steps.length" class="text-sm">{{ NO_STEPS_LINE }}</p>
    <p v-else-if="finished && !left.length" class="text-sm">Everything required here is in place.</p>
    <div v-else-if="finished" class="flex flex-wrap items-center gap-2">
      <p class="text-sm">{{ left.length }} still to do</p>
      <Button variant="outline" class="min-h-11" @click="go(left[0])">Go to the first one</Button>
    </div>

    <div v-else ref="body">
      <div v-for="(step, i) in steps" v-show="i === at" :key="step.key" :data-step="i" class="space-y-3">
        <template v-if="step.kind === 'item'">
          <template v-for="item in [byKey.get(step.key)]" :key="item?.key ?? step.key">
            <p v-if="!item" class="text-sm text-muted-foreground" aria-busy="true">Reading the form…</p>
            <template v-else>
              <p v-if="savedOf(item)" class="flex items-center gap-1 text-xs font-medium text-ok-fg">
                <PhCheck weight="bold" aria-hidden="true" />Saved: <span class="[overflow-wrap:anywhere]">{{ savedOf(item) }}</span>
              </p>
              <p v-else-if="item.type === 'field' && !item.value && item.workbook" class="text-xs text-muted-foreground">
                From the workbook: <span class="[overflow-wrap:anywhere]">{{ shownOf(item.workbook.value) }}</span>. Type a value to use instead.
              </p>

              <!-- A value carried or suggested waits for the analyst: confirm it as it stands, or type another and save. -->
              <div v-if="item.needs_confirmation && item.type === 'field'" class="flex flex-wrap items-center gap-3 rounded-md bg-cw-assistant px-4 py-3 text-sm">
                <p class="min-w-0 flex-1 basis-60">
                  {{ carriedWord(item) }}, not yet confirmed: <span class="font-semibold [overflow-wrap:anywhere]">{{ shownOf(item.value) }}</span>.
                </p>
                <Button variant="outline" class="min-h-11 bg-card" :disabled="busy !== null" @click="confirm(item.key)">
                  {{ busy === item.key ? "Saving…" : `Confirm ${shownOf(item.value)}` }}<span class="sr-only"> for {{ item.label }}</span>
                </Button>
              </div>

              <!-- A single value or a names box: the guidance sits beside it (below it on a phone). -->
              <div v-if="item.type === 'field'" class="grid gap-4 md:grid-cols-[minmax(0,1fr)_18rem]">
                <div class="min-w-0 space-y-1.5">
                  <label :for="id(item.key)" class="block text-sm font-medium">{{ item.label }}</label>
                  <p v-if="item.kind === 'names'" :id="id(item.key, '-lines')" class="text-xs text-muted-foreground">One per line.</p>
                  <div class="flex flex-wrap items-start gap-2">
                    <textarea
                      v-if="item.kind === 'names'"
                      :id="id(item.key)"
                      v-model="typed[item.key]"
                      rows="5"
                      :disabled="busy !== null"
                      :aria-describedby="`${id(item.key, '-lines')} ${id(item.key, '-help')} ${id(item.key, '-error')}`"
                      :aria-invalid="errors[item.key] ? true : undefined"
                      class="min-w-0 flex-1 basis-48 rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-flag"
                    />
                    <div v-else class="relative min-w-0 flex-1 basis-48">
                      <input
                        :id="id(item.key)"
                        v-model="typed[item.key]"
                        :type="item.kind === 'date' ? 'date' : 'text'"
                        :inputmode="item.kind === 'number' ? 'decimal' : undefined"
                        autocomplete="off"
                        :disabled="busy !== null"
                        :aria-describedby="`${id(item.key, '-unit')} ${id(item.key, '-help')} ${id(item.key, '-error')}`"
                        :aria-invalid="errors[item.key] ? true : undefined"
                        class="flex min-h-11 w-full rounded-md border border-input bg-card px-3 text-sm tabular-nums outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-flag"
                        :class="item.unit && 'pr-20'"
                        @keydown.enter.prevent="saveField(item)"
                      />
                      <span v-if="item.unit" :id="id(item.key, '-unit')" class="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground">{{ item.unit }}</span>
                    </div>
                    <Button variant="outline" class="min-h-11" :disabled="busy !== null" @click="saveField(item)">
                      {{ busy === item.key ? "Saving…" : "Save" }}<span class="sr-only">: {{ item.label }}</span>
                    </Button>
                  </div>
                  <p v-if="item.help" :id="id(item.key, '-help')" class="text-xs text-muted-foreground">{{ item.help }}</p>
                  <p :id="id(item.key, '-error')" aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[item.key] ?? "" }}</p>
                </div>
                <div class="self-start rounded-md bg-cw-assistant px-4 py-3 text-xs">
                  <p :id="id(item.key, '-guidance')" class="eyebrow mb-1">Input guidance</p>
                  <dl class="space-y-1" :aria-labelledby="id(item.key, '-guidance')">
                    <div><dt class="inline">Source: </dt><dd class="inline">{{ item.source }}</dd></div>
                    <div v-if="item.used_in"><dt class="inline">Used in: </dt><dd class="inline">{{ item.used_in }}</dd></div>
                    <div v-if="range(item.min, item.max, item.unit)"><dt class="inline">Expected: </dt><dd class="inline">{{ range(item.min, item.max, item.unit) }}</dd></div>
                  </dl>
                </div>
              </div>

              <!-- A table: the guidance goes above, so the editor keeps the card's full width. -->
              <div v-else class="space-y-3">
                <dl class="flex flex-wrap gap-x-6 gap-y-1 rounded-md bg-cw-assistant px-4 py-3 text-xs" :aria-label="`Input guidance for ${item.label}`">
                  <div><dt class="inline">Source: </dt><dd class="inline">{{ item.source }}</dd></div>
                  <div v-if="item.used_in"><dt class="inline">Used in: </dt><dd class="inline">{{ item.used_in }}</dd></div>
                </dl>
                <GridTable
                  v-if="item.mode === 'grid'"
                  :item="item"
                  :disabled="busy !== null"
                  @save="(rows) => save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } })"
                  @confirm="confirm(item.key)"
                />
                <PasteTable
                  v-else
                  :item="item"
                  :disabled="busy !== null"
                  @save="(text) => save(item.key, { tables: { [item.key]: text === null ? null : { text } } })"
                  @confirm="confirm(item.key)"
                />
                <p aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[item.key] ?? "" }}</p>
              </div>
            </template>
          </template>
        </template>
        <slot v-else name="step" :step="step" :next="next" />
      </div>
    </div>

    <div v-if="steps.length && !finished" class="flex flex-wrap justify-end gap-2 border-t pt-4">
      <Button variant="outline" class="min-h-11" :disabled="at === 0 || busy !== null" @click="go(at - 1)">
        <PhArrowLeft weight="bold" data-icon="inline-start" aria-hidden="true" />Previous
      </Button>
      <Button variant="outline" class="min-h-11" :disabled="busy !== null" @click="next">
        {{ last ? "Done" : "Next" }}<PhArrowRight v-if="!last" weight="bold" data-icon="inline-end" aria-hidden="true" />
      </Button>
    </div>
  </section>
</template>
