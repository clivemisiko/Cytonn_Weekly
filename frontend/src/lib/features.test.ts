import { afterEach, describe, expect, it, vi } from "vitest";
import { createSSRApp } from "vue";
import { renderToString } from "vue/server-renderer";
import { createMemoryHistory, createRouter } from "vue-router";
import * as features from "./features";

// The real ChatPage and PreparePage, rendered by Vue's server renderer (the repo has no DOM library), with the flag mocked.
let show = false;
vi.mock("@/lib/features", () => ({
  get SHOW_CHAT() {
    return show;
  },
}));

const PERIOD = "Week ending 2026-10-09";
const NOW = "2026-10-09T08:00:00+00:00";
const job = { job_id: 5, report_type: "weekly", period: PERIOD, section: "equities", status: "idle", paused_reason: null, calls_used: 1, call_budget: 20, input_tokens: 0, output_tokens: 0, token_budget: 200000, max_tool_calls: 8, budget_raises: 0, created_at: NOW };
const section = { slug: "equities", title: "Equities", available: true, needs_topic: false, requires_approved: false, uses_provider: true, reason: null, unblock: null, built_parts: [], subsections: [], charts: [], steps: [], latest: null };
const groups = { needs_analyst: [], carried_or_suggested: [], fetched: [], in_place: [], optional: [] };
// Invented stand-ins for the routes the page reads; anything else is a 404 the page reports in words.
function answer(url: string): unknown {
  if (url.includes("/readiness")) return { readiness: { section: "equities", week_ending: "2026-10-09", groups }, conversation: true };
  if (url.includes("/api/config")) return { dev_mode: false, dev_mode_label: "", provider: "bedrock", provider_problem: null };
  if (url.includes("/api/previous/weekly")) return { weeks: [], next_week_ending: null, default_week_ending: "2026-10-09", choices: [] };
  if (url.includes("/api/sections?")) return { today: "2026-10-09", drafting: null, drafting_list: [], report: { type: "weekly", period: PERIOD, kind: null }, sections: [section] };
  if (url.match(/\/api\/jobs\/5\/messages/)) return { messages: [], job };
  if (url.endsWith("/api/jobs")) return { job, created: false };
  return null;
}

async function mount(view: "prepare" | "conversation" | "list", page: "ChatPage" | "SideRail" = "ChatPage") {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const body = answer(String(input));
    return new Response(JSON.stringify(body ?? { detail: "Not here." }), { status: body ? 200 : 404, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("window", { matchMedia: () => ({ matches: true }), confirm: () => true, addEventListener() {}, removeEventListener() {}, location: { origin: "http://127.0.0.1:5173" } });
  vi.resetModules(); // SideRail reads the flag when its module loads
  const { default: ChatPage } = await import("@/pages/ChatPage.vue");
  const { default: SideRail } = await import("@/components/nav/SideRail.vue");
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/chat", component: ChatPage }] });
  await router.push(view === "list" ? `/chat?period=${encodeURIComponent(PERIOD)}` : `/chat?period=${encodeURIComponent(PERIOD)}&section=equities&view=${view}`);
  const app = createSSRApp(page === "ChatPage" ? ChatPage : SideRail);
  app.use(router);
  app.config.warnHandler = () => {};
  // Each component waits for what it reads on opening before it renders, as it would on screen a moment later.
  app.mixin({ serverPrefetch: () => new Promise((r) => setTimeout(r, 20)) });
  const out = await renderToString(app);
  return out;
}

afterEach(() => vi.unstubAllGlobals());

describe("SHOW_CHAT", { timeout: 30_000 }, () => {
  it("is false in the shipped flag file", async () => {
    const real = await vi.importActual<typeof features>("./features");
    expect(real.SHOW_CHAT).toBe(false);
  });

  for (const flag of [false, true]) {
    it(`${flag ? "shows" : "hides"} the message box, Send and the conversation log when it is ${flag}`, async () => {
      show = flag;
      const out = await mount("conversation");
      expect(out).toContain('data-card="live"'); // the draft and review cards stay either way
      expect(out.includes('id="chat-message"')).toBe(flag);
      expect(out.includes(">Send<")).toBe(flag);
      expect(out.includes('aria-label="Conversation"')).toBe(flag);
      // The chat's own budget; Section and Week stay.
      expect(out.includes("Model calls")).toBe(flag);
      expect(out.includes("Tokens")).toBe(flag);
      expect(out).toContain(">Section<");
      expect(out).toContain(">Week<");
    });

    it(`words the section list ${flag ? "as the chat" : "without the chat"} when it is ${flag}`, async () => {
      show = flag;
      const out = await mount("list");
      expect(out.includes("Choose what to talk about")).toBe(flag);
      expect(out.includes(">Choose a section<")).toBe(!flag);
      expect(out.includes("Each section is its own conversation.")).toBe(flag);
      expect(out).toContain("Choose a section to start.");
    });

    it(`names the left menu's section list item ${flag ? "Chat" : "Sections"} when it is ${flag}, going to /chat either way`, async () => {
      show = flag;
      const out = await mount("list", "SideRail");
      expect(out).toMatch(new RegExp(`<a[^>]*href="/chat"[^>]*>(?:(?!</a>).)*>${flag ? "Chat" : "Sections"}</span>`, "s"));
    });

    it(`${flag ? "shows" : "hides"} the prepare page's "Open the conversation" link when it is ${flag}`, async () => {
      show = flag;
      const out = await mount("prepare");
      expect(out).toContain('data-card="prepare"');
      expect(out.includes("Open the conversation")).toBe(flag);
    });
  }
});
