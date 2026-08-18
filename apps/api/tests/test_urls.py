import pytest

from prcrew.github.urls import InvalidPRUrl, parse_pr_url


def test_parses_valid_url():
    assert parse_pr_url("https://github.com/fastapi/fastapi/pull/1234") == ("fastapi", "fastapi", 1234)

def test_allows_trailing_slash():
    assert parse_pr_url("https://github.com/a/b/pull/7/") == ("a", "b", 7)

@pytest.mark.parametrize("bad", [
    "https://github.com/a/b/issues/7",
    "https://gitlab.com/a/b/pull/7",
    "https://github.com/a/b/pull/abc",
    "not a url",
    "https://github.com/a?x/b/pull/1",   # query char would steer the API path
    "https://github.com/a#x/b/pull/1",   # fragment char likewise
    "https://github.com/../b/pull/1",    # path traversal owner
    "https://github.com/a/../pull/1",    # path traversal repo
    "https://github.com/./b/pull/1",     # all-dot owner
])
def test_rejects_invalid(bad):
    with pytest.raises(InvalidPRUrl):
        parse_pr_url(bad)
