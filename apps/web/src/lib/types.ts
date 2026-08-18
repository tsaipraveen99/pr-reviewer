export type Severity = "critical" | "major" | "minor" | "info";
export interface Finding {
  agent: string; file: string; line: number | null;
  severity: Severity; claim: string; evidence: string;
}
export type StreamEvent =
  | { type: "node_started"; node: string }
  | { type: "finding"; node: string; finding: Finding }
  | { type: "node_finished"; node: string }
  | { type: "node_failed"; node: string; error: string }
  | { type: "verified"; confirmed: number; rejected: number }
  | { type: "review_complete"; review: string }
  | { type: "done" }
  | { type: "run_failed"; error: string };

export type AgentStatus = "queued" | "running" | "done" | "failed";
export interface AgentView { status: AgentStatus; findings: Finding[] }
export interface RunView {
  agents: Record<string, AgentView>;
  verifier: { status: AgentStatus; confirmed: number; rejected: number };
  review: string | null;
  error: string | null;
  done: boolean;
}
