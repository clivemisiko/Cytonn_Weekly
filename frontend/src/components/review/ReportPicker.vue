<script setup lang="ts">
import { PhCaretDown } from "@phosphor-icons/vue";
import { computed, ref, useId } from "vue";
import { useReportChoice } from "@/lib/reportchoice";
import Button from "@/components/ui/Button.vue";
import { weekChoiceLabel } from "@/lib/previous";
import type { CompanionKind, ReportChoice, ReportType, ReportTypeInfo, WeekChoice } from "@/lib/types";

const FIELD =
  "flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag aria-invalid:ring-3 aria-invalid:ring-flag/20";
const CARET = "pointer-events-none absolute top-1/2 right-3 size-3.5 -translate-y-1/2 text-muted-foreground";

const props = defineProps<{
  current: ReportChoice;
  types: ReportTypeInfo[];
  kinds: CompanionKind[];
  /** The weeks to choose from (the coming Friday and the last eight); none hides the selector. */
  weeks?: WeekChoice[];
  /** Resolves to an error message to show beside the period, or null once the overview has switched. */
  onApply: (next: ReportChoice) => Promise<string | null>;
}>();

const id = useId();
const pick = useReportChoice(() => props.current, () => props.types, () => props.kinds);
const { type, period, kind, info, periodLabel, hint } = pick;
const error = ref<string | null>(null);
const busy = ref(false);
const dirty = computed(
  () => type.value !== props.current.type || period.value.trim() !== props.current.period || (type.value === "companion" && kind.value !== props.current.kind),
);

function chooseType(next: ReportType) {
  error.value = null;
  pick.chooseType(next);
}

function chooseKind(next: string) {
  error.value = null;
  pick.chooseKind(next);
}

async function apply() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  const message = await props.onApply(pick.choice());
  busy.value = false;
  error.value = message;
}

const weekInList = computed(() => (props.weeks ?? []).some((w) => w.period === props.current.period));

/** Choosing a week from the list applies it at once, as the address bar would. */
function chooseWeek(next: string) {
  period.value = next;
  void apply();
}

</script>

<template>
  <!-- A compact toolbar under the page heading: the report, its period and (weekly) the week, in one row when there is room. -->
  <form :aria-labelledby="`${id}-title`" class="@container rounded-lg border bg-card px-3 py-2.5" @submit.prevent="apply">
    <h2 :id="`${id}-title`" class="sr-only">Report</h2>
    <div
      class="grid grid-cols-1 items-end gap-x-3 gap-y-2.5 @min-[30rem]:grid-cols-2"
      :class="
        current.type === 'weekly' && weeks?.length
          ? '@min-[40rem]:grid-cols-[minmax(0,0.8fr)_minmax(0,0.8fr)_auto_minmax(0,1.5fr)]'
          : '@min-[41rem]:grid-cols-[minmax(0,16rem)_minmax(0,14rem)_auto]'
      "
    >
      <div class="space-y-1">
        <label :for="`${id}-type`" class="eyebrow block truncate">Report type</label>
        <div class="relative">
          <select :id="`${id}-type`" :value="type" :disabled="busy" :class="[FIELD, 'appearance-none pr-9']" @change="chooseType(($event.target as HTMLSelectElement).value as ReportType)">
            <option v-for="t in types" :key="t.slug" :value="t.slug">{{ t.title }}</option>
          </select>
          <PhCaretDown weight="bold" :class="CARET" aria-hidden="true" />
        </div>
      </div>

      <!-- Its own full-width row: the reports' titles are long, and a native select cannot wrap them. -->
      <div v-if="type === 'companion'" class="space-y-1 @min-[30rem]:col-span-2 @min-[41rem]:col-span-full @min-[41rem]:row-start-2">
        <label :for="`${id}-kind`" class="eyebrow block truncate">Report Edition</label>
        <div class="relative">
          <select :id="`${id}-kind`" :value="kind" :disabled="busy" :class="[FIELD, 'appearance-none pr-9']" @change="chooseKind(($event.target as HTMLSelectElement).value)">
            <option v-for="k in kinds" :key="k.slug" :value="k.slug">{{ k.title }}</option>
          </select>
          <PhCaretDown weight="bold" :class="CARET" aria-hidden="true" />
        </div>
      </div>

      <div class="space-y-1">
        <label :for="`${id}-period`" class="eyebrow block truncate">{{ periodLabel }}</label>
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

      <Button type="submit" :variant="dirty ? 'default' : 'outline'" :disabled="busy" class="h-9 @min-[30rem]:col-span-2 @min-[30rem]:justify-self-start @min-[40rem]:col-span-1">
        {{ busy ? "Loading…" : "Show sections" }}
      </Button>
      <div v-if="current.type === 'weekly' && weeks?.length" class="space-y-1 @min-[30rem]:col-span-2 @min-[40rem]:col-span-1">
      <label :for="`${id}-week`" class="eyebrow block truncate">Week to draft</label>
      <div class="relative">
        <select :id="`${id}-week`" :value="current.period" :disabled="busy" :class="[FIELD, 'appearance-none pr-9']" @change="chooseWeek(($event.target as HTMLSelectElement).value)">
          <option v-if="!weekInList" :value="current.period">{{ current.period || "Unspecified Week (Current Default)" }}</option>
          <option v-for="w in weeks" :key="w.period" :value="w.period">{{ weekChoiceLabel(w) }}</option>
        </select>
        <PhCaretDown weight="bold" :class="CARET" aria-hidden="true" />
      </div>
      </div>
    </div>
    <p :id="`${id}-hint`" :role="error ? 'alert' : undefined" class="pt-1.5 text-xs" :class="error ? 'font-semibold text-flag-fg' : 'text-muted-foreground'">
      {{ error ?? hint }}
    </p>
  </form>
</template>
