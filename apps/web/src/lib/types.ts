export type Severity = "critical" | "major" | "minor" | "info";
export interface Finding {
  id?: string; agent: string; file: string; line: number | null;
  severity: Severity; claim: string; evidence: string;
}
export interface Usage { input_tokens: number; output_tokens: number }
export type StreamEvent =
  | { type: "node_started"; node: string }
  | { type: "finding"; node: string; finding: Finding }
  | { type: "node_finished"; node: string; usage?: Usage; cost_usd?: number | null }
  | { type: "node_failed"; node: string; error: string }
  | { type: "verified"; confirmed: number; rejected: number }
  | { type: "finding_verdict"; id: string; verdict: "confirmed" | "rejected";
      severity: Severity; reason: string }
  | { type: "review_complete"; review: string }
  | { type: "done" }
  | { type: "run_failed"; error: string };

export type AgentStatus = "queued" | "running" | "done" | "failed";
export type FindingView = Finding & { verdict?: "confirmed" | "rejected" };
export interface AgentView {
  status: AgentStatus;
  findings: FindingView[];
  usage?: Usage;
  cost_usd?: number | null;
}
export interface RunView {
  agents: Record<string, AgentView>;
  verifier: { status: AgentStatus; confirmed: number; rejected: number;
              usage?: Usage; cost_usd?: number | null };
  review: string | null;
  error: string | null;
  done: boolean;
  totals: { inputTokens: number; outputTokens: number; costUsd: number };
}
