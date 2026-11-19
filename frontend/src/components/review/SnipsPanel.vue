<script setup lang="ts">
import { onMounted } from "vue";
import { snipCounts, unconfirmedNote } from "@/lib/snips";
import { useSnips } from "@/lib/usesnips";
import { computed } from "vue";
import Notice from "./Notice.vue";
import SnipSector from "./SnipSector.vue";

const props = defineProps<{ week: string; disabled: boolean }>();
const emit = defineEmits<{ counts: [counts: ReturnType<typeof snipCounts> | null] }>();

const snips = useSnips(() => props.week, (next) => emit("counts", snipCounts(next)));
const { listing, error, bySector } = snips;
onMounted(snips.load);
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
      <p class="text-sm text-muted-foreground">
        You can also add a PDF (up to {{ listing ? Math.round(listing.pdf_max_bytes / 1048576) : 20 }} MB and
        {{ listing?.pdf_max_pages ?? 60 }} pages). The model picks out the passages about the sector it is uploaded under, each quoted word for word
        with its page; check them and confirm. A PDF is read for one sector only: to use the same PDF for two sectors, upload it once under each.
      </p>
    </div>

    <Notice v-if="error" role="alert" class="font-medium">{{ error }}</Notice>
    <Notice v-if="note" tone="warn" role="status">{{ note }}</Notice>
    <Notice v-for="w in listing?.warnings ?? []" :key="w" tone="warn" role="status">{{ w }}</Notice>
    <p v-if="!listing && !error" role="status" class="text-sm text-muted-foreground">Reading the saved snips…</p>

    <div v-for="sec in bySector" :key="sec.id" class="space-y-3 border-t pt-4">
      <SnipSector :sec="sec" :snips="snips" :week="week" :disabled="disabled" />
    </div>
  </section>
</template>
