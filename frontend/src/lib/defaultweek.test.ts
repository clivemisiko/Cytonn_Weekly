import { describe, expect, it } from "vitest";
import { MIDWAY_WEEKS, defaultWeek, openingWeek } from "./previous";
import type { Drafting, Overview, WeekChoice } from "./types";

const P = (d: string) => `Week ending ${d}`;
type S = WeekChoice["status"];
const week = (d: string, status: S = "not_started"): WeekChoice => ({ week_ending: d, period: P(d), status, approved: status === "approved" ? 5 : 0, total: 5 });
const draft = (d: string, state: Drafting["state"] = "running", report_type = "weekly") => ({ slug: "equities", report_type, period: P(d), state }) as Drafting;

/** The choices the API sends on a given day: the coming Friday and the last eight, newest first (export.week_choices). */
function choicesOn(today: string, status: Record<string, S> = {}): WeekChoice[] {
  const t = new Date(`${today}T00:00:00Z`);
  const latest = new Date(t.getTime() - ((t.getUTCDay() + 2) % 7) * 864e5);
  return Array.from({ length: 9 }, (_, i) => {
    const d = new Date(latest.getTime() + (1 - i) * 7 * 864e5).toISOString().slice(0, 10);
    return week(d, status[d]);
  });
}

describe("defaultWeek", () => {
  it("rule 1: a week with a section drafted and not fully approved", () => {
    expect(defaultWeek([week("2026-11-20"), week("2026-11-13", "in_progress"), week("2026-11-06", "approved")], [])).toBe(P("2026-11-13"));
  });
  it("rule 1: a week with a section drafting or queued, though nothing is saved yet", () => {
    const list = [week("2026-11-20"), week("2026-11-13"), week("2026-11-06", "approved")];
    expect(defaultWeek(list, [draft("2026-11-06", "queued")])).toBe(P("2026-11-06"));
    expect(defaultWeek(list, [draft("2026-11-13")])).toBe(P("2026-11-13"));
  });
  it("rule 1 ignores a failed draft and another report's draft", () => {
    const list = [week("2026-11-20"), week("2026-11-13", "approved")];
    expect(defaultWeek(list, [draft("2026-11-13", "failed"), { ...draft("2026-11-13"), report_type: "quarterly" }])).toBe(P("2026-11-20"));
  });
  it(`rule 1 counts only the ${MIDWAY_WEEKS} newest weeks`, () => {
    const list = choicesOn("2026-11-18", { "2026-11-13": "approved", "2026-11-06": "approved", "2026-10-30": "in_progress" });
    expect(defaultWeek(list, [draft("2026-10-23")])).toBe(P("2026-11-20")); // the 4th and 5th newest are out of the window
    expect(MIDWAY_WEEKS).toBe(3);
  });
  it("tie: the newest midway week wins", () => {
    const list = [week("2026-11-20", "in_progress"), week("2026-11-13", "in_progress")];
    expect(defaultWeek(list, [draft("2026-11-13")])).toBe(P("2026-11-20"));
  });
  it("rule 2: the newest week with no draft, never the latest finished Friday", () => {
    const list = [week("2026-11-13", "approved"), week("2026-11-20"), week("2026-11-06")];
    expect(defaultWeek(list, [])).toBe(P("2026-11-20"));
  });
  it("rule 2 skips a week that is drafting outside the midway window", () => {
    const list = choicesOn("2026-11-18", Object.fromEntries(choicesOn("2026-11-18").map((w) => [w.week_ending, "approved" as S])));
    list[4] = week(list[4].week_ending); list[5] = week(list[5].week_ending);
    expect(defaultWeek(list, [draft(list[4].week_ending)])).toBe(list[5].period);
  });
  it("rule 3: every week approved opens on the newest", () => {
    expect(defaultWeek([week("2026-11-13", "approved"), week("2026-11-20", "approved")], [])).toBe(P("2026-11-20"));
  });
  it("an empty list is null; a single week is that week", () => {
    expect(defaultWeek([], [])).toBeNull();
    for (const s of ["not_started", "in_progress", "approved"] as S[]) expect(defaultWeek([week("2026-11-20", s)], null)).toBe(P("2026-11-20"));
  });
  it("with no overview (drafting null) the statuses alone decide", () => {
    expect(defaultWeek([week("2026-11-20"), week("2026-11-13", "in_progress")], null)).toBe(P("2026-11-13"));
  });

  // Each weekday of one week, from Saturday 14 Nov to Friday 20 Nov 2026.
  const days = ["2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"];
  it.each(days)("on %s: last Friday finished opens on the coming one, a midway last Friday stays", (today) => {
    const fri = choicesOn(today)[1].week_ending; // the latest Friday on or before today
    const coming = choicesOn(today)[0].period;
    const done = choicesOn(today, Object.fromEntries(choicesOn(today).slice(1).map((w) => [w.week_ending, "approved" as S])));
    expect(defaultWeek(done, [])).toBe(coming);
    expect(defaultWeek(choicesOn(today, { [fri]: "in_progress" }), [])).toBe(P(fri));
  });
});

describe("openingWeek", () => {
  const base = { weeks: [], next_week_ending: null, default_week_ending: "2026-11-13" };
  it("reads drafting from the overview", async () => {
    const overview = { drafting_list: [draft("2026-11-13", "queued")] } as unknown as Overview;
    expect(await openingWeek({ ...base, choices: [week("2026-11-20"), week("2026-11-13")] }, () => Promise.resolve(overview))).toBe(P("2026-11-13"));
  });
  it("applies the rules on the statuses when the overview cannot be read", async () => {
    const fail = () => Promise.reject(new Error("down"));
    expect(await openingWeek({ ...base, choices: [week("2026-11-20"), week("2026-11-13", "approved")] }, fail)).toBe(P("2026-11-20"));
  });
  it("uses default_week_ending only when there are no choices", async () => {
    expect(await openingWeek({ ...base, choices: [] }, () => Promise.reject(new Error("x")))).toBe(P("2026-11-13"));
  });
});
