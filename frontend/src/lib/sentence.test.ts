import { describe, expect, it } from "vitest";
import { MAX_SENTENCE, sentenceCheck, sentenceLength, tidy } from "./sentence";

describe("the typed sentence", () => {
  it("is counted as the API stores it: one line, single spaces", () => {
    expect(tidy("  Lending  rose\n to   Sh30.1 billion.  ")).toBe("Lending rose to Sh30.1 billion.");
    expect(sentenceLength("  a \n b ")).toBe(3);
  });

  it("counts a character a person sees once, not twice", () => {
    expect(sentenceLength("Sh 30.1 \u{1F4C8}")).toBe(9);
  });

  it("can be saved at the limit and not one character over", () => {
    expect(sentenceCheck("x".repeat(MAX_SENTENCE), "old").ok).toBe(true);
    const over = sentenceCheck("x".repeat(MAX_SENTENCE + 1), "old");
    expect(over).toMatchObject({ over: 1, ok: false });
  });

  it("cannot be saved empty or unchanged", () => {
    expect(sentenceCheck("   ", "old")).toMatchObject({ empty: true, ok: false });
    expect(sentenceCheck("Lending  rose", "Lending rose")).toMatchObject({ same: true, ok: false });
    expect(sentenceCheck("Lending rose again", "Lending rose")).toMatchObject({ same: false, ok: true });
  });
});
