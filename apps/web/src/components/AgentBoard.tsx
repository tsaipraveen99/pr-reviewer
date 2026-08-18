import { formatCost, formatTokens } from "../lib/format";
import { AGENT_ORDER } from "../lib/reducer";
import type { AgentStatus, FindingView, RunView, Usage } from "../lib/types";

const STATUS_DOT: Record<AgentStatus, string> = {
  queued: "status-dot-queued",
  running: "status-dot-running",
  done: "status-dot-done",
  failed: "status-dot-failed",
};

const SEVERITY_BADGE: Record<FindingView["severity"], string> = {
  critical: "badge-critical",
  major: "badge-major",
  minor: "badge-minor",
  info: "badge-info",
};

// Intake and synthesizer never produce findings of their own; showing "No
// findings" on them reads as noise, so a static role description fills the
// card instead.
const ROLE_DESCRIPTION: Record<string, string> = {
  intake: "Fetches PR context and enforces guards.",
  synthesizer: "Writes the final review from confirmed findings.",
};

function StatusDot({ status }: { status: AgentStatus }) {
  return (
    <span role="status" aria-label={status} className={`status-dot ${STATUS_DOT[status]}`} />
  );
}

function FindingRow({ finding }: { finding: FindingView }) {
  const rejected = finding.verdict === "rejected";
  return (
    <li className={`text-sm ${rejected ? "opacity-50" : ""}`}>
      <div className="flex items-center gap-2">
        <span className={`badge ${SEVERITY_BADGE[finding.severity]}`}>{finding.severity}</span>
        <span className={`text-primary ${rejected ? "line-through" : ""}`}>{finding.claim}</span>
        {rejected && <span className="text-xs font-medium text-err">✕ rejected</span>}
        {finding.verdict === "confirmed" && (
          <span className="text-xs font-medium text-ok">✓ confirmed</span>
        )}
      </div>
      <p className="mono mt-0.5 text-secondary">
        {finding.file}
        {finding.line != null ? `:${finding.line}` : ""}
      </p>
    </li>
  );
}

function TokenFooter({ usage }: { usage?: Usage }) {
  const label = formatTokens(usage);
  if (!label) return null;
  return <p className="mono text-[11px] text-secondary">{label}</p>;
}

function AgentCard({ name, status, findings, usage }:
  { name: string; status: AgentStatus; findings: FindingView[]; usage?: Usage }) {
  const role = ROLE_DESCRIPTION[name];
  return (
    <div className="panel flex flex-col gap-2 p-4">
      <div className="flex items-center gap-2">
        <StatusDot status={status} />
        <h3 className="card-title capitalize">{name}</h3>
        <span className="card-meta ml-auto">{status}</span>
      </div>
      {role ? (
        <p className="text-sm text-secondary">{role}</p>
      ) : findings.length === 0 ? (
        status === "done" ? (
          <p className="text-sm font-medium text-ok">Clean ✓</p>
        ) : (
          <p className="text-sm text-secondary">No findings</p>
        )
      ) : (
        <ul className="flex flex-col gap-2">
          {findings.map((f, i) => (
            <FindingRow key={f.id ?? i} finding={f} />
          ))}
        </ul>
      )}
      <TokenFooter usage={usage} />
    </div>
  );
}

function VerifierCard({ status, confirmed, rejected, usage }:
  { status: AgentStatus; confirmed: number; rejected: number; usage?: Usage }) {
  return (
    <div className="panel flex flex-col gap-2 p-4">
      <div className="flex items-center gap-2">
        <StatusDot status={status} />
        <h3 className="card-title">Verifier</h3>
        <span className="card-meta ml-auto">{status}</span>
      </div>
      <p className="flex gap-4 text-sm">
        <span className="text-ok">{confirmed} confirmed ✓</span>
        <span className="text-err">{rejected} rejected ✕</span>
      </p>
      <TokenFooter usage={usage} />
    </div>
  );
}

/** Total tokens/cost chip; omits the cost segment while it's zero or unknown. */
export function UsageTotals({ totals }: { totals: RunView["totals"] }) {
  if (totals.inputTokens === 0 && totals.outputTokens === 0) return null;
  const total = totals.inputTokens + totals.outputTokens;
  const costSuffix = totals.costUsd > 0 ? ` · ${formatCost(totals.costUsd)}` : "";
  return (
    <p className="mono text-[11px] text-secondary">
      {total.toLocaleString()} tokens{costSuffix}
    </p>
  );
}

export function AgentBoard({ view }: { view: RunView }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <UsageTotals totals={view.totals} />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {AGENT_ORDER.map(name => (
          <AgentCard key={name} name={name} status={view.agents[name].status}
            findings={view.agents[name].findings} usage={view.agents[name].usage} />
        ))}
        <VerifierCard status={view.verifier.status} confirmed={view.verifier.confirmed}
          rejected={view.verifier.rejected} usage={view.verifier.usage} />
      </div>
    </div>
  );
}
