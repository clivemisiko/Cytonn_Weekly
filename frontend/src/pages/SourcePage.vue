<script setup lang="ts">
import { PhWarning } from "@phosphor-icons/vue";
import { cn } from "cn";
import { computed, nextTick, onMounted, ref, shallowRef } from "vue";
import { RouterLink, useRoute } from "vue-router";
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import { buttonVariants } from "@/components/ui/button";
import * as api from "@/lib/api";
import { friendlyTime } from "@/lib/format";
import { shell } from "@/lib/shell";
import { ORIGIN_WORDS, dateLabel, locateQuote } from "@/lib/sources";
import type { SourceMeta } from "@/lib/types";

const props = defineProps<{ sourceId: string }>();
const route = useRoute();

shell.invalidate(); // the rail knows no section's state here

const first = (v: unknown) => (Array.isArray(v) ? String(v[0] ?? "") : typeof v === "string" ? v : "");
const quote = first(route.query.quote).trim();
const review = first(route.query.review);
const backTo = /^\d+$/.test(review) ? { path: "/overview", query: { review } } : { path: "/overview" };

const meta = shallowRef<SourceMeta | null>(null);
const text = ref("");
const problem = ref<string | null>(null);
const loading = ref(true);
const mark = ref<HTMLElement | null>(null);

const found = computed(() => (quote && text.value ? locateQuote(text.value, quote) : null));
const parts = computed(() => {
  const f = found.value;
  return f ? { before: text.value.slice(0, f.start), hit: text.value.slice(f.start, f.end), after: text.value.slice(f.end) } : null;
});

onMounted(async () => {
  try {
    [meta.value, text.value] = await Promise.all([api.getSource(props.sourceId), api.getSourceText(props.sourceId)]);
  } catch (err) {
    problem.value = (err as api.ApiError).message;
  } finally {
    loading.value = false;
  }
  await nextTick();
  mark.value?.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
});
</script>

<template>
  <main id="main" tabindex="-1">
    <Masthead wide title="Saved source" />
    <PageGrid>
      <div class="min-w-0 space-y-4">
        <p v-if="loading" role="status" class="text-sm text-muted-foreground">Reading the saved source…</p>
        <Notice v-else-if="problem" role="alert" class="font-medium">{{ problem }}</Notice>

        <section v-else-if="meta" aria-labelledby="source-title" class="space-y-3 rounded-lg border bg-card p-4 sm:p-6">
          <p class="eyebrow font-mono [overflow-wrap:anywhere]">{{ meta.host }}</p>
          <h2 id="source-title" class="text-lg font-semibold [overflow-wrap:anywhere]">{{ meta.title }}</h2>
          <p class="text-sm [overflow-wrap:anywhere]">
            <a :href="meta.url" target="_blank" rel="noopener noreferrer" class="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">{{ meta.url }}</a>
          </p>
          <dl class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
            <dt class="eyebrow">Page date</dt>
            <dd>{{ dateLabel(meta.published_date) }}</dd>
            <dt class="eyebrow">Saved</dt>
            <dd>{{ friendlyTime(meta.fetched_at) }}</dd>
            <dt class="eyebrow">How</dt>
            <dd>{{ ORIGIN_WORDS[meta.origin] }}</dd>
            <dt class="eyebrow">Fingerprint</dt>
            <dd class="font-mono">{{ meta.sha256.slice(0, 8) }}</dd>
          </dl>
          <p v-if="meta.flags.length" class="flex items-start gap-1.5 text-sm font-medium text-warn-fg">
            <PhWarning weight="bold" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ meta.flags.join("; ") }}
          </p>
          <RouterLink :to="backTo" :class="cn(buttonVariants({ variant: 'outline' }))">Back to review</RouterLink>
        </section>

        <p v-if="meta && quote && !found" class="text-xs text-muted-foreground">The quoted passage could not be located in the saved text, so nothing is highlighted.</p>

        <article v-if="meta" aria-label="Saved text" class="max-w-[70ch] whitespace-pre-wrap text-base leading-7 [overflow-wrap:anywhere]">
          <template v-if="parts">{{ parts.before }}<mark ref="mark" class="rounded-sm bg-primary/35 px-0.5 text-foreground">{{ parts.hit }}</mark>{{ parts.after }}</template>
          <template v-else>{{ text }}</template>
        </article>
      </div>
    </PageGrid>
  </main>
</template>
