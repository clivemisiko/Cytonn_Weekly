import { describe, expect, it } from "vitest";
import { groupNotices, plainReason } from "./extraction";
import type { ExtractionNotice } from "./types";

const SHA = "3f9a".repeat(16);
const notice = (over: Partial<ExtractionNotice> = {}): ExtractionNotice => ({
  source: "CBK Weekly Bulletin",
  issue_date: "2026-10-23",
  sha256: SHA,
  location: "Table 3",
  reason: "Table 3 row '24-Sep-26 01-Oct-26 08-Oct-26 15-Oct-26 22-Oct-26' does not hold deals, value and KESONIA",
  text: "x",
  ...over,
});

describe("plainReason", () => {
  it("words a row that does not hold its figures calmly and keeps the raw row apart", () => {
    const r = plainReason(notice().reason);
    expect(r.reason).toBe("A row in Table 3 does not hold the deals, value and KESONIA figures it should.");
    expect(r.raw).toBe("Row: 24-Sep-26 01-Oct-26 08-Oct-26 15-Oct-26 22-Oct-26");
  });

  it("words a missing heading", () => {
    expect(plainReason("'Table 6:' not found")).toEqual({ reason: 'The heading "Table 6:" was not found in the file.', raw: "" });
  });

  it("shows a reason it has no wording for as written, with a full stop", () => {
    expect(plainReason("KeyError: 'usd'")).toEqual({ reason: "KeyError: 'usd'.", raw: "" });
    expect(plainReason("Table 2 prints 3 dates but 2 reserves and 3 import-cover figures.").reason).toBe(
      "Table 2 prints 3 dates but 2 reserves and 3 import-cover figures.",
    );
  });
});

describe("groupNotices", () => {
  it("puts notices from one file under one header, with the date written out", () => {
    const groups = groupNotices([notice(), notice({ location: "Table 5", reason: "Table 5 has no auction dates" })]);
    expect(groups).toHaveLength(1);
    expect(groups[0].title).toBe("CBK Weekly Bulletin of 23 Oct 2026");
    expect(groups[0].cards.map((c) => c.location)).toEqual(["Table 3", "Table 5"]);
    expect(groups[0].cards[0].fileId).toBe(SHA);
  });

  it("keeps different files in separate groups", () => {
    const groups = groupNotices([notice(), notice({ issue_date: "2026-10-16", sha256: "ab".repeat(32) }), notice({ source: "KCB IB weekly report" })]);
    expect(groups.map((g) => g.title)).toEqual(["CBK Weekly Bulletin of 23 Oct 2026", "CBK Weekly Bulletin of 16 Oct 2026", "KCB IB weekly report of 23 Oct 2026"]);
  });

  it("says so when no issue date was read", () => {
    expect(groupNotices([notice({ issue_date: null })])[0].title).toBe("CBK Weekly Bulletin, no issue date read");
  });

  it("keeps the raw row and the original wording under the technical detail", () => {
    const [card] = groupNotices([notice()])[0].cards;
    expect(card.rawDetail).toContain("Row: 24-Sep-26 01-Oct-26 08-Oct-26 15-Oct-26 22-Oct-26");
    expect(card.rawDetail).toContain("As reported: Table 3 row");
  });

  it("names a table that is not a numbered one as such", () => {
    const [card] = groupNotices([notice({ location: "Government Domestic Debt", reason: "'Government Domestic Debt' table not found" })])[0].cards;
    expect(card.consequence).toBe("The Government Domestic Debt table is not used in this draft. Any part of the draft that needs it is marked unavailable.");
    expect(card.reason).toBe('The "Government Domestic Debt" table was not found in the file.');
  });
});
