"""Shared sync GitHub client for App-authenticated REST calls (worker path)."""

import time

import httpx

from prcrew.github.client import GitHubError

_API = "https://api.github.com"
_MAX_ATTEMPTS = 4
_BACKOFFS = (1, 2, 4)
_RETRYABLE = {429, 500, 502, 503, 504}


class AppClient:
    def __init__(self, tokens, sleep=time.sleep):
        self._tokens = tokens
        self._sleep = sleep

    def request(self, installation_id: int, method: str, path: str,
                json_body: dict | None = None, headers: dict | None = None) -> httpx.Response:
        last: httpx.Response | None = None
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = httpx.request(
                    method, f"{_API}{path}", json=json_body, timeout=30,
                    headers={"Authorization": f"Bearer {self._tokens.token(installation_id)}",
                             "X-GitHub-Api-Version": "2022-11-28", **(headers or {})})
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    self._sleep(_BACKOFFS[attempt])
                continue
            if resp.status_code < 400:
                return resp
            last = resp
            if resp.status_code not in _RETRYABLE:
                raise GitHubError(resp.status_code, resp.text[:200])
            if attempt < _MAX_ATTEMPTS - 1:
                self._sleep(_BACKOFFS[attempt])
        if last is not None:
            raise GitHubError(last.status_code, last.text[:200])
        raise GitHubError(0, f"network error: {last_exc}")
