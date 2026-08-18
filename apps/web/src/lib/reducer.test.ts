import { describe, expect, it } from "vitest";
import { initialView, reduce } from "./reducer";
import type { StreamEvent } from "./types";

const ev = (e: object) => e as StreamEvent;

describe("reduce", () => {
  it("marks agent running then done, collecting findings", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "node_started", node: "correctness" }));
    expect(v.agents.correctness.status).toBe("running");
    v = reduce(v, ev({ type: "finding", node: "correctness",
      finding: { agent: "correctness", file: "x.py", line: 3,
                 severity: "major", claim: "bug", evidence: "+x" } }));
    v = reduce(v, ev({ type: "node_finished", node: "correctness" }));
    expect(v.agents.correctness.status).toBe("done");
    expect(v.agents.correctness.findings).toHaveLength(1);
  });

  it("tracks verifier counts", () => {
    let v = reduce(initialView(), ev({ type: "node_started", node: "verifier" }));
    v = reduce(v, ev({ type: "verified", confirmed: 2, rejected: 1 }));
    v = reduce(v, ev({ type: "node_finished", node: "verifier" }));
    expect(v.verifier).toMatchObject({ status: "done", confirmed: 2, rejected: 1 });
  });

  it("records failure without ending the run", () => {
    const v = reduce(initialView(), ev({ type: "node_failed", node: "security", error: "down" }));
    expect(v.agents.security.status).toBe("failed");
    expect(v.done).toBe(false);
  });

  it("completes on review_complete and done", () => {
    let v = reduce(initialView(), ev({ type: "review_complete", review: "## R" }));
    v = reduce(v, ev({ type: "done" }));
    expect(v.review).toBe("## R");
    expect(v.done).toBe(true);
  });

  it("fails the run on run_failed", () => {
    const v = reduce(initialView(), ev({ type: "run_failed", error: "boom" }));
    expect(v.error).toBe("boom");
    expect(v.done).toBe(true);
  });

  it("ignores events naming an unknown node instead of crashing", () => {
    const base = initialView();
    expect(reduce(base, ev({ type: "node_started", node: "mystery" }))).toEqual(base);
    expect(reduce(base, ev({ type: "node_finished", node: "mystery" }))).toEqual(base);
    expect(reduce(base, ev({ type: "node_failed", node: "mystery", error: "x" }))).toEqual(base);
    expect(reduce(base, ev({ type: "finding", node: "mystery",
      finding: { agent: "mystery", file: "x.py", line: 1,
                 severity: "minor", claim: "c", evidence: "e" } }))).toEqual(base);
  });

  it("synthesizes a finding id when the backend omits one", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "correctness",
      finding: { agent: "correctness", file: "x.py", line: 1,
                 severity: "minor", claim: "a", evidence: "e" } }));
    v = reduce(v, ev({ type: "finding", node: "correctness",
      finding: { agent: "correctness", file: "y.py", line: 2,
                 severity: "minor", claim: "b", evidence: "e" } }));
    expect(v.agents.correctness.findings.map(f => f.id)).toEqual(["correctness-0", "correctness-1"]);
  });

  it("keeps a backend-supplied finding id", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "correctness",
      finding: { id: "correctness-7", agent: "correctness", file: "x.py", line: 1,
                 severity: "minor", claim: "a", evidence: "e" } }));
    expect(v.agents.correctness.findings[0].id).toBe("correctness-7");
  });

  it("applies a finding_verdict to the matching finding across agent cards", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "security",
      finding: { id: "security-0", agent: "security", file: "y.py", line: 2,
                 severity: "critical", claim: "sqli", evidence: "+q" } }));
    v = reduce(v, ev({ type: "finding_verdict", id: "security-0", verdict: "rejected",
      severity: "minor", reason: "style nit" }));
    const f = v.agents.security.findings[0];
    expect(f.verdict).toBe("rejected");
    expect(f.severity).toBe("minor");
  });

  it("ignores a finding_verdict for an unknown id", () => {
    let v = initialView();
    v = reduce(v, ev({ type: "finding", node: "security",
      finding: { id: "security-0", agent: "security", file: "y.py", line: 2,
                 severity: "critical", claim: "sqli", evidence: "+q" } }));
    const before = v;
    v = reduce(v, ev({ type: "finding_verdict", id: "does-not-exist", verdict: "confirmed",
      severity: "critical", reason: "n/a" }));
    expect(v).toEqual(before);
  });

  it("returns the view unchanged for an unrecognized event type instead of crashing", () => {
    const base = initialView();
    expect(reduce(base, ev({ type: "bogus_future_event", whatever: 1 }))).toEqual(base);
  });
});
