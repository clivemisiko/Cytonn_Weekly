<script setup lang="ts">
import { PhTrash, PhUploadSimple } from "@phosphor-icons/vue";
import { ref, useTemplateRef, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import { FIELD, LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { ChartUpload } from "@/lib/types";
import ToneChip from "./ToneChip.vue";

const props = defineProps<{ entry: ChartUpload; week: string; busy: boolean; version: number }>();
const emit = defineEmits<{ upload: [key: string, file: File]; remove: [key: string]; leadIn: [key: string, text: string] }>();

const picker = useTemplateRef<HTMLInputElement>("picker");
const leadIn = ref(props.entry.lead_in);
watch(() => props.entry.lead_in, (next) => (leadIn.value = next));
const megabytes = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;

function picked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = ""; // the same file can be chosen again after a refusal
  if (file) emit("upload", props.entry.key, file);
}

function saveLeadIn() {
  if (leadIn.value.trim() !== props.entry.lead_in) emit("leadIn", props.entry.key, leadIn.value);
}
</script>

<template>
  <li class="space-y-2 border-t py-4 first:border-t-0 first:pt-0">
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <p class="flex flex-wrap items-center gap-2 text-sm font-semibold">
        {{ entry.title }}
        <ToneChip :tone="entry.has_image ? 'ok' : 'none'">{{ entry.has_image ? "Image added" : "No image" }}</ToneChip>
      </p>
      <div class="flex shrink-0 flex-wrap gap-2">
        <input
          ref="picker"
          type="file"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          @change="picked"
        />
        <Button variant="outline" size="sm" :disabled="busy" @click="picker?.click()">
          <PhUploadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
          {{ entry.has_image ? "Replace" : "Choose image" }}<span class="sr-only">: {{ entry.title }}</span>
        </Button>
      </div>
    </div>
    <div v-if="entry.has_image" class="flex flex-wrap items-end gap-3">
      <img
        :src="api.chartUploadUrl(week, entry.key, `${version}-${entry.size}`)"
        :alt="`The image added for ${entry.title}`"
        class="h-16 w-auto max-w-40 rounded-sm border bg-white object-contain"
      />
      <p class="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <span class="font-mono">{{ entry.type === "jpeg" ? "JPEG" : "PNG" }}, {{ megabytes(entry.size ?? 0) }}</span>
        <button
          type="button"
          :disabled="busy"
          :aria-label="`Remove the image for ${entry.title}`"
          :class="['inline-flex items-center gap-1 disabled:opacity-50', LINK]"
          @click="emit('remove', entry.key)"
        >
          <PhTrash weight="bold" class="size-3" aria-hidden="true" />
          Remove
        </button>
      </p>
    </div>
    <div class="space-y-1">
      <label :for="`lead-in-${entry.key}`" class="text-xs font-semibold">Sentence above the chart</label>
      <input
        :id="`lead-in-${entry.key}`"
        v-model="leadIn"
        type="text"
        autocomplete="off"
        maxlength="600"
        :disabled="busy"
        :placeholder="entry.default_lead_in"
        :class="[FIELD, 'w-full']"
        @blur="saveLeadIn"
      />
    </div>
  </li>
</template>
