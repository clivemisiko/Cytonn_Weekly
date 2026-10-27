import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { canShow, dialogProblem, dismiss, firstActionable, HIGHLIGHT, highlight, needsScroll, PLACEMENT, placementOf, raise, TARGETS } from "./attention";

// The backend's own table (backend/api/problems.py): the frontend's placements must cover exactly its codes and targets.
const python = readFileSync(new URL("../../../backend/api/problems.py", import.meta.url), "utf-8");
const table = python.slice(python.indexOf("PROBLEMS:"), python.indexOf("class ProblemError"));
const backendCodes = [...table.matchAll(/^\s+"([a-z_]+)": \(/gm)].map((m) => m[1]);
const backendTargets = [...(python.match(/^TARGETS = \(([^)]*)\)/m)?.[1] ?? "").matchAll(/"([a-z-]+)"/g)].map((m) => m[1]);

const problem = (code: string, target: string | null = "start-draft") => ({ code, headline: code, target });

describe("attention placements", () => {
  it("cover exactly the backend's problem codes", () => {
    expect(backendCodes.length).toBe(34);
    expect(Object.keys(PLACEMENT).sort()).toEqual([...backendCodes].sort());
  });

  it("name the same targets as the backend", () => {
    expect([...TARGETS].sort()).toEqual([...backendTargets].sort());
  });

  it("put the two full-page states nowhere and the whole-action failures in a dialog", () => {
    expect(placementOf("review_not_found")).toBe("none");
    expect(placementOf("run_unknown")).toBe("none");
    expect(placementOf("review_already_decided")).toBe("dialog");
    expect(placementOf("bulletin_fetch_failed")).toBe("inline");
    expect(placementOf("a_code_from_a_newer_backend")).toBe("none");
  });

  it("act on the first problem that has a placement", () => {
    expect(firstActionable([])).toBeNull();
    expect(firstActionable([problem("run_unknown", null), problem("draft_busy")])?.code).toBe("draft_busy");
    expect(firstActionable([problem("not_known")])).toBeNull();
  });
});

describe("needsScroll", () => {
  it("is false for a box wholly in the band below the sticky bars", () => {
    expect(needsScroll({ top: 100, bottom: 300 }, 800, 60)).toBe(false);
  });

  it("is true for a box above the band, under the bars, or past the foot", () => {
    expect(needsScroll({ top: -50, bottom: 40 }, 800, 60)).toBe(true);
    expect(needsScroll({ top: 30, bottom: 200 }, 800, 60)).toBe(true);
    expect(needsScroll({ top: 700, bottom: 900 }, 800, 60)).toBe(true);
  });
});

describe("raise", () => {
  it("opens the dialog for a dialog problem and replaces, never stacks", () => {
    dismiss();
    raise([problem("draft_busy")]);
    expect(dialogProblem.value?.code).toBe("draft_busy");
    raise([problem("review_already_decided", "review-status-bar")]);
    expect(dialogProblem.value?.code).toBe("review_already_decided");
    dismiss();
    expect(dialogProblem.value).toBeNull();
  });

  it("opens no dialog for an inline problem, a full-page one or none", () => {
    dismiss();
    raise([]);
    raise([problem("run_unknown", null)]);
    expect(dialogProblem.value).toBeNull();
  });
});

describe("the API tells the store about failed writes only", () => {
  const answer = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  const body = { detail: "Another draft is running.", problems: [problem("draft_busy")] };

  afterEach(() => {
    vi.unstubAllGlobals();
    api.setFailureHandler(null);
  });

  it("calls the handler for a failed write that names problems, and still throws", async () => {
    const told: unknown[] = [];
    api.setFailureHandler((problems) => told.push(problems));
    vi.stubGlobal("fetch", answer(409, body));
    await expect(api.removeInput("2026-10-02", "x.pdf")).rejects.toMatchObject({ status: 409, message: "Another draft is running." });
    expect(told).toEqual([body.problems]);
  });

  it("never calls it for a read, or for a write whose error names none", async () => {
    const told: unknown[] = [];
    api.setFailureHandler((problems) => told.push(problems));
    vi.stubGlobal("fetch", answer(409, body));
    await expect(api.getInputs("2026-10-02")).rejects.toBeInstanceOf(api.ApiError);
    vi.stubGlobal("fetch", answer(422, { detail: "plain" }));
    await expect(api.removeInput("2026-10-02", "x.pdf")).rejects.toBeInstanceOf(api.ApiError);
    expect(told).toEqual([]);
  });

  it("goes on when the handler itself throws", async () => {
    api.setFailureHandler(() => {
      throw new Error("broken handler");
    });
    vi.stubGlobal("fetch", answer(409, body));
    await expect(api.removeInput("2026-10-02", "x.pdf")).rejects.toMatchObject({ status: 409 });
  });
});

describe("the highlight on a problem the page went to", () => {
  /** An element as far as highlight() touches it: its attributes, and a reflow that is counted. */
  const fakeElement = () => {
    const attrs = new Map<string, string>();
    const log: string[] = [];
    return {
      attrs,
      log,
      removeAttribute: (n: string) => (log.push(`remove ${n}`), attrs.delete(n)),
      setAttribute: (n: string, v: string) => (log.push(`set ${n}`), attrs.set(n, v)),
      get offsetWidth() {
        log.push("reflow");
        return 0;
      },
    };
  };

  it("marks the element with the attribute the stylesheet draws the outline from", () => {
    const el = fakeElement();
    highlight(el as unknown as HTMLElement);
    expect(el.attrs.has(HIGHLIGHT)).toBe(true);
    expect(HIGHLIGHT).toBe("data-attention-on");
  });

  it("takes the mark off and reflows before setting it again, so a second visit pulses again", () => {
    const el = fakeElement();
    highlight(el as unknown as HTMLElement);
    highlight(el as unknown as HTMLElement);
    expect(el.log).toEqual([`remove ${HIGHLIGHT}`, "reflow", `set ${HIGHLIGHT}`, `remove ${HIGHLIGHT}`, "reflow", `set ${HIGHLIGHT}`]);
    expect(el.attrs.size).toBe(1);
  });
});

describe("whether Show me is offered", () => {
  afterEach(() => vi.unstubAllGlobals());
  const page = (found: { rects: number } | null) =>
    vi.stubGlobal("document", { querySelector: () => (found ? { getClientRects: () => ({ length: found.rects }) } : null) });

  it("is offered when the target is on the page and has a box (the export error in the feed)", () => {
    page({ rects: 1 });
    expect(canShow(problem("export_not_ready", "export-bar"))).toBe(true);
  });

  it("is not offered when the target has no box (a folded panel) or is not on the page", () => {
    page({ rects: 0 });
    expect(canShow(problem("export_not_ready", "export-bar"))).toBe(false);
    page(null);
    expect(canShow(problem("export_not_ready", "export-bar"))).toBe(false);
  });

  it("is not offered for a problem with no target, or no problem", () => {
    page({ rects: 1 });
    expect(canShow(problem("draft_failed", null))).toBe(false);
    expect(canShow(null)).toBe(false);
  });
});
