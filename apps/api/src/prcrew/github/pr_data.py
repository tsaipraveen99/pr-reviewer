"""Fetch PR context via the App installation token (sync, worker path)."""

import re

from prcrew.github.app_client import AppClient
from prcrew.github.client import GitHubError
from prcrew.models import PRContext


def fetch_pr(client: AppClient, installation_id: int, owner: str, repo: str,
             number: int) -> tuple[PRContext, dict]:
    path = f"/repos/{owner}/{repo}/pulls/{number}"
    meta = client.request(installation_id, "GET", path).json()
    diff = client.request(installation_id, "GET", path,
                          headers={"Accept": "application/vnd.github.diff"}).text
    ctx = PRContext(
        owner=owner, repo=repo, number=number,
        title=meta["title"], body=meta.get("body") or "",
        linked_issue=_linked_issue(client, installation_id, owner, repo,
                                   meta.get("body") or ""),
        diff=diff,
        changed_files=meta["changed_files"],
        changed_lines=meta["additions"] + meta["deletions"])
    return ctx, meta


def _linked_issue(client, installation_id, owner, repo, body: str) -> str | None:
    m = re.search(r"#(\d+)", body)
    if not m:
        return None
    try:
        issue = client.request(installation_id, "GET",
                               f"/repos/{owner}/{repo}/issues/{m.group(1)}").json()
        return f"#{m.group(1)} {issue['title']}\n{issue.get('body') or ''}"[:2000]
    except GitHubError:
        return None  # best-effort, same as the web path
