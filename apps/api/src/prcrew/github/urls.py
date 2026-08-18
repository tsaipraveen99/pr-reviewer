import re

# owner/repo restricted to GitHub-safe name characters so crafted segments
# ("?", "#", "..") can never steer the server's GitHub API GET path.
_PR_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)/?$"
)

class InvalidPRUrl(ValueError):
    pass

def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = _PR_URL.match(url.strip())
    # Reject all-dot segments ("." / "..") -- valid per the character class
    # but path-traversal primitives, and never real GitHub names.
    if not m or not m.group(1).strip(".") or not m.group(2).strip("."):
        raise InvalidPRUrl(f"Not a GitHub pull request URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))
