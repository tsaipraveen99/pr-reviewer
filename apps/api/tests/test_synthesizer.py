from prcrew.graph.synthesizer import make_synthesizer
from prcrew.models import NodeError, VerifiedFinding
from tests.fakes import FakeLLM
from tests.test_specialists import CTX, collector

V_OK = VerifiedFinding(agent="correctness", file="x.py", line=3, severity="major",
                       claim="off-by-one", evidence="+new",
                       verdict="confirmed", reason="matches")
V_BAD = VerifiedFinding(agent="security", file="y.py", line=None, severity="critical",
                        claim="fake", evidence="?", verdict="rejected", reason="no quote")

async def test_synthesizer_uses_confirmed_only_and_notes_failures():
    llm = FakeLLM(["## Review\nLooks solid."])
    events, config = collector()
    out = await make_synthesizer(llm)(
        {"pr_context": CTX, "verified": [V_OK, V_BAD],
         "errors": [NodeError(node="tests", message="api down")]}, config)
    assert out["review"] == "## Review\nLooks solid."
    prompt = llm.calls[0][1]
    assert "off-by-one" in prompt and "fake" not in prompt and "tests" in prompt
    assert events[-2]["type"] == "review_complete"

V_NO_LINE = VerifiedFinding(agent="tests", file="z.py", line=None, severity="minor",
                            claim="missing test", evidence="+z",
                            verdict="confirmed", reason="matches")

async def test_synthesizer_failure_produces_fallback_table():
    llm = FakeLLM([RuntimeError("down")])
    _events, config = collector()
    out = await make_synthesizer(llm)(
        {"pr_context": CTX, "verified": [V_OK, V_NO_LINE], "errors": []}, config)
    assert "off-by-one" in out["review"]  # fallback still shows findings
    assert "`x.py:3`" in out["review"]    # file:line when line is known
    assert "`z.py`" in out["review"]      # bare file when line is None
    assert "z.py:None" not in out["review"]
