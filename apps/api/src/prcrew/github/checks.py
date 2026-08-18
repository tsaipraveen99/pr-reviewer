"""GitHub Check Runs client used by the worker (sync)."""

import time

import httpx

from prcrew.github.client import GitHubError

_API = "https://api.github.com"
_MAX_ATTEMPTS = 4  # 1 try + 3 retries
_BACKOFFS = (1, 2, 4)


class CheckRuns:
    def __init__(self, tokens, sleep=time.sleep):
        self._tokens = tokens
        self._sleep = sleep

    def create(self, installation_id: int, owner: str, repo: str, head_sha: str) -> int:
        resp = self._request(installation_id, "POST",
                             f"/repos/{owner}/{repo}/check-runs",
                             {"name": "pr-reviewer", "head_sha": head_sha,
                              "status": "in_progress"})
        return resp.json()["id"]

    def complete(self, installation_id: int, owner: str, repo: str, check_run_id: int,
                 conclusion: str, title: str, summary: str) -> None:
        self._request(installation_id, "PATCH",
                      f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
                      {"status": "completed", "conclusion": conclusion,
                       "output": {"title": title, "summary": summary}})

    def _request(self, installation_id: int, method: str, path: str, body: dict):
        last: httpx.Response | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = httpx.request(
                    method, f"{_API}{path}", json=body, timeout=20,
                    headers={"Authorization": f"Bearer {self._tokens.token(installation_id)}",
                             "X-GitHub-Api-Version": "2022-11-28"})
            except httpx.TransportError:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                self._sleep(_BACKOFFS[attempt])
                continue
            if resp.status_code < 400:
                return resp
            last = resp
            if resp.status_code not in (429, 500, 502, 503, 504):
                raise GitHubError(resp.status_code, resp.text[:200])
            if attempt < _MAX_ATTEMPTS - 1:
                self._sleep(_BACKOFFS[attempt])
        raise GitHubError(last.status_code, last.text[:200])
