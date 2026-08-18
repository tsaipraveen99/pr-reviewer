from langchain_core.runnables import RunnableConfig

from prcrew.graph.events import emit_from
from prcrew.graph.specialists import render_context
from prcrew.llm import AgentLLM
from prcrew.models import Finding, NodeError, VerifiedFinding

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
                    },
                    "required": ["index", "verdict", "reason"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_SYSTEM = (
    "You are an adversarial verifier on a code review panel. For each numbered "
    "finding, re-read the diff and decide whether the finding is real. REJECT any "
    "finding whose evidence quote does not appear in the diff, misreads the code, "
    "or describes pre-existing code the diff did not touch. Default to rejected "
    "when uncertain.")

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
        try:
            out = await llm.structured(_SYSTEM, user, VERDICTS_TOOL)
            by_index = {v["index"]: v for v in out["verdicts"]}
            verified = [
                VerifiedFinding(
                    **f.model_dump(),
                    verdict=by_index.get(i, {}).get("verdict", "rejected"),
                    reason=by_index.get(i, {}).get("reason", "no verdict returned"))
                for i, f in enumerate(flat)]
            errors: list[NodeError] = []
        except Exception as e:  # noqa: BLE001
            verified = [VerifiedFinding(**f.model_dump(), verdict="confirmed",
                                        reason="verifier unavailable") for f in flat]
            errors = [NodeError(node="verifier", message=str(e))]
        confirmed = sum(1 for v in verified if v.verdict == "confirmed")
        await emit({"type": "verified", "confirmed": confirmed,
                    "rejected": len(verified) - confirmed})
        await emit({"type": "node_finished", "node": "verifier"})
        result: dict = {"verified": verified}
        if errors:
            result["errors"] = errors
        return result

    return node
