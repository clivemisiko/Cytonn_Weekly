import { describe, expect, it } from "vitest";
import { MAX_SECTIONS, MAX_SECTION_TITLE, sectionsProblem, sectionTitles } from "./topic";

describe("Focus section titles", () => {
  it("drops blank lines, tidies spaces and removes a typed Section N: prefix, as the API does", () => {
    expect(sectionTitles("\n  Overview \n\nSection 3:  Yields   and pricing\nsection IV - Risks\r\nRecommendations and Conclusion")).toEqual([
      "Overview",
      "Yields and pricing",
      "Risks",
      "Recommendations and Conclusion",
    ]);
    expect(sectionsProblem("")).toBeNull();
  });

  it("refuses more than the limit, a title over the limit and an empty one, in the API's words", () => {
    const nine = Array.from({ length: MAX_SECTIONS + 1 }, (_, n) => `Title ${n}`).join("\n");
    expect(sectionsProblem(nine)).toBe("9 section titles; the limit is 8");
    expect(sectionsProblem(`Fine\n${"x".repeat(MAX_SECTION_TITLE + 1)}`)).toBe("section title 2 is 121 characters; the limit is 120");
    expect(sectionsProblem("x".repeat(MAX_SECTION_TITLE))).toBeNull();
    expect(sectionsProblem("Section 2:")).toBe('section title 1 is empty once its "Section N:" prefix is removed');
  });

  it("counts a title in code points, as Python does", () => {
    expect(sectionsProblem("\u{1F600}".repeat(MAX_SECTION_TITLE))).toBeNull();
  });
});
