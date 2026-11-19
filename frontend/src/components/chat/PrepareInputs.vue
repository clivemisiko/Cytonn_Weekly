<script setup lang="ts">
import { PhArrowLeft, PhArrowRight, PhArrowUpRight, PhCheck } from "@phosphor-icons/vue";
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import { RouterLink } from "vue-router";
import GridTable from "@/components/review/analyst/GridTable.vue";
import PasteTable from "@/components/review/analyst/PasteTable.vue";
import Button from "@/components/ui/Button.vue";
import { LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { range } from "@/lib/analyst";
import { type ReadinessEntry, typedProblem, unsavedSteps } from "@/lib/chatcards";
import type { AnalystForm, AnalystItem } from "@/lib/types";

// ponytail: the step logic is TypedInputsCard's, laid out for the prepare page; the chat keeps that card for the other sections.
// Fold the two into one when every section has moved to the prepare page.
const props = defineProps<{
  steps: ReadinessEntry[];
  /** Lines still typed only on the inputs form (the large-cap list, the fund table): listed in the footer beside its link. */
  formOnly: ReadinessEntry[];
  week: string;
  section: string;
  formTo: string;
  n: number;
}>();
const emit = defineEmits<{ changed: [] }>();

const form = ref<AnalystForm | null>(null);
const readProblem = ref<string | null>(null);
const typed = ref<Record<string, string>>({});
const errors = ref<Record<string, string>>({});
const saved = ref<Record<string, string>>({});
const busy = ref<string | null>(null);
const at = ref(0);
const finished = ref(false);
const announce = ref("");
const body = useTemplateRef<HTMLElement>("body");

watch(
  () => `${props.week} ${props.section}`,
  (_now, _before, onCleanup) => {
    let live = true;
    onCleanup(() => (live = false));
    api
      .getAnalystInputs(props.week, props.section)
      .then((f) => {
        if (!live) return;
        form.value = f;
        readProblem.value = null;
      })
      .catch((err: Error) => live && (readProblem.value = err.message));
  },
  { immediate: true },
);

const items = computed(() => {
  const all = new Map<string, AnalystItem>((form.value?.groups ?? []).flatMap((g) => g.items.map((i) => [i.key, i] as const)));
  return props.steps.map((e) => ({ entry: e, item: all.get(e.key) ?? null }));
});
const left = computed(() => unsavedSteps(props.steps, saved.value));
const last = computed(() => at.value === props.steps.length - 1);

async function go(i: number) {
  at.value = i;
  finished.value = false;
  announce.value = `Step ${i + 1} of ${props.steps.length}, ${props.steps[i].label}`;
  await nextTick();
  body.value?.querySelector<HTMLElement>(`[data-step="${i}"] :is(input, textarea)`)?.focus();
}
function finish() {
  finished.value = true;
  announce.value = left.value.length ? `Done: ${left.value.length} still to type` : "Done: all typed values are saved";
}
const next = () => (last.value ? finish() : go(at.value + 1));

async function save(key: string, changes: api.AnalystChanges, shown: string) {
  busy.value = key;
  errors.value = { ...errors.value, [key]: "" };
  try {
    await api.saveAnalystInputs(props.week, props.section, changes);
    saved.value = { ...saved.value, [key]: shown };
    emit("changed");
    busy.value = null; // the inputs are enabled again before focus moves, or the next one cannot take it
    if (!last.value) await go(at.value + 1);
    else if (!left.value.length) finish();
  } catch (err) {
    errors.value = { ...errors.value, [key]: (err as Error).message };
  } finally {
    busy.value = null;
  }
}
function saveField(key: string) {
  const text = typed.value[key] ?? "";
  const problem = typedProblem(text);
  if (problem) errors.value = { ...errors.value, [key]: problem };
  else void save(key, { fields: { [key]: text.trim() } }, text.trim());
}
const rowsShown = (n: number) => `${n} row${n === 1 ? "" : "s"}`;
const pastedRows = (text: string) => text.split("\n").filter((l) => l.trim()).length;
</script>

<template>
  <section aria-labelledby="prepare-inputs-title" class="space-y-4 rounded-lg border p-4 sm:p-6" data-card="prepare_inputs">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 id="prepare-inputs-title" class="text-lg font-semibold"><span class="mr-2 tabular-nums">{{ n }}</span>Report inputs</h3>
      <p v-if="steps.length && form && !finished" class="text-sm text-muted-foreground tabular-nums">Step {{ at + 1 }} of {{ steps.length }}</p>
    </div>
    <p aria-live="polite" class="sr-only">{{ announce }}</p>
    <p v-if="readProblem" role="alert" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ readProblem }}</p>
    <p v-else-if="steps.length && !form" class="text-sm text-muted-foreground" aria-busy="true">Reading the form…</p>

    <p v-else-if="finished && !left.length" class="text-sm">All typed values are saved.</p>
    <div v-else-if="finished" class="flex flex-wrap items-center gap-2">
      <p class="text-sm">{{ left.length }} still to type</p>
      <Button variant="outline" class="min-h-11" @click="go(left[0])">Go to the first one</Button>
    </div>

    <div v-else-if="steps.length" ref="body">
      <div v-for="({ entry, item }, i) in items" v-show="i === at" :key="entry.key" :data-step="i">
        <p v-if="entry.key in saved" class="mb-2 flex items-center gap-1 text-xs font-medium text-ok-fg">
          <PhCheck weight="bold" aria-hidden="true" />Saved: <span class="[overflow-wrap:anywhere]">{{ saved[entry.key] }}</span>
        </p>

        <!-- A single value: the guidance sits beside the box (below it on a phone). -->
        <div v-if="item?.type === 'field' && item.kind !== 'names'" class="grid gap-4 md:grid-cols-[minmax(0,1fr)_18rem]">
          <div class="min-w-0 space-y-1.5">
            <label :for="`prepare-${item.key}`" class="block text-sm font-medium">{{ item.label }}</label>
            <div class="flex flex-wrap items-center gap-2">
              <div class="relative min-w-0 flex-1 basis-48">
                <input
                  :id="`prepare-${item.key}`"
                  v-model="typed[item.key]"
                  :type="item.kind === 'date' ? 'date' : 'text'"
                  :inputmode="item.kind === 'number' ? 'decimal' : undefined"
                  autocomplete="off"
                  :disabled="busy !== null"
                  :aria-describedby="`prepare-${item.key}-unit prepare-${item.key}-help prepare-${item.key}-error`"
                  :aria-invalid="errors[item.key] ? true : undefined"
                  class="flex min-h-11 w-full rounded-md border border-input bg-card px-3 text-sm tabular-nums outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-flag"
                  :class="item.unit && 'pr-20'"
                  @keydown.enter.prevent="saveField(item.key)"
                />
                <span v-if="item.unit" :id="`prepare-${item.key}-unit`" class="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground">{{ item.unit }}</span>
              </div>
              <Button variant="outline" class="min-h-11" :disabled="busy !== null" @click="saveField(item.key)">
                {{ busy === item.key ? "Saving…" : "Save" }}<span class="sr-only">: {{ item.label }}</span>
              </Button>
            </div>
            <p v-if="item.help" :id="`prepare-${item.key}-help`" class="text-xs text-muted-foreground">{{ item.help }}</p>
            <p :id="`prepare-${item.key}-error`" aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[item.key] ?? "" }}</p>
          </div>
          <div class="self-start rounded-md bg-cw-assistant px-4 py-3 text-xs">
            <p :id="`prepare-${item.key}-guidance`" class="eyebrow mb-1">Input guidance</p>
            <dl class="space-y-1" :aria-labelledby="`prepare-${item.key}-guidance`">
              <div><dt class="inline">Source: </dt><dd class="inline">{{ item.source }}</dd></div>
              <div v-if="item.used_in"><dt class="inline">Used in: </dt><dd class="inline">{{ item.used_in }}</dd></div>
              <div v-if="range(item.min, item.max, item.unit)"><dt class="inline">Expected: </dt><dd class="inline">{{ range(item.min, item.max, item.unit) }}</dd></div>
            </dl>
          </div>
        </div>

        <!-- A table: the guidance goes above, so the editor keeps the card's full width. -->
        <div v-else-if="item?.type === 'table'" class="space-y-3">
          <dl class="flex flex-wrap gap-x-6 gap-y-1 rounded-md bg-cw-assistant px-4 py-3 text-xs" :aria-label="`Input guidance for ${item.label}`">
            <div><dt class="inline">Source: </dt><dd class="inline">{{ item.source }}</dd></div>
            <div v-if="item.used_in"><dt class="inline">Used in: </dt><dd class="inline">{{ item.used_in }}</dd></div>
          </dl>
          <GridTable
            v-if="item.mode === 'grid'"
            :item="item"
            :disabled="busy !== null"
            @save="(rows) => save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } }, rows ? rowsShown(rows.length) : 'cleared')"
          />
          <PasteTable
            v-else
            :item="item"
            :disabled="busy !== null"
            @save="(text) => save(item.key, { tables: { [item.key]: text === null ? null : { text } } }, text ? rowsShown(pastedRows(text)) : 'cleared')"
          />
          <p aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[entry.key] ?? "" }}</p>
        </div>
        <p v-else class="text-sm">{{ entry.label }}: {{ entry.why }}</p>
      </div>
    </div>
    <p v-else class="text-sm text-muted-foreground">Nothing is left to type here.</p>

    <div class="flex flex-wrap items-end justify-between gap-3 border-t pt-4">
      <div v-if="formOnly.length || steps.length" class="space-y-0.5">
        <p v-if="formOnly.length" class="text-xs text-muted-foreground">{{ formOnly.map((e) => e.label).join(", ") }}</p>
        <RouterLink :to="formTo" :class="['inline-flex min-h-11 items-center gap-1 text-sm', LINK]">
          Open inputs form<PhArrowUpRight weight="bold" class="size-3.5" aria-hidden="true" />
        </RouterLink>
      </div>
      <div v-if="steps.length && form && !finished" class="ml-auto flex flex-wrap gap-2">
        <Button variant="outline" class="min-h-11" :disabled="at === 0 || busy !== null" @click="go(at - 1)">
          <PhArrowLeft weight="bold" data-icon="inline-start" aria-hidden="true" />Previous
        </Button>
        <Button variant="outline" class="min-h-11" :disabled="busy !== null" @click="next">
          {{ last ? "Done" : "Next" }}<PhArrowRight v-if="!last" weight="bold" data-icon="inline-end" aria-hidden="true" />
        </Button>
      </div>
    </div>
  </section>
</template>
