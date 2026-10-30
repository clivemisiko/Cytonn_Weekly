import { describe, expect, it } from "vitest";
import { draftChartsNote, exportChartsNote } from "./charts";
import type { ChartUpload } from "./types";

const slot = (key: string, section: string, has_image: boolean): ChartUpload => ({
  key, section, title: key, default_lead_in: "", lead_in: "", source: "", has_image, type: has_image ? "png" : null, size: has_image ? 1 : null,
});
const FI = ["a", "b", "c", "d", "e", "f"].map((k, i) => slot(k, "fixed_income", i < 3));
const EQ = [slot("g", "equities", true), slot("h", "equities", false)];

describe("draftChartsNote", () => {
  it("counts only the section's own charts", () => {
    expect(draftChartsNote([...FI, ...EQ], "fixed_income")).toBe(
      "3 of 6 charts have no image yet. You can draft now and add them later. Draft anyway?",
    );
    expect(draftChartsNote([...FI, ...EQ], "equities")).toBe(
      "1 of 2 charts has no image yet. You can draft now and add them later. Draft anyway?",
    );
  });
  it("asks nothing when every chart has an image or the section has none", () => {
    expect(draftChartsNote([slot("g", "equities", true)], "equities")).toBeNull();
    expect(draftChartsNote([...FI, ...EQ], "real_estate")).toBeNull();
  });
});

describe("exportChartsNote", () => {
  it("says how many placeholders the Word file will hold", () => {
    expect(exportChartsNote(2)).toBe("2 charts have no image. The Word file will contain placeholders for them.");
    expect(exportChartsNote(1)).toBe("1 chart has no image. The Word file will contain a placeholder for it.");
    expect(exportChartsNote(0)).toBeNull();
  });
});
