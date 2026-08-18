from prcrew.graph.verifier import make_verifier
from prcrew.models import Finding
from tests.fakes import FakeLLM
from tests.test_specialists import CTX, collector

F1 = Finding(id="correctness-0", agent="correctness", file="x.py", line=3, severity="major",
             claim="off-by-one", evidence="+new")
F2 = Finding(id="security-0", agent="security", file="y.py", line=None, severity="critical",
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

async def test_verifier_applies_corrected_severity_to_confirmed_finding():
    llm = FakeLLM([{"verdicts": [
        {"index": 0, "verdict": "confirmed", "reason": "real but overstated",
         "severity": "minor"}]}])
    _events, config = collector()
    out = await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1]}}, config)
    assert out["verified"][0].severity == "minor"
    assert out["verified"][0].verdict == "confirmed"

async def test_verifier_omitted_severity_keeps_original():
    llm = FakeLLM([{"verdicts": [
        {"index": 0, "verdict": "confirmed", "reason": "evidence matches diff"}]}])
    _events, config = collector()
    out = await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1]}}, config)
    assert out["verified"][0].severity == "major"

async def test_verifier_emits_finding_verdict_events_before_verified():
    llm = FakeLLM([{"verdicts": [
        {"index": 0, "verdict": "confirmed", "reason": "evidence matches diff"},
        {"index": 1, "verdict": "rejected", "reason": "quote not in diff"}]}])
    events, config = collector()
    await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1], "security": [F2]}}, config)
    verdict_events = [e for e in events if e["type"] == "finding_verdict"]
    assert verdict_events == [
        {"type": "finding_verdict", "id": "correctness-0", "verdict": "confirmed",
         "severity": "major", "reason": "evidence matches diff"},
        {"type": "finding_verdict", "id": "security-0", "verdict": "rejected",
         "severity": "critical", "reason": "quote not in diff"},
    ]
    types_order = [e["type"] for e in events]
    verified_idx = types_order.index("verified")
    verdict_indices = [i for i, t in enumerate(types_order) if t == "finding_verdict"]
    assert all(i < verified_idx for i in verdict_indices)

async def test_verifier_failure_emits_no_finding_verdict_events():
    llm = FakeLLM([RuntimeError("down")])
    events, config = collector()
    await make_verifier(llm)(
        {"pr_context": CTX, "findings": {"correctness": [F1]}}, config)
    assert [e for e in events if e["type"] == "finding_verdict"] == []
