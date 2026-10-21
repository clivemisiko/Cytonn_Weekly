import { describe, expect, it } from "vitest";
import { chartSummary } from "./chart";
import type { ChartBlock } from "./types";

const base: ChartBlock = {
  numeral: "VII",
  kind: "chart",
  id: "chart_nasi_pe",
  chart_id: "nasi_pe",
  title: "NASI P/E chart",
  caption: "The charts below indicate the historical P/E and dividend yields of the market (P/E chart)",
  status: "drawn",
  alt: "An invented chart.",
  points: 60,
  newest_date: "2026-10-02",
  png_sha256: "ab".repeat(32),
  defects: [],
};

describe("chart block fallback", () => {
  it("shows the caption and says a drawn chart was drawn", () => {
    const s = chartSummary(base);
    expect(s.caption).toBe(base.caption);
    expect(s.status).toBe("Drawn");
    expect(s.detail).toContain("60 points read, the newest dated 2026-10-02");
  });

  it("says a chart was not drawn and why, from its first blocking defect", () => {
    const s = chartSummary({
      ...base,
      status: "not_drawn",
      png_sha256: null,
      defects: [
        { kind: "blank_value", message: "Empty value cells", cells: ["B20"], blocking: false },
        { kind: "stale", message: "The newest point is dated 2026-09-25.", cells: ["B8"], blocking: true },
      ],
    });
    expect(s.status).toBe("Not drawn");
    expect(s.detail).toBe("The newest point is dated 2026-09-25. Its checks are under Review items.");
    expect(s.caption).toBe(base.caption);
  });

  it("still says where the checks are when no defect is blocking", () => {
    expect(chartSummary({ ...base, status: "not_drawn" }).detail).toBe("Its checks are under Review items.");
  });
});
