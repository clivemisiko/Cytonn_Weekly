import { friendlyDate } from "./format";
import type { ChartBlock, ChartSeriesFile } from "./types";

/** The card's state in words (never by colour alone): what the coordinator is looking at and why. */
export function chartState(block: ChartBlock): { key: "team" | "drawn" | "not_drawn" | "no_workbook"; label: string } {
  if (block.status === "no_workbook") return { key: "no_workbook", label: "No workbook uploaded" };
  if (block.use_team_chart) return { key: "team", label: "Using the team's own chart" };
  if (block.status === "drawn") return { key: "drawn", label: "Drawn by the tool" };
  return { key: "not_drawn", label: "Not drawn" };
}

/**
 * One row of facts under the picture, in the order the coordinator checks them. Only for a chart that was drawn: a stale or
 * rejected series still carries its last value and average, but presenting them as the chart's would read as this week's.
 */
export function chartFacts(block: ChartBlock): { label: string; value: string }[] {
  if (block.status !== "drawn" || !block.last_value || !block.average || !block.window || !block.newest_date) return [];
  return [
    { label: "Points read", value: String(block.points) },
    { label: "Window", value: `Up to ${block.window.years} years, ${friendlyDate(block.window.first)} to ${friendlyDate(block.window.last)}` },
    { label: "Newest point", value: friendlyDate(block.newest_date) },
    { label: "Last value", value: block.last_value.display },
    { label: "Average", value: `${block.average.display}, ${block.average.count} points since ${friendlyDate(block.average.first)}` },
  ];
}

/** The line that says where the plotted history comes from (a drawn chart only). */
export function provenanceLine(block: ChartBlock): string {
  const s = block.source;
  if (block.status !== "drawn" || !s) return "";
  const where = `${s.workbook}, '${s.sheet}'${s.cells ? `!${s.cells}` : ""}`;
  return `${s.provenance[0].toUpperCase()}${s.provenance.slice(1)} (${where}).`;
}

/** The choice the coordinator can make on a chart: the button's name, and what it does, in the card's own words. */
export function teamChartAction(block: ChartBlock): { label: string; help: string } {
  return block.use_team_chart
    ? {
        label: "Use the tool's chart again",
        help: "Takes back the choice: this chart's review items are unresolved again and you review the tool's chart as before.",
      }
    : {
        label: "Use the team's own chart",
        help: "Sets the tool's chart aside: its review items are accepted as not used, and the Word file keeps the placeholder for the team's own Excel chart.",
      };
}

/** The points the picture shows (from the window's first day), newest first, as the points table lists them. */
export function plottedPoints(series: ChartSeriesFile, windowFirst: string | null): { date: string; value: string; cell: string }[] {
  return series.points
    .filter(([date]) => !windowFirst || date >= windowFirst)
    .map(([date, , cell, display]) => ({ date, value: display, cell }))
    .reverse();
}

/**
 * What the card says when its picture or its points could not be read from the API (a changed or missing stored file).
 * `subject` carries its own verb: "The picture is", "The plotted points are".
 */
export function pictureProblem(status: number | null, subject: string): string {
  return status === 409
    ? `${subject} not shown: the stored file was changed after the draft, so it no longer matches what this review recorded. Draft the section again.`
    : `${subject} not available: the stored file is missing or the API could not be reached. Draft the section again.`;
}
