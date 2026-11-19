<script setup lang="ts">
import { PhCheck } from "@phosphor-icons/vue";
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import GridTable from "@/components/review/analyst/GridTable.vue";
import PasteTable from "@/components/review/analyst/PasteTable.vue";
import SourceLine from "@/components/review/analyst/SourceLine.vue";
import Button from "@/components/ui/Button.vue";
import { FIELD } from "@/components/ui/button";
import * as api from "@/lib/api";
import { range } from "@/lib/analyst";
import { type ReadinessEntry, typedProblem, unsavedSteps } from "@/lib/chatcards";
import type { AnalystForm, AnalystItem } from "@/lib/types";

const props = defineProps<{ steps: ReadinessEntry[]; week: string; section: string }>();
/** `empty`: the card has nothing left to show, so the page puts focus on its heading. */
const emit = defineEmits<{ changed: []; empty: [] }>();

const form = ref<AnalystForm | null>(null);
const readProblem = ref<string | null>(null);
const typed = ref<Record<string, string>>({});
const errors = ref<Record<string, string>>({});
/** What each saved step holds now, shown beside its "Saved" mark. */
const saved = ref<Record<string, string>>({});
const busy = ref<string | null>(null);
const at = ref(0);
const finished = ref(false);
const announce = ref("");
const body = useTemplateRef<HTMLElement>("body");

watch(
  () => [props.week, props.section],
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

// The form is read once: each editor stays mounted (hidden when not its step), so text typed and not saved survives Previous and Next.
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
async function finish() {
  finished.value = true;
  announce.value = left.value.length ? `Done: ${left.value.length} still to type` : "Done: all typed values are saved";
  if (!left.value.length) {
    await nextTick();
    emit("empty");
  }
}
const next = () => (last.value ? finish() : go(at.value + 1));

/** The inputs form's own save route and checks; a refusal keeps what was typed and shows the API's words under it. */
async function save(key: string, changes: api.AnalystChanges, shown: string) {
  busy.value = key;
  errors.value = { ...errors.value, [key]: "" };
  try {
    await api.saveAnalystInputs(props.week, props.section, changes);
    saved.value = { ...saved.value, [key]: shown };
    emit("changed");
    if (!last.value) await go(at.value + 1);
    else if (!left.value.length) await finish();
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
  <section aria-labelledby="typed-title" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="typed_inputs">
    <h3 id="typed-title" class="text-sm font-semibold">Type these here</h3>
    <p aria-live="polite" class="sr-only">{{ announce }}</p>
    <p v-if="readProblem" role="alert" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ readProblem }}</p>
    <p v-else-if="!form" class="text-sm text-muted-foreground" aria-busy="true">Reading the form…</p>

    <p v-else-if="finished && !left.length" class="text-sm">All typed values are saved.</p>
    <div v-else-if="finished" class="flex flex-wrap items-center gap-2">
      <p class="text-sm">{{ left.length }} still to type</p>
      <Button variant="outline" class="min-h-11" @click="go(left[0])">Go to the first one</Button>
    </div>

    <template v-else>
      <div ref="body">
        <div v-for="({ entry, item }, i) in items" v-show="i === at" :key="entry.key" :data-step="i" class="space-y-1.5">
          <p v-if="entry.key in saved" class="flex items-center gap-1 text-xs font-medium text-ok-fg">
            <PhCheck weight="bold" aria-hidden="true" />Saved: <span class="[overflow-wrap:anywhere]">{{ saved[entry.key] }}</span>
          </p>
          <template v-if="item?.type === 'field' && item.kind !== 'names'">
            <label :for="`chat-typed-${item.key}`" class="text-sm font-medium">{{ item.label }}</label>
            <div class="flex flex-wrap items-center gap-2">
              <input
                :id="`chat-typed-${item.key}`"
                v-model="typed[item.key]"
                :type="item.kind === 'date' ? 'date' : 'text'"
                :inputmode="item.kind === 'number' ? 'decimal' : undefined"
                autocomplete="off"
                :disabled="busy !== null"
                :aria-describedby="`chat-typed-${item.key}-hint chat-typed-${item.key}-error`"
                :aria-invalid="errors[item.key] ? true : undefined"
                :class="[FIELD, 'min-h-11', item.kind === 'text' ? 'w-full max-w-md' : 'w-44 tabular-nums']"
                @keydown.enter.prevent="saveField(item.key)"
              />
              <span v-if="item.unit" class="text-sm text-muted-foreground">{{ item.unit }}</span>
              <Button class="min-h-11" :disabled="busy !== null" @click="saveField(item.key)">
                {{ busy === item.key ? "Saving…" : "Save" }}<span class="sr-only">: {{ item.label }}</span>
              </Button>
            </div>
            <div :id="`chat-typed-${item.key}-hint`" class="space-y-1">
              <p v-if="item.help" class="text-xs text-muted-foreground">{{ item.help }}</p>
              <SourceLine :source="item.source" :used-in="item.used_in" :expected="range(item.min, item.max, item.unit)" />
            </div>
          </template>
          <GridTable
            v-else-if="item?.type === 'table' && item.mode === 'grid'"
            :item="item"
            :disabled="busy !== null"
            @save="(rows) => save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } }, rows ? rowsShown(rows.length) : 'cleared')"
          />
          <PasteTable
            v-else-if="item?.type === 'table'"
            :item="item"
            :disabled="busy !== null"
            @save="(text) => save(item.key, { tables: { [item.key]: text === null ? null : { text } } }, text ? rowsShown(pastedRows(text)) : 'cleared')"
          />
          <p v-else class="text-sm">{{ entry.label }}: {{ entry.why }}</p>
          <p :id="`chat-typed-${entry.key}-error`" aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[entry.key] ?? "" }}</p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2 border-t pt-2">
        <Button variant="outline" class="min-h-11" :disabled="at === 0 || busy !== null" @click="go(at - 1)">Previous</Button>
        <span class="text-sm text-muted-foreground tabular-nums">Step {{ at + 1 }} of {{ steps.length }}</span>
        <Button variant="outline" class="min-h-11" :disabled="busy !== null" @click="next">{{ last ? "Done" : "Next" }}</Button>
      </div>
    </template>
  </section>
</template>
