import pytest

from prcrew.graph.specialists import SPECIALISTS, make_specialist, render_context
from prcrew.models import PRContext
from tests.fakes import FakeLLM

CTX = PRContext(owner="o", repo="r", number=1, title="Fix parser",
                body="Fixes #9", linked_issue="#9 Bug", diff="diff --git a/x b/x\n+new",
                changed_files=1, changed_lines=1)

def collector():
    events = []
    async def emit(ev): events.append(ev)
    return events, {"configurable": {"emit": emit}}

async def test_specialist_returns_findings_and_emits():
    llm = FakeLLM([{"findings": [
        {"file": "x.py", "line": 3, "severity": "major",
         "claim": "off-by-one", "evidence": "+new"}]}])
    node = make_specialist("correctness", llm)
    events, config = collector()
    out = await node({"pr_context": CTX}, config)
    assert out["findings"]["correctness"][0].agent == "correctness"
    assert [e["type"] for e in events] == ["node_started", "finding", "node_finished"]
    # the specialist saw the PR context
    assert "Fix parser" in llm.calls[0][1]

async def test_specialist_node_finished_carries_usage_and_cost():
    llm = FakeLLM([{"findings": []}])
    node = make_specialist("correctness", llm)
    events, config = collector()
    out = await node({"pr_context": CTX}, config)
    finished = next(e for e in events if e["type"] == "node_finished")
    assert finished["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert finished["cost_usd"] == pytest.approx(0.00105)
    assert out["usage"][0].node == "correctness"
    assert out["usage"][0].cost_usd == pytest.approx(0.00105)

async def test_specialist_failure_records_error_not_crash():
    llm = FakeLLM([RuntimeError("api down")])
    node = make_specialist("security", llm)
    events, config = collector()
    out = await node({"pr_context": CTX}, config)
    assert out["errors"][0].node == "security"
    assert events[-1]["type"] == "node_failed"

def test_four_specialists_defined():
    assert set(SPECIALISTS) == {"intent", "correctness", "tests", "security"}

def test_render_context_includes_diff_and_issue():
    text = render_context(CTX)
    assert "diff --git" in text and "#9 Bug" in text
