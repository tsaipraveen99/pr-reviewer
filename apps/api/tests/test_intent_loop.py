import pytest

from prcrew.graph.intent_loop import make_intent_agent
from prcrew.graph.intent_tools import GRAPH_NEIGHBORS_TOOL, GREP_TOOL, READ_FILE_TOOL
from prcrew.graph.specialists import FINDINGS_TOOL
from tests.fakes import FakeLLM
from tests.test_specialists import CTX, collector

_EXECUTORS = {"graph_neighbors": lambda args: "ok",
              "read_file": lambda args: "ok", "grep": lambda args: "ok"}


class FakeToolBelt:
    """Stand-in for intent_tools.ToolBelt: only executors() is needed by the node."""
    def executors(self) -> dict:
        return _EXECUTORS


async def test_intent_agent_returns_findings_and_emits():
    llm = FakeLLM([{"findings": [
        {"file": "a.py", "line": 3, "severity": "major",
         "claim": "diff drops the cache", "evidence": "-cache.set(...)"}]}])
    node = make_intent_agent(llm, FakeToolBelt())
    events, config = collector()

    out = await node({"pr_context": CTX}, config)

    finding = out["findings"]["intent"][0]
    assert finding.id == "intent-0"
    assert finding.agent == "intent"
    assert finding.claim == "diff drops the cache"
    assert out["usage"][0].node == "intent"

    assert [e["type"] for e in events] == ["node_started", "finding", "node_finished"]
    finished = next(e for e in events if e["type"] == "node_finished")
    assert finished["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert finished["cost_usd"] == pytest.approx(0.00105)
    assert out["usage"][0].cost_usd == pytest.approx(0.00105)


async def test_intent_agent_calls_tool_loop_with_tools_and_executors():
    llm = FakeLLM([{"findings": []}])
    toolbelt = FakeToolBelt()
    node = make_intent_agent(llm, toolbelt)
    _events, config = collector()

    await node({"pr_context": CTX}, config)

    assert len(llm.tool_loop_calls) == 1
    call = llm.tool_loop_calls[0]
    assert call["tools"] == [GRAPH_NEIGHBORS_TOOL, READ_FILE_TOOL, GREP_TOOL]
    assert call["final_tool"] == FINDINGS_TOOL
    assert call["max_tool_calls"] == 10
    assert call["executors"] == toolbelt.executors()


async def test_intent_agent_user_prompt_includes_slice_text():
    llm = FakeLLM([{"findings": []}])
    node = make_intent_agent(llm, FakeToolBelt())
    _events, config = collector()

    await node({"pr_context": CTX, "graph_slice": "[changed] app.helper (app.py:4-5)"},
              config)

    user = llm.tool_loop_calls[0]["user"]
    assert "Fix parser" in user  # base PR context still present
    assert "[changed] app.helper (app.py:4-5)" in user  # slice text included


async def test_intent_agent_failure_records_error_not_crash():
    llm = FakeLLM([RuntimeError("model refused after forced attempts")])
    node = make_intent_agent(llm, FakeToolBelt())
    events, config = collector()

    out = await node({"pr_context": CTX}, config)

    assert out["errors"][0].node == "intent"
    assert out["findings"] == {"intent": []}
    assert events[-1]["type"] == "node_failed"
    assert "usage" not in out
