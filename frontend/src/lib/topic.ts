export const MAX_TOPIC = 500;

/**
 * A Focus topic's length as the API counts it (clean_topic in focus/review_run.py): edge whitespace dropped, each run
 * of whitespace counted as one space, then characters counted as code points (an emoji is one, as in Python), which
 * is why this spreads the string instead of reading .length. The API stays the judge; this only keeps the form from
 * disagreeing with it.
 */
export function topicLength(topic: string): number {
  return [...topic.trim().replace(/\s+/g, " ")].length;
}

export const MAX_SECTIONS = 8;
export const MAX_SECTION_TITLE = 120;
const SECTION_PREFIX = /^\s*section\s+(?:\d+|[ivxlcdm]+)\s*[:.\-–—]\s*/i;

/** The section titles typed one per line, as the API cleans them (clean_sections): blank lines dropped, a typed "Section N:" removed. */
export function sectionTitles(text: string): string[] {
  return text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => line.trim().replace(/\s+/g, " ").replace(SECTION_PREFIX, "").trim().replace(/\s+/g, " "));
}

/** Why the titles would be refused, in the API's words (clean_sections), or null. Nothing is ever cut. */
export function sectionsProblem(text: string): string | null {
  const titles = sectionTitles(text);
  const n = titles.findIndex((t) => !t || [...t].length > MAX_SECTION_TITLE);
  if (n >= 0) {
    return titles[n]
      ? `section title ${n + 1} is ${[...titles[n]].length} characters; the limit is ${MAX_SECTION_TITLE}`
      : `section title ${n + 1} is empty once its "Section N:" prefix is removed`;
  }
  return titles.length > MAX_SECTIONS ? `${titles.length} section titles; the limit is ${MAX_SECTIONS}` : null;
}
