import type { StreamEvent } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      // FastAPI errors use {"detail": ...}; slowapi's 429 handler uses {"error": ...}
      const detail = body?.detail ?? body?.error;
      if (typeof detail === "string") message = detail;
    } catch {
      // non-JSON error body; fall back to statusText
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export function startReview(prUrl: string): Promise<{ run_id: string }> {
  return request("/reviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pr_url: prUrl }),
  });
}

export function streamUrl(runId: string): string {
  return `${BASE_URL}/reviews/${runId}/stream`;
}

export interface ShowcaseSummary {
  slug: string;
  title: string;
  pr_url: string;
}

export interface ShowcaseEvent {
  at_ms: number;
}

export interface Showcase {
  slug: string;
  title: string;
  pr_url: string;
  recorded_at: string;
  events: (StreamEvent & ShowcaseEvent)[];
  review: string;
}

export function fetchShowcases(): Promise<ShowcaseSummary[]> {
  return request("/showcases");
}

export function fetchShowcase(slug: string): Promise<Showcase> {
  return request(`/showcases/${slug}`);
}

export interface ReviewResult {
  review: string;
  verified: unknown[];
  usage?: { input_tokens: number; output_tokens: number; cost_usd: number | null };
}

export interface ReviewStatus {
  status: string;
  result: ReviewResult | null;
}

/** Full shape of `GET /reviews/{id}`: a permalink-loadable run record. */
export interface RunRecord extends ReviewStatus {
  pr_url: string;
  events: StreamEvent[];
}

export function fetchRun(runId: string): Promise<RunRecord> {
  return request(`/reviews/${runId}`);
}

export function fetchReview(runId: string): Promise<ReviewStatus> {
  return fetchRun(runId);
}

/**
 * Translates a `GET /reviews/{run_id}` response into the StreamEvent(s) the
 * reducer expects, for use when the SSE stream drops before a terminal
 * event arrives and the client falls back to a one-shot refetch.
 */
export function reviewResultToEvents(status: string, result: ReviewResult | null): StreamEvent[] {
  if (status === "done" && result) {
    return [
      { type: "review_complete", review: result.review },
      { type: "done" },
    ];
  }
  if (status === "failed") {
    return [{ type: "run_failed", error: "run failed" }];
  }
  return [{ type: "run_failed", error: "connection lost" }];
}
