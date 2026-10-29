import type { ChartUpload } from "./types";

// Asked before a Fixed Income or Equities draft; null when every chart of the section has an image, or it has none.
export function draftChartsNote(charts: ChartUpload[], section: string): string | null {
  const mine = charts.filter((c) => c.section === section);
  const missing = mine.filter((c) => !c.has_image).length;
  if (!missing) return null;
  const verb = missing === 1 ? "has" : "have";
  return `${missing} of ${mine.length} charts ${verb} no image yet. You can draft now and add them later. Draft anyway?`;
}

export function exportChartsNote(missing: number): string | null {
  if (!missing) return null;
  return missing === 1
    ? "1 chart has no image. The Word file will contain a placeholder for it."
    : `${missing} charts have no image. The Word file will contain placeholders for them.`;
}
