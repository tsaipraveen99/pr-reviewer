import httpx
import pytest
import respx

from prcrew.github.app_client import AppClient
from prcrew.github.client import GitHubError


class FakeTokens:
    def token(self, installation_id):
        return "ghs_test"


def make_client():
    return AppClient(FakeTokens(), sleep=lambda s: None)


@respx.mock
def test_exhausted_transport_error_raises_github_error_status_zero():
    route = respx.post("https://api.github.com/repos/x/y/check-runs")
    route.side_effect = httpx.ConnectError("boom")
    with pytest.raises(GitHubError) as exc_info:
        make_client().request(111, "POST", "/repos/x/y/check-runs", {"a": 1})
    assert exc_info.value.status == 0
    assert "boom" in exc_info.value.detail
    assert route.call_count == 4
