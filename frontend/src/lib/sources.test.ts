import { describe, expect, it } from "vitest";
import {
  NOT_ON_LIST,
  charsLabel,
  claimSource,
  dateLabel,
  hashPrefix,
  isPaste,
  missingSourcesNote,
  piecesWithoutSources,
  sourceFacts,
  usesSources,
} from "./sources";
import type { SourceMeta, SourcePiece } from "./types";

const source = (over: Partial<SourceMeta> = {}): SourceMeta => ({
  id: "a1b2c3d4",
  subject: "Visa",
  week_end: "2026-11-06",
  url: "https://investor.visa.com/news/1",
  host: "investor.visa.com",
  title: "Visa results",
  published_date: "2026-11-04",
  fetched_at: "2026-11-06T09:00:00+00:00",
  origin: "pasted",
  sha256: "0123456789abcdef".repeat(4),
  chars: 12345,
  flags: [],
  ...over,
});
const piece = (subject: string, sources: SourceMeta[] = []): SourcePiece => ({ subject, end: "2026-11-06", week_end: "2026-11-06", sources });

describe("usesSources", () => {
  it("is on only for Bedrock and a section that calls a provider", () => {
    expect(usesSources({ provider: "bedrock" }, { uses_provider: true })).toBe(true);
    expect(usesSources({ provider: " Bedrock " }, { uses_provider: true })).toBe(true);
    expect(usesSources({ provider: "bedrock" }, { uses_provider: false })).toBe(false);
    expect(usesSources({ provider: "anthropic" }, { uses_provider: true })).toBe(false);
    expect(usesSources({ provider: "local" }, { uses_provider: true })).toBe(false);
  });
});

describe("pieces with no source", () => {
  const pieces = [piece("Visa", [source()]), piece("Mastercard"), piece("Circle")];
  it("lists them in order", () => expect(piecesWithoutSources(pieces)).toEqual(["Mastercard", "Circle"]));
  it("names one", () => expect(missingSourcesNote(["Circle"])).toBe("“Circle” has no sources, so it will come back unavailable."));
  it("names several with a count", () =>
    expect(missingSourcesNote(["Mastercard", "Circle"])).toBe("2 pieces have no sources, so each will come back unavailable: “Mastercard”, “Circle”."));
  it("says nothing when every piece has one", () => {
    expect(missingSourcesNote(piecesWithoutSources([piece("Visa", [source()])]))).toBeNull();
    expect(missingSourcesNote([])).toBeNull();
  });
});

describe("a source's facts", () => {
  it("shows the date, size, when it was saved in East Africa Time, and the fingerprint's first eight characters", () => {
    expect(sourceFacts(source())).toEqual(["4 Nov 2026", "12,345 characters", "pasted 6 Nov 2026, 12:00 EAT", "fingerprint 01234567"]);
  });
  it("says fetched for a fetched page and says so when it has no date", () => {
    const facts = sourceFacts(source({ origin: "fetched", published_date: "" }));
    expect(facts[0]).toBe("no date given");
    expect(facts[2]).toBe("fetched 6 Nov 2026, 12:00 EAT");
  });
  it("has small helpers that agree", () => {
    expect(hashPrefix("abcdef0123456789")).toBe("abcdef01");
    expect(dateLabel("")).toBe("no date given");
    expect(charsLabel(2)).toBe("2 characters");
  });
});

describe("isPaste", () => {
  it("is a fetch for an address alone and a paste once text or a date is typed", () => {
    expect(isPaste({ url: "https://www.imf.org/x" })).toBe(false);
    expect(isPaste({ url: "https://www.imf.org/x", text: "  ", date: " " })).toBe(false);
    expect(isPaste({ url: "https://www.imf.org/x", text: "a" })).toBe(true);
    expect(isPaste({ url: "https://www.imf.org/x", date: "2026-11-05" })).toBe(true);
  });
});

describe("claimSource", () => {
  it("is null for a claim that is not quoted from a supplied source", () => {
    expect(claimSource({ text: "t", url: "u", cited_text: "c" })).toBeNull();
  });
  it("reads the host, date, quote, origin, time and fingerprint, and the off-list flag", () => {
    const got = claimSource({
      source_id: "a1b2c3d4",
      host: "blog.example.com",
      published_date: "2026-09-30",
      cited_text: "paid $5 million",
      origin: "pasted",
      fetched_at: "2026-11-06T09:00:00+00:00",
      sha256: "f".repeat(64),
      source_flags: [NOT_ON_LIST],
    });
    expect(got).toEqual({
      id: "a1b2c3d4",
      host: "blog.example.com",
      date: "30 Sep 2026",
      quote: "paid $5 million",
      origin: "pasted",
      savedAt: "6 Nov 2026, 12:00 EAT",
      fingerprint: "ffffffff",
      flags: [NOT_ON_LIST],
      offList: true,
    });
  });
  it("has no off-list mark when the flags are empty or absent", () => {
    expect(claimSource({ source_id: "x", source_flags: [] })?.offList).toBe(false);
    expect(claimSource({ source_id: "x" })?.offList).toBe(false);
  });
});
