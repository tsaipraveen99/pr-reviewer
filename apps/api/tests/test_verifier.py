from prcrew.graph.verifier import make_verifier
from prcrew.models import Finding
from tests.fakes import FakeLLM
from tests.test_specialists import CTX, collector

F1 = Finding(agent="correctness", file="x.py", line=3, severity="major",
             claim="off-by-one", evidence="+new")
F2 = Finding(agent="security", file="y.py", line=None, severity="critical",
             claim="sql injection", evidence="+query")

async def test_verifier_confirms_and_rejects():
    llm = FakeLLM([{"verdicts": [
        {"index": 0, "verdict": "confirmed", "reason": "evidence matches diff"},
        {"index": 1, "verdict": "rejected", "reason": "quote not in diff"}]}])
    events, config = collector()
    out = await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1], "security": [F2]}}, config)
    verdicts = {v.claim: v.verdict for v in out["verified"]}
    assert verdicts == {"off-by-one": "confirmed", "sql injection": "rejected"}
    assert {"type": "verified", "confirmed": 1, "rejected": 1} in events

async def test_verifier_failure_passes_findings_through():
    llm = FakeLLM([RuntimeError("down")])
    _events, config = collector()
    out = await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1]}}, config)
    assert out["verified"][0].verdict == "confirmed"
    assert out["errors"][0].node == "verifier"

async def test_verifier_skips_llm_when_no_findings():
    llm = FakeLLM([])
    _events, config = collector()
    out = await make_verifier(llm)({"pr_context": CTX, "findings": {"intent": []}}, config)
    assert out["verified"] == []
    assert llm.calls == []
