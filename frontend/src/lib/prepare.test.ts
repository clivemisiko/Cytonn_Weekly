import { afterEach, describe, expect, it, vi } from "vitest";
import type { Readiness } from "./chatcards";
import { coveredKeys, focusProblems, itemSteps, keepStep, noDocumentsLine, openingStep, prepareCounts, prepareSteps, readFocus, splitSteps, stepIndex, writeFocus } from "./prepare";
import type { AnalystForm, SnipMeta, SnipsListing, SourcePiece } from "./types";

const field = (key: string, kind = "number") => ({ type: "field", key, label: `Fake ${key}`, kind }) as never;
const table = (key: string) => ({ type: "table", key, label: `Fake ${key}`, mode: "paste" }) as never;
const form = (...items: never[]) => ({ groups: [{ section: "x", key: "g", title: "G", items }] }) as unknown as AnalystForm;
const readiness = (groups: Partial<Readiness["groups"]> = {}): Readiness => ({
  section: "x",
  weekEnding: "2031-01-03",
  groups: { needs_analyst: [], carried_or_suggested: [], fetched: [], in_place: [], optional: [], ...groups },
  snips: null,
  sources: null,
  note: null,
});
const snip = (sector: string, confirmed: boolean) => ({ hash: `${sector}${confirmed}`, sector, confirmed, text: "fake", kind: "image" }) as unknown as SnipMeta;
const listing = (...snips: SnipMeta[]) =>
  ({ sectors: [{ id: "land", label: "Land" }, { id: "hotels", label: "Hotels" }, { id: "homes", label: "Homes" }], snips }) as SnipsListing;

describe("the prepare page's steps", () => {
  it("lists every form item: names first, then values, then tables, then the fund table and its lines; fetched tables are left to card 1", () => {
    const f = form(field("pe"), table("universe"), field("large_caps", "names"), table("interbank"), table("mmf"), field("mmf_source", "text"), field("mmf_published", "date"));
    expect(itemSteps(f, true).map((s) => s.key)).toEqual(["large_caps", "pe", "universe", "fund", "mmf_source", "mmf_published"]);
    expect(itemSteps(f, false).map((s) => s.key)).toEqual(["large_caps", "pe", "universe", "mmf_source", "mmf_published"]); // the chat shows the fund card itself
  });
  it("builds a section's steps from its data alone, in one order", () => {
    expect(prepareSteps({ form: null, sectors: [], topic: true, sources: true }).map((s) => s.key)).toEqual(["topic", "titles", "sources"]);
    expect(prepareSteps({ form: null, sectors: [{ id: "land", label: "Land" }], topic: false, sources: false }).map((s) => s.key)).toEqual(["snips:land"]);
    expect(prepareSteps({ form: null, sectors: [], topic: false, sources: false })).toEqual([]);
  });
  it("opens on the step the address names, else the first one still missing, else the first", () => {
    const steps = prepareSteps({ form: form(field("a"), field("b")), sectors: [{ id: "land", label: "Land" }], topic: false, sources: true });
    expect(openingStep(steps, ["b"], "sources")).toBe(3);
    expect(openingStep(steps, ["b"], "snips")).toBe(2);
    expect(openingStep(steps, ["b"], "no_such_step")).toBe(1);
    expect(openingStep(steps, [])).toBe(0);
    expect(stepIndex(steps, null)).toBe(-1);
  });
  it("says where an empty card 1's inputs are instead", () => {
    expect(noDocumentsLine(prepareSteps({ form: null, sectors: [], topic: true, sources: false }))).toMatch(/topic and section titles are typed in the next card/);
    expect(noDocumentsLine(prepareSteps({ form: null, sectors: [{ id: "land", label: "Land" }], topic: false, sources: false }))).toMatch(/snips are added in the next card/);
  });
});

describe("the prepare page's counts", () => {
  it("are the readiness check's own when the page knows nothing more", () => {
    const c = prepareCounts(readiness({ needs_analyst: [{ kind: "field", key: "pe", label: "P/E", why: "x" }], carried_or_suggested: [{ kind: "field", key: "fy", label: "FY", why: "y" }] }), {});
    expect([c.required, c.optional, c.missing]).toEqual([1, 0, ["pe", "fy"]]);
  });
  it("count an unconfirmed snip as required, a sector with none as optional, a confirmed sector as in place", () => {
    const c = prepareCounts(readiness(), { snips: listing(snip("land", false), snip("homes", true)) });
    expect([c.required, c.optional, c.missing]).toEqual([1, 1, ["snips:land"]]);
    expect(c.checklist.find((g) => g.key === "in_place")?.items.map((e) => e.key)).toEqual(["snips:homes"]);
  });
  it("count a piece with no saved source as optional", () => {
    const pieces = [{ subject: "A", sources: [] }, { subject: "B", sources: [{}] }] as unknown as SourcePiece[];
    expect(prepareCounts(readiness(), { sources: pieces }).optional).toBe(1);
  });
  it("count a Focus's topic, and its titles only where the engine needs them", () => {
    expect(prepareCounts(readiness(), { focus: { topic: "", titles: "", bedrock: true } }).missing).toEqual(["topic", "titles"]);
    expect(prepareCounts(readiness(), { focus: { topic: "Fake topic", titles: "", bedrock: false } })).toMatchObject({ required: 0, optional: 1 });
    expect(prepareCounts(readiness(), { focus: { topic: "Fake topic", titles: "One\nTwo", bedrock: true } }).required).toBe(0);
  });
});

describe("Focus of the Week", () => {
  it("names what still stops a draft", () => {
    expect(focusProblems("", "", true)).toEqual(["the topic", "the section titles"]);
    expect(focusProblems("Fake", "", false)).toEqual([]);
    expect(focusProblems("x".repeat(501), "A", true)).toEqual(["a topic of 500 characters or fewer"]);
    expect(focusProblems("Fake", Array.from({ length: 9 }, (_, i) => `T${i}`).join("\n"), true)).toEqual(["section titles within the limits"]);
  });
  afterEach(() => vi.unstubAllGlobals());
  it("mirrors the topic and titles in session storage, and works without it", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("sessionStorage", { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v), removeItem: (k: string) => store.delete(k) });
    writeFocus("Week ending 2031-01-03", "focus", { topic: "Fake topic", titles: "A" });
    expect(readFocus("Week ending 2031-01-03", "focus")).toEqual({ topic: "Fake topic", titles: "A" });
    expect(readFocus("Week ending 2031-01-10", "focus")).toEqual({ topic: "", titles: "" });
    writeFocus("Week ending 2031-01-03", "focus", null);
    expect(readFocus("Week ending 2031-01-03", "focus")).toEqual({ topic: "", titles: "" });
    vi.stubGlobal("sessionStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => {} });
    expect(() => writeFocus("p", "focus", { topic: "x", titles: "" })).not.toThrow();
    expect(readFocus("p", "focus")).toEqual({ topic: "", titles: "" });
  });
});

describe("a carried item the uploaded workbook holds (the API reports it as the workbook's)", () => {
  const entry = (key: string, why: string) => ({ kind: "field", key, label: `Fake ${key}`, why });
  const shape = (needs: boolean, workbook: boolean) =>
    ({ type: "field", key: "fake", value: needs ? "1.0" : null, workbook: workbook ? { value: "2.0", ref: "Fake!B2" } : null, differences: [], carried: needs ? { from: "2031-01-03", note: "", whole: true, cells: {} } : null, needs_confirmation: needs }) as never;
  for (const section of ["fixed_income", "equities"]) {
    it(`${section}: shows the workbook's chip and counts nothing missing; one with no workbook still waits`, async () => {
      const { fieldOrigin } = await import("./analyst");
      expect(fieldOrigin(shape(false, true))).toBe("workbook");
      expect(fieldOrigin(shape(true, false))).toBe("unconfirmed");
      expect(fieldOrigin(shape(false, false))).toBe("empty");
      const r = readiness({ in_place: [entry("held", "from the workbook")], carried_or_suggested: [entry("waits", "carried from last week, not yet confirmed")] });
      const c = prepareCounts({ ...r, section }, {});
      expect(c.required).toBe(0);
      expect(c.missing).toEqual(["waits"]);
    });
  }
});

describe("inputs this week's workbook already answers", () => {
  const book = (key: string, value: string | null, extra: object = {}) =>
    ({ type: "field", key, label: `Fake ${key}`, kind: "number", value: null, workbook: value === null ? null : { value, ref: "Fake!B2" }, workbook_stale: null, differences: [], carried: null, needs_confirmation: false, ...extra }) as never;
  const rows = (key: string, columns: string[], got: Record<string, string>[] | null, extra: object = {}) =>
    ({ type: "table", key, label: `Fake ${key}`, mode: "grid", columns: columns.map((c) => ({ key: c })), fixed_rows: [], rows: null, workbook_rows: got, workbook_ref: got ? "Fake 'Sheet'" : null, workbook_stale: null, differences: [], carried: null, needs_confirmation: false, ...extra }) as never;
  const stale = { workbook_stale: { note: "dated another week", found: "2031-01-02", expected: ["2031-01-09"] } };
  // Each section's form as the API would send it for a week whose workbook is uploaded; the three without a form have none.
  const SECTIONS: { slug: string; form: AnalystForm | null; covered: string[] }[] = [
    {
      slug: "fixed_income",
      form: form(
        book("placements", "9.5"),
        book("liquidity_driver", null),
        book("borrowing_target", null),
        rows("eurobond_issues", ["amount_mn", "maturity", "yield_at_issue"], [{ row: "a", amount_mn: "1,000", maturity: "2031-02-28" }]),
        rows("borrowing_redemptions", ["bond", "amount"], null),
        rows("mmf", ["rank", "fund", "rate"], [{ rank: "1", fund: "Fake Fund", rate: "9.9" }], { workbook_first: true }),
        book("mmf_published", "2031-01-02", { kind: "date" }),
        book("mmf_source", null, { kind: "text" }),
      ),
      covered: ["placements", "fund", "mmf_published"],
    },
    { slug: "equities", form: form(book("large_caps", "Fake Bank", { kind: "names" }), book("pe", "6.1"), book("universe_month_end", null, { kind: "date" })), covered: ["large_caps", "pe"] },
    { slug: "real_estate", form: null, covered: [] },
    { slug: "digital_payments", form: null, covered: [] },
    { slug: "focus", form: null, covered: [] },
  ];
  const stepsOf = (f: AnalystForm | null) => prepareSteps({ form: f, sectors: [], topic: false, sources: true });
  /** The same form with no workbook: what the page held before the upload, or holds after the removal. */
  const f0 = (f: AnalystForm | null) =>
    f && ({ groups: f.groups.map((g) => ({ ...g, items: g.items.map((i) => ({ ...i, ...(i.type === "field" ? { workbook: null } : { workbook_rows: null, workbook_ref: null }) })) })) } as AnalystForm);

  for (const s of SECTIONS) {
    it(`${s.slug}: what the workbook holds leaves the step-through, and the count is of what is left`, () => {
      const all = stepsOf(s.form);
      const covered = coveredKeys(all, s.form);
      expect(covered).toEqual(s.covered);
      const { shown, folded } = splitSteps(all, covered);
      expect(folded.map((x) => x.key)).toEqual(s.covered);
      expect(shown.map((x) => x.key)).toEqual(all.map((x) => x.key).filter((k) => !s.covered.includes(k)));
      expect(shown.length).toBe(all.length - s.covered.length); // the "Step n of N" count
    });

    it(`${s.slug}: overridden, an input goes back into the step-through in its own place`, () => {
      const all = stepsOf(s.form);
      const covered = coveredKeys(all, s.form);
      for (const key of covered) {
        const { shown, folded } = splitSteps(all, covered, [key]);
        expect(folded.map((x) => x.key)).not.toContain(key);
        expect(shown.map((x) => x.key)).toEqual(all.map((x) => x.key).filter((k) => k === key || !covered.includes(k)));
      }
    });

    it(`${s.slug}: with no workbook, or one for another week, nothing is folded and the steps are today's`, () => {
      const strip = (f: AnalystForm | null, more: object) =>
        f && ({ groups: f.groups.map((g) => ({ ...g, items: g.items.map((i) => ({ ...i, ...(i.type === "field" ? { workbook: null } : { workbook_rows: null, workbook_ref: null }), ...more })) })) } as AnalystForm);
      for (const f of [strip(s.form, {}), strip(s.form, stale)]) {
        const all = stepsOf(f);
        expect(coveredKeys(all, f)).toEqual([]);
        expect(splitSteps(all, coveredKeys(all, f)).shown).toEqual(all);
      }
    });

    it(`${s.slug}: a refold after an upload or a removal keeps the step the analyst is on, else opens the first one left`, () => {
      const none = f0(s.form);
      const keys = (f: AnalystForm | null) => splitSteps(stepsOf(f), coveredKeys(stepsOf(f), f)).shown.map((x) => x.key);
      for (const [before, now] of [[keys(none), keys(s.form)], [keys(s.form), keys(none)]]) {
        before.forEach((key, at) => {
          const i = keepStep(before, now, at);
          if (now.includes(key)) expect(now[i]).toBe(key);
          else expect(i).toBe(0);
        });
      }
      // a removal only brings steps back, so the analyst never moves to another step
      keys(s.form).forEach((key, at) => expect(keys(none)[keepStep(keys(s.form), keys(none), at)]).toBe(key));
    });

    it(`${s.slug}: the banner, the readiness check and the step count agree`, () => {
      const all = stepsOf(s.form);
      const covered = coveredKeys(all, s.form);
      const { shown } = splitSteps(all, covered);
      // the readiness route's grouping of the same form: a workbook value is in place, an empty required one is missing
      const items = (s.form?.groups ?? []).flatMap((g) => g.items);
      const held = (i: (typeof items)[number]) => (i.type === "field" ? !!i.workbook : !!i.workbook_rows?.length);
      const entry = (i: (typeof items)[number]) => ({ kind: i.type, key: i.key, label: i.label, why: "fake" });
      const c = prepareCounts(readiness({ in_place: items.filter(held).map(entry), needs_analyst: items.filter((i) => !held(i)).map(entry) }), {});
      expect(c.required).toBe(items.filter((i) => !held(i)).length);
      for (const key of c.missing) expect(covered).not.toContain(key === "mmf" ? "fund" : key);
      const stepKeys = shown.map((x) => x.key);
      for (const key of c.missing) if (all.some((x) => x.key === key)) expect(stepKeys).toContain(key);
      expect(openingStep(shown, c.missing)).toBe(Math.max(stepKeys.findIndex((k) => c.missing.includes(k)), 0));
    });
  }

  it("a table the workbook fills only in part stays a step (the Eurobond issues have no yield at issue in it)", () => {
    const f = form(rows("eurobond_issues", ["amount_mn", "yield_at_issue"], [{ row: "a", amount_mn: "1,000" }]));
    expect(coveredKeys(stepsOf(f), f)).toEqual([]);
    const full = form(rows("eurobond_issues", ["amount_mn", "yield_at_issue"], [{ row: "a", amount_mn: "1,000" }, { row: "b", yield_at_issue: "7.0" }]));
    expect(coveredKeys(stepsOf(full), full)).toEqual(["eurobond_issues"]);
  });

  it("a value still waiting to be confirmed is never folded away", () => {
    const f = form(book("placements", "9.5", { needs_confirmation: true, value: "9.0" }));
    expect(coveredKeys(stepsOf(f), f)).toEqual([]);
  });

  it("a typed override is folded with the workbook's value and its own origin; the typed value is the API's to use", async () => {
    const { fieldOrigin, originLabel } = await import("./analyst");
    const typed = book("placements", "9.5", { value: "9.75", differences: ["typed as 9.75%, but the workbook has 9.5%. The typed value is used."] });
    const f = form(typed);
    expect(coveredKeys(stepsOf(f), f)).toEqual(["placements"]);
    expect(originLabel(fieldOrigin(typed as never), null, undefined, true)).toBe("Typed, differs from the workbook");
  });
});

describe("keepStep", () => {
  it("follows the step by its key, and falls back to the first step when it is folded away", () => {
    expect(keepStep(["a", "b", "c"], ["a", "c"], 2)).toBe(1);
    expect(keepStep(["a", "b", "c"], ["a", "c"], 1)).toBe(0);
    expect(keepStep(["a", "c"], ["a", "b", "c"], 1)).toBe(2);
    expect(keepStep(["a"], [], 0)).toBe(0);
  });
});
