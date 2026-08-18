import { render, screen } from "@testing-library/react";
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
});
