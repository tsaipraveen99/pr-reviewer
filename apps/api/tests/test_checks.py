import httpx
import pytest
import respx

from prcrew.github.checks import CheckRuns
from prcrew.github.client import GitHubError


class FakeTokens:
    def token(self, installation_id):
        return "ghs_test"


def make_client():
    return CheckRuns(FakeTokens(), sleep=lambda s: None)


@respx.mock
def test_create_returns_id_and_sends_token():
    route = respx.post("https://api.github.com/repos/x/y/check-runs").mock(
        return_value=httpx.Response(201, json={"id": 555}))
    assert make_client().create(111, "x", "y", "c" * 40) == 555
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer ghs_test"
    import json
    body = json.loads(req.content)
    assert body == {"name": "pr-reviewer", "head_sha": "c" * 40, "status": "in_progress"}


@respx.mock
def test_complete_patches_conclusion():
    route = respx.patch("https://api.github.com/repos/x/y/check-runs/555").mock(
        return_value=httpx.Response(200, json={"id": 555}))
    make_client().complete(111, "x", "y", 555, "neutral", "title", "summary")
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["status"] == "completed"
    assert body["conclusion"] == "neutral"
    assert body["output"] == {"title": "title", "summary": "summary"}


@respx.mock
def test_retries_5xx_then_succeeds():
    route = respx.post("https://api.github.com/repos/x/y/check-runs")
    route.side_effect = [httpx.Response(502), httpx.Response(201, json={"id": 1})]
    assert make_client().create(111, "x", "y", "c" * 40) == 1
    assert route.call_count == 2


@respx.mock
def test_4xx_raises_without_retry():
    route = respx.post("https://api.github.com/repos/x/y/check-runs").mock(
        return_value=httpx.Response(422, json={"message": "bad"}))
    with pytest.raises(GitHubError):
        make_client().create(111, "x", "y", "c" * 40)
    assert route.call_count == 1


@respx.mock
def test_exhausted_retries_raise():
    respx.post("https://api.github.com/repos/x/y/check-runs").mock(
        return_value=httpx.Response(503))
    with pytest.raises(GitHubError):
        make_client().create(111, "x", "y", "c" * 40)
