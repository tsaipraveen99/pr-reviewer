import httpx
import respx

from prcrew.diffs import ChangedFile
from prcrew.github.app_client import AppClient
from prcrew.github.pr_reviews import build_inline_comments, compose_body, post_review
from prcrew.models import VerifiedFinding


class FakeTokens:
    def token(self, installation_id):
        return "ghs_test"


def vf(agent, file, line, severity="major", verdict="confirmed"):
    return VerifiedFinding(id=f"{agent}-0", agent=agent, file=file, line=line,
                          severity=severity, claim=f"{agent} claim",
                          evidence="+code", verdict=verdict, reason="checked")


FILES = [ChangedFile(path="src/app.py", ranges=[(10, 20)])]


def test_inline_comments_only_mappable_intent():
    confirmed = [vf("intent", "src/app.py", 12),        # mappable -> inline
                 vf("intent", "src/app.py", 99),        # outside ranges -> body
                 vf("intent", "other.py", 1),           # unknown file -> body
                 vf("intent", "src/app.py", None),      # no line -> body
                 vf("correctness", "src/app.py", 12)]   # not intent -> body
    comments, unmapped = build_inline_comments(confirmed, FILES)
    assert len(comments) == 1
    assert comments[0] == {"path": "src/app.py", "line": 12, "side": "RIGHT",
                           "body": comments[0]["body"]}
    assert "intent claim" in comments[0]["body"]
    assert len(unmapped) == 4


def test_compose_body_sections():
    body = compose_body([vf("intent", "a.py", 1)], [vf("correctness", "a.py", 2)],
                        "## Review\n\nfull text",
                        {"input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.0123})
    assert body.index("Intent") < body.index("<details>")
    assert "full text" in body and "</details>" in body
    assert "cost: $0.012" in body and "1,500 tokens" in body


def test_compose_body_clean_intent():
    body = compose_body([], [], "## Review\n\nNo confirmed findings.",
                        {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001})
    assert "matches" in body.lower() or "no intent" in body.lower()


@respx.mock
def test_post_review_success():
    route = respx.post("https://api.github.com/repos/x/y/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 4242}))
    client = AppClient(FakeTokens(), sleep=lambda s: None)
    rid = post_review(client, 111, "x", "y", 7, "body", [{"path": "a", "line": 1,
                                                          "side": "RIGHT", "body": "b"}])
    assert rid == 4242
    import json
    sent = json.loads(route.calls[0].request.content)
    assert sent["event"] == "COMMENT" and len(sent["comments"]) == 1


@respx.mock
def test_post_review_422_falls_back_to_body_only():
    route = respx.post("https://api.github.com/repos/x/y/pulls/7/reviews")
    route.side_effect = [httpx.Response(422, json={"message": "position invalid"}),
                         httpx.Response(200, json={"id": 1})]
    client = AppClient(FakeTokens(), sleep=lambda s: None)
    rid = post_review(client, 111, "x", "y", 7, "body",
                      [{"path": "a", "line": 1, "side": "RIGHT", "body": "orphan note"}])
    assert rid == 1
    import json
    second = json.loads(route.calls[1].request.content)
    assert second["comments"] == [] and "orphan note" in second["body"]
