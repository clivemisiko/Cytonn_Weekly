import { describe, expect, it } from "vitest";
import { chartFacts, chartState, pictureProblem, plottedPoints, provenanceLine, teamChartAction } from "./chart";
import type { ChartBlock, ChartSeriesFile } from "./types";

const drawn: ChartBlock = {
  numeral: "VII",
  kind: "chart",
  id: "chart_nasi_pe",
  chart_id: "nasi_pe",
  title: "NASI P/E chart",
  caption: "The charts below indicate the historical P/E and dividend yields of the market (P/E chart)",
  status: "drawn",
  unit: "multiple",
  use_team_chart: false,
  reason: null,
  unblock: null,
  alt: "An invented chart.",
  source: { workbook: "Equities workbook", sheet: "NASI-PE & Dividend Yield", provenance: "from the analyst workbook, not verified", cells: "B8:B67" },
  points: 60,
  window: { years: 5, first: "2021-10-08", last: "2026-10-02", points: 260 },
  newest_date: "2026-10-02",
  last_value: { display: "10.0x", value: "10.0", cell: "B8" },
  average: { display: "13.0x", value: "12.95", count: 60, first: "2025-08-15", last: "2026-10-02", cells: "B8:B67", from: "2009-01-01", note: null },
  stated: { cell: "B7", value: "12.95", formula_range: null },
  png_sha256: "ab".repeat(32),
  defects: [],
};
const notDrawn: ChartBlock = { ...drawn, status: "not_drawn", png_sha256: null, alt: null, window: null, last_value: null, average: null };
const noWorkbook: ChartBlock = { ...notDrawn, status: "no_workbook", source: null, points: 0, reason: "No workbook.", unblock: "Upload it." };

describe("chart card state", () => {
  it("names each state in words", () => {
    expect(chartState(drawn)).toEqual({ key: "drawn", label: "Drawn by the tool" });
    expect(chartState(notDrawn)).toEqual({ key: "not_drawn", label: "Not drawn" });
    expect(chartState(noWorkbook)).toEqual({ key: "no_workbook", label: "No workbook uploaded" });
  });

  it("says the team's own chart is in use, for a drawn chart and for one that was not drawn, but never for no workbook", () => {
    expect(chartState({ ...drawn, use_team_chart: true }).label).toBe("Using the team's own chart");
    expect(chartState({ ...notDrawn, use_team_chart: true }).key).toBe("team");
    expect(chartState({ ...noWorkbook, use_team_chart: true }).key).toBe("no_workbook");
  });
});

describe("chart card facts", () => {
  it("lists points, window, newest date, last value and the average with what it covers", () => {
    expect(chartFacts(drawn)).toEqual([
      { label: "Points read", value: "60" },
      { label: "Window", value: "Up to 5 years, 8 Oct 2021 to 2 Oct 2026" },
      { label: "Newest point", value: "2 Oct 2026" },
      { label: "Last value", value: "10.0x" },
      { label: "Average", value: "13.0x, 60 points since 15 Aug 2025" },
    ]);
  });

  it("has no facts for a chart that was not drawn or read, even when its series still carries a last value and an average", () => {
    expect(chartFacts(notDrawn)).toEqual([]);
    expect(chartFacts(noWorkbook)).toEqual([]);
    expect(chartFacts({ ...drawn, status: "not_drawn" })).toEqual([]);
    expect(provenanceLine({ ...drawn, status: "not_drawn" })).toBe("");
  });

  it("says where the history comes from, with the label the tool uses everywhere", () => {
    expect(provenanceLine(drawn)).toBe("From the analyst workbook, not verified (Equities workbook, 'NASI-PE & Dividend Yield'!B8:B67).");
    expect(provenanceLine(noWorkbook)).toBe("");
  });
});

describe("the team's own chart action", () => {
  it("is named as the coordinator reads it, and turns into taking it back", () => {
    expect(teamChartAction(drawn).label).toBe("Use the team's own chart");
    expect(teamChartAction(drawn).help).toContain("Word file keeps the placeholder");
    expect(teamChartAction({ ...drawn, use_team_chart: true }).label).toBe("Use the tool's chart again");
  });
});

describe("plotted points", () => {
  const series: ChartSeriesFile = {
    chart_id: "nasi_pe",
    week_ending: "2026-10-02",
    workbook: "Equities workbook",
    sheet: "NASI-PE & Dividend Yield",
    unit: "multiple",
    points: [
      ["2021-10-01", "9.0", "B9", "9.0x"],
      ["2021-10-08", "9.5", "B8", "9.5x"],
      ["2026-10-02", "10.0", "B7", "10.0x"],
    ],
  };

  it("keeps only the points from the window's first day, newest first, as the tool prints them", () => {
    expect(plottedPoints(series, "2021-10-08")).toEqual([
      { date: "2026-10-02", value: "10.0x", cell: "B7" },
      { date: "2021-10-08", value: "9.5x", cell: "B8" },
    ]);
    expect(plottedPoints(series, null)).toHaveLength(3);
  });
});

describe("picture problems", () => {
  it("tells a changed file from a missing one, in a sentence that reads whole", () => {
    expect(pictureProblem(409, "The picture is")).toMatch(/^The picture is not shown: the stored file was changed after the draft/);
    expect(pictureProblem(404, "The plotted points are")).toMatch(/^The plotted points are not available: the stored file is missing/);
    expect(pictureProblem(null, "The picture is")).toContain("API could not be reached");
  });
});
