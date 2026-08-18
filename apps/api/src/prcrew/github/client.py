import re

import httpx

from prcrew.models import PRContext

MAX_FILES = 20
MAX_LINES = 500
_API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"GitHub API {status}: {detail}")
        self.status = status
        self.detail = detail


class PrivateRepoError(Exception):
    pass


class PRTooLargeError(Exception):
    pass


class GitHubClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def fetch_pr(self, owner: str, repo: str, number: int) -> PRContext:
        url = f"{_API}/repos/{owner}/{repo}/pulls/{number}"
        async with httpx.AsyncClient(headers=self._headers, timeout=20) as http:
            meta = await self._get_json(http, url)
            if meta["base"]["repo"]["private"]:
                raise PrivateRepoError("Only public repositories are supported.")
            changed_lines = meta["additions"] + meta["deletions"]
            if meta["changed_files"] > MAX_FILES or changed_lines > MAX_LINES:
                raise PRTooLargeError(
                    f"PR too large: {meta['changed_files']} files / {changed_lines} lines "
                    f"(limits: {MAX_FILES} files, {MAX_LINES} lines)."
                )
            diff_resp = await http.get(
                url, headers={"Accept": "application/vnd.github.diff"}
            )
            if diff_resp.status_code >= 400:
                raise GitHubError(diff_resp.status_code, diff_resp.text[:200])
            linked_issue = await self._linked_issue(
                http, owner, repo, meta.get("body") or ""
            )
            return PRContext(
                owner=owner,
                repo=repo,
                number=number,
                title=meta["title"],
                body=meta.get("body") or "",
                linked_issue=linked_issue,
                diff=diff_resp.text,
                changed_files=meta["changed_files"],
                changed_lines=changed_lines,
            )

    async def _get_json(self, http: httpx.AsyncClient, url: str) -> dict:
        resp = await http.get(url)
        if resp.status_code >= 400:
            raise GitHubError(resp.status_code, resp.text[:200])
        return resp.json()

    async def _linked_issue(
        self, http, owner: str, repo: str, body: str
    ) -> str | None:
        m = re.search(r"#(\d+)", body)
        if not m:
            return None
        try:
            issue = await self._get_json(
                http, f"{_API}/repos/{owner}/{repo}/issues/{m.group(1)}"
            )
            return f"#{m.group(1)} {issue['title']}\n{issue.get('body') or ''}"[:2000]
        except GitHubError:
            return None  # linked issue is best-effort
