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
      return { ...view, agents: { ...view.agents,
        [ev.node]: { ...agent, findings: [...agent.findings, ev.finding] } } };
    }
    case "verified":
      return { ...view, verifier: { ...view.verifier, confirmed: ev.confirmed, rejected: ev.rejected } };
    case "review_complete": return { ...view, review: ev.review };
    case "done": return { ...view, done: true };
    case "run_failed": return { ...view, error: ev.error, done: true };
  }
}
