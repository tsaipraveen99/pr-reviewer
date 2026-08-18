import type { RunView, StreamEvent } from "./types";

export const AGENT_ORDER = ["intake", "intent", "correctness", "tests", "security", "synthesizer"];

export function initialView(): RunView {
  return {
    agents: Object.fromEntries(AGENT_ORDER.map(n => [n, { status: "queued", findings: [] }])),
    verifier: { status: "queued", confirmed: 0, rejected: 0 },
    review: null, error: null, done: false,
  };
}

export function reduce(view: RunView, ev: StreamEvent): RunView {
  // Events naming an unknown node are ignored so a newer backend emitting an
  // unrecognized node name can never crash the reducer.
  const setAgent = (node: string, patch: object): RunView =>
    node === "verifier"
      ? { ...view, verifier: { ...view.verifier, ...patch } }
      : node in view.agents
        ? { ...view, agents: { ...view.agents, [node]: { ...view.agents[node], ...patch } } }
        : view;

  switch (ev.type) {
    case "node_started": return setAgent(ev.node, { status: "running" });
    case "node_finished": return setAgent(ev.node, { status: "done" });
    case "node_failed": return setAgent(ev.node, { status: "failed" });
    case "finding": {
      const agent = view.agents[ev.node];
      if (!agent) return view;
      // Old showcases predate finding ids; synthesize one client-side so
      // verdict matching still has a key (those showcases have no
      // finding_verdict events anyway, so this is harmless there).
      const id = ev.finding.id ?? `${ev.node}-${agent.findings.length}`;
      return { ...view, agents: { ...view.agents,
        [ev.node]: { ...agent, findings: [...agent.findings, { ...ev.finding, id }] } } };
    }
    case "verified":
      return { ...view, verifier: { ...view.verifier, confirmed: ev.confirmed, rejected: ev.rejected } };
    case "finding_verdict": {
      for (const [name, agent] of Object.entries(view.agents)) {
        const idx = agent.findings.findIndex(f => f.id === ev.id);
        if (idx === -1) continue;
        const findings = [...agent.findings];
        findings[idx] = { ...findings[idx], verdict: ev.verdict, severity: ev.severity };
        return { ...view, agents: { ...view.agents, [name]: { ...agent, findings } } };
      }
      return view;
    }
    case "review_complete": return { ...view, review: ev.review };
    case "done": return { ...view, done: true };
    case "run_failed": return { ...view, error: ev.error, done: true };
    default: return view;
  }
}
