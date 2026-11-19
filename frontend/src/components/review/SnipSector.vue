<script setup lang="ts">
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import * as api from "@/lib/api";
import { friendlyTime } from "@/lib/format";
import { hasUnclear, snipStatus } from "@/lib/snips";
import { hashPrefix } from "@/lib/sources";
import type { SnipMeta } from "@/lib/types";
import type { Snips } from "@/lib/usesnips";

const props = defineProps<{ sec: { id: string; label: string; snips: SnipMeta[] }; snips: Snips; week: string; disabled: boolean }>();
// The page's one snip store: its refs are unwrapped here so the markup reads as it did in SnipsPanel.
const { listing, drafts, busy, uploading, upload, read, move, setDate, confirm, remove } = props.snips;
</script>

<template>
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 class="text-sm font-semibold">{{ sec.label }}</h3>
      <span class="font-mono text-xs text-muted-foreground">{{ sec.snips.length }} of {{ listing?.max_per_sector }}</span>
    </div>
    <div>
      <label :for="`snip-file-${sec.id}`" class="text-xs text-muted-foreground">Add a snip or a PDF for {{ sec.label }}</label>
      <input
        :id="`snip-file-${sec.id}`"
        type="file"
        multiple
        accept="image/png,image/jpeg,image/webp,application/pdf"
        :disabled="disabled || uploading || sec.snips.length >= (listing?.max_per_sector ?? 6)"
        class="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-card file:px-3 file:py-1 file:text-sm"
        @change="(e) => { const t = e.target as HTMLInputElement; void upload(sec.id, t.files).then(() => (t.value = '')); }"
      />
    </div>
    <p v-if="!sec.snips.length" class="text-sm text-muted-foreground">No snip yet. This sector will say “not included” unless one is confirmed.</p>
    <ul v-if="sec.snips.length" class="space-y-4" :aria-label="`${sec.label} snips`">
      <li v-for="s in sec.snips" :key="s.hash" class="grid gap-3 rounded-lg border p-3 md:grid-cols-2">
        <dl v-if="s.kind === 'pdf'" class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 self-start rounded-md border p-3 text-xs">
          <dt class="text-muted-foreground">PDF</dt>
          <dd><a :href="api.snipImageUrl(week, s.hash)" download class="break-all font-mono underline">{{ s.filename }}</a></dd>
          <dt class="text-muted-foreground">Pages</dt>
          <dd>{{ s.pages }}</dd>
          <dt class="text-muted-foreground">Size</dt>
          <dd>{{ ((s.size ?? 0) / 1048576).toFixed(1) }} MB</dd>
          <dt class="text-muted-foreground">Uploaded</dt>
          <dd>{{ s.uploaded_at ? friendlyTime(s.uploaded_at) : "" }}</dd>
          <dt class="text-muted-foreground">Fingerprint</dt>
          <dd class="font-mono">{{ hashPrefix(s.file_sha ?? "") }}</dd>
        </dl>
        <a v-else :href="api.snipImageUrl(week, s.hash)" target="_blank" rel="noopener" class="block self-start">
          <img :src="api.snipImageUrl(week, s.hash)" :alt="`Snip ${s.filename}`" class="max-h-72 w-full rounded-md border object-contain" loading="lazy" />
        </a>
        <div class="space-y-2">
          <p class="flex flex-wrap items-center gap-2 text-xs">
            <span class="break-all font-mono">{{ s.filename }}</span>
            <span :class="s.confirmed ? 'font-semibold text-ok-fg' : 'font-semibold text-warn-fg'" role="status">
              {{ busy[s.hash] ?? snipStatus(s, drafts[s.hash]) }}
            </span>
          </p>
          <template v-if="s.kind === 'pdf' && s.text !== null">
            <p v-if="!s.passages?.length" class="text-sm">
              No passage about {{ sec.label }} was found in this PDF, so there is nothing to confirm. Remove it, or upload it under the sector it covers.
            </p>
            <template v-else>
              <p class="text-xs font-semibold">Passages about {{ sec.label }}, each word for word from its page</p>
              <ul class="max-h-72 space-y-2 overflow-y-auto text-sm" :aria-label="`Passages from ${s.filename}`">
                <li v-for="(p, i) in s.passages" :key="i">
                  <span class="font-mono text-xs text-muted-foreground">Page {{ p.page }}</span>
                  <span v-if="s.ocr_pages?.includes(p.page)" class="ml-2 text-xs font-semibold text-warn-fg">read by OCR, check the text</span>
                  <p>{{ p.quote }}</p>
                </li>
              </ul>
            </template>
            <p v-if="s.dropped" class="text-xs text-muted-foreground">
              {{ s.dropped }} {{ s.dropped === 1 ? "passage was" : "passages were" }} dropped: not word for word on the page the model named.
            </p>
            <p v-if="s.ocr_pages?.length" class="text-xs text-warn-fg">
              {{ s.ocr_pages.length === 1 ? "Page" : "Pages" }} {{ s.ocr_pages.join(", ") }} had no selectable text and {{ s.ocr_pages.length === 1 ? "was" : "were" }} read by OCR, check the text.
            </p>
          </template>
          <template v-else-if="s.text !== null">
            <label :for="`snip-text-${s.hash}`" class="text-xs font-semibold">Text in the image</label>
            <Textarea
              :id="`snip-text-${s.hash}`"
              v-model="drafts[s.hash]"
              rows="6"
              :disabled="disabled || !!busy[s.hash]"
              :aria-invalid="hasUnclear(drafts[s.hash] ?? '') || undefined"
              :aria-describedby="`snip-help-${s.hash}`"
              class="min-h-32 py-2 font-mono text-xs"
            />
            <p :id="`snip-help-${s.hash}`" class="text-xs" :class="hasUnclear(drafts[s.hash] ?? '') ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
              {{ hasUnclear(drafts[s.hash] ?? "") ? "Replace every [unclear] mark with what the image shows, or delete it, before confirming." : "Compare it with the image: every number, unit, date and name must be as printed." }}
            </p>
          </template>
          <p v-else class="text-sm text-muted-foreground">Not read yet.</p>
          <div class="flex flex-wrap items-end gap-3">
            <div>
              <label :for="`snip-sector-${s.hash}`" class="block text-xs text-muted-foreground">Sector</label>
              <select
                :id="`snip-sector-${s.hash}`"
                :value="s.sector"
                :disabled="disabled || !!busy[s.hash] || s.kind === 'pdf'"
                class="h-8 rounded-md border border-input bg-card px-2 text-sm"
                @change="(e) => move(s, (e.target as HTMLSelectElement).value)"
              >
                <option v-for="o in listing?.sectors" :key="o.id" :value="o.id">{{ o.label }}</option>
              </select>
            </div>
            <div>
              <label :for="`snip-date-${s.hash}`" class="block text-xs text-muted-foreground">Date of the page (optional)</label>
              <input
                :id="`snip-date-${s.hash}`"
                type="date"
                :value="s.date"
                :disabled="disabled || !!busy[s.hash]"
                class="h-8 rounded-md border border-input bg-card px-2 text-sm"
                @change="(e) => setDate(s, (e.target as HTMLInputElement).value)"
              />
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button v-if="s.text === null" size="sm" :disabled="disabled || !!busy[s.hash]" @click="read(s.hash)">{{ s.kind === "pdf" ? "Read this PDF" : "Read this snip" }}</Button>
            <Button
              v-else
              size="sm"
              :disabled="disabled || !!busy[s.hash] || !(drafts[s.hash] ?? '').trim() || hasUnclear(drafts[s.hash] ?? '') || (s.confirmed && drafts[s.hash] === s.text)"
              @click="confirm(s)"
            >
              {{ s.confirmed ? "Confirmed" : "Confirm" }}
            </Button>
            <Button size="sm" variant="outline" :disabled="disabled || !!busy[s.hash]" @click="remove(s)">Remove</Button>
          </div>
        </div>
      </li>
    </ul>
</template>
