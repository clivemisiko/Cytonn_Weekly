import { friendlyDate, friendlyTime } from "./format";
import type { AppConfig, ClaimContext, SectionSummary, SourceInput, SourceMeta, SourcePiece } from "./types";

/** The only provider whose drafts are written from supplied sources (the others search). */
export const SOURCES_PROVIDER = "bedrock";

/** The off_list flag the API puts on a fetched or pasted source from a host that is not a known site; the review shows it as it stands. */
export const NOT_ON_LIST = "host not on the approved list";

/** The hint in every piece's address box. Generic on purpose: the same box serves every section, so it names no site. */
export const ADDRESS_PLACEHOLDER = "www.example.org/the-page";

/** A piece nobody has searched for yet: calm, because a draft searches by itself. */
export const NOT_LOOKED_YET = "Sources are found automatically when you draft.";
export const LOOKING = "Looking for sources…";
/** The only warning a piece gets: a search ran, found nothing, and no source was added. */
export const NOTHING_FOUND = "No sources found for this topic yet. Please provide a web link or paste reference text to ensure it can be drafted.";
/** The search service is not set up: nothing to warn about, only something to know. */
export const SEARCH_NOT_SET_UP = "Automated search is not enabled for this environment. Please provide a web link or paste reference text manually.";

export type PieceState = "has_sources" | "never_looked" | "nothing_found" | "not_set_up";

/** What a piece's sources area says: from its sources and the last look, never from a guess. */
export function pieceState(piece: SourcePiece): PieceState {
  if (piece.sources.length > 0) return "has_sources";
  const look = piece.gather;
  if (!look) return "never_looked";
  return look.searched ? "nothing_found" : "not_set_up";
}

/** Whether this section's start screen asks for sources: only when the draft is written from them. */
export const usesSources = (config: Pick<AppConfig, "provider">, section: Pick<SectionSummary, "uses_provider">) =>
  config.provider.trim().toLowerCase() === SOURCES_PROVIDER && section.uses_provider;

/** The pieces that have no source yet, in the order listed. */
export const piecesWithoutSources = (pieces: SourcePiece[]) => pieces.filter((p) => p.sources.length === 0).map((p) => p.subject);

/** The pieces a search has already looked at and found nothing for, with no source added since: the only ones a draft asks about. */
export const piecesNothingFoundFor = (pieces: SourcePiece[]) => pieces.filter((p) => pieceState(p) === "nothing_found").map((p) => p.subject);

/** What the confirmation says before a draft, or null when no search has found nothing for a piece. */
export function missingSourcesNote(subjects: string[]): string | null {
  if (subjects.length === 0) return null;
  const list = subjects.map((s) => `“${s}”`).join(", ");
  return subjects.length === 1
    ? `${list}: the last search found nothing and no source was added, so it will come back unavailable.`
    : `${subjects.length} pieces: the last search found nothing and no source was added, so each will come back unavailable: ${list}.`;
}

export const hashPrefix = (sha256: string) => sha256.slice(0, 8);

export const dateLabel = (iso: string) => (iso ? friendlyDate(iso) : "no date given");

export const charsLabel = (n: number) => `${n.toLocaleString("en-GB")} characters`;

/** The text_from_search flag the API puts on a found source whose page could not be read: the search service's text was kept instead. */
export const TEXT_FROM_SEARCH = "Text supplied by the search service";

/** How a source came to be saved, in the words of its facts line and the review. */
export const ORIGIN_WORDS = { fetched: "fetched", pasted: "pasted", found: "found automatically" } as const;

/** Where a saved source is read as a styled page; `quote` is highlighted and `review` is the run the Back button returns to. */
export function sourcePageHref(id: string, quote?: string, review?: number): string {
  const q = new URLSearchParams();
  if (quote) q.set("quote", quote);
  if (review !== undefined) q.set("review", String(review));
  const query = q.toString();
  return `/sources/${encodeURIComponent(id)}${query ? `?${query}` : ""}`;
}

// The same tolerance as the quote checker (backend common/checks.normalise_quote): whitespace runs, quotation marks and dashes
// made plain, and nothing else (no case folding, no punctuation removed).
const plainOf = (to: string, ...codes: number[]) => codes.map((c) => [String.fromCodePoint(c), to] as const);
const FOLD: Record<string, string> = Object.fromEntries([
  ...plainOf("'", 0x2018, 0x2019, 0x201a, 0x201b, 0x2032),
  ...plainOf('"', 0x201c, 0x201d, 0x201e, 0x201f, 0x2033),
  ...plainOf("-", 0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212),
]);

function fold(s: string): { text: string; at: number[] } {
  let text = "";
  const at: number[] = []; // for each folded character, where it came from in `s`
  let gap = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (/\s/.test(c)) {
      gap = text.length > 0;
      continue;
    }
    if (gap) {
      text += " ";
      at.push(i);
      gap = false;
    }
    text += FOLD[c] ?? c;
    at.push(i);
  }
  return { text, at };
}

/** Where `quote` is in `text` as saved ([start, end) in `text`), or null when it cannot be found. */
export function locateQuote(text: string, quote: string): { start: number; end: number } | null {
  const q = fold(quote).text;
  if (!q) return null;
  const t = fold(text);
  const i = t.text.indexOf(q);
  return i < 0 ? null : { start: t.at[i], end: t.at[i + q.length - 1] + 1 };
}

/** One saved source's facts as separate short strings, for a list. */
export function sourceFacts(s: SourceMeta): string[] {
  return [
    dateLabel(s.published_date),
    charsLabel(s.chars),
    `${ORIGIN_WORDS[s.origin]} ${friendlyTime(s.fetched_at)}`,
    `fingerprint ${hashPrefix(s.sha256)}`,
  ];
}

/** Whether what was typed is a paste (text or a date given) or a fetch (an address alone), as the API decides it. */
export const isPaste = (input: SourceInput) => !!(input.text?.trim() || input.date?.trim());

/** What the review shows of a claim's source, or null for a claim that is not quoted from a supplied source. */
export interface ClaimSource {
  id: string;
  host: string;
  date: string;
  quote: string;
  origin: "fetched" | "pasted" | "found";
  savedAt: string;
  fingerprint: string;
  flags: string[];
  offList: boolean;
  textFromSearch: boolean;
}

export function claimSource(ctx: ClaimContext): ClaimSource | null {
  if (!ctx.source_id) return null;
  const flags = ctx.source_flags ?? [];
  return {
    id: ctx.source_id,
    host: ctx.host ?? "",
    date: dateLabel(ctx.published_date ?? ""),
    quote: ctx.cited_text ?? "",
    origin: ctx.origin ?? "pasted",
    savedAt: ctx.fetched_at ? friendlyTime(ctx.fetched_at) : "",
    fingerprint: hashPrefix(ctx.sha256 ?? ""),
    flags,
    offList: flags.includes(NOT_ON_LIST),
    textFromSearch: flags.includes(TEXT_FROM_SEARCH),
  };
}

/** The Focus's section titles that take sources are the typed ones; with none typed there is nothing to list yet. */
export const NEEDS_TITLES = "Type the section titles in the form below. Each one, except a closing “Recommendations and Conclusion” part, takes its own sources.";

/** A Bedrock draft of a section with no typed titles is refused by the API; the screen says so before the click. */
export const TITLES_REQUIRED = "Section titles must be specified before drafting. Enter your section titles under Sections above.";

export const ADDRESS_EMPTY = "Please enter the webpage address (URL) to fetch.";
export const ADDRESS_SPACES = "Web addresses cannot contain spaces. Please check the URL and try again.";

// A bare domain or a link without a scheme gets https://; any address that names a scheme is sent as typed, so the API refuses a scheme other than http and https in its own words.
export function normalizeAddress(raw: string): { url: string } | { error: string } {
  const v = raw.trim();
  if (!v) return { error: ADDRESS_EMPTY };
  if (/\s/.test(v)) return { error: ADDRESS_SPACES };
  return { url: /^[a-z][a-z\d+.-]*:\/\//i.test(v) ? v : `https://${v}` };
}
