<script setup lang="ts">
import { PhCheck, PhCloudArrowDown, PhQuestion, PhTrash, PhUploadSimple } from "@phosphor-icons/vue";
import { computed, useTemplateRef } from "vue";
import Button from "@/components/ui/Button.vue";
import { LINK } from "@/components/ui/button";
import { friendlyDate } from "@/lib/format";
import type { InputSlot as InputSlotInfo } from "@/lib/types";
import ToneChip from "./ToneChip.vue";

/** One input of the week: what was received for it, the date read from the file itself, and its upload control. */
const props = defineProps<{ entry: InputSlotInfo; week: string; busy: boolean }>();
const emit = defineEmits<{ upload: [slot: string, files: File[]]; remove: [storedName: string]; fetch: [] }>();

const picker = useTemplateRef<HTMLInputElement>("picker");
const file = computed(() => props.entry.file ?? null);
const days = computed(() => props.entry.days ?? []);
const got = computed(() => days.value.filter((d) => d.received).length);
const tone = computed<"ok" | "warn" | "none">(() =>
  props.entry.per_day
    ? got.value === days.value.length
      ? "ok"
      : got.value > 0
        ? "warn"
        : "none"
    : file.value
      ? file.value.matches
        ? "ok"
        : "warn"
      : "none",
);
const label = computed(() =>
  props.entry.per_day
    ? `${got.value} of ${days.value.length} received`
    : file.value
      ? file.value.matches
        ? "Received, this week’s"
        : props.entry.slug === "nse_yield_curve"
          ? "Received, dated outside this week"
          : "Received, not this week’s"
      : props.entry.optional
        ? "Not received (optional)"
        : "Not received",
);
const megabytes = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;

function picked(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = ""; // the same file can be chosen again after a refusal
  if (files.length) emit("upload", props.entry.slug, files);
}
</script>

<template>
  <li class="space-y-2 border-t py-4 first:border-t-0 first:pt-0">
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="min-w-0 space-y-1">
        <p class="flex flex-wrap items-center gap-2 text-sm font-semibold">
          {{ entry.title }}
          <ToneChip :tone="tone">{{ label }}</ToneChip>
        </p>
        <p class="text-xs text-muted-foreground">{{ entry.help }}</p>
      </div>
      <div class="flex shrink-0 flex-wrap gap-2">
        <Button v-if="entry.fetchable && !file" variant="outline" size="sm" :disabled="busy" @click="emit('fetch')">
          <PhCloudArrowDown weight="bold" data-icon="inline-start" aria-hidden="true" />
          Fetch from CBK
        </Button>
        <input
          ref="picker"
          type="file"
          :accept="entry.kind === 'pdf' ? '.pdf,application/pdf' : '.xlsx'"
          :multiple="entry.per_day"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="picked"
        />
        <Button variant="outline" size="sm" :disabled="busy" @click="picker?.click()">
          <PhUploadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
          {{ entry.per_day ? "Upload reports" : file ? "Replace" : "Upload" }}<span class="sr-only">: {{ entry.title }}</span>
        </Button>
      </div>
    </div>
    <template v-if="file">
      <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span class="font-mono [overflow-wrap:anywhere]">{{ file.original_name || file.stored_name }}</span>
        <span aria-hidden="true">·</span>
        <span>dated <span class="font-mono">{{ file.read_date ? friendlyDate(file.read_date) : "unread" }}</span></span>
        <span aria-hidden="true">·</span>
        <span class="font-mono">{{ megabytes(file.size) }}</span>
        <template v-if="file.fetched_from">
          <span aria-hidden="true">·</span>
          <span>fetched from CBK</span>
        </template>
        <button
          type="button"
          :disabled="busy"
          :aria-label="`Remove ${file.original_name || file.stored_name}`"
          :class="['inline-flex items-center gap-1 disabled:opacity-50', LINK]"
          @click="emit('remove', file.stored_name)"
        >
          <PhTrash weight="bold" class="size-3" aria-hidden="true" />
          Remove
        </button>
      </p>
      <p v-if="!file.matches && file.read_date" class="text-xs font-medium text-warn-fg">
        The file itself is dated {{ friendlyDate(file.read_date) }}; this week ends {{ friendlyDate(week) }}.{{
          entry.slug === "nse_yield_curve" ? " It is still shown as context, with its own date." : " Figures it does not hold for this week are left out."
        }}
      </p>
      <p v-if="file.note" class="text-xs text-warn-fg">{{ file.note }}</p>
    </template>
    <ul v-if="entry.per_day" class="grid gap-2 sm:grid-cols-5">
      <li
        v-for="d in days"
        :key="d.date"
        class="space-y-1 rounded-md border px-2 py-2 text-xs"
        :class="d.received ? 'border-ok/40 bg-ok/10' : 'border-dashed border-input'"
      >
        <p class="flex items-center justify-between gap-1 font-semibold">
          {{ d.weekday }}
          <PhCheck v-if="d.received" weight="bold" class="size-3 text-ok-fg" aria-hidden="true" />
          <PhQuestion v-else weight="bold" class="size-3 text-muted-foreground" aria-hidden="true" />
        </p>
        <p class="font-mono text-muted-foreground">{{ friendlyDate(d.date) }}</p>
        <button v-if="d.received && d.file" type="button" :disabled="busy" :class="['disabled:opacity-50', LINK]" @click="emit('remove', d.file.stored_name)">
          Remove<span class="sr-only"> {{ d.weekday }}’s report</span>
        </button>
        <p v-else class="text-muted-foreground">Missing</p>
      </li>
    </ul>
  </li>
</template>
