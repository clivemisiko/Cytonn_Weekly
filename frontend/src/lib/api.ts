import type { AppConfig, Decision, Overview, ReportChoice, Resolution, Review, Run } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const READ_TIMEOUT_MS = 30_000;

/** `status` is null when no HTTP response arrived (network down, API not running, timeout). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
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
      throw new ApiError(`The request timed out after ${Math.round(timeoutMs / 1000)} seconds.`, null);
    }
    throw new ApiError(`Could not reach the review API at ${API_BASE}. Is it running?`, null);
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
    throw new ApiError(detailText(body, `${res.status} ${res.statusText}`), res.status);
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

/** `note` omitted keeps the item's existing note; a string replaces it (blank clears it). */
export const resolveItem = (runId: number, index: number, resolution: Resolution, note?: string) =>
  request<Review>(`/api/reviews/${runId}/items/${index}`, {
    method: "PATCH",
    body: JSON.stringify(note === undefined ? { resolution } : { resolution, note }),
  });

export const acceptClean = (runId: number) =>
  request<Review>(`/api/reviews/${runId}/accept-clean`, { method: "POST" });

export const decide = (runId: number, decision: Decision) =>
  request<Review>(`/api/reviews/${runId}/decide`, { method: "POST", body: JSON.stringify({ decision }) });
