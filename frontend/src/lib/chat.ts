import { ref, shallowRef } from "vue";
import type { AppConfig } from "./types";

export type JobStatus = "idle" | "working" | "paused";
export type PauseReason = "tool_calls" | "call_budget" | "token_budget";

export interface Job {
  job_id: number;
  report_type: string;
  period: string;
  section: string;
  status: JobStatus;
  paused_reason: PauseReason | null;
  calls_used: number;
  call_budget: number;
  input_tokens: number;
  output_tokens: number;
  token_budget: number;
  max_tool_calls: number;
  budget_raises: number;
  created_at: string;
}

/** A card the API saved with a message. Only its type is relied on here; `chatcards.ts` reads the rest defensively. */
export interface ChatCard {
  type: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  seq: number;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_name: string | null;
  cards: ChatCard[] | null;
  created_at: string;
}

export interface ChatApi {
  open: (section: string, period: string) => Promise<{ job: Job; created: boolean }>;
  list: (jobId: number, after: number) => Promise<{ job: Job; messages: ChatMessage[] }>;
  send: (jobId: number, content: string) => Promise<{ seq: number; job: Job }>;
  raise: (jobId: number) => Promise<{ job: Job }>;
}

// ---- Reading the API's answers: anything that is not the expected shape is refused whole, never half used ----

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const STATUSES: readonly string[] = ["idle", "working", "paused"];
const REASONS: readonly string[] = ["tool_calls", "call_budget", "token_budget"];
const ROLES: readonly string[] = ["user", "assistant", "tool"];
const NUMBERS = ["job_id", "calls_used", "call_budget", "input_tokens", "output_tokens", "token_budget", "max_tool_calls", "budget_raises"] as const;

export function parseJob(value: unknown): Job | null {
  if (!isObject(value)) return null;
  if (NUMBERS.some((k) => typeof value[k] !== "number")) return null;
  if (typeof value.status !== "string" || !STATUSES.includes(value.status)) return null;
  const reason = value.paused_reason ?? null;
  if (reason !== null && (typeof reason !== "string" || !REASONS.includes(reason))) return null;
  if (["report_type", "period", "section", "created_at"].some((k) => typeof value[k] !== "string")) return null;
  return { ...(value as unknown as Job), paused_reason: reason as PauseReason | null };
}

export function parseMessage(value: unknown): ChatMessage | null {
  if (!isObject(value) || typeof value.seq !== "number" || typeof value.role !== "string" || !ROLES.includes(value.role)) return null;
  if (typeof value.content !== "string" || typeof value.created_at !== "string") return null;
  const cards = value.cards ?? null;
  if (cards !== null && !(Array.isArray(cards) && cards.every((c) => isObject(c) && typeof c.type === "string"))) return null;
  const tool = value.tool_name ?? null;
  if (tool !== null && typeof tool !== "string") return null;
  return { seq: value.seq, role: value.role as ChatMessage["role"], content: value.content, tool_name: tool, cards: cards as ChatCard[] | null, created_at: value.created_at };
}

/** `{job, messages}` as GET .../messages answers; null when any part of it is not as expected. */
export function parseListing(body: unknown): { job: Job; messages: ChatMessage[] } | null {
  if (!isObject(body) || !Array.isArray(body.messages)) return null;
  const job = parseJob(body.job);
  const messages = body.messages.map(parseMessage);
  return job && messages.every((m) => m !== null) ? { job, messages: messages as ChatMessage[] } : null;
}

// ---- Messages ----

/** The messages with the new ones added: one per number, a later copy of a number replacing the earlier, oldest first. */
export function mergeMessages(have: readonly ChatMessage[], incoming: readonly ChatMessage[]): ChatMessage[] {
  const bySeq = new Map<number, ChatMessage>();
  for (const m of [...have, ...incoming]) bySeq.set(m.seq, m);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/** The highest message number held, which the poll sends as `after` (0 before any). */
export const lastSeq = (messages: readonly ChatMessage[]) => messages.reduce((n, m) => Math.max(n, m.seq), 0);

/** A tool turn is shown as one small line naming the tool, never its input or result. */
export const toolLine = (m: ChatMessage) => `Looked at: ${(m.tool_name ?? "a tool").replace(/_/g, " ")}`;

// ---- When to poll, and what the job's state says in words ----

export const POLL_MS = 1200;
export const MAX_FAILED_POLLS = 5;
const MAX_DELAY_MS = 8000;

/** Poll only while the assistant is working. An idle job has finished; a paused one waits for the analyst, so nothing will change by itself. */
export const shouldPoll = (job: Job | null) => job?.status === "working";

/** The wait before the next poll: the usual interval, doubling after each failed poll up to a ceiling. */
export const nextDelay = (failures: number, base = POLL_MS) => Math.min(base * 2 ** Math.max(failures, 0), MAX_DELAY_MS);

export interface StatusLine {
  kind: "working" | "paused";
  text: string;
  /** The raise-budget button is offered only for a stop at a budget. */
  canRaise: boolean;
}

/** What the job's state says, in plain words; null while it is idle. The state is the words and an icon, never colour alone. */
export function statusLine(job: Job | null): StatusLine | null {
  if (!job || job.status === "idle") return null;
  if (job.status === "working") return { kind: "working", text: "The assistant is answering.", canRaise: false };
  if (job.paused_reason === "call_budget") {
    return { kind: "paused", text: `Paused. This conversation has used ${job.calls_used} of its ${job.call_budget} model calls. Raise the budget to go on.`, canRaise: true };
  }
  if (job.paused_reason === "token_budget") {
    const used = (job.input_tokens + job.output_tokens).toLocaleString("en-GB");
    return { kind: "paused", text: `Paused. This conversation has used ${used} of its ${job.token_budget.toLocaleString("en-GB")} tokens. Raise the budget to go on.`, canRaise: true };
  }
  return { kind: "paused", text: `Paused. The assistant stopped after ${job.max_tool_calls} tool calls for one message. Send another message to go on.`, canRaise: false };
}

/** Why the message box is off, or null when a message may be sent. The API refuses the same cases; this only says so first. */
export function composerOff(job: Job | null, config: AppConfig | null, sending: boolean): string | null {
  if (config && config.provider !== "bedrock") {
    return `The assistant answers through Amazon Bedrock, and this copy of the tool is not set up for it (${config.provider || "not configured"}). The cards still work.`;
  }
  if (config?.provider_problem) return config.provider_problem;
  if (sending || job?.status === "working") return "The assistant is answering. Wait for it, then send your message.";
  if (job?.status === "paused" && (job.paused_reason === "call_budget" || job.paused_reason === "token_budget")) return "Raise the budget first, then send your message.";
  return null;
}

// ---- One conversation: opening it, sending, polling ----

interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}
const browserTimers: Timers = { set: (fn, ms) => setTimeout(fn, ms), clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) };

/** The status an error carries, when it has one (an ApiError); the page reads the word, never the type. */
const statusOf = (err: unknown) => (err as { status?: number | null }).status ?? null;
const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

/**
 * One section's conversation. `api` is the four calls (the app passes the API's; a test passes its own) and `timers` how a wait
 * is made. Polling runs only while the job is working (`shouldPoll`); a response that arrives after the conversation was
 * stopped or another one opened is dropped; failed polls back off and stop after MAX_FAILED_POLLS, saying so.
 */
export function createConversation(api: ChatApi, timers: Timers = browserTimers) {
  const job = shallowRef<Job | null>(null);
  const messages = shallowRef<ChatMessage[]>([]);
  /** A refusal or failure of the last action, in the API's own words. */
  const notice = ref<string | null>(null);
  /** The poll's own problem: the server could not be reached. */
  const lost = ref<string | null>(null);
  const sending = ref(false);
  let handle: unknown = null;
  let generation = 0;
  let failures = 0;

  function stop() {
    if (handle !== null) timers.clear(handle);
    handle = null;
  }

  function schedule() {
    stop();
    const mine = generation;
    handle = timers.set(() => void tick(mine), nextDelay(failures));
  }

  async function tick(mine = generation) {
    handle = null;
    if (mine !== generation || !job.value) return;
    try {
      const got = await api.list(job.value.job_id, lastSeq(messages.value));
      if (mine !== generation) return;
      failures = 0;
      lost.value = null;
      job.value = got.job;
      messages.value = mergeMessages(messages.value, got.messages);
    } catch (err) {
      if (mine !== generation) return;
      failures++;
      lost.value = failures >= MAX_FAILED_POLLS ? `${messageOf(err)} The page stopped asking. Reload it to look again.` : messageOf(err);
      if (failures >= MAX_FAILED_POLLS) return;
    }
    if (shouldPoll(job.value)) schedule();
  }

  async function open(section: string, period: string) {
    stop();
    generation++;
    const mine = generation;
    failures = 0;
    job.value = null;
    messages.value = [];
    notice.value = lost.value = null;
    try {
      const opened = await api.open(section, period);
      const got = await api.list(opened.job.job_id, 0);
      if (mine !== generation) return;
      job.value = got.job;
      messages.value = got.messages;
    } catch (err) {
      if (mine === generation) notice.value = messageOf(err);
      return;
    }
    if (shouldPoll(job.value)) schedule();
  }

  async function send(content: string) {
    const current = job.value;
    const body = content.trim();
    if (!current || !body || sending.value) return false;
    sending.value = true;
    notice.value = null;
    try {
      const sent = await api.send(current.job_id, body);
      job.value = sent.job;
      // The server's own copy replaces this one on the next poll (same number).
      messages.value = mergeMessages(messages.value, [{ seq: sent.seq, role: "user", content: body, tool_name: null, cards: null, created_at: new Date().toISOString() }]);
      failures = 0;
      schedule();
      return true;
    } catch (err) {
      notice.value = messageOf(err);
      // A 409 or 429 may mean the job's state is not what this page showed (another tab, an answer still running): look again.
      if (statusOf(err) === 409 || statusOf(err) === 429) void tick();
      return false;
    } finally {
      sending.value = false;
    }
  }

  async function raise() {
    const current = job.value;
    if (!current) return;
    notice.value = null;
    try {
      job.value = (await api.raise(current.job_id)).job;
      await tick(); // the API saved a note about it; show it now
    } catch (err) {
      notice.value = messageOf(err);
      void tick();
    }
  }

  /** Read once now (after a draft finished, say): the new messages, and the job's state, with polling carried on only while it is working. */
  async function refresh() {
    stop();
    await tick();
  }

  return { job, messages, notice, lost, sending, open, send, raise, refresh, stop };
}
