import re

_PR_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")

class InvalidPRUrl(ValueError):
    pass

def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = _PR_URL.match(url.strip())
    if not m:
        raise InvalidPRUrl(f"Not a GitHub pull request URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))
