import { describe, expect, it } from "vitest";
import { ROWS_LABEL, fileNameOf, rowsMessage, rowsWeek } from "./rows";

describe("this week's rows button", () => {
  it("is labelled as the team asked", () => {
    expect(ROWS_LABEL).toBe("This week's rows (xlsx)");
  });

  it("takes the Friday from a weekly period and nothing from any other", () => {
    expect(rowsWeek("Week ending 2026-10-02")).toBe("2026-10-02");
    expect(rowsWeek("")).toBeNull();
    expect(rowsWeek("Weekly #38.2026")).toBeNull();
    expect(rowsWeek("Week ending 2026-10-02 and more")).toBeNull();
  });

  it("puts the 422 and the 409 in plain words, and leaves any other answer as the server gave it", () => {
    expect(rowsMessage(422, "'2026-10-01' is not a Friday")).toBe("That week is not one the report can use. Choose the Friday the week ends on, then try again.");
    expect(rowsMessage(409, "An uploaded workbook cannot be read, so the layout cannot be taken from it: eq.xlsx could not be opened")).toBe(
      "An uploaded workbook cannot be read, so the layout cannot be taken from it: eq.xlsx could not be opened. Upload that workbook again or remove it, then try again.",
    );
    expect(rowsMessage(409, "Already ends.")).toBe("Already ends. Upload that workbook again or remove it, then try again.");
    expect(rowsMessage(null, "Could not reach the report tool's server")).toBe("Could not reach the report tool's server");
    expect(rowsMessage(500, "500 Internal Server Error")).toBe("500 Internal Server Error");
  });
});

describe("the saved file's name", () => {
  it("reads the plain form, the encoded form the server uses for spaces and commas, and falls back", () => {
    expect(fileNameOf('attachment; filename="Cytonn-Weekly-e2e.docx"', "x.docx")).toBe("Cytonn-Weekly-e2e.docx");
    expect(fileNameOf("attachment; filename*=utf-8''Weekly%20rows%2C%20week%20ending%202026-10-09.xlsx", "x.xlsx")).toBe("Weekly rows, week ending 2026-10-09.xlsx");
    expect(fileNameOf("attachment; filename*=utf-8''%E0%A4%A", "x.xlsx")).toBe("x.xlsx");
    expect(fileNameOf(null, "weekly-rows.xlsx")).toBe("weekly-rows.xlsx");
  });
});
