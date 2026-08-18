import { AGENT_ORDER } from "../lib/reducer";
import type { AgentStatus, FindingView, RunView } from "../lib/types";

const STATUS_DOT: Record<AgentStatus, string> = {
  queued: "bg-zinc-600",
  running: "bg-blue-500 animate-pulse",
  done: "bg-emerald-500",
  failed: "bg-red-500",
};

const SEVERITY_BADGE: Record<FindingView["severity"], string> = {
  critical: "bg-red-500/15 text-red-400 border-red-500/40",
  major: "bg-orange-500/15 text-orange-400 border-orange-500/40",
  minor: "bg-yellow-500/15 text-yellow-400 border-yellow-500/40",
  info: "bg-zinc-500/15 text-zinc-400 border-zinc-500/40",
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
    <span
      role="status"
      aria-label={status}
      className={`inline-block h-2.5 w-2.5 rounded-full ${STATUS_DOT[status]}`}
    />
  );
}

function FindingRow({ finding }: { finding: FindingView }) {
  const rejected = finding.verdict === "rejected";
  return (
    <li className={`text-sm ${rejected ? "opacity-50" : ""}`}>
      <div className="flex items-center gap-2">
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${SEVERITY_BADGE[finding.severity]}`}
        >
          {finding.severity}
        </span>
        <span className={`text-zinc-300 ${rejected ? "line-through" : ""}`}>{finding.claim}</span>
        {rejected && (
          <span className="text-xs font-medium text-red-400">✕ rejected</span>
        )}
        {finding.verdict === "confirmed" && (
          <span className="text-xs font-medium text-emerald-400">✓ confirmed</span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-zinc-500">
        {finding.file}
        {finding.line != null ? `:${finding.line}` : ""}
      </p>
    </li>
  );
}

function AgentCard({ name, status, findings }: { name: string; status: AgentStatus; findings: FindingView[] }) {
  const role = ROLE_DESCRIPTION[name];
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="mb-2 flex items-center gap-2">
        <StatusDot status={status} />
        <h3 className="font-medium capitalize text-zinc-100">{name}</h3>
        <span className="ml-auto text-xs text-zinc-500">{status}</span>
      </div>
      {role ? (
        <p className="text-sm text-zinc-500">{role}</p>
      ) : findings.length === 0 ? (
        status === "done" ? (
          <p className="text-sm font-medium text-emerald-400">Clean ✓</p>
        ) : (
          <p className="text-sm text-zinc-600">No findings</p>
        )
      ) : (
        <ul className="flex flex-col gap-2">
          {findings.map((f, i) => (
            <FindingRow key={f.id ?? i} finding={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function VerifierCard({ status, confirmed, rejected }: { status: AgentStatus; confirmed: number; rejected: number }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="mb-2 flex items-center gap-2">
        <StatusDot status={status} />
        <h3 className="font-medium text-zinc-100">Verifier</h3>
        <span className="ml-auto text-xs text-zinc-500">{status}</span>
      </div>
      <p className="flex gap-4 text-sm">
        <span className="text-emerald-400">{confirmed} confirmed ✓</span>
        <span className="text-red-400">{rejected} rejected ✕</span>
      </p>
    </div>
  );
}

export function AgentBoard({ view }: { view: RunView }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {AGENT_ORDER.map(name => (
        <AgentCard key={name} name={name} status={view.agents[name].status} findings={view.agents[name].findings} />
      ))}
      <VerifierCard status={view.verifier.status} confirmed={view.verifier.confirmed} rejected={view.verifier.rejected} />
    </div>
  );
}
