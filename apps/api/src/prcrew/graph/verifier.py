from langchain_core.runnables import RunnableConfig

from prcrew.graph.events import emit_from
from prcrew.graph.specialists import render_context
from prcrew.llm import AgentLLM
from prcrew.models import Finding, NodeError, NodeUsage, VerifiedFinding
from prcrew.pricing import cost_usd

VERDICTS_TOOL = {
    "name": "report_verdicts",
    "description": "Verdict for each numbered finding.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "verdict": {"type": "string", "enum": ["confirmed", "rejected"]},
                        "reason": {"type": "string"},
                        "severity": {"type": "string",
                                     "enum": ["critical", "major", "minor", "info"],
                                     "description": "corrected severity; omit if "
                                                     "the reported severity is right"},
                    },
                    "required": ["index", "verdict", "reason"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_SEVERITY_RUBRIC = (
    "Severity rubric:\n"
    "- critical: exploitable vulnerability or data loss/corruption.\n"
    "- major: will produce incorrect behavior for real inputs.\n"
    "- minor: style, robustness, or maintainability concern.\n"
    "- info: neutral observation worth noting.")

_SYSTEM = (
    "You are an adversarial verifier on a code review panel. For each numbered "
    "finding, re-read the diff and decide whether the finding is real. REJECT any "
    "finding whose evidence quote does not appear in the diff, misreads the code, "
    "or describes pre-existing code the diff did not touch. Also REJECT a finding "
    "when it is (a) a style/consistency observation presented as a defect, (b) an "
    "argument with the PR description's wording rather than an actionable defect "
    "in the change, or (c) not something a competent human reviewer would raise on "
    "this diff. Default to rejected when uncertain.\n\n"
    f"{_SEVERITY_RUBRIC}\nIf a finding is real but its severity is wrong per this "
    "rubric, confirm it and supply the corrected severity.")

def _flatten(findings: dict[str, list[Finding]]) -> list[Finding]:
    return [f for group in findings.values() for f in group]

def make_verifier(llm: AgentLLM):
    async def node(state: dict, config: RunnableConfig | None = None) -> dict:
        emit = emit_from(config)
        await emit({"type": "node_started", "node": "verifier"})
        flat = _flatten(state.get("findings", {}))
        if not flat:
            await emit({"type": "verified", "confirmed": 0, "rejected": 0})
            await emit({"type": "node_finished", "node": "verifier"})
            return {"verified": []}
        numbered = "\n".join(
            f"[{i}] ({f.agent}, {f.severity}) {f.file}:{f.line} — {f.claim}\n"
            f"    evidence: {f.evidence}" for i, f in enumerate(flat))
        user = f"{render_context(state['pr_context'])}\n\nFindings to verify:\n{numbered}"
        usage: dict | None = None
        cost: float | None = None
        try:
            out, usage = await llm.structured(_SYSTEM, user, VERDICTS_TOOL)
            by_index = {v["index"]: v for v in out["verdicts"]}
            verified = []
            for i, f in enumerate(flat):
                v = by_index.get(i, {})
                verdict = v.get("verdict", "rejected")
                data = f.model_dump()
                corrected_severity = v.get("severity")
                if verdict == "confirmed" and corrected_severity:
                    data["severity"] = corrected_severity
                verified.append(VerifiedFinding(
                    **data, verdict=verdict,
                    reason=v.get("reason", "no verdict returned")))
            errors: list[NodeError] = []
            cost = cost_usd(llm.model, usage["input_tokens"], usage["output_tokens"])
            for vf in verified:
                await emit({"type": "finding_verdict", "id": vf.id, "verdict": vf.verdict,
                            "severity": vf.severity, "reason": vf.reason})
        except Exception as e:  # noqa: BLE001
            verified = [VerifiedFinding(**f.model_dump(), verdict="confirmed",
                                        reason="verifier unavailable") for f in flat]
            errors = [NodeError(node="verifier", message=str(e))]
        confirmed = sum(1 for v in verified if v.verdict == "confirmed")
        await emit({"type": "verified", "confirmed": confirmed,
                    "rejected": len(verified) - confirmed})
        finished: dict = {"type": "node_finished", "node": "verifier"}
        if usage is not None:
            finished["usage"] = usage
            finished["cost_usd"] = cost
        await emit(finished)
        result: dict = {"verified": verified}
        if errors:
            result["errors"] = errors
        if usage is not None:
            result["usage"] = [NodeUsage(node="verifier", input_tokens=usage["input_tokens"],
                                         output_tokens=usage["output_tokens"], cost_usd=cost)]
        return result

    return node
