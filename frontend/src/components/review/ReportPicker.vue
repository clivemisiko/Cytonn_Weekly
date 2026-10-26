<script setup lang="ts">
import { PhCaretDown } from "@phosphor-icons/vue";
import { computed, ref, useId } from "vue";
import Button from "@/components/ui/Button.vue";
import type { CompanionKind, ReportChoice, ReportType, ReportTypeInfo } from "@/lib/types";

const FIELD =
  "flex h-10 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag aria-invalid:ring-3 aria-invalid:ring-flag/20";
const CARET = "pointer-events-none absolute top-1/2 right-3 size-3.5 -translate-y-1/2 text-muted-foreground";

const props = defineProps<{
  current: ReportChoice;
  types: ReportTypeInfo[];
  kinds: CompanionKind[];
  /** Resolves to an error message to show beside the period, or null once the overview has switched. */
  onApply: (next: ReportChoice) => Promise<string | null>;
}>();

const id = useId();
const type = ref<ReportType>(props.current.type);
const period = ref(props.current.period);
const kind = ref(props.current.kind ?? props.kinds[0]?.slug ?? "");
const error = ref<string | null>(null);
const busy = ref(false);
const info = computed(() => props.types.find((t) => t.slug === type.value));
const issueOf = (slug: string) => props.kinds.find((k) => k.slug === slug)?.issue ?? "";
const dirty = computed(
  () => type.value !== props.current.type || period.value.trim() !== props.current.period || (type.value === "companion" && kind.value !== props.current.kind),
);

function chooseType(next: ReportType) {
  type.value = next;
  error.value = null;
  const nextInfo = props.types.find((t) => t.slug === next);
  if (next === props.current.type) period.value = props.current.period;
  // A companion report has no "period just ended": it rides with the weekly issue its kind was published in.
  else if (next === "companion") period.value = issueOf(kind.value);
  else period.value = nextInfo?.suggested_period ?? "";
}

/** Another companion report: its own issue replaces the last one's, unless the coordinator typed a different one. */
function chooseKind(next: string) {
  const before = kind.value;
  kind.value = next;
  error.value = null;
  if (!period.value.trim() || period.value.trim() === issueOf(before)) period.value = issueOf(next);
}

async function apply() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  const message = await props.onApply({ type: type.value, period: period.value.trim(), kind: type.value === "companion" ? kind.value : null });
  busy.value = false;
  error.value = message;
}

const periodLabel = computed(() => (type.value === "companion" ? "Weekly issue it rides with" : info.value?.period_required ? "Period" : "Issue (optional)"));
const hint = computed(() => {
  if (type.value === "companion") {
    const k = props.kinds.find((x) => x.slug === kind.value);
    return k ? `${k.title} ran as the Focus of the Week of Cytonn ${k.issue} (${k.published}).` : "";
  }
  return info.value ? `Structure verified against ${info.value.published_as}.` : "";
});
</script>

<template>
  <form :aria-labelledby="`${id}-title`" class="@container rounded-xl border border-border bg-card p-4.5 shadow-xs sm:p-6" @submit.prevent="apply">
    <h2 :id="`${id}-title`" class="eyebrow flex items-center gap-2 pb-3">
      <span class="size-1.5 rounded-full bg-primary" aria-hidden="true" />
      Report
    </h2>
    <div class="grid grid-cols-1 items-end gap-4 @min-[30rem]:grid-cols-2 @min-[41rem]:grid-cols-[minmax(0,16rem)_minmax(0,14rem)_auto]">
      <div class="space-y-1">
        <label :for="`${id}-type`" class="text-sm font-semibold">Report type</label>
        <div class="relative">
          <select :id="`${id}-type`" :value="type" :disabled="busy" :class="[FIELD, 'appearance-none pr-9']" @change="chooseType(($event.target as HTMLSelectElement).value as ReportType)">
            <option v-for="t in types" :key="t.slug" :value="t.slug">{{ t.title }}</option>
          </select>
          <PhCaretDown weight="bold" :class="CARET" aria-hidden="true" />
        </div>
      </div>

      <!-- Its own full-width row: the reports' titles are long, and a native select cannot wrap them. -->
      <div v-if="type === 'companion'" class="space-y-1 @min-[30rem]:col-span-2 @min-[41rem]:col-span-full @min-[41rem]:row-start-2">
        <label :for="`${id}-kind`" class="text-sm font-semibold">Which report</label>
        <div class="relative">
          <select :id="`${id}-kind`" :value="kind" :disabled="busy" :class="[FIELD, 'appearance-none pr-9']" @change="chooseKind(($event.target as HTMLSelectElement).value)">
            <option v-for="k in kinds" :key="k.slug" :value="k.slug">{{ k.title }}</option>
          </select>
          <PhCaretDown weight="bold" :class="CARET" aria-hidden="true" />
        </div>
      </div>

      <div class="space-y-1">
        <label :for="`${id}-period`" class="text-sm font-semibold">{{ periodLabel }}</label>
        <input
          :id="`${id}-period`"
          v-model="period"
          name="period"
          type="text"
          autocomplete="off"
          spellcheck="false"
          maxlength="40"
          :disabled="busy"
          :placeholder="info?.period_hint ?? ''"
          :aria-invalid="error ? true : undefined"
          :aria-describedby="`${id}-hint`"
          :class="[FIELD, 'font-mono']"
          @input="error = null"
        />
      </div>

      <Button type="submit" size="lg" :variant="dirty ? 'default' : 'outline'" :disabled="busy" class="@min-[30rem]:col-span-2 @min-[30rem]:justify-self-start @min-[41rem]:col-span-1">
        {{ busy ? "Loading…" : "Show sections" }}
      </Button>
    </div>
    <p :id="`${id}-hint`" :role="error ? 'alert' : undefined" class="pt-2 text-xs" :class="error ? 'font-semibold text-flag-fg' : 'text-muted-foreground'">
      {{ error ?? hint }}
    </p>
  </form>
</template>
