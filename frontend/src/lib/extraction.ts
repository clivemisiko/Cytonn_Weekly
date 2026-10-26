import { friendlyDate } from "./format";
import type { ExtractionNotice } from "./types";

/**
 * Plain wording for a table an input file could not give. The API sends the fields (source, issue date, location, reason);
 * this only words them calmly. A reason it has no wording for is shown as the API wrote it, so nothing is hidden, and the
 * parts that are raw (a row of the file) go to the technical detail.
 */

const sentence = (text: string) => {
  const t = text.trim();
  const s = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(s) ? s : `${s}.`;
};

const unquote = (text: string) => text.replace(/^(['"])(.*)\1$/, "$2");

/** The reason as a calm sentence, and the raw text it quoted from the file (or ""). */
export function plainReason(reason: string): { reason: string; raw: string } {
  let m = /^(Table \d+) row (.+) does not hold (.+)$/.exec(reason);
  if (m) return { reason: `A row in ${m[1]} does not hold the ${m[3]} figures it should.`, raw: `Row: ${unquote(m[2])}` };
  m = /^(Table \d+) row for (.+?) does not hold (\d+) rates like the first row: (.+)$/.exec(reason);
  if (m) return { reason: `The row for ${m[2]} in ${m[1]} does not hold the same ${m[3]} rates as the first row.`, raw: `Row: ${unquote(m[4])}` };
  m = /^(Table \d+) row for (.+?) has (\d+) figures, expected (\d+)$/.exec(reason);
  if (m) return { reason: `The row for ${m[2]} in ${m[1]} has ${m[3]} figures where ${m[4]} are expected.`, raw: "" };
  m = /^'(.+)' not found$/.exec(reason);
  if (m) return { reason: `The heading "${m[1]}" was not found in the file.`, raw: "" };
  m = /^(Table \d+) has no (.+)$/.exec(reason);
  if (m) return { reason: `${m[1]} has no ${m[2]}.`, raw: "" };
  return { reason: sentence(reason), raw: "" };
}

export interface NoticeCard {
  location: string;
  reason: string;
  consequence: string;
  rawDetail: string;
  fileId: string;
}

export interface NoticeGroup {
  key: string;
  /** "CBK Weekly Bulletin of 23 Oct 2026" */
  title: string;
  cards: NoticeCard[];
}

/** Notices grouped by the file they came from, in the order they arrived. */
export function groupNotices(notices: ExtractionNotice[]): NoticeGroup[] {
  const groups = new Map<string, NoticeGroup>();
  for (const n of notices) {
    const key = `${n.source}|${n.issue_date ?? ""}|${n.sha256}`;
    let g = groups.get(key);
    if (!g) {
      g = { key, title: n.issue_date ? `${n.source} of ${friendlyDate(n.issue_date)}` : `${n.source}, no issue date read`, cards: [] };
      groups.set(key, g);
    }
    const plain = plainReason(n.reason);
    g.cards.push({
      location: n.location,
      reason: plain.reason,
      consequence: `${n.location} is not used in this draft. Any part of the draft that needs it is marked unavailable.`,
      rawDetail: [plain.raw, plain.reason === sentence(n.reason) ? "" : `As reported: ${n.reason}`].filter(Boolean).join("\n"),
      fileId: n.sha256,
    });
  }
  return [...groups.values()];
}
