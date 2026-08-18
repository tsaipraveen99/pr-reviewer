from prcrew.graph.build import build_graph
from tests.fakes import FakeLLM
from tests.test_specialists import CTX, collector


def findings_payload(claim):
    return {"findings": [{"file": "x.py", "line": 1, "severity": "minor",
                          "claim": claim, "evidence": "+new"}]}

async def test_full_graph_run():
    # 4 specialists (order nondeterministic, same shape) + 1 verifier call
    specialist_llm = FakeLLM([findings_payload(f"claim-{i}") for i in range(4)] +
                             [{"verdicts": [
                                 {"index": i, "verdict": "confirmed", "reason": "ok"}
                                 for i in range(4)]}])
    synth_llm = FakeLLM(["## Final review"])
    graph = build_graph(specialist_llm, synth_llm)
    events, config = collector()
    result = await graph.ainvoke({"pr_context": CTX}, config)
    assert result["review"] == "## Final review"
    assert len(result["verified"]) == 4
    started = [e["node"] for e in events if e["type"] == "node_started"]
    assert started[0] == "intake" and started[-1] == "synthesizer"
    assert {"intent", "correctness", "tests", "security"} <= set(started)
    # verifier ran after all four specialists
    assert started.index("verifier") > max(started.index(s)
        for s in ["intent", "correctness", "tests", "security"])
    # 4 specialists + verifier + synthesizer each contributed one NodeUsage
    assert len(result["usage"]) == 6
    assert {u.node for u in result["usage"]} == \
        {"intent", "correctness", "tests", "security", "verifier", "synthesizer"}
    assert all(u.cost_usd is not None for u in result["usage"])

async def test_graph_completes_with_partial_failure():
    # NOTE: FakeLLM has no retry; AgentLLM does. One RuntimeError = one failed node here.
    specialist_llm = FakeLLM([findings_payload("a"), RuntimeError("down"),
                              findings_payload("b"), findings_payload("c"),
                              {"verdicts": [{"index": i, "verdict": "confirmed", "reason": "ok"}
                                            for i in range(3)]}])
    synth_llm = FakeLLM(["## Partial review"])
    graph = build_graph(specialist_llm, synth_llm)
    _events, config = collector()
    result = await graph.ainvoke({"pr_context": CTX}, config)
    assert result["review"] == "## Partial review"
    assert len(result["errors"]) == 1
