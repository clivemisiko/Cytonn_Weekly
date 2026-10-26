<script setup lang="ts">
import { computed, inject, nextTick, onMounted, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { APPROVED_NOTE, OPEN_REVIEW, forgetSlots, lastRecheck, slotsFor } from "@/lib/fixfile";
import { weekOfReview } from "@/lib/notable";
import { shell } from "@/lib/shell";
import type { InputSlot, Review, ReviewItem } from "@/lib/types";
import RedraftDialog from "./RedraftDialog.vue";

/**
 * "Add the missing file" / "Replace the file", on a flagged item whose cause is an input file. The reviewer picks the
 * file (asked which one first when two inputs feed the item, and warned first when the section is approved); the API
 * checks it, re-reads the figures that file feeds and saves a new, undecided review, which then opens in place of this
 * one. The upload and the re-check are one request, so the card says "uploading and re-checking" while it runs.
 */
const props = defineProps<{ review: Review; item: ReviewItem }>();
const openReview = inject(OPEN_REVIEW, null);

type Phase = "idle" | "asking" | "confirming" | "working";
const phase = ref<Phase>("idle");
const chosen = ref("");
const error = ref<string | null>(null);
const picker = ref<HTMLInputElement | null>(null);
const errorEl = ref<HTMLElement | null>(null);
const held = ref<InputSlot[]>([]);

const slots = computed(() => props.item.fix_slots ?? []);
const week = computed(() => weekOfReview(props.review));
// "Replace" only when every input that can fix the item is already there.
const label = computed(() => (slots.value.every((s) => held.value.find((h) => h.slug === s.slug)?.received) ? "Replace the file" : "Add the missing file"));

onMounted(() => {
  if (week.value && slots.value.length) slotsFor(week.value).then((s) => (held.value = s)).catch(() => undefined);
});

function start() {
  error.value = null;
  chosen.value = slots.value.length === 1 ? slots.value[0].slug : "";
  if (slots.value.length > 1) phase.value = "asking";
  else afterSlot();
}

function afterSlot() {
  if (!chosen.value) return;
  if (props.review.decision === "approved") phase.value = "confirming";
  else pick();
}

/** Open the file picker. It is called straight from a click, so the browser allows it. */
function pick() {
  phase.value = "idle";
  const el = picker.value;
  if (!el) return;
  const kind = held.value.find((h) => h.slug === chosen.value)?.kind;
  el.accept = kind === "xlsx" ? ".xlsx" : kind === "pdf" ? ".pdf" : "";
  el.click();
}

async function picked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = ""; // the same file can be chosen again
  if (!file) return;
  phase.value = "working";
  error.value = null;
  try {
    const out = await api.fixFromInput(props.review.run_id, props.item.index, chosen.value, file);
    if (week.value) forgetSlots(week.value);
    lastRecheck.value = { runId: out.review.run_id, result: out.result };
    shell.invalidate(); // the section's newest review is now an undecided one
    void shell.refreshFor(out.review.report_type, out.review.period);
    openReview?.(out.review);
  } catch (err) {
    error.value = (err as Error).message;
    phase.value = "idle";
    await nextTick();
    errorEl.value?.focus();
  }
}
</script>

<template>
  <div v-if="slots.length" class="contents">
    <Button variant="outline" size="sm" :disabled="phase === 'working'" :aria-label="`${label} for ${item.ref}`" @click="start">{{ label }}</Button>
    <span v-if="phase === 'working'" role="status" class="text-xs text-muted-foreground">Uploading and re-checking the figures…</span>

    <fieldset v-if="phase === 'asking'" class="basis-full space-y-1">
      <legend class="text-sm font-medium">Which file is it?</legend>
      <label v-for="s in slots" :key="s.slug" class="flex items-center gap-2 text-sm">
        <input v-model="chosen" type="radio" :name="`fix-slot-${item.index}`" :value="s.slug" class="size-4" />
        {{ s.title }}
      </label>
      <div class="flex gap-2 pt-1">
        <Button size="sm" :disabled="!chosen" @click="afterSlot">Choose the file</Button>
        <Button size="sm" variant="outline" @click="phase = 'idle'">Cancel</Button>
      </div>
    </fieldset>

    <p v-if="error" ref="errorEl" tabindex="-1" role="alert" data-problem class="basis-full text-sm font-medium text-flag-fg [overflow-wrap:anywhere]">{{ error }}</p>

    <input ref="picker" type="file" hidden @change="picked" />
    <RedraftDialog
      :open="phase === 'confirming'"
      title="Check a new file for this section?"
      :notes="[APPROVED_NOTE]"
      confirm-label="Continue"
      @confirm="pick"
      @cancel="phase = 'idle'"
    />
  </div>
</template>
