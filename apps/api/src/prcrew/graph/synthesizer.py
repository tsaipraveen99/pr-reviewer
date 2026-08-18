from prcrew.graph.events import emit_from
from prcrew.llm import AgentLLM
from prcrew.models import VerifiedFinding

_SYSTEM = (
    "You are the lead reviewer writing the final review for a pull request, "
    "based only on the confirmed findings from your review panel. Write GitHub-"
    "flavored markdown: a one-paragraph verdict, then findings ordered by "
    "severity (critical, major, minor, info) with file:line references. Be "
    "direct and specific; do not pad. If there are no findings, say the PR "
    "looks good and note anything the panel could not check.")

def _fallback(confirmed: list[VerifiedFinding]) -> str:
    if not confirmed:
        return "## Review\n\nNo confirmed findings."
    rows = "\n".join(f"| {f.severity} | `{f.file}:{f.line}` | {f.claim} |" for f in confirmed)
    return ("## Review\n\n(Synthesis unavailable — raw confirmed findings.)\n\n"
            "| Severity | Location | Finding |\n|---|---|---|\n" + rows)

def make_synthesizer(llm: AgentLLM):
    async def node(state: dict, config: dict | None = None) -> dict:
        emit = emit_from(config)
        await emit({"type": "node_started", "node": "synthesizer"})
        confirmed = [v for v in state.get("verified", []) if v.verdict == "confirmed"]
        failed = [e.node for e in state.get("errors", [])]
        ctx = state["pr_context"]
        findings_text = "\n".join(
            f"- ({f.agent}, {f.severity}) {f.file}:{f.line} — {f.claim}\n  evidence: {f.evidence}"
            for f in confirmed) or "(none)"
        note = f"\n\nAgents that failed and whose perspective is missing: {', '.join(failed)}" if failed else ""
        user = (f"PR: {ctx.owner}/{ctx.repo}#{ctx.number} — {ctx.title}\n\n"
                f"Confirmed findings:\n{findings_text}{note}")
        try:
            review = await llm.text(_SYSTEM, user)
        except Exception:  # noqa: BLE001
            review = _fallback(confirmed)
        await emit({"type": "review_complete", "review": review})
        await emit({"type": "node_finished", "node": "synthesizer"})
        return {"review": review}

    return node
