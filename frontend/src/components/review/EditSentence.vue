<script setup lang="ts">
import { computed, inject, nextTick, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import * as api from "@/lib/api";
import { OPEN_REVIEW } from "@/lib/fixfile";
import { APPROVED_SENTENCE_NOTE, MAX_PARAGRAPH, MAX_SENTENCE, lastSentence, sentenceCheck } from "@/lib/sentence";
import { shell } from "@/lib/shell";
import type { Review, ReviewItem } from "@/lib/types";
import RedraftDialog from "./RedraftDialog.vue";

const props = defineProps<{ review: Review; item: ReviewItem }>();
const openReview = inject(OPEN_REVIEW, null);

type Phase = "idle" | "editing" | "confirming" | "working";
const phase = ref<Phase>("idle");
const action = ref<"edit" | "remove" | "paragraph">("edit");
const text = ref("");
const error = ref<string | null>(null);
const errorEl = ref<HTMLElement | null>(null);

const paragraph = computed(() => !!props.item.edit_paragraph);
const noun = computed(() => (paragraph.value ? "paragraph" : "sentence"));
const limit = computed(() => (paragraph.value ? MAX_PARAGRAPH : MAX_SENTENCE));
const original = computed(() => props.item.context.text ?? "");
const check = computed(() => sentenceCheck(text.value, original.value, limit.value));
const boxId = computed(() => `edit-sentence-${props.item.index}`);
const approved = computed(() => props.review.decision === "approved");

async function startEdit() {
  error.value = null;
  text.value = original.value;
  phase.value = "editing";
  await nextTick();
  document.getElementById(boxId.value)?.focus();
}

function cancel() {
  phase.value = "idle";
  error.value = null;
}

function ask(next: "edit" | "remove") {
  action.value = next === "edit" && paragraph.value ? "paragraph" : next;
  if (approved.value) phase.value = "confirming";
  else void send();
}

async function send() {
  const kind = action.value;
  phase.value = "working";
  error.value = null;
  try {
    const out = await api.changeSentence(props.review.run_id, props.item.index, kind, kind === "remove" ? undefined : text.value);
    lastSentence.value = { runId: out.review.run_id, result: out.result };
    shell.invalidate(); // the section's newest review is now an undecided one
    void shell.refreshFor(out.review.report_type, out.review.period);
    openReview?.(out.review);
  } catch (err) {
    error.value = (err as Error).message;
    phase.value = kind === "remove" ? "idle" : "editing";
    await nextTick();
    errorEl.value?.focus();
  }
}
</script>

<template>
  <div v-if="item.edit_sentence || item.edit_paragraph" class="contents">
    <Button variant="outline" size="sm" :disabled="phase === 'working'" :aria-label="`Edit this ${noun}: ${item.ref}`" @click="startEdit">Edit this {{ noun }}</Button>
    <Button v-if="!paragraph" variant="outline" size="sm" :disabled="phase === 'working'" :aria-label="`Remove this sentence: ${item.ref}`" @click="ask('remove')">Remove this sentence</Button>
    <span v-if="phase === 'working'" role="status" class="text-xs text-muted-foreground">
      {{ paragraph ? "Saving a new version…" : "Checking the figures and saving a new version…" }}
    </span>

    <form v-if="phase === 'editing'" class="basis-full space-y-2" @submit.prevent="ask('edit')">
      <label :for="boxId" class="block text-sm font-medium">Your {{ noun }}</label>
      <p v-if="paragraph" :id="`${boxId}-help`" class="text-xs text-muted-foreground">
        Plain text only: no links or formatting, and line breaks become spaces, so a list becomes one paragraph. Saving creates a new version of the
        section; this one stays saved. The checker has no source for what you write, so you must read every figure in it against its source by hand.
      </p>
      <p v-else :id="`${boxId}-help`" class="text-xs text-muted-foreground">
        Plain text only: no links or formatting. Saving creates a new version of the section; this one stays saved. A figure that is not in the source
        cited for the earlier wording stays flagged, and you can then accept it knowingly.
      </p>
      <Textarea :id="boxId" v-model="text" :rows="paragraph ? '8' : '3'" autocomplete="off" :aria-describedby="`${boxId}-help ${boxId}-count`" :aria-invalid="check.over > 0" class="resize-y" />
      <p :id="`${boxId}-count`" class="text-xs" :class="check.over ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
        {{ check.length }} of {{ limit }} characters<template v-if="check.over">. Over the limit by {{ check.over }} {{ check.over === 1 ? "character" : "characters" }}.</template>
      </p>
      <p v-if="check.same && !check.empty" class="text-xs text-muted-foreground">Change the {{ noun }} to save it.</p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm" :disabled="!check.ok">Save as a new version</Button>
        <Button size="sm" variant="outline" @click="cancel">Cancel</Button>
      </div>
    </form>

    <p v-if="error" ref="errorEl" tabindex="-1" role="alert" data-problem class="basis-full text-sm font-medium text-flag-fg [overflow-wrap:anywhere]">{{ error }}</p>

    <RedraftDialog
      :open="phase === 'confirming'"
      :title="action === 'remove' ? 'Remove this sentence?' : `Save your ${noun} as a new version?`"
      :notes="[APPROVED_SENTENCE_NOTE]"
      :confirm-label="action === 'remove' ? 'Remove the sentence' : 'Save a new version'"
      @confirm="send"
      @cancel="phase = action === 'remove' ? 'idle' : 'editing'"
    />
  </div>
</template>
