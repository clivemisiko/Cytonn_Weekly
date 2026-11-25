import { describe, expect, it } from "vitest";
import { shownFigure, workbookShown } from "./analyst";
import type { AnalystField } from "./types";

const field = (value: string | string[], kind: AnalystField["kind"] = "number") =>
  ({ type: "field", key: "k", kind, workbook: { value, ref: "Sheet!A1" } }) as unknown as AnalystField;

describe("shownFigure, display only", () => {
  it("rounds a long decimal to 2 places, half up on its digits", () => {
    expect(shownFigure("4348.32363745")).toBe("4348.32");
    expect(shownFigure("620.256924482")).toBe("620.26");
    expect(shownFigure("11.1630994664")).toBe("11.16");
    expect(shownFigure("2.225")).toBe("2.23");
    expect(shownFigure("9.995")).toBe("10.00");
    expect(shownFigure("-1.005")).toBe("-1.01");
    expect(shownFigure("-0.001")).toBe("0.00");
  });
  it("leaves short decimals, integers, dates, names and text as they are", () => {
    expect(shownFigure("9.5")).toBe("9.5");
    expect(shownFigure("9.75")).toBe("9.75");
    expect(shownFigure("919")).toBe("919");
    expect(shownFigure("2026-11-13", "date")).toBe("2026-11-13");
    expect(shownFigure("1.23456", "text")).toBe("1.23456");
    expect(shownFigure("")).toBe("");
  });
  it("never changes the value it is given", () => {
    const item = field("4348.32363745");
    expect(workbookShown(item)).toBe("4348.32");
    expect(item.workbook!.value).toBe("4348.32363745");
    expect(workbookShown(field(["Safaricom", "Equity Group"], "names"))).toBe("Safaricom, Equity Group");
  });
});
