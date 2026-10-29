import type {
  AnalystForm,
  AnalystRow,
  AppConfig,
  ChartSeriesFile,
  Decision,
  DismissReason,
  ExportStatus,
  FixResult,
  Notable,
  Overview,
  RejectedDraftNotes,
  ReportChoice,
  Resolution,
  Review,
  Run,
  SentenceResult,
  WeeklyInputs,
} from "./types";

/** Empty by default: the page calls its own origin, and Vite proxies /api to the backend (vite.config.ts). */
export const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");
/** The address named when the API cannot be reached. */
const API_NAME = API_BASE || (typeof window === "undefined" ? "" : window.location.origin);

const READ_TIMEOUT_MS = 30_000;
/** An upload is read and checked by the API before it answers (a workbook takes a few seconds). */
const UPLOAD_TIMEOUT_MS = 180_000;

/** One problem the API names beside an error's sentence: a stable code, a short headline, and the part of the screen it belongs to (or null). */
export interface ApiProblem {
  code: string;
  headline: string;
  target: string | null;
}

/**
 * The `problems` an error body carries, or [] when it has none. Anything that is not a list of well-formed problems is
 * ignored whole (an entry missing its code or headline, or with a target that is neither text nor null, makes the list [])
 * so a client never acts on half of one.
 */
export function parseProblems(body: unknown): ApiProblem[] {
  const list = (body as { problems?: unknown } | null)?.problems;
  if (!Array.isArray(list)) return [];
  const out: ApiProblem[] = [];
  for (const entry of list) {
    const p = entry as Partial<ApiProblem> | null;
    if (!p || typeof p.code !== "string" || typeof p.headline !== "string") return [];
    if (p.target !== null && p.target !== undefined && typeof p.target !== "string") return [];
    out.push({ code: p.code, headline: p.headline, target: p.target ?? null });
  }
  return out;
}

/** `status` is null when no HTTP response arrived (network down, API not running, timeout). `problems` is empty unless the API named some. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly problems: ApiProblem[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Told about a failed write that named its problems (main.ts installs the attention store here). Never called for a read,
// so polling and page loads never open a dialog or move the page; the error is thrown to its caller either way.
let onFailure: ((problems: ApiProblem[]) => void) | null = null;

/** Install what is told about a failed write's problems (lib/attention.ts `raise`, from main.ts). */
export function setFailureHandler(handler: ((problems: ApiProblem[]) => void) | null): void {
  onFailure = handler;
}

function failed(message: string, status: number, problems: ApiProblem[], write: boolean): ApiError {
  if (write && problems.length > 0) {
    try {
      onFailure?.(problems);
    } catch {
      /* the screen's own handling of the error goes on regardless */
    }
  }
  return new ApiError(message, status, problems);
}

function detailText(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ loc, msg, type }, ...]
    return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = READ_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      throw new ApiError(`The server did not answer within ${Math.round(timeoutMs / 1000)} seconds. A change you made may or may not have been saved: reload the page to check, then try again.`, null);
    }
    throw new ApiError(`Could not reach the report tool's server (${API_NAME}). Check that it is running, then try again.`, null);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON: keep the status text */
    }
    const write = (init.method ?? "GET").toUpperCase() !== "GET";
    throw failed(detailText(body, `${res.status} ${res.statusText}`), res.status, parseProblems(body), write);
  }
  return (await res.json()) as T;
}

export const getConfig = async (): Promise<AppConfig> => {
  const config = await request<AppConfig>("/api/config");
  // An API from before `provider_problem` existed omits it: fall back to the one check it did report.
  const problem = config.provider_problem ?? (config.provider_valid ? null : `Unknown CYTONN_LLM_PROVIDER value “${config.provider}”.`);
  return { ...config, provider_problem: problem };
};

/** The weekly report with no period label: what the screen showed before report types existed. */
export const WEEKLY_REPORT: ReportChoice = { type: "weekly", period: "", kind: null };

const reportQuery = (report: ReportChoice) => {
  const q = new URLSearchParams({ report_type: report.type });
  if (report.period) q.set("period", report.period);
  if (report.kind) q.set("kind", report.kind);
  return q.toString();
};

/** One report's sections at a glance, with its review for this period (if any). A period that does not fit is a 422. */
export const getOverview = async (report: ReportChoice = WEEKLY_REPORT): Promise<Overview> => {
  const overview = await request<Overview>(`/api/sections?${reportQuery(report)}`);
  // An API from before `drafting` existed omits it; absent means nothing is drafting, never undefined.
  return { ...overview, drafting: overview.drafting ?? null };
};

/**
 * Start a draft of one section of one report with the real pipeline, and get its run id back at once; the run view
 * then shows the draft as it happens. Focus of the Week needs the coordinator's topic, Company Updates their text.
 * `provider` is the provider this screen told the coordinator a draft would use: the API refuses the run if it is
 * configured for another, and never takes it as a choice.
 */
export const startRun = (
  slug: string,
  report: ReportChoice,
  input: { topic?: string; text?: string; provider?: string } = {},
) =>
  request<{ run_id: string }>("/api/runs", {
    method: "POST",
    body: JSON.stringify({ ...input, section: slug, report_type: report.type, period: report.period || null, kind: report.kind }),
  });

/** A run's status, events so far, and (once finished) its saved review. 404 once the API has restarted. */
export const getRun = (runId: string) => request<Run>(`/api/runs/${encodeURIComponent(runId)}`);

/** The run's Server-Sent Events stream: every event so far, then each new one, closing when the run ends. */
export const runEventsUrl = (runId: string) => `${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`;

export const getReview = (runId: number) => request<Review>(`/api/reviews/${runId}`);

/** The rejected draft just before this run, with its fix-needed items and notes; null when there is none to show. */
export const getRejectedDraftNotes = (runId: number) => request<RejectedDraftNotes | null>(`/api/reviews/${runId}/rejected-draft-notes`);

/** `note` omitted keeps the item's existing note; a string replaces it (blank clears it). */
export const resolveItem = (runId: number, index: number, resolution: Resolution, note?: string) =>
  request<Review>(`/api/reviews/${runId}/items/${index}`, {
    method: "PATCH",
    body: JSON.stringify(note === undefined ? { resolution } : { resolution, note }),
  });

export const acceptClean = (runId: number) =>
  request<Review>(`/api/reviews/${runId}/accept-clean`, { method: "POST" });

/** The picture of a drawn chart, served only while it is the file the review recorded (a changed or missing file is an error). */
export const chartImageUrl = (runId: number, chartId: string) => `${API_BASE}/api/reviews/${runId}/charts/${encodeURIComponent(chartId)}.png`;

/** The series a drawn chart was drawn from, from the same hash-checked store. */
export const getChartSeries = (runId: number, chartId: string) =>
  request<ChartSeriesFile>(`/api/reviews/${runId}/charts/${encodeURIComponent(chartId)}/series`);

/** Set the tool's chart aside for the team's own (use true) or take that back; the whole review comes back. */
export const setTeamChart = (runId: number, chartId: string, use: boolean) =>
  request<Review>(`/api/reviews/${runId}/charts/${encodeURIComponent(chartId)}/team-chart`, { method: "PUT", body: JSON.stringify({ use }) });

/**
 * Check one flagged item against a file: the API re-reads the figures that file feeds (no network, no model), keeps the file
 * and saves a new undecided review; the earlier one is untouched. A refusal or a failed check changes nothing.
 */
export const fixFromInput = (runId: number, index: number, slot: string, file: File) =>
  request<{ review: Review; result: FixResult }>(
    `/api/reviews/${runId}/items/${index}/fix-input?slot=${encodeURIComponent(slot)}&filename=${encodeURIComponent(file.name.slice(0, 200))}`,
    { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } },
    UPLOAD_TIMEOUT_MS,
  );

/**
 * Rewrite or remove one flagged sentence by hand. The API checks the figures again (no network, no model) and saves a new
 * undecided review; the earlier one is untouched. A refusal or a failed check changes nothing.
 */
export const changeSentence = (runId: number, index: number, action: "edit" | "remove" | "paragraph", text?: string) =>
  request<{ review: Review; result: SentenceResult }>(`/api/reviews/${runId}/items/${index}/sentence`, {
    method: "POST",
    body: JSON.stringify(action === "remove" ? { action } : { action, text }),
  });

export const decide = (runId: number, decision: Decision) =>
  request<Review>(`/api/reviews/${runId}/decide`, { method: "POST", body: JSON.stringify({ decision }) });

/** "Week ending 2026-10-02": the weekly report period that names its week. */
export const weekPeriod = (weekEnding: string) => `Week ending ${weekEnding}`;

const inputsPath = (weekEnding: string) => `/api/inputs/weekly/${encodeURIComponent(weekEnding)}`;

/** What has been received for one report week. */
export const getInputs = (weekEnding: string) => request<WeeklyInputs>(inputsPath(weekEnding));

/** Upload one input: the file is the request body. The API checks and reads it; a refusal carries its reason. */
export const uploadInput = (weekEnding: string, slot: string, file: File) =>
  request<WeeklyInputs>(
    `${inputsPath(weekEnding)}/${encodeURIComponent(slot)}?filename=${encodeURIComponent(file.name.slice(0, 200))}`,
    { method: "PUT", body: file, headers: { "Content-Type": "application/octet-stream" } },
    UPLOAD_TIMEOUT_MS,
  );

export const removeInput = (weekEnding: string, storedName: string) =>
  request<WeeklyInputs>(`${inputsPath(weekEnding)}/${encodeURIComponent(storedName)}`, { method: "DELETE" });

/** Have the API fetch the week's CBK Weekly Bulletin from centralbank.go.ke. */
export const fetchBulletin = (weekEnding: string) =>
  request<WeeklyInputs>(`${inputsPath(weekEnding)}/cbk_bulletin/fetch`, { method: "POST" }, UPLOAD_TIMEOUT_MS);

export const saveInputNotes = (weekEnding: string, notes: { bidding_range?: string; previous_issue?: string }) =>
  request<WeeklyInputs>(`${inputsPath(weekEnding)}/notes`, { method: "PUT", body: JSON.stringify(notes) });

const analystPath = (weekEnding: string, section: string) =>
  `${inputsPath(weekEnding)}/analyst?section=${encodeURIComponent(section)}`;

/** The "Weekly analyst inputs" form for one section of one report week. */
export const getAnalystInputs = (weekEnding: string, section: string) => request<AnalystForm>(analystPath(weekEnding, section));

export interface AnalystChanges {
  /** A field left out is kept; null clears it. */
  fields?: Record<string, string | null>;
  /** Pasted lines, or a grid's rows; null clears the table. */
  tables?: Record<string, { text: string } | { rows: AnalystRow[] } | null>;
  /** Carried or suggested values to accept as they stand. */
  confirm?: string[];
}

/** Save what was typed. The API checks every value; a refusal lists each reason on its own line and stores nothing. */
export const saveAnalystInputs = (weekEnding: string, section: string, changes: AnalystChanges) =>
  request<AnalystForm>(analystPath(weekEnding, section), { method: "PUT", body: JSON.stringify(changes) }, UPLOAD_TIMEOUT_MS);

/** Start this week's form from last week's. A weekly-changing value is carried unconfirmed. 409 if there is nothing to carry. */
export const carryAnalystInputs = (weekEnding: string, section: string) =>
  request<AnalystForm>(`${inputsPath(weekEnding)}/analyst/carry?section=${encodeURIComponent(section)}`, { method: "POST" }, UPLOAD_TIMEOUT_MS);

/** Have the API work out a running total (last week's saved total plus this week's figure) and keep it, unconfirmed. */
export const suggestAnalystInput = (weekEnding: string, section: string, field: string) =>
  request<AnalystForm>(
    `${inputsPath(weekEnding)}/analyst/suggest/${encodeURIComponent(field)}?section=${encodeURIComponent(section)}`,
    { method: "POST" },
    UPLOAD_TIMEOUT_MS,
  );

const exportPath = (period: string) => `/api/export/weekly${period ? `?period=${encodeURIComponent(period)}` : ""}`;

/** Whether the week's report can be exported: every weekly section's state. */
export const getExportStatus = (period: string) => request<ExportStatus>(exportPath(period));

/** The approved weekly report as a Word file. The API refuses (409, naming each section) unless all are approved. */
export const exportWeekly = async (period: string): Promise<{ blob: Blob; name: string }> => {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${exportPath(period)}`, { method: "POST", cache: "no-store" });
  } catch {
    throw new ApiError(`Could not reach the report tool's server (${API_NAME}). Check that it is running, then try again.`, null);
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON: keep the status text */
    }
    throw failed(detailText(body, `${res.status} ${res.statusText}`), res.status, parseProblems(body), true);
  }
  const named = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  return { blob: await res.blob(), name: named ? named[1] : "cytonn-weekly.docx" };
};

const notablePath = (section: string) => `/api/notable/${encodeURIComponent(section)}`;
const weekQuery = (weekEnding: string) => `week_ending=${encodeURIComponent(weekEnding)}`;

/** The section's "Notable this week" suggestions for one report week, each with the analyst's decision on it. */
export const getNotable = (section: string, weekEnding: string) => request<Notable>(`${notablePath(section)}?${weekQuery(weekEnding)}`);

export interface NotableChoice {
  suggestionId: string;
  decision: "selected" | "dismissed";
  /** A rewording of the headline; selected only. */
  editedHeadline?: string;
  /** Why it was dismissed; dismissed only. */
  dismissReason?: DismissReason;
}

/** Accept (or edit and accept) or dismiss one suggestion. Returns the section's whole list again. */
export const decideNotable = (section: string, weekEnding: string, c: NotableChoice) =>
  request<Notable>(`${notablePath(section)}/decisions?${weekQuery(weekEnding)}`, {
    method: "POST",
    body: JSON.stringify({
      suggestion_id: c.suggestionId,
      decision: c.decision,
      edited_headline: c.editedHeadline ?? null,
      dismiss_reason: c.dismissReason ?? null,
    }),
  });

/** Take a decision back: the suggestion is open again. */
export const restoreNotable = (section: string, weekEnding: string, suggestionId: string) =>
  request<Notable>(`${notablePath(section)}/decisions/${encodeURIComponent(suggestionId)}?${weekQuery(weekEnding)}`, { method: "DELETE" });
