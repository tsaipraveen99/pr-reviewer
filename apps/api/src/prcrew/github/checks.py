"""GitHub Check Runs client used by the worker (sync)."""

import time

from prcrew.github.app_client import AppClient


class CheckRuns:
    def __init__(self, tokens, sleep=time.sleep):
        self._client = AppClient(tokens, sleep)

    def create(self, installation_id: int, owner: str, repo: str, head_sha: str) -> int:
        resp = self._client.request(installation_id, "POST",
                                    f"/repos/{owner}/{repo}/check-runs",
                                    {"name": "pr-reviewer", "head_sha": head_sha,
                                     "status": "in_progress"})
        return resp.json()["id"]

    def complete(self, installation_id: int, owner: str, repo: str, check_run_id: int,
                 conclusion: str, title: str, summary: str) -> None:
        self._client.request(installation_id, "PATCH",
                             f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
                             {"status": "completed", "conclusion": conclusion,
                              "output": {"title": title, "summary": summary}})
