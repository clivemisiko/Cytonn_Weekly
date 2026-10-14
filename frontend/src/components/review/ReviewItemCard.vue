<script setup lang="ts">
import { PhArrowSquareOut } from "@phosphor-icons/vue";
import { computed, ref, watch } from "vue";
import Textarea from "@/components/ui/Textarea.vue";
import { KIND_LABELS, RESOLUTION_CHIPS, STATUS_META, pyRepr, resolutionKey } from "@/lib/format";
import type { Flag, Resolution, ReviewItem } from "@/lib/types";
import ResolutionControl from "./ResolutionControl.vue";

const CHIP_STYLE = {
  none: "border-border text-muted-foreground",
  accept: "border-ok/40 bg-ok/10 text-ok-fg",
  fix_needed: "border-flag/40 bg-flag/10 text-flag-fg",
} as const;

/** One review item: its status, what the checker found, and the coordinator's resolution and note. */
const props = defineProps<{
  item: ReviewItem;
  locked: boolean;
  onResolve: (index: number, resolution: Resolution, note?: string) => Promise<boolean>;
}>();

const meta = computed(() => STATUS_META[props.item.status]);
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
const inputs = computed(() => Object.entries(ctx.value.inputs ?? {}));
const cells = (flag: Flag): [string, string][] => [
  ["Drafted", pyRepr(flag.drafted)],
  ["Expected (normalized source)", flag.expected ?? "None"],
  ["Source value", pyRepr(flag.source_value)],
];
</script>

<template>
  <li class="surface-state space-y-3 p-4" :class="`state-${item.status}`" :data-status="item.status" :data-index="item.index">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span
        class="inline-flex items-center gap-1 rounded-full border py-0.5 pr-2 pl-0.5 text-xs font-semibold whitespace-nowrap text-(--hue-fg)"
        :class="item.status === 'not_auto_verified' && 'border-dashed'"
        :style="{ borderColor: 'color-mix(in srgb, var(--hue) 55%, transparent)', background: 'color-mix(in srgb, var(--hue) 10%, transparent)' }"
      >
        <span class="glyph size-4 text-xs" aria-hidden="true">{{ meta.glyph }}</span>
        {{ meta.label }}
      </span>
      <span class="text-sm font-semibold">{{ item.ref }}</span>
      <span class="text-xs text-muted-foreground">{{ KIND_LABELS[item.kind] ?? item.kind }}</span>
      <span class="relative ml-auto">
        <span class="block rounded-sm border px-2 py-0.5 text-xs font-medium" :class="CHIP_STYLE[chipKey]">{{ RESOLUTION_CHIPS[chipKey] }}</span>
      </span>
    </div>

    <div v-if="hasDetail" class="space-y-3">
      <div v-for="(flag, i) in flags" :key="i" class="space-y-2">
        <!-- A web link in supplied text: the message names it in plain text (never a link to click); a possible one is softer. -->
        <p v-if="flag.kind === 'link' || flag.kind === 'possible_link'" class="text-sm font-medium [overflow-wrap:anywhere]" :class="flag.kind === 'link' ? 'text-flag-fg' : 'text-warn-fg'">
          {{ flag.message }}
        </p>
        <p v-else class="text-sm">
          <strong class="font-semibold text-flag-fg">{{ flag.kind }}</strong><span class="text-muted-foreground"> in </span>{{ flag.message }}
        </p>
        <dl v-if="flag.drafted !== null || flag.expected !== null" class="grid gap-2 sm:grid-cols-3">
          <div v-for="[k, v] in cells(flag)" :key="k" class="min-w-0 rounded-sm border bg-card px-3 py-2">
            <dt class="text-xs text-muted-foreground">{{ k }}</dt>
            <dd class="mt-1 font-mono text-sm font-medium [overflow-wrap:anywhere]">{{ v }}</dd>
          </div>
        </dl>
        <ul v-if="flag.sources.length > 0" class="space-y-1 text-xs text-muted-foreground">
          <li v-for="s in flag.sources" :key="s.source">
            {{ s.source }}: <span class="font-mono">{{ String(s.value) }}</span> (normalized <span class="font-mono">{{ String(s.normalized) }}</span
            >)
          </li>
        </ul>
      </div>
      <blockquote v-if="ctx.text" class="border-l-2 border-input pl-3 text-sm text-foreground/85">{{ ctx.text }}</blockquote>
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
            <span class="font-mono font-medium">{{ String(input.value) }}</span>{{ " " }}<span class="text-muted-foreground">
              {{ input.origin === "ocr" ? "read by OCR from " : "" }}{{ input.source }}{{ input.second ? `; also ${String(input.second.value)} in ${input.second.source}` : "" }}
            </span>
          </li>
          <li v-if="inputs.length > 12" class="text-muted-foreground">and {{ inputs.length - 12 }} more inputs of the same kind.</li>
        </ul>
        <p v-if="ctx.note" class="text-xs text-muted-foreground">{{ ctx.note }}</p>
      </div>
      <p v-if="item.status === 'not_auto_verified' && typeof item.detail === 'string'" class="text-xs whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{{ item.detail }}</p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <ResolutionControl :label="item.ref" :value="shown" :disabled="locked" @change="(next) => send(next)" />
      <Textarea
        v-model="note"
        rows="1"
        :name="`note-${item.index}`"
        autocomplete="off"
        :readonly="locked"
        :aria-label="`Note for ${item.ref}`"
        placeholder="Add a note (optional)…"
        maxlength="2000"
        class="min-w-48 flex-1 resize-none text-sm md:text-sm"
        :class="locked && 'bg-muted text-muted-foreground'"
        @input="dirty = true"
        @blur="commitNote"
        @keydown="noteKey"
      />
    </div>
  </li>
</template>
