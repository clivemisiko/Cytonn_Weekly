import { describe, expect, it } from "vitest";
import { canonical, isCarried, linesOf, originLabel, range, rowsOf, tableOrigin } from "./analyst";
import { ApiError, parseProblems } from "./api";
import { draftAgainOff, stateOf, when } from "./drafting";
import { elapsed, friendlyDate, friendlyTime, plural, pyRepr } from "./format";
import { renderMarkdown } from "./markdown";
import { redraftNotes } from "./redraft";
import { mergeEvents, overviewHref, stepLines } from "./run";
import { THEME_SCRIPT } from "./theme-script";
import { MAX_TOPIC, topicLength } from "./topic";
import type { AnalystTable, AppConfig, Drafting, RunEvent, SectionSummary } from "./types";

const event = (seq: number, kind: RunEvent["kind"], label = "", extra: Partial<RunEvent> = {}): RunEvent => ({
  seq,
  kind,
  label,
  detail: null,
  counts: null,
  at: "2026-10-13T10:00:00+00:00",
  ...extra,
});

describe("run steps", () => {
  it("replaces a started line in place with its closing event and spins only the latest open step", () => {
    const lines = stepLines([
      event(1, "run_started"),
      event(2, "source_started", "CBK rates"),
      event(3, "source_finished", "CBK rates"),
      event(4, "piece_started", "T-bills"),
      event(5, "check_started", "T-bills"),
    ]);
    expect(lines.map((l) => [l.text, l.mark, l.active])).toEqual([
      ["Starting the draft.", "done", false],
      ["Fetched CBK rates.", "done", false],
      ["Drafting T-bills.", "working", false],
      ["Checking T-bills.", "working", true],
    ]);
  });

  it("marks the open step failed when the run fails, with the error after the fixed words", () => {
    const lines = stepLines([event(1, "source_started", "Ibuka"), event(2, "run_failed", "", { detail: "The source is down." })]);
    expect(lines.map((l) => [l.text, l.mark])).toEqual([
      ["Fetching Ibuka.", "failed"],
      ["The draft stopped. The source is down.", "failed"],
    ]);
  });

  it("words a check with its counts, and a skipped part with its reason", () => {
    const lines = stepLines([
      event(1, "check_finished", "Table", { counts: { clean: 3, flagged: 1, not_auto_verified: 2 } }),
      event(2, "part_skipped", "MMF yields", { detail: "No source." }),
    ]);
    expect(lines.map((l) => l.text)).toEqual(["Checked Table: 3 clean, 1 flagged, 2 not auto-verified.", "Skipped MMF yields. No source."]);
    expect(lines[1].mark).toBe("skipped");
  });

  it("merges events by seq without duplicates", () => {
    const have = [event(1, "run_started")];
    expect(mergeEvents(have, [event(1, "run_started")])).toBe(have);
    expect(mergeEvents(have, [event(3, "run_finished"), event(2, "piece_finished", "x")]).map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("builds the overview address", () => {
    expect(overviewHref("weekly", "")).toBe("/overview");
    expect(overviewHref("weekly", "Week ending 2026-10-09", 12)).toBe("/overview?report=weekly&period=Week+ending+2026-10-09&review=12");
    expect(overviewHref("quarterly", "Q3'2026")).toBe("/overview?report=quarterly&period=Q3%272026");
  });
});

describe("format", () => {
  it("formats dates, times, durations and Python values", () => {
    expect(friendlyDate("2026-10-02")).toBe("2 Oct 2026");
    expect(friendlyDate("not a date")).toBe("not a date");
    expect(friendlyTime("2026-10-01T13:24:13+00:00")).toBe("1 Oct 2026, 16:24 EAT");
    expect(elapsed(75)).toBe("1:15");
    expect(elapsed(3675)).toBe("1:01:15");
    expect(pyRepr(null)).toBe("None");
    expect(pyRepr("a")).toBe("'a'");
    expect(plural(1, "report section")).toBe("1 report section");
    expect(plural(6, "report section")).toBe("6 report sections");
  });

  it("shows stored UTC times in East Africa Time, whatever the process timezone", () => {
    // Intl is given the zone explicitly, so the process TZ cannot matter; the loop proves it for three zones.
    const original = process.env.TZ;
    try {
      for (const tz of ["UTC", "Africa/Nairobi", "America/Los_Angeles"]) {
        process.env.TZ = tz;
        expect(friendlyTime("2026-10-23T23:30:00+00:00")).toBe("24 Oct 2026, 02:30 EAT");
        expect(friendlyTime("2026-10-23T23:30:00")).toBe("24 Oct 2026, 02:30 EAT"); // no offset: read as UTC
        expect(friendlyTime("2026-10-23T23:30:00.123Z")).toBe("24 Oct 2026, 02:30 EAT");
        expect(friendlyTime("2026-10-23T23:30:00-03:00")).toBe("24 Oct 2026, 05:30 EAT");
        expect(friendlyDate("2026-10-23")).toBe("23 Oct 2026"); // a calendar date keeps its own day
      }
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });

  it("counts a topic as the API does", () => {
    expect(topicLength("  two   words \n")).toBe(9);
    expect(topicLength("😀")).toBe(1);
    expect(MAX_TOPIC).toBe(500);
  });

  it("words the period on a section card", () => {
    expect(when("")).toBe("this week");
    expect(when("Q3'2026")).toBe("for Q3'2026");
    expect(when("Week ending 2026-10-02")).toBe("for w/e 2 Oct 2026");
  });

  it("reads a section's state from its latest run", () => {
    const base = { available: true, latest: null } as unknown as SectionSummary;
    expect(stateOf({ ...base, available: false })).toBe("unavailable");
    expect(stateOf(base)).toBe("not_drafted");
    const run = (over: object) => ({ ...base, latest: { current: true, this_week: true, decision: null, ...over } }) as unknown as SectionSummary;
    expect(stateOf(run({}))).toBe("in_review");
    expect(stateOf(run({ decision: "approved" }))).toBe("approved");
    expect(stateOf(run({ decision: "rejected" }))).toBe("rejected");
    expect(stateOf(run({ current: false }))).toBe("not_drafted");
  });
});

describe("draft again", () => {
  const section = (uses_provider: boolean) => ({ slug: "equities", uses_provider }) as unknown as SectionSummary;
  const config = (provider_problem: string | null) => ({ provider_problem }) as unknown as AppConfig;
  const running = (over: Partial<Drafting> = {}) =>
    ({ slug: "real_estate", title: "Real Estate (Week ending 2026-10-09)", report_type: "weekly", period: "Week ending 2026-10-09", stale: false, ...over }) as Drafting;
  const weekly = { type: "weekly", period: "Week ending 2026-10-09", kind: null } as const;

  it("is off for the same two reasons the draft button is, and only for a section that calls the provider", () => {
    expect(draftAgainOff(section(true), null, config(null), weekly)).toBeNull();
    expect(draftAgainOff(section(true), running(), config(null), weekly)).toBe(
      "Real Estate (Week ending 2026-10-09) is drafting now. Only one draft runs at a time, across every section.",
    );
    expect(draftAgainOff(section(true), running({ slug: "equities", title: "Equities" }), config(null), weekly)).toMatch(/^This section is drafting now/);
    expect(draftAgainOff(section(true), null, config("No key."), weekly)).toBe("No key. Drafting is off until then.");
    // a stuck draft does not hold the slot (the next draft replaces it); a section with no provider is never held up
    expect(draftAgainOff(section(true), running({ stale: true }), config(null), weekly)).toBeNull();
    expect(draftAgainOff(section(false), running(), config("No key."), weekly)).toBeNull();
  });

  it("tells a coordinator what happens to the earlier review, and about the export only after an approval", () => {
    expect(redraftNotes({ run_id: 7, decision: "rejected" }, "weekly", false)).toEqual([
      "The earlier review (run 7, rejected) stays saved and read-only.",
      "The new draft becomes the current one and starts undecided.",
    ]);
    expect(redraftNotes({ run_id: 8, decision: null }, "weekly", false)[0]).toMatch(/run 8\) was still in review\. It stays saved as it is, undecided/);
    const approved = redraftNotes({ run_id: 9, decision: "approved" }, "weekly", false);
    expect(approved).toHaveLength(3);
    expect(approved[2]).toBe("This section is approved now. The weekly export needs it approved again.");
    expect(redraftNotes({ run_id: 9, decision: "approved" }, "quarterly", false)[2]).toMatch(/^This section is approved now\. The Executive Summary needs it approved again/);
    expect(redraftNotes({ run_id: 9, decision: "approved" }, "quarterly", true)).toHaveLength(2); // the summary itself composes the others
  });
});

describe("analyst form helpers", () => {
  const table = (over: Partial<AnalystTable>): AnalystTable =>
    ({
      key: "coverage",
      label: "Coverage",
      columns: [
        { key: "company", label: "Company", kind: "text", unit: "" },
        { key: "price", label: "Price", kind: "number", unit: "Kshs" },
        { key: "target", label: "Target", kind: "number", unit: "Kshs" },
      ],
      fixed_rows: [],
      rows: null,
      workbook_rows: null,
      auto_rows: null,
      differences: [],
      carried: null,
      needs_confirmation: false,
      ...over,
    }) as unknown as AnalystTable;

  it("lists typed rows first, then the workbook's other rows, with KCB's price ahead of the workbook's", () => {
    const item = table({
      rows: [{ company: "Alpha", target: "12" }],
      workbook_rows: [
        { company: "alpha ", price: "10", target: "11" },
        { company: "Beta", price: "20" },
      ],
      auto_rows: [{ company: "Alpha", price: "10.5" }],
    });
    const lines = linesOf(item);
    expect(lines.map((l) => [l.label, l.listed])).toEqual([
      ["Alpha", true],
      ["Beta", true],
    ]);
    expect(lines[0].book).toMatchObject({ price: "10.5", target: "11" });
    // Only what was typed is sent: the untouched workbook row is not.
    expect(rowsOf(item, lines)).toEqual([{ company: "Alpha", target: "12" }]);
    expect(canonical(item, rowsOf(item, lines))).toBe(canonical(item, item.rows ?? []));
  });

  it("sends a fixed grid's rows by their key and leaves empty ones out", () => {
    const item = table({ fixed_rows: [{ key: "y2034", label: "2034" }, { key: "y2048", label: "2048" }] as AnalystTable["fixed_rows"] });
    const lines = linesOf(item);
    lines[1].typed.price = " 9.1 ";
    expect(rowsOf(item, lines)).toEqual([{ row: "y2048", price: "9.1" }]);
  });

  it("names where a value comes from", () => {
    expect(tableOrigin(table({}))).toBe("empty");
    expect(tableOrigin(table({ workbook_rows: [{ company: "A" }] }))).toBe("workbook");
    expect(tableOrigin(table({ rows: [{ company: "A" }], differences: ["x"] }))).toBe("differs");
    const carried = { from: "2026-10-02", whole: true, cells: {}, note: null } as unknown as NonNullable<AnalystTable["carried"]>;
    expect(originLabel("unconfirmed", carried, "3 rows")).toBe("Carried from week ending 2 Oct 2026, 3 rows, not confirmed");
    expect(originLabel("typed", null)).toBe("Typed");
    expect(originLabel("differs", null, "1 row")).toBe("Typed, 1 row, differs from the workbook");
    expect(range(1, 40, "%")).toBe("1 to 40%");
    expect(range(1, 5000, "Kshs bn")).toBe("1 to 5,000 Kshs bn");
    expect(range(null, 40, "%")).toBe("");
  });

  it("shows a cell as carried only while it still holds the carried value", () => {
    const carried = { from: "2026-10-02", whole: false, cells: { Alpha: ["target"] }, note: null } as unknown as NonNullable<AnalystTable["carried"]>;
    const item = table({ rows: [{ company: "Alpha", target: "12", price: "10" }], carried });
    const [line] = linesOf(item);
    expect(isCarried(item, line, "target")).toBe(true);
    expect(isCarried(item, line, "price")).toBe(false);
    line.typed.target = "13";
    expect(isCarried(item, line, "target")).toBe(false);
  });
});

describe("markdown", () => {
  it("renders links to open in a new tab and never renders raw HTML or an unsafe link", () => {
    const html = renderMarkdown('**Bold** [source](https://example.com/a) <script>alert(1)</script> [bad](javascript:alert(1))');
    expect(html).toContain("<strong>Bold</strong>");
    expect(html).toContain('<a href="https://example.com/a" target="_blank" rel="noopener noreferrer"');
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain('href="javascript:');
  });
});

describe("markdown, what must never render", () => {
  it("drops every unsafe link and image address, raw tags and autolinks, and adds nothing GFM", () => {
    const html = renderMarkdown(
      [
        "![x](javascript:alert(1))",
        "[a](vbscript:msgbox(1)) [b](data:text/html,<b>x</b>) [c](JaVaScRiPt:alert(1))",
        "<javascript:alert(1)>",
        '<a href="https://example.com" onclick="x()">raw</a> <img src=x onerror=alert(1)>',
        "~~struck~~ https://bare.example.com",
        "[ok](/relative) [mail](mailto:a@example.com)",
      ].join("\n\n"),
    );
    expect(html).not.toMatch(/(href|src)="(javascript|vbscript|data):/i);
    expect(html).not.toMatch(/<(img|a) [^>]*on[a-z]+=/i); // no tag carries an event handler
    expect(html).not.toContain("<a href=\"https://example.com\" onclick");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<del>"); // CommonMark only: no GFM strikethrough
    expect(html).not.toContain('href="https://bare.example.com"');
    expect(html).toContain('<a href="/relative" target="_blank" rel="noopener noreferrer"');
    expect(html).toContain('<a href="mailto:a@example.com" target="_blank" rel="noopener noreferrer"');
    // Every link that does render opens in a new tab without handing over the opener.
    for (const tag of html.match(/<a [^>]*>/g) ?? []) expect(tag).toContain('target="_blank" rel="noopener noreferrer"');
  });
});

describe("theme script", () => {
  it("only ever restores light or dark, inside a try", () => {
    expect(THEME_SCRIPT).toContain('localStorage.getItem("cytonn-theme")');
    expect(THEME_SCRIPT.startsWith("try{")).toBe(true);
    expect(THEME_SCRIPT).toContain('t==="light"||t==="dark"');
  });
});

describe("parseProblems", () => {
  const ok = { code: "upload_refused", headline: "A file was not added", target: "inputs-panel" };

  it("reads a well formed list, and a missing target as null", () => {
    expect(parseProblems({ detail: "x", problems: [ok, { code: "run_unknown", headline: "Gone" }] })).toEqual([ok, { code: "run_unknown", headline: "Gone", target: null }]);
  });

  it("is empty when the body has no problems, or no body", () => {
    expect(parseProblems({ detail: "x" })).toEqual([]);
    expect(parseProblems(null)).toEqual([]);
    expect(parseProblems("text")).toEqual([]);
  });

  it("ignores a malformed list whole", () => {
    expect(parseProblems({ problems: "nope" })).toEqual([]);
    expect(parseProblems({ problems: [ok, { headline: "no code" }] })).toEqual([]);
    expect(parseProblems({ problems: [ok, { code: "c", headline: 3 }] })).toEqual([]);
    expect(parseProblems({ problems: [{ ...ok, target: 7 }] })).toEqual([]);
    expect(parseProblems({ problems: [null] })).toEqual([]);
  });

  it("rides on an ApiError, empty by default", () => {
    expect(new ApiError("m", 409, [ok]).problems).toEqual([ok]);
    expect(new ApiError("m", null).problems).toEqual([]);
  });
});
