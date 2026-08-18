from langchain_core.runnables import RunnableConfig

from prcrew.graph.events import emit_from
from prcrew.llm import AgentLLM
from prcrew.models import Finding, NodeError, NodeUsage, PRContext
from prcrew.pricing import cost_usd

FINDINGS_TOOL = {
    "name": "report_findings",
    "description": "Report code review findings for this pull request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": ["integer", "null"]},
                        "severity": {"type": "string",
                                     "enum": ["critical", "major", "minor", "info"]},
                        "claim": {"type": "string",
                                  "description": "One-sentence statement of the issue"},
                        "evidence": {"type": "string",
                                     "description": "Exact quote from the diff supporting the claim"},
                    },
                    "required": ["file", "severity", "claim", "evidence"],
                },
            }
        },
        "required": ["findings"],
    },
}

_BASE = (
    "You are one reviewer on a panel reviewing a GitHub pull request. "
    "Report only findings you can support with a direct quote from the diff. "
    "If you find nothing in your specialty, return an empty findings list — "
    "do not invent issues.\n\n"
    "Severity rubric:\n"
    "- critical: exploitable vulnerability or data loss/corruption.\n"
    "- major: will produce incorrect behavior for real inputs.\n"
    "- minor: style, robustness, or maintainability concern.\n"
    "- info: neutral observation worth noting.\n"
    "Report each finding at the severity an experienced staff engineer would "
    "assign. Style or consistency observations are never above minor. An "
    "empty findings list is a good outcome — most small PRs are fine. Never "
    "stretch to find something.\n\nYour specialty: "
)

SPECIALISTS: dict[str, str] = {
    "intent": _BASE + (
        "INTENT CONFORMANCE. Compare what the PR title, description, and linked "
        "issue claim against what the diff actually does. Flag: changes not "
        "mentioned in the description, claims not fulfilled by the diff, and "
        "scope creep. Differences of wording between the description and the "
        "diff are minor at most. Only flag an intent mismatch as major when "
        "the description would materially mislead a reviewer about what the "
        "change does."),
    "correctness": _BASE + (
        "CORRECTNESS. Logic errors, off-by-one mistakes, broken invariants, "
        "unhandled edge cases, incorrect error handling introduced by this diff."),
    "tests": _BASE + (
        "TEST COVERAGE. Behavior changed by this diff that has no test, tests "
        "with weak or missing assertions, and tests deleted or weakened."),
    "security": _BASE + (
        "SECURITY. Injection risks, missing authorization, secrets in code, "
        "unsafe deserialization, path traversal, and unsafe defaults "
        "introduced by this diff."),
}

def render_context(ctx: PRContext, graph_slice: str | None = None) -> str:
    issue = f"\n\nLinked issue:\n{ctx.linked_issue}" if ctx.linked_issue else ""
    sliced = (f"\n\nRepository context (code-graph slice — symbols around the "
              f"changed lines, with their callers/callees/importers):\n{graph_slice}"
              if graph_slice else "")
    return (
        f"PR: {ctx.owner}/{ctx.repo}#{ctx.number}\n"
        f"Title: {ctx.title}\n\nDescription:\n{ctx.body or '(empty)'}{issue}\n\n"
        f"Diff ({ctx.changed_files} files, {ctx.changed_lines} lines):\n{ctx.diff}{sliced}"
    )

def make_specialist(name: str, llm: AgentLLM):
    system = SPECIALISTS[name]

    async def node(state: dict, config: RunnableConfig | None = None) -> dict:
        emit = emit_from(config)
        await emit({"type": "node_started", "node": name})
        try:
            out, usage = await llm.structured(
                system, render_context(state["pr_context"], state.get("graph_slice")),
                FINDINGS_TOOL)
            findings = [Finding(id=f"{name}-{i}", agent=name, **f)
                        for i, f in enumerate(out.get("findings", []))]
            for f in findings:
                await emit({"type": "finding", "node": name, "finding": f.model_dump()})
            cost = cost_usd(llm.model, usage["input_tokens"], usage["output_tokens"])
            await emit({"type": "node_finished", "node": name, "usage": usage, "cost_usd": cost})
            node_usage = NodeUsage(node=name, input_tokens=usage["input_tokens"],
                                   output_tokens=usage["output_tokens"], cost_usd=cost)
            return {"findings": {name: findings}, "usage": [node_usage]}
        except Exception as e:  # noqa: BLE001
            await emit({"type": "node_failed", "node": name, "error": str(e)})
            return {"errors": [NodeError(node=name, message=str(e))], "findings": {name: []}}

    node.__name__ = name
    return node
