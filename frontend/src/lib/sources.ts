import { friendlyDate, friendlyTime } from "./format";
import type { AppConfig, ClaimContext, SectionSummary, SourceInput, SourceMeta, SourcePiece } from "./types";

/** The only provider whose drafts are written from supplied sources (the others search). */
export const SOURCES_PROVIDER = "bedrock";

/** The flag the API puts on pasted text from a host off the approved list; the review shows it as it stands. */
export const NOT_ON_LIST = "host not on the approved list";

export const NO_SOURCES_YET = "No sources yet: this piece will come back unavailable";

/** Whether this section's start screen asks for sources: only when the draft is written from them. */
export const usesSources = (config: Pick<AppConfig, "provider">, section: Pick<SectionSummary, "uses_provider">) =>
  config.provider.trim().toLowerCase() === SOURCES_PROVIDER && section.uses_provider;

/** The pieces that have no source yet, in the order listed. */
export const piecesWithoutSources = (pieces: SourcePiece[]) => pieces.filter((p) => p.sources.length === 0).map((p) => p.subject);

/** What the confirmation says before a draft that has pieces with no sources, or null when every piece has one. */
export function missingSourcesNote(subjects: string[]): string | null {
  if (subjects.length === 0) return null;
  const list = subjects.map((s) => `“${s}”`).join(", ");
  return subjects.length === 1
    ? `${list} has no sources, so it will come back unavailable.`
    : `${subjects.length} pieces have no sources, so each will come back unavailable: ${list}.`;
}

export const hashPrefix = (sha256: string) => sha256.slice(0, 8);

export const dateLabel = (iso: string) => (iso ? friendlyDate(iso) : "no date given");

export const charsLabel = (n: number) => `${n.toLocaleString("en-GB")} characters`;

/** One saved source's facts as separate short strings, for a list. */
export function sourceFacts(s: SourceMeta): string[] {
  return [
    dateLabel(s.published_date),
    charsLabel(s.chars),
    s.origin === "fetched" ? `fetched ${friendlyTime(s.fetched_at)}` : `pasted ${friendlyTime(s.fetched_at)}`,
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
  origin: "fetched" | "pasted";
  savedAt: string;
  fingerprint: string;
  flags: string[];
  offList: boolean;
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
  };
}

/** The Focus's section titles that take sources are the typed ones; with none typed there is nothing to list yet. */
export const NEEDS_TITLES = "Type the section titles in the form below. Each one, except a closing “Recommendations and Conclusion” part, takes its own sources.";

/** A Bedrock draft of a section with no typed titles is refused by the API; the screen says so before the click. */
export const TITLES_REQUIRED = "Amazon Bedrock does not propose section titles, because it has nothing to search. Type them under Sections.";
