import type { ChartBlock } from "./types";

/** What the review screen shows of a chart block until the chart pane exists: its caption, whether it was drawn, and one line. */
export function chartSummary(block: ChartBlock): { caption: string; status: string; detail: string } {
  if (block.status === "drawn") {
    return {
      caption: block.caption,
      status: "Drawn",
      detail: `${block.points} points read, the newest dated ${block.newest_date}. Its checks are under Review items.`,
    };
  }
  const stop = block.defects.find((d) => d.blocking);
  return {
    caption: block.caption,
    status: "Not drawn",
    detail: stop ? `${stop.message} Its checks are under Review items.` : "Its checks are under Review items.",
  };
}
