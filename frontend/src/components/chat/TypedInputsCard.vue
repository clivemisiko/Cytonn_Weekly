<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef, watch } from "vue";
import GridTable from "@/components/review/analyst/GridTable.vue";
import PasteTable from "@/components/review/analyst/PasteTable.vue";
import SourceLine from "@/components/review/analyst/SourceLine.vue";
import Button from "@/components/ui/Button.vue";
import { FIELD } from "@/components/ui/button";
import * as api from "@/lib/api";
import { range } from "@/lib/analyst";
import { type ReadinessEntry, typedProblem } from "@/lib/chatcards";
import type { AnalystForm, AnalystItem } from "@/lib/types";

const props = defineProps<{ entries: ReadinessEntry[]; week: string; section: string }>();
const emit = defineEmits<{ changed: [] }>();

const form = ref<AnalystForm | null>(null);
const readProblem = ref<string | null>(null);
const typed = ref<Record<string, string>>({});
const errors = ref<Record<string, string>>({});
const busy = ref<string | null>(null);
const heading = useTemplateRef<HTMLElement>("heading");

watch(
  () => [props.week, props.section, props.entries.map((e) => e.key).join()],
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
  return props.entries.map((e) => ({ entry: e, item: all.get(e.key) ?? null }));
});

/** The inputs form's own save route and checks; a refusal keeps what was typed and shows the API's words under it. */
async function save(key: string, changes: api.AnalystChanges) {
  busy.value = key;
  errors.value = { ...errors.value, [key]: "" };
  try {
    await api.saveAnalystInputs(props.week, props.section, changes);
    delete typed.value[key];
    emit("changed");
    // The line leaves the card once readiness is read again: focus goes to the card's heading, not to the page's body.
    await nextTick();
    heading.value?.focus();
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
  else void save(key, { fields: { [key]: text.trim() } });
}
</script>

<template>
  <section aria-labelledby="typed-title" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="typed_inputs">
    <h3 id="typed-title" ref="heading" tabindex="-1" class="text-sm font-semibold outline-none">Type these here</h3>
    <p v-if="readProblem" role="alert" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ readProblem }}</p>
    <p v-else-if="!form" class="text-sm text-muted-foreground" aria-busy="true">Reading the form…</p>

    <ul v-else class="space-y-4">
      <li v-for="{ entry, item } in items" :key="entry.key" class="space-y-1.5">
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
              :class="[FIELD, item.kind === 'text' ? 'w-full max-w-md' : 'w-44 tabular-nums']"
              @keydown.enter.prevent="saveField(item.key)"
            />
            <span v-if="item.unit" class="text-sm text-muted-foreground">{{ item.unit }}</span>
            <Button size="sm" :disabled="busy !== null" @click="saveField(item.key)">
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
          @save="(rows) => save(item.key, { tables: { [item.key]: rows === null ? null : { rows } } })"
        />
        <PasteTable
          v-else-if="item?.type === 'table'"
          :item="item"
          :disabled="busy !== null"
          @save="(text) => save(item.key, { tables: { [item.key]: text === null ? null : { text } } })"
        />
        <p v-else class="text-sm">{{ entry.label }}: {{ entry.why }}</p>
        <p :id="`chat-typed-${entry.key}-error`" aria-live="polite" class="text-xs font-medium whitespace-pre-line text-flag-fg">{{ errors[entry.key] ?? "" }}</p>
      </li>
    </ul>
  </section>
</template>
