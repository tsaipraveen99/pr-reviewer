import httpx
import pytest
import respx

from prcrew.github.client import (
    GitHubClient,
    GitHubError,
    PrivateRepoError,
    PRTooLargeError,
)

META_URL = "https://api.github.com/repos/o/r/pulls/1"


def meta(private=False, files=3, additions=10, deletions=5, body="Fixes #9"):
    return {
        "title": "Fix parser",
        "body": body,
        "changed_files": files,
        "additions": additions,
        "deletions": deletions,
        "base": {"repo": {"private": private}},
    }


@respx.mock
async def test_fetches_pr_context():
    respx.get(META_URL).mock(
        side_effect=[
            httpx.Response(200, json=meta()),  # meta call
            httpx.Response(200, text="diff --git a/x b/x\n+new"),  # diff call
        ]
    )
    respx.get("https://api.github.com/repos/o/r/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Bug", "body": "It crashes"})
    )
    ctx = await GitHubClient(token="t").fetch_pr("o", "r", 1)
    assert ctx.title == "Fix parser"
    assert ctx.changed_lines == 15
    assert "diff --git" in ctx.diff
    assert "Bug" in ctx.linked_issue


@respx.mock
async def test_private_repo_rejected():
    respx.get(META_URL).mock(return_value=httpx.Response(200, json=meta(private=True)))
    with pytest.raises(PrivateRepoError):
        await GitHubClient(token="t").fetch_pr("o", "r", 1)


@respx.mock
async def test_oversized_pr_rejected():
    respx.get(META_URL).mock(return_value=httpx.Response(200, json=meta(additions=600)))
    with pytest.raises(PRTooLargeError):
        await GitHubClient(token="t").fetch_pr("o", "r", 1)


@respx.mock
async def test_github_error_surfaces_status():
    respx.get(META_URL).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(GitHubError) as e:
        await GitHubClient(token="t").fetch_pr("o", "r", 1)
    assert e.value.status == 404
