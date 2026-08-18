import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialView, reduce } from "../lib/reducer";
import type { StreamEvent } from "../lib/types";
import { AgentBoard } from "./AgentBoard";

const ev = (e: object) => e as StreamEvent;

describe("AgentBoard", () => {
  it("renders a card per agent with status and findings", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "node_started", node: "security" }));
    v = reduce(v, ev({ type: "finding", node: "security",
      finding: { agent: "security", file: "y.py", line: 2,
                 severity: "critical", claim: "sqli", evidence: "+q" } }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText(/security/i)).toBeInTheDocument();
    expect(screen.getByText("sqli")).toBeInTheDocument();
    expect(screen.getByText(/critical/i)).toBeInTheDocument();
  });

  it("shows verifier counts", () => {
    const v = reduce(initialView(), ev({ type: "verified", confirmed: 3, rejected: 2 }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText(/3/)).toBeInTheDocument();
    expect(screen.getByText(/2/)).toBeInTheDocument();
  });

  it("shows a role description instead of 'No findings' on the intake card", () => {
    render(<AgentBoard view={initialView()} />);
    const card = screen.getByText("intake").closest("div.panel") as HTMLElement;
    expect(within(card).queryByText(/no findings/i)).not.toBeInTheDocument();
    expect(within(card).getByText(/fetches pr context/i)).toBeInTheDocument();
  });

  it("shows a role description instead of 'No findings' on the synthesizer card", () => {
    render(<AgentBoard view={initialView()} />);
    const card = screen.getByText("synthesizer").closest("div.panel") as HTMLElement;
    expect(within(card).queryByText(/no findings/i)).not.toBeInTheDocument();
    expect(within(card).getByText(/writes the final review/i)).toBeInTheDocument();
  });

  it("shows 'Clean' for a specialist card that finished with zero findings", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "node_started", node: "correctness" }));
    v = reduce(v, ev({ type: "node_finished", node: "correctness" }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText(/clean/i)).toBeInTheDocument();
  });

  it("renders a rejected finding dimmed with a rejected tag", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "security",
      finding: { id: "security-0", agent: "security", file: "y.py", line: 2,
                 severity: "critical", claim: "sqli", evidence: "+q" } }));
    v = reduce(v, ev({ type: "finding_verdict", id: "security-0", verdict: "rejected",
      severity: "minor", reason: "style nit" }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText("sqli")).toBeInTheDocument();
    expect(screen.getByText("✕ rejected")).toBeInTheDocument();
  });

  it("shows a compact token count on a card that has usage", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "node_finished", node: "correctness",
      usage: { input_tokens: 900, output_tokens: 200 }, cost_usd: 0.005 }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText("1.1k tok")).toBeInTheDocument();
  });

  it("omits the token footer when a card has no usage (old showcases)", () => {
    render(<AgentBoard view={initialView()} />);
    expect(screen.queryByText(/tok$/)).not.toBeInTheDocument();
  });

  it("shows a total tokens · cost chip once any usage has accrued", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "node_finished", node: "correctness",
      usage: { input_tokens: 100, output_tokens: 50 }, cost_usd: 0.00105 }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText(/150 tokens · \$0\.001/)).toBeInTheDocument();
  });

  it("omits the totals chip when no usage has accrued yet", () => {
    render(<AgentBoard view={initialView()} />);
    expect(screen.queryByText(/tokens ·/)).not.toBeInTheDocument();
  });

  it("renders a confirmed finding with a confirmed mark", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "security",
      finding: { id: "security-0", agent: "security", file: "y.py", line: 2,
                 severity: "critical", claim: "sqli", evidence: "+q" } }));
    v = reduce(v, ev({ type: "finding_verdict", id: "security-0", verdict: "confirmed",
      severity: "critical", reason: "real bug" }));
    render(<AgentBoard view={v} />);
    expect(screen.getByText("✓ confirmed")).toBeInTheDocument();
  });
});
