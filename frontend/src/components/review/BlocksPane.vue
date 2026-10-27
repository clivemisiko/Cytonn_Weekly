<script setup lang="ts">
import { PhChartBar, PhLockSimple } from "@phosphor-icons/vue";
import { SCOPE_LABELS, friendlyDate, friendlyTime, weekRange } from "@/lib/format";
import type { BlocksSection, ComputedBlock, NarrativeBlock, NotCovered, Review, TableBlock } from "@/lib/types";
import DataTable from "./DataTable.vue";
import ExtractionNotices from "./ExtractionNotices.vue";
import ChartCard from "./ChartCard.vue";
import Markdown from "./Markdown.vue";
import Notice from "./Notice.vue";
import NoticeStack from "./NoticeStack.vue";
import Numeral from "./Numeral.vue";
import PartsLine from "./PartsLine.vue";
import Warnings from "./Warnings.vue";

defineProps<{ review: Review; section: BlocksSection; onTeamChart: (chartId: string, use: boolean) => Promise<boolean> }>();

const BODY = "max-w-[68ch] text-base leading-7 md:pl-11";
const PIECE = "space-y-3 border-t px-4 py-6 sm:px-6";
const HEAD = "flex items-start gap-3 text-base font-semibold";
const SOURCE_LINK = "text-link underline decoration-link/40 underline-offset-2 hover:decoration-link";

const safeUrl = (url: string | null | undefined) => (url && /^https?:\/\//.test(url) ? url : null);
const typedRows = (block: TableBlock) => block.rows.filter((r) => r.typed).length;
/** The sentences the reviewer rewrote in a piece. A removed one is in the review items, not in the text. */
const edited = (block: NarrativeBlock) => (block.edits ?? []).filter((e) => e.kind === "edited");
/** The warnings that are not a refused table: those sentences are shown as cards from `notices`. */
const otherWarnings = (s: BlocksSection) => {
  const shown = new Set((s.notices ?? []).map((n) => n.text));
  return s.warnings.filter((w) => !shown.has(w));
};

/** A computed paragraph's one line of facts: how many figures were checked, and what kinds of input they rest on. */
function computedParts(block: ComputedBlock) {
  const origins = new Set(block.figures.flatMap((f) => Object.values(f.inputs).map((i) => i.origin)));
  const sources = block.sources.map((s) => s.name).join("; ");
  return [
    { text: "Worked out by the tool", style: "name" as const },
    { text: `${block.figures.length} ${block.figures.length === 1 ? "figure" : "figures"} checked` },
    { text: origins.has("analyst_input") ? "includes analyst input" : "" },
    { text: origins.has("ocr") ? "includes OCR readings" : "" },
    { text: sources ? `Sources: ${sources}` : "" },
  ];
}

/** What an approved section holds that the Executive Summary leaves out, by kind. */
const leftOut = (s: NotCovered): [string, string[]][] =>
  (
    [
      ["Tables", s.tables],
      ["Parts not yet drafted", s.unavailable],
      ["Further pieces", s.further_pieces],
    ] as [string, string[]][]
  ).filter(([, names]) => names.length > 0);
</script>

<template>
  <section aria-labelledby="draft-title" class="min-w-0 rounded-xl border border-border bg-card shadow-xs [overflow-wrap:anywhere]">
    <div class="flex flex-col gap-3 px-4 py-5 sm:px-6">
      <h2 id="draft-title" class="text-lg font-semibold tracking-tight text-foreground">Drafted section: {{ weekRange(section.week_start, section.week_end) }}</h2>
      <p v-if="section.topic" class="text-sm"><span class="eyebrow mr-2">Topic</span>{{ section.topic }}</p>
      <div class="space-y-2 empty:hidden">
        <Notice v-if="review.is_dev_draft && review.dev_mode_label" role="alert" class="font-semibold">{{ review.dev_mode_label }}</Notice>
        <Notice v-if="section.summary_note" tone="info" role="status">{{ section.summary_note }}</Notice>
        <Notice v-if="section.shortfall > 0" tone="warn" role="status" class="font-semibold">
          Only {{ section.pieces_found }} of {{ section.pieces_expected }} drafted pieces were found {{ review.period ? `for ${review.period}` : "this week" }}.
        </Notice>
        <ExtractionNotices :notices="section.notices ?? []" />
        <NoticeStack :items="otherWarnings(section)" />
      </div>

      <!-- Executive Summary only: for each section it includes, what that section's approved review holds that the
           summary does not carry. A note, not a review item: it lists names and nothing here was drafted or checked. -->
      <section
        v-if="section.not_covered && section.not_covered.length > 0"
        aria-labelledby="not-covered-title"
        class="space-y-3 rounded-md border border-dashed bg-muted/50 px-4 py-3"
      >
        <h3 id="not-covered-title" class="text-sm font-semibold">Not covered by this summary</h3>
        <ul class="space-y-3">
          <li v-for="s in section.not_covered" :key="s.section" class="space-y-1">
            <p class="text-sm font-medium">
              {{ s.title }} <span class="font-mono text-xs font-normal text-muted-foreground">run {{ s.run_id }}</span>
            </p>
            <Notice v-if="(s.dev_pieces ?? []).length > 0" tone="flag" class="text-xs font-semibold">
              Dev-mode draft: {{ (s.dev_pieces ?? []).map((d) => `${d.piece} (${d.drafted_by})`).join("; ") }}. This section's approval carries the
              dev mark into the summary, though the summary may not quote that piece.
            </Notice>
            <p v-if="leftOut(s).length === 0" class="text-xs text-muted-foreground">Nothing else in this section.</p>
            <dl v-else class="space-y-1 text-sm">
              <div v-for="[label, names] in leftOut(s)" :key="label" class="grid gap-x-3 @min-[28rem]:grid-cols-[10rem_1fr]">
                <dt class="eyebrow">{{ label }}</dt>
                <dd class="min-w-0">{{ names.join("; ") }}</dd>
              </div>
            </dl>
          </li>
        </ul>
      </section>

      <!-- The real issue's charts for this section. The tool does not draw them, so they are listed for the coordinator
           to add by hand, with the issue they were read from. A note, not a review item. -->
      <section
        v-if="section.chart_notes && section.chart_notes.length > 0"
        aria-labelledby="charts-title"
        class="space-y-2 rounded-md border border-dashed bg-muted/50 px-4 py-3"
      >
        <h3 id="charts-title" class="flex items-center gap-2 text-sm font-semibold">
          <PhChartBar weight="bold" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          Charts to add by hand ({{ section.chart_notes.length }})
        </h3>
        <p class="text-xs text-muted-foreground">
          Not generated by the tool. Titles as printed in {{ section.chart_reference ?? "the reference issue" }}; update their period and data before
          publishing.
        </p>
        <ol class="list-decimal space-y-1 pl-5 text-sm marker:font-mono marker:text-xs marker:text-muted-foreground">
          <li v-for="c in section.chart_notes" :key="c">{{ c }}</li>
        </ol>
      </section>
    </div>

    <template v-for="b in section.blocks" :key="b.id">
      <article v-if="b.kind === 'narrative'" :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" :class="HEAD">
          <Numeral>{{ b.numeral }}</Numeral>
          <span>{{ b.headline }}</span>
        </h3>
        <Markdown :class="BODY" :text="b.body_md" />
        <ul v-if="edited(b).length" aria-label="Sentences you edited" class="space-y-1 text-xs text-muted-foreground md:pl-11">
          <li v-for="e in edited(b)" :key="`${e.at}|${e.now}`" class="[overflow-wrap:anywhere]">
            <span class="font-medium text-foreground">Edited by you, {{ friendlyTime(e.at) }}.</span> Now: "{{ e.now }}" Was: "{{ e.was }}"
          </li>
        </ul>
        <PartsLine
          :parts="[
            { text: b.topic, style: 'name' },
            { text: b.search_scope ? (SCOPE_LABELS[b.search_scope] ?? b.search_scope) : '' },
            { text: b.preferred_domains.join(', '), style: 'mono' },
            { text: `Drafted by ${b.drafted_by}`, style: 'mono' },
          ]"
        />
        <!-- Always there: hidden when empty, it still keeps the line above from being the last child. -->
        <div class="md:pl-11 empty:hidden"><Warnings :items="b.warnings" /></div>
      </article>

      <section v-else-if="b.kind === 'table'" :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" class="flex items-center gap-3 text-base font-semibold">
          <Numeral>{{ b.numeral }}</Numeral>
          {{ b.title }}
        </h3>
        <DataTable :id="b.id" :title="b.title" :columns="b.columns" :rows="b.rows" :row-key="b.key_field" />
        <p class="text-xs text-muted-foreground">
          Source:
          <a v-if="safeUrl(b.source.url)" :href="safeUrl(b.source.url)!" target="_blank" rel="noopener noreferrer" :class="SOURCE_LINK">{{ b.source.name }}</a>
          <template v-else>{{ b.source.name }}</template>
          <template v-if="b.source.as_of">
            · as of <span class="font-mono">{{ b.source.as_of.length === 10 ? friendlyDate(b.source.as_of) : friendlyTime(b.source.as_of) }}</span>
          </template>
        </p>
        <p v-if="typedRows(b) > 0" class="text-xs text-warn-fg">
          Analyst input: {{ typedRows(b) }} of {{ b.rows.length }} rows rest on cells typed in the
          workbook. They are checked against the workbook, which is not a published source.
        </p>
        <p v-for="f in b.footnotes ?? []" :key="f" class="text-xs text-muted-foreground">{{ f }}</p>
        <p v-for="n in b.notes ?? []" :key="n" class="text-xs text-muted-foreground">{{ n }}</p>
        <template v-for="r in b.rows" :key="String(r[b.key_field])">
          <p v-if="r.error" class="text-sm text-flag-fg">{{ String(r[b.columns[0].key]) }}: {{ r.error }}</p>
        </template>
      </section>

      <!-- Text the coordinator supplied (Company Updates), shown as written. Never drafted, never checked. -->
      <article v-else-if="b.kind === 'supplied'" :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" :class="HEAD">
          <Numeral>{{ b.numeral }}</Numeral>
          <span>{{ b.title }}</span>
        </h3>
        <Markdown :class="BODY" :text="b.body_md" />
        <PartsLine :parts="[{ text: 'Supplied by you', style: 'name' }, { text: 'Not drafted and not checked by the tool' }]" />
        <p v-if="b.context" class="text-xs text-muted-foreground md:pl-11">{{ b.context }}</p>
      </article>

      <!-- A paragraph the tool worked out, not drafted: fixed wording around figures, each one a review item. -->
      <article v-else-if="b.kind === 'computed'" :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" :class="HEAD">
          <Numeral>{{ b.numeral }}</Numeral>
          <span>{{ b.title }}</span>
        </h3>
        <Markdown :class="BODY" :text="b.body_md" />
        <PartsLine :parts="computedParts(b)" />
        <p v-for="n in b.notes" :key="n" class="text-xs text-muted-foreground md:pl-11">{{ n }}</p>
      </article>

      <!-- Text copied from the previous issue. It was not written for this week, so it is always flagged. -->
      <article v-else-if="b.kind === 'carried'" :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" class="flex flex-wrap items-start gap-3 text-base font-semibold">
          <Numeral>{{ b.numeral }}</Numeral>
          <span>{{ b.title }}</span>
        </h3>
        <Notice v-if="b.edits?.length" tone="warn" class="font-medium md:ml-11">
          Edited by you, {{ friendlyTime(b.edits[b.edits.length - 1].at) }}. You wrote this paragraph, so the checker has no source for it. It was
          copied from {{ b.carried_from.issue_id ? `issue ${b.carried_from.issue_id}` : "the previous issue" }} before you changed it.
        </Notice>
        <Notice v-else tone="flag" class="font-medium md:ml-11">
          Carried forward, edit before approving. Copied from
          {{ b.carried_from.issue_id ? `issue ${b.carried_from.issue_id} on cytonnreport.com` : "the previous issue"
          }}{{ b.carried_from.published ? `, published ${friendlyDate(b.carried_from.published)}` : "" }}.
        </Notice>
        <Markdown :class="BODY" :text="b.body_md" />
      </article>

      <!-- A chart the tool draws from the analyst workbook: the picture, its facts and its points. Its checks are review
           items in the panel beside the draft; its notices are in the card. -->
      <ChartCard v-else-if="b.kind === 'chart'" :review="review" :block="b" :on-team-chart="onTeamChart" />

      <!-- A part of the real report this tool cannot draft yet. Neutral, not a review-state colour: nothing was checked. -->
      <section v-else :class="PIECE" :aria-labelledby="`blk-${b.id}`">
        <h3 :id="`blk-${b.id}`" class="flex flex-wrap items-center gap-3 text-base font-semibold">
          <Numeral>{{ b.numeral }}</Numeral>
          {{ b.title }}
          <span class="inline-flex items-center gap-1 rounded-full border border-input px-2 py-0.5 text-xs font-semibold text-muted-foreground">
            <PhLockSimple weight="bold" class="size-3" aria-hidden="true" />
            Not available yet
          </span>
        </h3>
        <div class="space-y-2 rounded-md border bg-muted px-4 py-3 text-sm md:ml-11">
          <p>{{ b.reason }}</p>
          <p class="text-muted-foreground"><span class="font-semibold text-foreground">Unblocked by:</span> {{ b.unblock }}</p>
        </div>
      </section>
    </template>

    <section v-if="review.summary" aria-labelledby="summary-title" class="space-y-2 border-t px-4 py-6 sm:px-6">
      <h3 id="summary-title" class="text-base font-semibold">Section summary for the CMS</h3>
      <p class="text-xs text-muted-foreground">
        Composed from this section’s own lead paragraphs; nothing here is newly written. The website builds the issue’s
        Executive Summary from these.
      </p>
      <Markdown class="max-w-[68ch] text-sm leading-6" :text="review.summary" />
    </section>
  </section>
</template>
