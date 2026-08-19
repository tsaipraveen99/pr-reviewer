"""Intent agent for the bot path: a bounded tool-use loop over the clone."""

from langchain_core.runnables import RunnableConfig

from prcrew.graph.events import emit_from
from prcrew.graph.intent_tools import (
    GRAPH_NEIGHBORS_TOOL,
    GREP_TOOL,
    READ_FILE_TOOL,
    ToolBelt,
)
from prcrew.graph.specialists import FINDINGS_TOOL, SPECIALISTS, render_context
from prcrew.llm import AgentLLM
from prcrew.models import Finding, NodeError, NodeUsage
from prcrew.pricing import cost_usd

_SYSTEM = SPECIALISTS["intent"] + (
    "\n\nYou can explore the repository before reporting: graph_neighbors shows "
    "callers/callees/importers of a symbol, read_file reads exact lines, grep "
    "searches file contents. Use them to check whether the change actually does "
    "what the description claims and whether it breaks or bypasses the callers "
    "shown in the graph slice. Explore only what you need (at most 10 tool "
    "calls), then report findings. Cite file and NEW-side line numbers from the "
    "diff so comments can be placed inline.")


def make_intent_agent(llm: AgentLLM, toolbelt: ToolBelt, token_budget: int | None = None):
    async def node(state: dict, config: RunnableConfig | None = None) -> dict:
        emit = emit_from(config)
        await emit({"type": "node_started", "node": "intent"})
        try:
            out, usage = await llm.tool_loop(
                _SYSTEM,
                render_context(state["pr_context"], state.get("graph_slice")),
                [GRAPH_NEIGHBORS_TOOL, READ_FILE_TOOL, GREP_TOOL],
                toolbelt.executors(), FINDINGS_TOOL, max_tool_calls=10,
                max_tokens=8192, token_budget=token_budget)
            findings = [Finding(id=f"intent-{i}", agent="intent", **f)
                        for i, f in enumerate(out.get("findings", []))]
            for f in findings:
                await emit({"type": "finding", "node": "intent", "finding": f.model_dump()})
            cost = cost_usd(llm.model, usage["input_tokens"], usage["output_tokens"],
                            usage.get("cache_creation_input_tokens", 0),
                            usage.get("cache_read_input_tokens", 0))
            # Event contract and NodeUsage stay input/output-only: the cache
            # counts feed cost_usd above but don't otherwise change the wire
            # shape (NodeUsage has no cache fields).
            await emit({"type": "node_finished", "node": "intent",
                        "usage": {"input_tokens": usage["input_tokens"],
                                 "output_tokens": usage["output_tokens"]},
                        "cost_usd": cost})
            node_usage = NodeUsage(node="intent", input_tokens=usage["input_tokens"],
                                   output_tokens=usage["output_tokens"], cost_usd=cost)
            return {"findings": {"intent": findings}, "usage": [node_usage]}
        except Exception as e:  # noqa: BLE001
            await emit({"type": "node_failed", "node": "intent", "error": str(e)})
            return {"errors": [NodeError(node="intent", message=str(e))],
                    "findings": {"intent": []}}

    node.__name__ = "intent"
    return node
