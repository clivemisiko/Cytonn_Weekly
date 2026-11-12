<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import * as api from "@/lib/api";
import { hasUnclear, snipCounts, snipStatus, unconfirmedNote } from "@/lib/snips";
import type { SnipMeta, SnipsListing } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{ week: string; disabled: boolean }>();
const emit = defineEmits<{ counts: [counts: ReturnType<typeof snipCounts> | null] }>();

const listing = ref<SnipsListing | null>(null);
const error = ref<string | null>(null);
// The text typed in each snip's box, by image hash; saved when the snip is confirmed or its sector or date changes.
const drafts = ref<Record<string, string>>({});
const busy = ref<Record<string, string>>({}); // hash -> what it is doing ("Reading…", "Confirming…")
const uploading = ref(false);

function take(next: SnipsListing) {
  listing.value = next;
  for (const s of next.snips) if (s.text !== null && !(s.hash in drafts.value)) drafts.value[s.hash] = s.text;
  emit("counts", snipCounts(next));
}
async function run<T>(hash: string, label: string, fn: () => Promise<T>): Promise<T | undefined> {
  busy.value[hash] = label;
  error.value = null;
  try {
    return await fn();
  } catch (err) {
    error.value = (err as api.ApiError).message;
  } finally {
    delete busy.value[hash];
  }
}
onMounted(async () => {
  try {
    take(await api.getSnips(props.week));
    for (const s of listing.value?.snips ?? []) if (s.text === null) await read(s.hash); // one at a time: one vision call at once from here
  } catch (err) {
    error.value = (err as api.ApiError).message;
  }
});

async function upload(sector: string, files: FileList | null) {
  if (!files?.length) return;
  uploading.value = true;
  error.value = null;
  const added: string[] = [];
  for (const file of Array.from(files)) {
    try {
      const before = new Set((listing.value?.snips ?? []).map((s) => s.hash));
      const next = await api.uploadSnip(props.week, sector, file);
      take(next);
      added.push(...next.snips.filter((s) => !before.has(s.hash)).map((s) => s.hash));
    } catch (err) {
      error.value = `${file.name}: ${(err as api.ApiError).message}`;
    }
  }
  uploading.value = false;
  for (const h of added) await read(h);
}
async function read(hash: string) {
  const next = await run(hash, "Reading the image…", () => api.readSnip(props.week, hash));
  if (next) take(next);
}
async function move(s: SnipMeta, sector: string) {
  const next = await run(s.hash, "Moving…", () => api.changeSnip(props.week, s.hash, { sector }));
  if (next) take(next);
}
async function setDate(s: SnipMeta, date: string) {
  const next = await run(s.hash, "Saving…", () => api.changeSnip(props.week, s.hash, { date }));
  if (next) take(next);
}
async function confirm(s: SnipMeta) {
  const next = await run(s.hash, "Confirming…", async () => {
    if ((drafts.value[s.hash] ?? "") !== (s.text ?? "")) await api.changeSnip(props.week, s.hash, { text: drafts.value[s.hash] });
    return api.confirmSnip(props.week, s.hash);
  });
  if (next) take(next);
  else take(await api.getSnips(props.week)); // a refused confirm may still have saved the text: show what the server holds
}
async function remove(s: SnipMeta) {
  const next = await run(s.hash, "Removing…", () => api.removeSnip(props.week, s.hash));
  if (next) {
    delete drafts.value[s.hash];
    take(next);
  }
}

const bySector = computed(() =>
  (listing.value?.sectors ?? []).map((sec) => ({ ...sec, snips: (listing.value?.snips ?? []).filter((s) => s.sector === sec.id) })),
);
const note = computed(() => (listing.value ? unconfirmedNote(listing.value) : null));
</script>

<template>
  <section aria-labelledby="snips-title" class="space-y-4 rounded-lg border border-t-[3px] border-t-primary bg-card p-6" data-attention="snips">
    <div class="space-y-1">
      <h2 id="snips-title" class="text-lg font-semibold">Snips</h2>
      <p class="text-sm text-muted-foreground">
        This section is written only from the snips you upload here; nothing is searched for it. Upload images (PNG, JPG or WebP, up to
        {{ listing ? Math.round(listing.max_bytes / 1048576) : 5 }} MB each, {{ listing?.max_per_sector ?? 6 }} a sector) under the sector each belongs to.
        The model reads the text in each one; check it against the image, fix it, and confirm. A sector with no confirmed snip is left out.
      </p>
    </div>

    <Notice v-if="error" role="alert" class="font-medium">{{ error }}</Notice>
    <Notice v-if="note" tone="warn" role="status">{{ note }}</Notice>
    <p v-if="!listing && !error" role="status" class="text-sm text-muted-foreground">Reading the saved snips…</p>

    <div v-for="sec in bySector" :key="sec.id" class="space-y-3 border-t pt-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h3 class="text-sm font-semibold">{{ sec.label }}</h3>
        <span class="font-mono text-xs text-muted-foreground">{{ sec.snips.length }} of {{ listing?.max_per_sector }}</span>
      </div>
      <div>
        <label :for="`snip-file-${sec.id}`" class="text-xs text-muted-foreground">Add images for {{ sec.label }}</label>
        <input
          :id="`snip-file-${sec.id}`"
          type="file"
          multiple
          accept="image/png,image/jpeg,image/webp"
          :disabled="disabled || uploading || sec.snips.length >= (listing?.max_per_sector ?? 6)"
          class="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-card file:px-3 file:py-1 file:text-sm"
          @change="(e) => { const t = e.target as HTMLInputElement; void upload(sec.id, t.files).then(() => (t.value = '')); }"
        />
      </div>
      <p v-if="!sec.snips.length" class="text-sm text-muted-foreground">No snip yet. This sector will say “not included” unless one is confirmed.</p>
      <ul v-if="sec.snips.length" class="space-y-4" :aria-label="`${sec.label} snips`">
        <li v-for="s in sec.snips" :key="s.hash" class="grid gap-3 rounded-lg border p-3 md:grid-cols-2">
          <a :href="api.snipImageUrl(week, s.hash)" target="_blank" rel="noopener" class="block self-start">
            <img :src="api.snipImageUrl(week, s.hash)" :alt="`Snip ${s.filename}`" class="max-h-72 w-full rounded-md border object-contain" loading="lazy" />
          </a>
          <div class="space-y-2">
            <p class="flex flex-wrap items-center gap-2 text-xs">
              <span class="break-all font-mono">{{ s.filename }}</span>
              <span :class="s.confirmed ? 'font-semibold text-ok-fg' : 'font-semibold text-warn-fg'" role="status">
                {{ busy[s.hash] ?? snipStatus(s, drafts[s.hash]) }}
              </span>
            </p>
            <template v-if="s.text !== null">
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
                  :disabled="disabled || !!busy[s.hash]"
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
              <Button v-if="s.text === null" size="sm" :disabled="disabled || !!busy[s.hash]" @click="read(s.hash)">Read this snip</Button>
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
    </div>
  </section>
</template>
