<script setup lang="ts">
import { PhArrowSquareOut, PhCaretDown, PhPencilSimple, PhWarning } from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, inject } from "vue";
import { KIND_LABELS, friendlyTime, pyRepr } from "@/lib/format";
import { READ_ONLY } from "@/lib/previous";
import { ADDED_BY_ANALYST, NEWS_SITE, TEXT_FROM_SEARCH, claimSource, sourcePageHref } from "@/lib/sources";
import type { Flag, Review, ReviewItem } from "@/lib/types";
import EditSentence from "./EditSentence.vue";
import FixFromFile from "./FixFromFile.vue";
import RemoveFinding from "./RemoveFinding.vue";
import SeverityPill from "./SeverityPill.vue";
import TextWithIds from "./TextWithIds.vue";

const props = defineProps<{
  item: ReviewItem;
  /** The review the item is in: the fix-from-a-file control needs its week, run and decision. */
  review: Review;
  /** "01 / 05" in the review's list; absent in the chat's full view. */
  position?: string;
}>();

// Whether Technical details is open. Collapsed by default.
const open = defineModel<boolean>("open", { default: false });
const readOnly = inject(READ_ONLY, false);
// A review saved before the resolve controls were removed may hold a mark or a note: shown read-only, only when there is one.
const oldMark = computed(() => {
  const mark = props.item.resolution === "accept" ? "Accepted" : props.item.resolution === "fix_needed" ? "Fix needed" : "";
  const note = (props.item.resolution_note ?? "").trim();
  return mark || note ? `${mark ? `Marked ${mark}` : ""}${mark && note ? ". " : ""}${note ? `Note: ${note}` : ""}` : "";
});
const ctx = computed(() => props.item.context);
// A claim quoted from a supplied source: the host, the date and the verified quote are shown, and so is a host off the approved list.
const source = computed(() => claimSource(ctx.value));
const safeUrl = computed(() => (ctx.value.url && /^https?:\/\//.test(ctx.value.url) ? ctx.value.url : null));
const sourceHost = computed(() => {
  try {
    return safeUrl.value ? new URL(safeUrl.value).host : null;
  } catch {
    return null;
  }
});
const flags = computed<Flag[]>(() => (props.item.status === "flagged" && Array.isArray(props.item.detail) ? props.item.detail : []));
const detailText = computed(() => (typeof props.item.detail === "string" ? props.item.detail : ""));
const callout = computed(() => (flags.value[0]?.message ?? detailText.value).trim());
// The first flag that carries figures fills the two cards; every flag stays listed in Technical details.
const figures = computed(() => flags.value.find((f) => f.drafted !== null || f.expected !== null) ?? null);
const whatToCheck = computed(() => (ctx.value.note && ctx.value.note !== detailText.value ? ctx.value.note : ""));
const inputs = computed(() => Object.entries(ctx.value.inputs ?? {}));
const cells = (flag: Flag): [string, string][] => [
  ["Drafted", pyRepr(flag.drafted)],
  ["Expected (normalized source)", flag.expected ?? "None"],
  ["Source value", pyRepr(flag.source_value)],
];
const sourceHref = computed(() => (source.value ? sourcePageHref(source.value.id, source.value.quote, props.review.run_id) : safeUrl.value));
</script>

<template>
  <article :id="`review-item-${item.index}`" class="@container space-y-4 scroll-mt-28" :class="`state-${item.status}`" :aria-labelledby="`review-item-${item.index}-title`">
    <header class="space-y-1">
      <div class="flex items-start justify-between gap-3">
        <h3 :id="`review-item-${item.index}-title`" class="text-xl font-semibold tracking-tight text-foreground">{{ item.ref }}</h3>
        <span v-if="position" class="shrink-0 font-mono text-sm text-muted-foreground">{{ position }}</span>
      </div>
      <p class="text-sm text-muted-foreground">{{ KIND_LABELS[item.kind] ?? item.kind }} / {{ item.ref }}</p>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1">
        <SeverityPill :kind="item.status" />
        <span v-if="source?.offList" class="inline-flex items-center gap-1 text-xs font-medium text-warn-fg">
          <PhWarning weight="bold" class="size-3.5" aria-hidden="true" />Unverified Source Domain
        </span>
        <span v-if="source?.textFromSearch" class="inline-flex items-center gap-1 text-xs font-medium text-warn-fg">
          <PhWarning weight="bold" class="size-3.5" aria-hidden="true" />{{ TEXT_FROM_SEARCH }}
        </span>
        <span v-if="source?.newsSite" class="inline-flex items-center gap-1 text-xs font-medium text-warn-fg">
          <PhWarning weight="bold" class="size-3.5" aria-hidden="true" />{{ NEWS_SITE }}
        </span>
        <span v-if="source?.addedByAnalyst" class="text-xs font-medium text-muted-foreground">{{ ADDED_BY_ANALYST }}</span>
        <span v-if="ctx.edited_at" class="inline-flex items-center gap-1 text-xs font-medium">
          <PhPencilSimple weight="bold" class="size-3.5" aria-hidden="true" />Edited by you, {{ friendlyTime(ctx.edited_at) }}
        </span>
        <span v-else-if="ctx.removed_at" class="inline-flex items-center gap-1 text-xs font-medium">
          <PhPencilSimple weight="bold" class="size-3.5" aria-hidden="true" />Removed by you, {{ friendlyTime(ctx.removed_at) }}
        </span>
      </div>
    </header>

    <p v-if="callout" class="surface-state px-4 py-3 text-sm whitespace-pre-line text-foreground" :class="`state-${item.status}`">
      <TextWithIds :text="callout" />
    </p>

    <div v-if="figures || ctx.text || source || safeUrl" class="grid gap-4 @min-[40rem]:grid-cols-2">
      <section class="min-w-0 space-y-2 rounded-lg border p-4" aria-label="In the report">
        <p class="eyebrow">In the report</p>
        <p v-if="figures && figures.drafted !== null" class="text-2xl font-semibold tracking-tight">{{ pyRepr(figures.drafted) }}</p>
        <blockquote v-if="ctx.text" class="text-sm text-foreground/85">{{ ctx.text }}</blockquote>
        <p v-if="ctx.edited_at" class="text-xs text-muted-foreground">
          Original text: "{{ ctx.was }}". Please verify that the cited source below accurately supports your revised wording.
        </p>
      </section>
      <section class="min-w-0 space-y-2 rounded-lg border p-4" aria-label="Source check">
        <p class="eyebrow">Source check</p>
        <template v-if="figures && figures.expected !== null">
          <p class="text-2xl font-semibold tracking-tight">{{ figures.expected }}</p>
          <p class="text-xs text-muted-foreground">Expected (normalized source) · Source value {{ pyRepr(figures.source_value) }}</p>
        </template>
        <template v-else-if="source">
          <p class="text-sm"><span class="font-mono">{{ source.host }}</span> · {{ source.date }}</p>
          <p class="text-sm">“{{ source.quote }}”</p>
        </template>
        <template v-else>
          <p class="text-lg font-semibold">No verified comparison yet</p>
          <p v-if="sourceHost" class="text-sm"><span class="font-mono">{{ sourceHost }}</span></p>
        </template>
        <a
          v-if="sourceHref"
          :href="sourceHref"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        >
          {{ source ? "View saved text" : "Open source" }}<PhArrowSquareOut weight="bold" class="size-4" aria-hidden="true" />
        </a>
      </section>
    </div>

    <div v-if="whatToCheck" class="space-y-1 rounded-lg bg-muted px-4 py-3">
      <p class="eyebrow">What to check</p>
      <p class="text-sm whitespace-pre-line">{{ whatToCheck }}</p>
    </div>

    <CollapsibleRoot v-model:open="open" class="rounded-lg border">
      <CollapsibleTrigger class="flex w-full items-center gap-2 rounded-lg px-4 py-3 text-left text-sm font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
        <span class="flex-1">Technical details</span>
        <PhCaretDown weight="bold" aria-hidden="true" class="size-4 shrink-0 text-muted-foreground transition-transform duration-200" :class="open && 'rotate-180'" />
      </CollapsibleTrigger>
      <CollapsibleContent class="collapsible overflow-hidden">
        <div class="space-y-3 border-t px-4 py-3">
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
          <p v-if="safeUrl" class="text-sm">
            Source:
            <a :href="safeUrl" target="_blank" rel="noopener noreferrer" class="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">
              {{ ctx.title || safeUrl }}<PhArrowSquareOut weight="bold" class="ml-1 inline size-4 align-[-3px]" aria-hidden="true" />
            </a>
          </p>
          <dl v-if="source" data-testid="claim-source" class="grid gap-x-3 gap-y-1 text-sm @min-[28rem]:grid-cols-[6rem_1fr]">
            <dt class="eyebrow">Source</dt>
            <dd class="min-w-0 [overflow-wrap:anywhere]">
              <span class="font-mono">{{ source.host }}</span> · {{ source.date }}
              <span v-if="source.offList" class="font-medium text-warn-fg"> · Unverified Source Domain</span>
              <span v-if="source.textFromSearch" class="font-medium text-warn-fg"> · {{ TEXT_FROM_SEARCH }}</span>
              <span v-if="source.newsSite" class="font-medium text-warn-fg"> · {{ NEWS_SITE }}</span>
              <span v-if="source.addedByAnalyst" class="font-medium"> · {{ ADDED_BY_ANALYST }}</span>
            </dd>
            <dt class="eyebrow">Quote</dt>
            <dd class="min-w-0 [overflow-wrap:anywhere]">“{{ source.quote }}” <span class="text-xs text-muted-foreground">(verified word-for-word against the saved document)</span></dd>
            <dt class="eyebrow">Saved copy</dt>
            <dd class="min-w-0 text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {{ source.origin === "found" ? "Found automatically" : source.origin === "fetched" ? "Fetched" : "Pasted" }} {{ source.savedAt }} · fingerprint <span class="font-mono">{{ source.fingerprint }}</span> ·
              <a :href="sourcePageHref(source.id, source.quote, review.run_id)" target="_blank" rel="noopener noreferrer" class="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">View saved text</a>
            </dd>
          </dl>
          <p v-else-if="ctx.cited_text" class="text-xs text-muted-foreground">Cited text: “{{ ctx.cited_text }}”</p>
          <div v-if="inputs.length > 0" class="space-y-1">
            <p class="eyebrow">Worked out from</p>
            <ul class="space-y-1 text-xs">
              <li v-for="[name, input] in inputs.slice(0, 12)" :key="name" class="[overflow-wrap:anywhere]">
                <span class="font-medium">{{ String(input.value) }}</span>{{ " " }}<span class="text-muted-foreground">
                  {{ input.origin === "ocr" ? "read by OCR from " : "" }}{{ input.source }}{{ input.second ? `; also ${String(input.second.value)} in ${input.second.source}` : "" }}
                </span>
              </li>
              <li v-if="inputs.length > 12" class="text-muted-foreground">and {{ inputs.length - 12 }} additional inputs of this type.</li>
            </ul>
          </div>
          <p v-if="ctx.note && ctx.note !== detailText" data-testid="item-note" class="text-xs whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">{{ ctx.note }}</p>
          <p v-if="detailText" data-testid="item-detail" class="text-xs whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]"><TextWithIds :text="detailText" /></p>
          <p v-if="!flags.length && !safeUrl && !source && !ctx.cited_text && !inputs.length && !whatToCheck && !detailText" class="text-xs text-muted-foreground">Checked with no flag.</p>
        </div>
      </CollapsibleContent>
    </CollapsibleRoot>

    <p v-if="oldMark" class="text-xs text-muted-foreground [overflow-wrap:anywhere]">{{ oldMark }}</p>
    <div v-if="!readOnly && (item.fix_slots?.length || item.edit_sentence || item.edit_paragraph || item.remove_finding)" class="flex flex-wrap items-center gap-2">
      <FixFromFile :review="review" :item="item" />
      <EditSentence :review="review" :item="item" />
      <RemoveFinding :review="review" :item="item" />
    </div>
  </article>
</template>
