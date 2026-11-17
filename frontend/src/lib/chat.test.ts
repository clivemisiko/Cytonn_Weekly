import { describe, expect, it } from "vitest";
import {
  type ChatApi,
  type ChatMessage,
  type Job,
  MAX_FAILED_POLLS,
  POLL_MS,
  cardView,
  composerOff,
  createConversation,
  lastSeq,
  mergeMessages,
  nextDelay,
  parseJob,
  parseListing,
  parseMessage,
  shouldPoll,
  statusLine,
  toolLine,
} from "./chat";
import type { AppConfig } from "./types";

const job = (over: Partial<Job> = {}): Job => ({
  job_id: 7, report_type: "weekly", period: "Week ending 2026-10-02", section: "fixed_income", status: "idle", paused_reason: null,
  calls_used: 2, call_budget: 20, input_tokens: 1000, output_tokens: 500, token_budget: 200000, max_tool_calls: 8, budget_raises: 0,
  created_at: "2026-10-02T08:00:00+00:00", ...over,
});
const msg = (seq: number, over: Partial<ChatMessage> = {}): ChatMessage => ({ seq, role: "assistant", content: `m${seq}`, tool_name: null, cards: null, created_at: "2026-10-02T08:00:00+00:00", ...over });
const config = (over: Partial<AppConfig> = {}): AppConfig => ({ provider: "bedrock", provider_valid: true, dev_mode: false, dev_mode_label: "", spends_api_budget: true, provider_problem: null, ...over });

describe("parsing the API's answers", () => {
  it("reads a job and refuses one with a wrong status, a missing number or an unknown pause reason", () => {
    expect(parseJob(job())).toEqual(job());
    expect(parseJob({ ...job(), status: "sleeping" })).toBeNull();
    expect(parseJob({ ...job(), calls_used: "2" })).toBeNull();
    expect(parseJob({ ...job(), paused_reason: "mood" })).toBeNull();
    expect(parseJob(null)).toBeNull();
    expect(parseJob({ ...job(), status: "paused", paused_reason: "call_budget" })?.paused_reason).toBe("call_budget");
  });

  it("reads a message and a card list, and refuses a card with no type", () => {
    expect(parseMessage(msg(1))).toEqual(msg(1));
    expect(parseMessage(msg(2, { role: "tool", content: "", tool_name: "week_status" }))?.tool_name).toBe("week_status");
    expect(parseMessage({ ...msg(3), role: "system" })).toBeNull();
    expect(parseMessage({ ...msg(3), cards: [{ data: {} }] })).toBeNull();
    expect(parseMessage({ ...msg(3), cards: [{ type: "readiness", data: {} }] })?.cards).toHaveLength(1);
  });

  it("refuses a whole listing when any one message is wrong", () => {
    expect(parseListing({ job: job(), messages: [msg(1), msg(2)] })?.messages).toHaveLength(2);
    expect(parseListing({ job: job(), messages: [msg(1), { seq: "2" }] })).toBeNull();
    expect(parseListing({ job: { nope: 1 }, messages: [] })).toBeNull();
    expect(parseListing({ job: job() })).toBeNull();
  });
});

describe("the message list", () => {
  it("merges by number, a later copy replacing an earlier one, oldest first", () => {
    const merged = mergeMessages([msg(2), msg(1)], [msg(2, { content: "newer" }), msg(3)]);
    expect(merged.map((m) => m.seq)).toEqual([1, 2, 3]);
    expect(merged[1].content).toBe("newer");
  });

  it("asks for what comes after the highest number held", () => {
    expect(lastSeq([])).toBe(0);
    expect(lastSeq([msg(4), msg(9), msg(6)])).toBe(9);
  });

  it("shows a tool turn as its name and nothing else", () => {
    expect(toolLine(msg(1, { role: "tool", content: "", tool_name: "review_summary" }))).toBe("Looked at: review summary");
  });
});

describe("when to poll", () => {
  it("polls only while the job is working", () => {
    expect(shouldPoll(job({ status: "working" }))).toBe(true);
    expect(shouldPoll(job({ status: "idle" }))).toBe(false);
    expect(shouldPoll(job({ status: "paused", paused_reason: "call_budget" }))).toBe(false);
    expect(shouldPoll(null)).toBe(false);
  });

  it("waits longer after each failed poll, up to a ceiling", () => {
    expect(nextDelay(0)).toBe(POLL_MS);
    expect(nextDelay(1)).toBe(POLL_MS * 2);
    expect(nextDelay(20)).toBeLessThanOrEqual(8000);
  });
});

describe("what the job's state says", () => {
  it("says nothing while idle and offers the raise only for a stop at a budget", () => {
    expect(statusLine(job())).toBeNull();
    expect(statusLine(job({ status: "working" }))).toMatchObject({ kind: "working", canRaise: false });
    expect(statusLine(job({ status: "paused", paused_reason: "call_budget" }))).toMatchObject({ kind: "paused", canRaise: true });
    expect(statusLine(job({ status: "paused", paused_reason: "token_budget" }))?.canRaise).toBe(true);
    const tools = statusLine(job({ status: "paused", paused_reason: "tool_calls" }));
    expect(tools?.canRaise).toBe(false);
    expect(tools?.text).toContain("8 tool calls");
  });

  it("turns the message box off for a copy not set up for Bedrock, an answer in progress, or a budget stop", () => {
    expect(composerOff(job(), config(), false)).toBeNull();
    expect(composerOff(job(), config({ provider: "local" }), false)).toContain("not set up");
    expect(composerOff(job(), config({ provider_problem: "No AWS settings." }), false)).toBe("No AWS settings.");
    expect(composerOff(job({ status: "working" }), config(), false)).toContain("answering");
    expect(composerOff(job(), config(), true)).toContain("answering");
    expect(composerOff(job({ status: "paused", paused_reason: "token_budget" }), config(), false)).toContain("Raise the budget");
    expect(composerOff(job({ status: "paused", paused_reason: "tool_calls" }), config(), false)).toBeNull();
  });
});

describe("cards", () => {
  it("summarises a readiness card by group, with snips and sources", () => {
    const v = cardView({
      type: "readiness",
      data: {
        section: "fixed_income", week_ending: "2026-10-02",
        groups: { needs_analyst: [{ label: "Bidding range", why: "typed by the team" }], fetched: [{ label: "CBK bulletin", why: "fetched" }] },
        sources: { total: 3, in_week: 2, outside_week: 1 },
      },
    });
    expect(v.title).toBe("What fixed income needs for the week ending 2026-10-02");
    expect(v.blocks[0]).toEqual({ heading: "Needs you (1)", lines: ["Bidding range: typed by the team"] });
    expect(v.blocks.map((b) => b.heading)).toEqual(["Needs you (1)", "Fetched (1)", "Sources"]);
  });

  it("caps a long list and says how many were left out", () => {
    const items = Array.from({ length: 13 }, (_, i) => ({ label: `L${i}`, why: "w" }));
    const lines = cardView({ type: "readiness", data: { groups: { optional: items } } }).blocks[0].lines;
    expect(lines).toHaveLength(11);
    expect(lines[10]).toBe("and 3 more");
  });

  it("summarises a review card, with the dev mark in words", () => {
    const v = cardView({ type: "review_summary", review_id: 12, is_dev_draft: true, data: { counts: { flagged: 1, not_auto_verified: 2, clean: 3 }, items: [{ index: 4, ref: "yield", status: "not_auto_verified" }] } });
    expect(v.title).toBe("Draft saved as review 12");
    expect(v.blocks[0].lines).toEqual(["Flagged: 1", "Not automatically verified: 2", "Clean: 3"]);
    expect(v.blocks[1].lines).toEqual(["Item 4, yield: not automatically verified"]);
    expect(v.blocks.at(-1)?.heading).toBe("Dev draft");
  });

  it("labels a card it does not know and does not fail on odd data", () => {
    expect(cardView({ type: "approve_buttons" }).title).toBe("Card: approve buttons");
    expect(() => cardView({ type: "readiness", data: "nonsense" })).not.toThrow();
  });
});

/** A scheduler the test runs by hand, so no real wait happens. */
function manual() {
  const pending = new Map<number, () => void>();
  let id = 0;
  return {
    timers: { set: (fn: () => void) => (pending.set(++id, fn), id), clear: (h: unknown) => void pending.delete(h as number) },
    count: () => pending.size,
    async fire() {
      const [[key, fn]] = [...pending];
      pending.delete(key);
      fn();
      await new Promise((r) => setTimeout(r, 0));
    },
  };
}

describe("a conversation's polling", () => {
  function fake(states: Job[], extra: Partial<ChatApi> = {}) {
    let n = 0;
    const calls = { list: 0 };
    const api: ChatApi = {
      open: async () => ({ job: states[0], created: false }),
      list: async () => ({ job: states[Math.min(n++, states.length - 1)], messages: [msg(n)] }),
      send: async () => ({ seq: 50, job: job({ status: "working" }) }),
      raise: async () => ({ job: job() }),
      ...extra,
    };
    const counted: ChatApi = { ...api, list: (...a) => ((calls.list += 1), api.list(...a)) };
    return { api: counted, calls };
  }

  it("does not poll an idle or paused job after opening it", async () => {
    for (const status of ["idle", "paused"] as const) {
      const t = manual();
      const { api } = fake([job({ status, paused_reason: status === "paused" ? "call_budget" : null })]);
      const c = createConversation(api, t.timers);
      await c.open("fixed_income", "Week ending 2026-10-02");
      expect(t.count()).toBe(0);
      expect(c.messages.value).toHaveLength(1);
    }
  });

  it("keeps polling while working and stops once the job is idle", async () => {
    const t = manual();
    const { api, calls } = fake([job({ status: "working" }), job({ status: "working" }), job({ status: "idle" })]);
    const c = createConversation(api, t.timers);
    await c.open("fixed_income", "Week ending 2026-10-02");
    expect(t.count()).toBe(1);
    await t.fire();
    expect(t.count()).toBe(1);
    await t.fire();
    expect(c.job.value?.status).toBe("idle");
    expect(t.count()).toBe(0);
    expect(calls.list).toBe(3);
  });

  it("stops after too many failed polls and says to reload", async () => {
    const t = manual();
    const { api } = fake([job({ status: "working" })]);
    let opened = false;
    api.list = async () => {
      if (!opened) return (opened = true), { job: job({ status: "working" }), messages: [] };
      throw new Error("down");
    };
    const c = createConversation(api, t.timers);
    await c.open("fixed_income", "Week ending 2026-10-02");
    for (let i = 0; i < MAX_FAILED_POLLS; i++) await t.fire();
    expect(t.count()).toBe(0);
    expect(c.lost.value).toContain("Reload");
  });

  it("drops an answer that arrives after another conversation was opened", async () => {
    const t = manual();
    let release: (() => void) | undefined;
    const slow = new Promise<void>((r) => (release = r));
    const api: ChatApi = {
      open: async (section) => ({ job: job({ section, job_id: section === "equities" ? 8 : 7 }), created: false }),
      list: async (id) => {
        if (id === 7) await slow;
        return { job: job({ job_id: id }), messages: [msg(id)] };
      },
      send: async () => ({ seq: 1, job: job() }),
      raise: async () => ({ job: job() }),
    };
    const c = createConversation(api, t.timers);
    const stale = c.open("fixed_income", "Week ending 2026-10-02");
    await c.open("equities", "Week ending 2026-10-02");
    release?.();
    await stale;
    expect(c.job.value?.job_id).toBe(8);
    expect(c.messages.value.map((m) => m.seq)).toEqual([8]);
  });

  it("shows a refusal in the API's words and looks again after a 409", async () => {
    const t = manual();
    const refused = Object.assign(new Error("Already answering."), { status: 409 });
    const { api, calls } = fake([job()], { send: async () => { throw refused; } });
    const c = createConversation(api, t.timers);
    await c.open("fixed_income", "Week ending 2026-10-02");
    const before = calls.list;
    expect(await c.send("hello")).toBe(false);
    expect(c.notice.value).toBe("Already answering.");
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.list).toBe(before + 1);
  });

  it("starts polling after a message is accepted, and ignores an empty one", async () => {
    const t = manual();
    const { api } = fake([job()]);
    const c = createConversation(api, t.timers);
    await c.open("fixed_income", "Week ending 2026-10-02");
    expect(await c.send("   ")).toBe(false);
    expect(await c.send(" what is missing? ")).toBe(true);
    expect(t.count()).toBe(1);
    expect(c.messages.value.at(-1)).toMatchObject({ seq: 50, role: "user", content: "what is missing?" });
  });
});
