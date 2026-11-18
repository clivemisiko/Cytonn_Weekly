import { describe, expect, it } from "vitest";
import { countsLine, listText, parseFundSnip, parseList, whyNotYet, withFix, type FundSnip } from "./fundsnip";

const answer = (over: Record<string, unknown> = {}) => ({
  image: { sha256: "a".repeat(64), type: "png", size: 10 },
  read: true,
  rows: [
    { id: 0, name: "Alpha Fund", currency: "KES", rate: "10.5", group: "keep", list_name: "Alpha Money Market Fund", duplicate: false, unresolved: [] },
    { id: 1, name: "Beta Fund", currency: "KES", rate: null, group: "pending", list_name: null, duplicate: false, unresolved: ["rate"] },
    { id: 2, name: "Gamma Fund", currency: "KES", rate: "9", group: "new", list_name: null, duplicate: false, unresolved: [] },
  ],
  left_out: [{ id: 3, name: "Zeta Bond Fund", why: "by its name" }],
  ignored: [{ id: 4, name: "Eta" }],
  usd: 2,
  typed: [{ fund: "Delta Fund", rate: "8" }],
  not_on_page: ["Omega Fund"],
  unresolved: 1,
  new: 1,
  kept: 1,
  fixes: {},
  settings: { include: ["Alpha Money Market Fund", "Delta Fund"], exclude: [], aliases: {} },
  ...over,
});

describe("the fund snip card's data", () => {
  it("reads the API's answer whole and refuses any other shape", () => {
    const s = parseFundSnip(answer()) as FundSnip;
    expect(s.rows.map((r) => r.group)).toEqual(["keep", "pending", "new"]);
    expect(s.rows[0].listName).toBe("Alpha Money Market Fund");
    expect(s.include).toHaveLength(2);
    expect(parseFundSnip(null)).toBeNull();
    expect(parseFundSnip({ ...answer(), rows: "x" })).toBeNull();
    expect(parseFundSnip({ ...answer(), settings: undefined })).toBeNull();
  });

  it("gives counts only, with the dollar funds named as outside the table", () => {
    expect(countsLine(parseFundSnip(answer()) as FundSnip)).toBe("7 rows read: 1 on the list, 1 to decide, 1 left out, 2 dollar funds (not in the table).");
  });

  it("says each reason Use this table is off, and none when it can be pressed", () => {
    const s = parseFundSnip(answer()) as FundSnip;
    expect(whyNotYet(s, "")).toEqual([
      "1 row has a cell to type or a row to ignore.",
      "1 fund not on the list is still to decide.",
      "The table needs at least 5 funds.",
      "Enter the day the page was published.",
    ]);
    const ok = parseFundSnip(answer({ unresolved: 0, new: 0, kept: 5, typed: [] })) as FundSnip;
    expect(whyNotYet(ok, "2026-10-02")).toEqual([]);
    expect(whyNotYet(ok, "2 Oct")).toEqual(["Enter the day the page was published."]);
    const twice = parseFundSnip(answer({ unresolved: 0, new: 0, kept: 5, typed: [], rows: [{ ...answer().rows[0], duplicate: true }, { ...answer().rows[0], id: 9, duplicate: true }] })) as FundSnip;
    expect(whyNotYet(twice, "2026-10-02")).toEqual(["2 rows are the same list fund: ignore the extra ones."]);
  });

  it("keeps the corrections together and drops one that is emptied", () => {
    const one = withFix({}, 3, { rate: "9.1" });
    const two = withFix(one, 3, { name: "Gamma" });
    expect(two).toEqual({ "3": { rate: "9.1", name: "Gamma" } });
    expect(withFix(two, 3, { rate: "", name: "" })).toEqual({});
    expect(withFix({ "5": { ignore: true } }, 5, { ignore: false })).toEqual({});
  });

  it("round-trips the fund list one name a line, ignoring blank lines and extra spaces", () => {
    expect(parseList("  A  Fund \r\n\r\nB Fund\n")).toEqual(["A Fund", "B Fund"]);
    expect(parseList(listText(["A Fund", "B Fund"]))).toEqual(["A Fund", "B Fund"]);
  });
});
