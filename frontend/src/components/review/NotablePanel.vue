<script setup lang="ts">
import { PhCaretDown, PhCaretRight, PhCopy } from "@phosphor-icons/vue";
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { partition, selectedText, shown, TOP_N } from "@/lib/notable";
import type { DismissReason, Notable } from "@/lib/types";
import NotableCard from "./NotableCard.vue";
import Notice from "./Notice.vue";

const props = defineProps<{
  /** The section's slug ("fixed_income"). */
  section: string;
  sectionTitle: string;
  /** The Friday the report week ends on (ISO date). */
  week: string;
}>();

const data = ref<Notable | null>(null);
const loadError = ref<string | null>(null);
const actionError = ref<string | null>(null);
const busy = ref(false);
const showAll = ref(false);
const showDismissed = ref(false);
const copied = ref<"done" | "failed" | null>(null);

function load() {
  loadError.value = null;
  data.value = null;
  let live = true;
  api
    .getNotable(props.section, props.week)
    .then((n) => live && (data.value = n))
    .catch((err: Error) => live && (loadError.value = err.message));
  return () => (live = false);
}
watch(() => [props.section, props.week], (_now, _before, onCleanup) => onCleanup(load()), { immediate: true });

/** One change to a decision: the API answers with the whole list again. */
async function act(work: () => Promise<Notable>) {
  busy.value = true;
  actionError.value = null;
  try {
    data.value = await work();
    copied.value = null;
  } catch (err) {
    actionError.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}
const choose = (id: string, decision: "selected" | "dismissed", extra: { editedHeadline?: string; dismissReason?: DismissReason } = {}) =>
  act(() => api.decideNotable(props.section, props.week, { suggestionId: id, decision, ...extra }));
const restore = (id: string) => act(() => api.restoreNotable(props.section, props.week, id));

const lists = computed(() => partition(data.value?.suggestions ?? []));
const visible = computed(() => shown(lists.value.open, showAll.value));
const text = computed(() => selectedText(lists.value.selected, props.sectionTitle, props.week));
const failed = computed(() => data.value?.failed_checks ?? 0);

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value);
    copied.value = "done";
  } catch {
    copied.value = "failed";
  }
}
</script>

<template>
  <section aria-labelledby="notable-title" class="space-y-4 rounded-lg border bg-card p-6">
    <div class="space-y-1 border-b pb-4">
      <h2 id="notable-title" class="text-lg font-semibold">Notable this week</h2>
      <p class="max-w-[72ch] text-sm text-muted-foreground">
        Suggestions worked out by code from history, each with its working. Accept, edit or dismiss them as your own worklist for
        the week ending <span class="font-mono">{{ week }}</span
        >. They are never added to the draft, the review, the inputs or the Word export, and what you choose here does not change a
        review.
      </p>
    </div>

    <div v-if="!data && !loadError" aria-busy="true" aria-label="Loading suggestions" class="space-y-2">
      <div data-slot="skeleton" class="h-16 w-full animate-pulse rounded-md bg-border/60" />
      <div data-slot="skeleton" class="h-16 w-full animate-pulse rounded-md bg-border/60" />
    </div>

    <div v-else-if="loadError" class="space-y-2">
      <Notice role="alert">Notable suggestions could not be loaded: {{ loadError }}</Notice>
      <Button variant="outline" size="sm" @click="load">Try again</Button>
    </div>

    <template v-else-if="data">
      <Notice v-if="failed" tone="warn" role="status">
        {{ failed === 1 ? "One check could not run." : `${failed} checks could not run.` }}
        {{ data.suggestions.length ? "The other suggestions are not affected." : "" }}
      </Notice>
      <Notice v-if="actionError" role="alert">That change could not be saved: {{ actionError }}</Notice>

      <p v-if="!data.suggestions.length" class="text-sm text-muted-foreground">Nothing notable has been computed for this section yet.</p>

      <template v-else>
        <div class="space-y-3">
          <p v-if="!lists.open.length" class="text-sm text-muted-foreground">No open suggestions. Everything has been dealt with below.</p>
          <ul v-else aria-label="Suggestions" class="space-y-3">
            <NotableCard
              v-for="s in visible"
              :key="s.id"
              :suggestion="s"
              mode="open"
              :disabled="busy"
              @accept="choose(s.id, 'selected')"
              @edit="(h) => choose(s.id, 'selected', { editedHeadline: h })"
              @dismiss="(r) => choose(s.id, 'dismissed', { dismissReason: r ?? undefined })"
            />
          </ul>
          <Button v-if="lists.open.length > TOP_N" variant="outline" size="sm" @click="showAll = !showAll">
            {{ showAll ? `Show top ${TOP_N}` : `Show all (${lists.open.length})` }}
          </Button>
        </div>

        <div class="space-y-3 border-t pt-4">
          <h3 class="text-base font-semibold">Selected for this week</h3>
          <p v-if="!lists.selected.length" class="text-sm text-muted-foreground">Nothing selected yet.</p>
          <template v-else>
            <ul aria-label="Selected items" class="space-y-3">
              <NotableCard
                v-for="s in lists.selected"
                :key="s.id"
                :suggestion="s"
                mode="selected"
                :disabled="busy"
                @edit="(h) => choose(s.id, 'selected', { editedHeadline: h })"
                @restore="restore(s.id)"
              />
            </ul>
            <div class="flex flex-wrap items-center gap-3">
              <Button variant="outline" size="sm" @click="copy"><PhCopy weight="bold" aria-hidden="true" />Copy as text</Button>
              <p v-if="copied === 'done'" role="status" class="text-xs text-muted-foreground">Copied to the clipboard.</p>
            </div>
            <div v-if="copied === 'failed'" class="space-y-1">
              <p role="status" class="text-xs font-medium text-warn-fg">It could not be copied automatically. Select the text below and copy it.</p>
              <textarea
                readonly
                aria-label="Selected items as text"
                rows="6"
                class="w-full rounded-md border border-input bg-card p-2 font-mono text-xs"
                :value="text"
                @focus="($event.target as HTMLTextAreaElement).select()"
              />
            </div>
          </template>
        </div>

        <div v-if="lists.dismissed.length" class="space-y-3 border-t pt-4">
          <Button variant="ghost" size="sm" :aria-expanded="showDismissed" aria-controls="notable-dismissed" @click="showDismissed = !showDismissed">
            <component :is="showDismissed ? PhCaretDown : PhCaretRight" weight="bold" aria-hidden="true" />Dismissed ({{ lists.dismissed.length }})
          </Button>
          <ul v-if="showDismissed" id="notable-dismissed" aria-label="Dismissed items" class="space-y-3">
            <NotableCard v-for="s in lists.dismissed" :key="s.id" :suggestion="s" mode="dismissed" :disabled="busy" @restore="restore(s.id)" />
          </ul>
        </div>
      </template>
    </template>
  </section>
</template>
