import { afterEach, describe, expect, it, vi } from "vitest";
import type { Readiness } from "./chatcards";
import { focusProblems, itemSteps, noDocumentsLine, openingStep, prepareCounts, prepareSteps, readFocus, stepIndex, writeFocus } from "./prepare";
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
