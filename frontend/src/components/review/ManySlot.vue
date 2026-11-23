<script setup lang="ts">
import { PhTrash, PhUploadSimple } from "@phosphor-icons/vue";
import { computed } from "vue";
import Button from "@/components/ui/Button.vue";
import { buttonVariants } from "@/components/ui/button";
import { bankRows } from "@/lib/slotguess";
import type { InputSlot } from "@/lib/types";
import BatchDropzone from "./BatchDropzone.vue";
import Notice from "./Notice.vue";
import ToneChip from "./ToneChip.vue";

const props = defineProps<{ entry: InputSlot; busy: boolean; refused: { name: string; reason: string }[] }>();
const emit = defineEmits<{ upload: [files: File[]]; remove: [storedName: string] }>();
const rows = computed(() => bankRows(props.entry.files ?? [], props.refused));
const replaced = computed(() => (props.entry.files ?? []).filter((f) => f.read?.replaced).map((f) => `${f.read!.bank}: replaced ${f.read!.replaced}`));
const headingId = computed(() => `many-${props.entry.slug}`);

function picked(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  if (files.length) emit("upload", files);
}
</script>

<template>
  <li class="space-y-3 border-t py-4 first:border-t-0 first:pt-0 list-none" :aria-labelledby="headingId" :data-slot="entry.slug">
    <div class="space-y-1">
      <p :id="headingId" class="flex flex-wrap items-center gap-2 text-sm font-semibold">
        {{ entry.title }}
        <ToneChip :tone="rows.some((r) => r.stored) ? 'ok' : 'none'">{{ entry.files?.length ? `${entry.files.length} received (optional)` : "Not received (optional)" }}</ToneChip>
      </p>
      <p class="text-xs text-muted-foreground">{{ entry.help }}</p>
    </div>
    <BatchDropzone title="Drop several banks' statement PDFs at once" hint="Each file is read when it arrives; a refused file is listed with the reason and nothing of it is kept." @files="(f) => emit('upload', f)">
      <label :class="[buttonVariants({ variant: 'outline' }), 'mt-1 min-h-11 cursor-pointer has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50']">
        <input type="file" multiple accept=".pdf" :disabled="busy" :aria-label="`Upload ${entry.title}`" class="sr-only" @change="picked" />
        <PhUploadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
        <span aria-hidden="true">{{ busy ? "Uploading…" : "Choose files" }}</span>
      </label>
    </BatchDropzone>
    <Notice v-if="entry.warning" tone="warn" role="status">{{ entry.warning }}</Notice>
    <p v-if="replaced.length" role="status" class="text-xs">{{ replaced.join(". ") }}.</p>
    <ul v-if="rows.length" class="divide-y rounded-lg border text-sm" :aria-label="`${entry.title}: files`">
      <li v-for="r in rows" :key="r.key" class="flex flex-wrap items-start justify-between gap-2 p-3" :data-bank-row="r.stored ?? 'refused'">
        <div class="min-w-0 space-y-0.5">
          <p class="font-medium [overflow-wrap:anywhere]">{{ r.bank }}</p>
          <p v-if="r.period" class="text-xs text-muted-foreground">{{ r.period }}</p>
          <p class="flex flex-wrap items-center gap-2"><ToneChip :tone="r.tone === 'bad' ? 'warn' : r.tone">{{ r.tone === "bad" ? "Refused" : r.status }}</ToneChip></p>
          <p v-if="r.tone === 'bad'" class="text-xs [overflow-wrap:anywhere]">{{ r.status }}</p>
          <details v-if="r.flags.length" class="text-xs">
            <summary class="cursor-pointer">The {{ r.flags.length }} {{ r.flags.length === 1 ? "flag" : "flags" }}</summary>
            <ul class="mt-1 list-disc pl-5">
              <li v-for="(f, i) in r.flags" :key="i">{{ f }}</li>
            </ul>
          </details>
        </div>
        <div v-if="r.stored" class="flex gap-2">
          <label :class="[buttonVariants({ variant: 'outline' }), 'min-h-11 cursor-pointer has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50']">
            <input type="file" accept=".pdf" :disabled="busy" :aria-label="`Replace ${r.bank}`" class="sr-only" @change="picked" />
            <span aria-hidden="true">Replace</span>
          </label>
          <Button variant="outline" class="min-h-11" :disabled="busy" :aria-label="`Remove ${r.bank}`" @click="emit('remove', r.stored)">
            <PhTrash weight="bold" data-icon="inline-start" aria-hidden="true" />Remove
          </Button>
        </div>
      </li>
    </ul>
  </li>
</template>
