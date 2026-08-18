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
      if (typeof body?.detail === "string") message = body.detail;
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
