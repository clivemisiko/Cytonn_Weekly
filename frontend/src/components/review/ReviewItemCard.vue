<script setup lang="ts">
import { PhArrowSquareOut, PhCaretDown, PhPencilSimple } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, ref, watch } from "vue";
import Textarea from "@/components/ui/Textarea.vue";
import { KIND_LABELS, friendlyTime, pyRepr, resolutionKey } from "@/lib/format";
import type { Flag, Resolution, Review, ReviewItem } from "@/lib/types";
import EditSentence from "./EditSentence.vue";
import FixFromFile from "./FixFromFile.vue";
import ResolutionControl from "./ResolutionControl.vue";
import SeverityPill from "./SeverityPill.vue";
import TextWithIds from "./TextWithIds.vue";

const props = defineProps<{
  item: ReviewItem;
  /** The review the item is in: the fix-from-a-file control needs its week, run and decision. */
  review: Review;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
}>();

// Collapsed: the evidence (what the checker found, the quote, the working) is hidden; the title, pill, a one-line summary and
// the resolution controls stay, so triage needs no expansion.  ItemsPane's Expand all / Collapse all drive this.
const open = defineModel<boolean>("open", { default: false });
const serverNote = computed(() => props.item.resolution_note ?? "");

// What the control shows while its write is in flight, so a click answers at once.  Writes are
// queued in order; only the newest write's completion clears this, so rapid clicks do not flicker.
const pending = ref<Resolution | undefined>(undefined);
let latest = 0;
const shown = computed(() => (pending.value !== undefined ? pending.value : props.item.resolution));

// The note box is the coordinator's own until it is committed; a server refresh must not overwrite typing.
const note = ref(serverNote.value);
const dirty = ref(false);
watch(serverNote, (next) => {
  if (!dirty.value) note.value = next;
});
watch(dirty, (now, _before, onCleanup) => {
  if (!now) return;
  const warn = (e: BeforeUnloadEvent) => e.preventDefault(); // a typed note is only saved when the box is left
  window.addEventListener("beforeunload", warn);
  onCleanup(() => window.removeEventListener("beforeunload", warn));
});

function send(next: Resolution, withNote?: string) {
  const mine = ++latest;
  pending.value = next;
  void props.onResolve(props.item.index, next, withNote).finally(() => {
    if (latest === mine) pending.value = undefined;
  });
}

function commitNote() {
  if (!dirty.value) return;
  dirty.value = false;
  if (note.value.trim() === serverNote.value.trim()) return;
  send(shown.value, note.value);
}

function noteKey(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    (event.currentTarget as HTMLTextAreaElement).blur(); // commit through blur
  }
}

const chipKey = computed(() => resolutionKey(shown.value));
const ctx = computed(() => props.item.context);
const hasDetail = computed(() => props.item.status === "flagged" || props.item.status === "not_auto_verified" || Object.keys(ctx.value).length > 0);
const safeUrl = computed(() => (ctx.value.url && /^https?:\/\//.test(ctx.value.url) ? ctx.value.url : null));
const flags = computed<Flag[]>(() => (props.item.status === "flagged" && Array.isArray(props.item.detail) ? props.item.detail : []));
const summary = computed(() => {
  const first = flags.value[0]?.message ?? (typeof props.item.detail === "string" ? props.item.detail : "") ?? "";
  return (first || ctx.value.text || "").trim();
});
const detailText = computed(() => (typeof props.item.detail === "string" ? props.item.detail : ""));
const inputs = computed(() => Object.entries(ctx.value.inputs ?? {}));
const cells = (flag: Flag): [string, string][] => [
  ["Drafted", pyRepr(flag.drafted)],
  ["Expected (normalized source)", flag.expected ?? "None"],
  ["Source value", pyRepr(flag.source_value)],
];
</script>

<template>
  <li class="surface-state rise-in @container space-y-3 p-3 transition-shadow duration-200 hover:shadow-md" :class="`state-${item.status}`" :data-status="item.status" :data-index="item.index">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <SeverityPill :kind="item.status" />
      <span class="text-sm font-semibold">{{ item.ref }}</span>
      <span class="text-xs text-muted-foreground">{{ KIND_LABELS[item.kind] ?? item.kind }}</span>
      <span v-if="ctx.edited_at" class="inline-flex items-center gap-1 text-xs font-medium">
        <PhPencilSimple weight="bold" class="size-3.5" aria-hidden="true" />Edited by you, {{ friendlyTime(ctx.edited_at) }}
      </span>
      <span v-else-if="ctx.removed_at" class="inline-flex items-center gap-1 text-xs font-medium">
        <PhPencilSimple weight="bold" class="size-3.5" aria-hidden="true" />Removed by you, {{ friendlyTime(ctx.removed_at) }}
      </span>
      <span class="ml-auto"><SeverityPill :kind="chipKey" /></span>
    </div>

    <CollapsibleRoot v-if="hasDetail" v-model:open="open">
      <CollapsibleTrigger class="flex w-full items-center gap-2 rounded-sm text-left text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
        <span class="min-w-0 flex-1 truncate">{{ summary || "Show the evidence" }}</span>
        <span class="shrink-0 font-medium">{{ open ? "Hide" : "Show" }} details</span>
        <PhCaretDown weight="bold" aria-hidden="true" class="size-4 shrink-0 transition-transform duration-200" :class="open && 'rotate-180'" />
      </CollapsibleTrigger>
      <CollapsibleContent class="collapsible overflow-hidden">
    <div class="space-y-3 pt-3">
      <div v-for="(flag, i) in flags" :key="i" class="space-y-2">
        <!-- A web link in supplied text: the message names it in plain text (never a link to click); a possible one is softer. -->
        <p v-if="flag.kind === 'link' || flag.kind === 'possible_link'" class="text-sm font-medium [overflow-wrap:anywhere]" :class="flag.kind === 'link' ? 'text-flag-fg' : 'text-warn-fg'">
          {{ flag.message }}
        </p>
        <dl v-else class="grid gap-x-3 gap-y-1 text-sm @min-[28rem]:grid-cols-[6rem_1fr]">
          <dt class="eyebrow">Issue</dt>
          <dd class="font-semibold text-flag-fg">{{ flag.kind }}</dd>
          <dt class="eyebrow">Row</dt>
          <dd class="min-w-0"><TextWithIds :text="flag.subject" /></dd>
          <template v-if="flag.field">
            <dt class="eyebrow">Field</dt>
            <dd class="min-w-0"><TextWithIds :text="flag.field" /></dd>
          </template>
          <dt class="eyebrow">Reason</dt>
          <dd class="min-w-0"><TextWithIds :text="flag.message" /></dd>
        </dl>
        <dl v-if="flag.drafted !== null || flag.expected !== null" class="grid gap-2 @min-[34rem]:grid-cols-3">
          <div v-for="[k, v] in cells(flag)" :key="k" class="min-w-0 rounded-sm border bg-card px-3 py-2">
            <dt class="text-xs text-muted-foreground">{{ k }}</dt>
            <dd class="mt-1 text-sm font-medium [overflow-wrap:anywhere]">{{ v }}</dd>
          </div>
        </dl>
        <ul v-if="flag.sources.length > 0" class="space-y-1 text-xs text-muted-foreground">
          <li v-for="s in flag.sources" :key="s.source">
            <TextWithIds :text="s.source" />: <span>{{ String(s.value) }}</span> (normalized <span>{{ String(s.normalized) }}</span
            >)
          </li>
        </ul>
      </div>
      <blockquote v-if="ctx.text" class="border-l-2 border-input pl-3 text-sm text-foreground/85">{{ ctx.text }}</blockquote>
      <p v-if="ctx.edited_at" class="text-xs text-muted-foreground [overflow-wrap:anywhere]">
        Your wording replaced: "{{ ctx.was }}". The source below was cited for the earlier wording, so read it to check that it supports yours.
      </p>
      <p v-if="safeUrl" class="text-sm">
        Source:
        <a :href="safeUrl" target="_blank" rel="noopener noreferrer" class="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">
          {{ ctx.title || safeUrl }}<PhArrowSquareOut weight="bold" class="ml-1 inline size-4 align-[-3px]" aria-hidden="true" />
        </a>
      </p>
      <p v-if="ctx.cited_text" class="text-xs text-muted-foreground">Cited text: “{{ ctx.cited_text }}”</p>
      <div v-if="inputs.length > 0" class="space-y-1">
        <p class="eyebrow">Worked out from</p>
        <ul class="space-y-1 text-xs">
          <li v-for="[name, input] in inputs.slice(0, 12)" :key="name" class="[overflow-wrap:anywhere]">
            <span class="font-medium">{{ String(input.value) }}</span>{{ " " }}<span class="text-muted-foreground">
              {{ input.origin === "ocr" ? "read by OCR from " : "" }}{{ input.source }}{{ input.second ? `; also ${String(input.second.value)} in ${input.second.source}` : "" }}
            </span>
          </li>
          <li v-if="inputs.length > 12" class="text-muted-foreground">and {{ inputs.length - 12 }} more inputs of the same kind.</li>
        </ul>
      </div>
      <p v-if="ctx.note && ctx.note !== detailText" data-testid="item-note" class="text-xs whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{{ ctx.note }}</p>
      <p v-if="detailText" data-testid="item-detail" class="text-xs whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]"><TextWithIds :text="detailText" /></p>
    </div>
      </CollapsibleContent>
    </CollapsibleRoot>

    <div class="flex flex-wrap items-center gap-2">
      <ResolutionControl :label="item.ref" :value="shown" :disabled="locked" @change="(next) => send(next)" />
      <FixFromFile :review="review" :item="item" />
      <EditSentence :review="review" :item="item" />
      <Textarea
        v-model="note"
        rows="1"
        :name="`note-${item.index}`"
        autocomplete="off"
        :readonly="locked"
        :aria-label="`Note for ${item.ref}`"
        placeholder="Add a note (optional)…"
        maxlength="2000"
        class="min-w-48 flex-1 resize-none text-sm"
        :class="locked && 'bg-muted text-muted-foreground'"
        @input="dirty = true"
        @blur="commitNote"
        @keydown="noteKey"
      />
    </div>
  </li>
</template>
