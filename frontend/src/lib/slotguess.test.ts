import { describe, expect, it } from "vitest";
import { type Readiness, parseReadiness, sourceRows } from "./chatcards";
import { prepareCounts } from "./prepare";
import { friendlyDate } from "./format";
import { bankRows, guessSlot } from "./slotguess";
import type { InputFile } from "./types";

const ON = ["equities_workbook", "kcb_daily", "kcb_weekly", "cbk_bulletin", "bank_results"];
const OFF = ON.slice(0, -1);

describe("the dropzone's file-name rule", () => {
  it.each([
    ["Co-op-Bank-Financial-Statements-Q3-2026.pdf", "bank_results"],
    ["equity-group-unaudited-financial-results-sep-2026.pdf", "bank_results"],
    ["KCB Group Results 30 Sep 2026.pdf", "bank_results"],
    ["KCB IB Daily Trading Report 2026-11-20.pdf", "kcb_daily"],
    ["KCB IB Weekly Trading Report.pdf", "kcb_weekly"],
    ["weekly-results-summary.pdf", "kcb_weekly"],
    ["daily results.pdf", "kcb_daily"],
    ["CBK Weekly Bulletin results.pdf", "cbk_bulletin"],
    ["Equities Workbook.xlsx", "equities_workbook"],
    ["results.xlsx", null],
  ])("%s goes to %s", (name, slot) => {
    expect(guessSlot(name, ON)).toBe(slot);
  });
  it("keeps the old rules when the results slot is not offered", () => {
    expect(guessSlot("equity-group-results.pdf", OFF)).toBe("equities_workbook");
    expect(guessSlot("Co-op-Bank-Financial-Statements.pdf", OFF)).toBeNull();
    expect(guessSlot("KCB IB Daily Trading Report.pdf", OFF)).toBe("kcb_daily");
  });
});

const file = (over: Partial<InputFile>): InputFile => ({
  stored_name: "bank_results_kcb.pdf", read_date: "2026-09-30", matches: true, note: "", size: 1, original_name: "kcb.pdf", received_at: "", fetched_from: null,
  read: { bank: "Fake Bank", ticker: "FAKE", period: "2026-09-30", entities: ["GROUP"], group_entity: "GROUP", checks_passed: true, flag_count: 0, flags: [], replaced: null },
  ...over,
});

describe("the bank results rows", () => {
  it("shows bank, period and read ok, read with N flags (named), or refused with the reason", () => {
    const flagged = file({ stored_name: "bank_results_x.pdf", read: { ...file({}).read!, bank: "Other Fake", checks_passed: false, flag_count: 2, flags: ["GROUP, 30 Sep 2026: a", "GROUP, 30 Jun 2026: b"] } });
    const rows = bankRows([file({}), flagged], [{ name: "scan.pdf", reason: "Bank results: this is a scanned page" }]);
    expect(rows.map((r) => [r.bank, r.period, r.status, r.stored])).toEqual([
      ["Fake Bank", `Period ended ${friendlyDate("2026-09-30")}`, "Read OK", "bank_results_kcb.pdf"],
      ["Other Fake", `Period ended ${friendlyDate("2026-09-30")}`, "Read with 2 flags", "bank_results_x.pdf"],
      ["scan.pdf", "", "Refused: Bank results: this is a scanned page", null],
    ]);
    expect(rows[1].flags).toHaveLength(2);
  });
});

describe("the readiness rule for bank results", () => {
  const entry = (why: string) => ({ kind: "upload", key: "bank_results", label: "Bank results", why, many: true });
  const r = (groups: Partial<Readiness["groups"]>) =>
    parseReadiness({ section: "equities", week_ending: "2026-11-20", groups: { needs_analyst: [], carried_or_suggested: [], fetched: [], in_place: [], optional: [], ...groups } })!;
  it("is never required, never blocks, and is not a table row", () => {
    for (const got of [r({ optional: [entry("not uploaded")] }), r({ in_place: [entry("2 files uploaded")] })]) {
      const c = prepareCounts(got, {});
      expect(c.required).toBe(0);
      expect(c.missing).not.toContain("bank_results");
      expect(sourceRows(got)).toEqual([]);
    }
    expect(r({ optional: [entry("not uploaded")] }).groups.optional[0].many).toBe(true);
  });
});
