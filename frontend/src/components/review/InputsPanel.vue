<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { FIELD } from "@/components/ui/button";
import * as api from "@/lib/api";
import { friendlyDate } from "@/lib/format";
import type { WeeklyInputs } from "@/lib/types";
import InputSlot from "./InputSlot.vue";
import Notice from "./Notice.vue";

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
/** The weekday of an ISO date, read as a calendar date (no time zone shift). */
const weekdayOf = (iso: string) => WEEKDAYS[new Date(`${iso}T00:00:00Z`).getUTCDay()];

/**
 * "This week's inputs": the files the analysts send each Friday, uploaded here for one report week. Each file is checked
 * and read by the API before it is kept; this shows what was received, the date read from the file itself, and whether
 * that is this week. Nothing is derived here, and a refused upload shows the API's own reason.
 * The start screen keys this panel on the week, so a new week starts from empty state.
 */
const props = defineProps<{
  /** The Friday the report week ends on (ISO date). */
  week: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{
  /** Choose another week: the report on screen changes with it. */
  week: [weekEnding: string];
  /** After an upload, a removal or a fetch changed what is stored (the analyst inputs form re-reads its prefill). */
  change: [];
}>();

const status = ref<WeeklyInputs | null>(null);
const busy = ref(false);
const error = ref<string | null>(null);
// Files an upload refused, one line each (shown in the same box as `error`).
const refusedFiles = ref<string[]>([]);
const picked = ref(props.week);
const bidding = ref("");
const previous = ref("");
const notFriday = computed(() =>
  picked.value && weekdayOf(picked.value) !== "Friday" ? `${friendlyDate(picked.value)} is a ${weekdayOf(picked.value)}. A weekly report's week ends on a Friday, so choose a Friday.` : null,
);
const locked = computed(() => busy.value || !!props.disabled);
let live = true;
onUnmounted(() => (live = false));

function show(next: WeeklyInputs) {
  status.value = next;
  bidding.value = next.notes.bidding_range ?? "";
  previous.value = next.notes.previous_issue ?? "";
}

onMounted(() => {
  api
    .getInputs(props.week)
    .then((s) => live && show(s))
    .catch((err: Error) => live && (error.value = err.message));
});

/** Run one change against the API and show what it returns; a refusal is shown in the API's words. */
async function act(work: () => Promise<WeeklyInputs>) {
  busy.value = true;
  error.value = null;
  refusedFiles.value = [];
  try {
    show(await work());
    emit("change");
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

const upload = (slot: string, files: File[]) =>
  act(async () => {
    let last: WeeklyInputs | null = null;
    const refused: string[] = [];
    for (const file of files) {
      try {
        last = await api.uploadInput(props.week, slot, file);
        status.value = last;
      } catch (err) {
        refused.push(`${file.name}: ${(err as Error).message}`);
      }
    }
    if (refused.length) setTimeout(() => (refusedFiles.value = refused), 0);
    return last ?? (await api.getInputs(props.week));
  });

const remove = (name: string) => act(() => api.removeInput(props.week, name));
const fetchBulletin = () => act(() => api.fetchBulletin(props.week));

function saveNote(key: "bidding_range" | "previous_issue", value: string) {
  if ((status.value?.notes[key] ?? "") === value.trim()) return;
  void act(() => api.saveInputNotes(props.week, { [key]: value }));
}
</script>

<template>
  <section aria-labelledby="inputs-title" class="space-y-4 rounded-lg border bg-card p-4">
    <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b pb-4">
      <div class="space-y-1">
        <h2 id="inputs-title" class="text-lg font-semibold">This week’s inputs</h2>
        <p class="max-w-[62ch] text-sm text-muted-foreground">
          The workbooks and reports the analysts send each Friday. A part of the section whose input is missing is marked
          unavailable in the draft; no figure is ever filled in.
        </p>
      </div>
      <div class="space-y-1">
        <label for="week-ending" class="eyebrow block">Week ending (a Friday)</label>
        <div class="flex flex-wrap gap-2">
          <input
            id="week-ending"
            v-model="picked"
            type="date"
            :disabled="locked"
            :aria-invalid="notFriday ? true : undefined"
            :aria-describedby="notFriday ? 'week-ending-error' : undefined"
            :class="[FIELD, 'font-mono']"
          />
          <Button variant="outline" :disabled="locked || !picked || !!notFriday || picked === week" @click="emit('week', picked)">Show this week</Button>
        </div>
        <p v-if="notFriday" id="week-ending-error" role="alert" class="text-xs font-medium text-flag-fg">{{ notFriday }}</p>
      </div>
    </div>

    <Notice v-if="error" role="alert" class="font-medium">{{ error }}</Notice>
    <Notice v-if="refusedFiles.length" role="alert" class="font-medium">
      <p>{{ refusedFiles.length === 1 ? "This file was not added:" : `These ${refusedFiles.length} files were not added:` }}</p>
      <ul class="mt-1 list-disc space-y-1 pl-5">
        <li v-for="line in refusedFiles" :key="line">{{ line }}</li>
      </ul>
    </Notice>

    <p v-if="status === null && !error" class="text-sm text-muted-foreground" aria-busy="true">
      Reading what has been received for the week ending <span class="font-mono">{{ friendlyDate(week) }}</span>…
    </p>
    <template v-else-if="status">
      <p class="text-sm">
        Week ending <span class="font-mono font-semibold">{{ friendlyDate(status.week_ending) }}</span>: Monday
        <span class="font-mono">{{ friendlyDate(status.monday) }}</span> to Friday.
      </p>
      <ul>
        <InputSlot
          v-for="slot in status.slots"
          :key="slot.slug"
          :entry="slot"
          :week="status.week_ending"
          :busy="locked"
          @upload="upload"
          @remove="remove"
          @fetch="fetchBulletin"
        />
      </ul>

      <div class="space-y-4 border-t pt-4">
        <div class="space-y-1">
          <label for="bidding-range" class="text-sm font-semibold">T-bond bidding range (the analysts’ recommendation)</label>
          <Textarea
            id="bidding-range"
            v-model="bidding"
            rows="3"
            maxlength="2000"
            :disabled="locked"
            placeholder="e.g. Our recommended bidding range for FXD1/2019/020 is 12.8% - 13.3%…"
            aria-describedby="bidding-range-hint"
            class="py-2"
            @blur="saveNote('bidding_range', bidding)"
          />
          <p id="bidding-range-hint" class="text-xs text-muted-foreground">
            The analysts’ own call, carried as you type it. The tool never proposes a range; left empty, the draft marks
            the range as missing.
          </p>
        </div>
        <div class="space-y-1">
          <label for="previous-issue" class="text-sm font-semibold">Previous issue (optional)</label>
          <input
            id="previous-issue"
            v-model="previous"
            type="text"
            autocomplete="off"
            :disabled="locked"
            placeholder="https://cytonnreport.com/research/…"
            aria-describedby="previous-issue-hint"
            :class="[FIELD, 'w-full']"
            @blur="saveNote('previous_issue', previous)"
          />
          <p id="previous-issue-hint" class="text-xs text-muted-foreground">
            Where the carried-forward paragraphs come from. Left empty, the newest issue published by this Friday is
            used. Carried text is always flagged for you to edit.
          </p>
        </div>
      </div>
    </template>
  </section>
</template>
