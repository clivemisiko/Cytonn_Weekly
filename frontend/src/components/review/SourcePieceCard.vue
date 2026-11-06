<script setup lang="ts">
import { PhArrowSquareOut, PhWarning } from "@phosphor-icons/vue";
import { computed, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import * as api from "@/lib/api";
import { ADDRESS_PLACEHOLDER, NO_SOURCES_YET, normalizeAddress, sourceFacts, sourcePageHref } from "@/lib/sources";
import type { ReportChoice, SourceMeta, SourcePiece } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{
  piece: SourcePiece;
  /** Stable per piece on this screen, so two pieces never share a field id. */
  uid: string;
  slug: string;
  report: ReportChoice;
  /** A Focus's typed section titles, which are what name its pieces. */
  titles: string;
  disabled: boolean;
}>();
const emit = defineEmits<{ update: [sources: SourceMeta[]] }>();

const open = ref(false);
const fetchUrl = ref("");
const pasteUrl = ref("");
const pasteDate = ref("");
const pasteText = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const saved = ref<string | null>(null);
const off = computed(() => props.disabled || busy.value);

async function run(work: () => Promise<{ sources: SourceMeta[]; source?: SourceMeta; note?: string }>, done: () => void) {
  error.value = null;
  saved.value = null;
  busy.value = true;
  try {
    const res = await work();
    emit("update", res.sources);
    saved.value = res.note ?? (res.source ? `Saved ${res.source.title} (${res.source.host}).` : "Removed.");
    done();
  } catch (err) {
    // The API's own sentence, shown as it stands: why it was refused and what to do instead.
    error.value = (err as api.ApiError).message;
  } finally {
    busy.value = false;
  }
}

const add = (url: string, extra: { date?: string; text?: string } = {}) =>
  api.addSource(props.slug, props.report, props.piece.subject, { url, ...extra }, props.titles);

const fetchIt = () => {
  const address = normalizeAddress(fetchUrl.value);
  if ("error" in address) {
    saved.value = null;
    error.value = address.error;
    return;
  }
  return run(
    () => add(address.url),
    () => (fetchUrl.value = ""),
  );
};
const pasteIt = () =>
  run(
    () => add(pasteUrl.value.trim(), { date: pasteDate.value, text: pasteText.value }),
    () => {
      pasteUrl.value = "";
      pasteDate.value = "";
      pasteText.value = "";
      open.value = false;
    },
  );
const lookAgain = () =>
  run(
    async () => {
      const res = await api.gatherSources(props.slug, props.report, props.piece.subject, props.titles);
      const note = res.reason ?? (res.found ? `Found ${res.found} ${res.found === 1 ? "page" : "pages"}` : "Nothing found");
      return { sources: res.sources, note };
    },
    () => undefined,
  );
const remove = (s: SourceMeta) =>
  run(async () => {
    await api.removeSource(s.id);
    return { sources: props.piece.sources.filter((x) => x.id !== s.id) };
  }, () => undefined);
</script>

<template>
  <li role="group" :aria-label="`Sources for ${piece.subject}`" class="space-y-3 rounded-lg border bg-card p-4">
    <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h3 class="text-sm font-semibold [overflow-wrap:anywhere]">{{ piece.subject }}</h3>
      <span class="text-xs text-muted-foreground">{{ piece.sources.length }} {{ piece.sources.length === 1 ? "source" : "sources" }}</span>
    </div>

    <Notice v-if="piece.sources.length === 0" tone="warn">{{ NO_SOURCES_YET }}</Notice>
    <ul v-else class="space-y-2">
      <li v-for="s in piece.sources" :key="s.id" class="space-y-1 rounded-md border px-3 py-2">
        <p class="text-sm font-medium [overflow-wrap:anywhere]">{{ s.title }}</p>
        <p class="text-xs text-muted-foreground [overflow-wrap:anywhere]">
          <span class="font-mono">{{ s.host }}</span> · {{ sourceFacts(s).join(" · ") }}
        </p>
        <p v-if="s.flags.length" class="flex items-start gap-1.5 text-xs font-medium text-warn-fg">
          <PhWarning weight="bold" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ s.flags.join("; ") }}
        </p>
        <div class="flex flex-wrap items-center gap-3 pt-1 text-xs">
          <a :href="sourcePageHref(s.id)" target="_blank" rel="noopener noreferrer" class="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">
            View saved text<PhArrowSquareOut weight="bold" class="ml-1 inline size-4 align-[-3px]" aria-hidden="true" /><span class="sr-only"> of {{ s.title }}</span>
          </a>
          <Button size="sm" variant="outline" :disabled="off" :aria-label="`Remove ${s.title} from ${piece.subject}`" @click="remove(s)">Remove</Button>
        </div>
      </li>
    </ul>

    <div>
      <Button size="sm" variant="outline" :disabled="off" :aria-label="`Look again for sources for ${piece.subject}`" @click="lookAgain">Look again</Button>
    </div>

    <details :open="open" class="rounded-md border" @toggle="open = ($event.target as HTMLDetailsElement).open">
      <summary class="cursor-pointer rounded-md px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">Add a source</summary>
      <div class="space-y-5 border-t p-3">
        <form class="space-y-2" @submit.prevent="fetchIt">
          <label :for="`fetch-${uid}`" class="text-sm font-semibold">Address (URL) to fetch</label>
          <input :id="`fetch-${uid}`" v-model="fetchUrl" type="text" inputmode="url" autocomplete="off" :disabled="off" :placeholder="ADDRESS_PLACEHOLDER" class="flex h-10 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60" :aria-describedby="`fetch-hint-${uid}`" />
          <p :id="`fetch-hint-${uid}`" class="text-xs text-muted-foreground">A link with or without http:// or https:// works. Give the page that holds the facts, not the site’s home page. A page on a site we do not know is fetched too and marked so, and an http:// page is marked not secure. If a page cannot be fetched, paste its text below.</p>
          <Button type="submit" variant="outline" :disabled="off">Fetch page</Button>
        </form>

        <form class="space-y-2 border-t pt-4" @submit.prevent="pasteIt">
          <p class="text-sm font-semibold">Or paste the text</p>
          <label :for="`paste-url-${uid}`" class="text-xs text-muted-foreground">Address (URL) the text came from</label>
          <input :id="`paste-url-${uid}`" v-model="pasteUrl" type="url" autocomplete="off" :disabled="off" placeholder="https://…" class="flex h-10 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60" />
          <label :for="`paste-date-${uid}`" class="text-xs text-muted-foreground">Date of the page</label>
          <input :id="`paste-date-${uid}`" v-model="pasteDate" type="date" :disabled="off" class="flex h-10 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 sm:max-w-56" />
          <label :for="`paste-text-${uid}`" class="text-xs text-muted-foreground">Pasted text</label>
          <Textarea :id="`paste-text-${uid}`" v-model="pasteText" rows="6" :disabled="off" placeholder="Paste the page’s text exactly as it reads…" class="min-h-32 py-2" />
          <p class="text-xs text-muted-foreground">It is kept exactly as pasted. Text from a site we do not know is kept too, and marked so on the review.</p>
          <Button type="submit" variant="outline" :disabled="off || !pasteUrl.trim() || !pasteDate || !pasteText.trim()">Save pasted text</Button>
        </form>
      </div>
    </details>

    <Notice v-if="error" role="alert" class="font-medium">{{ error }}</Notice>
    <p v-else-if="saved" role="status" class="text-xs font-medium text-ok-fg">{{ saved }}</p>
  </li>
</template>
