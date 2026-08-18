import httpx
import respx

from prcrew.github.app_client import AppClient
from prcrew.github.pr_data import fetch_pr


class FakeTokens:
    def token(self, installation_id):
        return "ghs_test"


META = {
    "title": "Add feature", "body": "Does the thing. Fixes #9", "draft": False,
    "changed_files": 2, "additions": 10, "deletions": 3,
    "head": {"sha": "c" * 40}, "base": {"repo": {"private": False}},
}


@respx.mock
def test_fetch_pr_returns_context_and_meta():
    respx.route(method="GET", url="https://api.github.com/repos/x/y/pulls/7",
                headers={"accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(
            200, text="diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -1 +1,2 @@\n+x\n"))
    respx.get("https://api.github.com/repos/x/y/pulls/7").mock(
        return_value=httpx.Response(200, json=META))
    respx.get("https://api.github.com/repos/x/y/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "The bug", "body": "details"}))
    ctx, meta = fetch_pr(AppClient(FakeTokens(), sleep=lambda s: None), 111, "x", "y", 7)
    assert ctx.owner == "x" and ctx.number == 7
    assert ctx.changed_files == 2 and ctx.changed_lines == 13
    assert ctx.linked_issue.startswith("#9 The bug")
    assert "diff --git" in ctx.diff
    assert meta["head"]["sha"] == "c" * 40


@respx.mock
def test_fetch_pr_linked_issue_best_effort():
    respx.route(method="GET", url="https://api.github.com/repos/x/y/pulls/7",
                headers={"accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(200, text="d"))
    respx.get("https://api.github.com/repos/x/y/pulls/7").mock(
        return_value=httpx.Response(200, json={**META, "body": "no ref"}))
    ctx, _ = fetch_pr(AppClient(FakeTokens(), sleep=lambda s: None), 111, "x", "y", 7)
    assert ctx.linked_issue is None
