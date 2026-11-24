import { computed, ref } from "vue";
import type { CompanionKind, ReportChoice, ReportType, ReportTypeInfo } from "./types";

/**
 * The report picker's choice before it is applied: the type, its period or issue and (companion) the edition, with the
 * period each type suggests, the label of its field and the line under it. The overview's picker and the section chooser
 * both use it, so a type changes its control the same way in both.
 */
export function useReportChoice(current: () => ReportChoice, types: () => ReportTypeInfo[], kinds: () => CompanionKind[]) {
  const type = ref<ReportType>(current().type);
  const period = ref(current().period);
  const kind = ref(current().kind ?? kinds()[0]?.slug ?? "");
  const info = computed(() => types().find((t) => t.slug === type.value));
  const issueOf = (slug: string) => kinds().find((k) => k.slug === slug)?.issue ?? "";

  function chooseType(next: ReportType) {
    type.value = next;
    const now = current();
    if (next === now.type) period.value = now.period;
    // A companion report has no "period just ended": it rides with the weekly issue its kind was published in.
    else if (next === "companion") {
      // The editions may have arrived after this was set up (the chooser reads them with the report).
      if (!kinds().some((k) => k.slug === kind.value)) kind.value = kinds()[0]?.slug ?? "";
      period.value = issueOf(kind.value);
    }
    else period.value = types().find((t) => t.slug === next)?.suggested_period ?? "";
  }

  /** Another companion report: its own issue replaces the last one's, unless the analyst typed a different one. */
  function chooseKind(next: string) {
    const before = kind.value;
    kind.value = next;
    if (!period.value.trim() || period.value.trim() === issueOf(before)) period.value = issueOf(next);
  }

  const periodLabel = computed(() => (type.value === "companion" ? "Associated Weekly Report Issue" : info.value?.period_required ? "Period" : "Issue (optional)"));
  const hint = computed(() => {
    if (type.value === "companion") {
      const k = kinds().find((x) => x.slug === kind.value);
      return k ? `${k.title} ran as the Focus of the Week of Cytonn ${k.issue} (${k.published}).` : "";
    }
    return info.value ? `Structure verified against ${info.value.published_as}.` : "";
  });
  const choice = (): ReportChoice => ({ type: type.value, period: period.value.trim(), kind: type.value === "companion" ? kind.value : null });

  return { type, period, kind, info, chooseType, chooseKind, periodLabel, hint, choice };
}
