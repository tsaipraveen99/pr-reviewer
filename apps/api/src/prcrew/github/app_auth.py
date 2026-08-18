"""GitHub App authentication: App JWT and cached installation tokens (sync)."""

import time
from datetime import UTC, datetime

import httpx
import jwt

_API = "https://api.github.com"
_REFRESH_MARGIN_S = 300


def make_app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = {"iat": int(now) - 60, "exp": int(now) + 540, "iss": app_id}
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


class InstallationTokens:
    """Fetch and cache installation access tokens (~55 min effective life)."""

    def __init__(self, app_id: str, private_key_pem: str, clock=time.time):
        self._app_id = app_id
        self._pem = private_key_pem
        self._clock = clock
        self._cache: dict[int, tuple[str, float]] = {}

    def token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached and cached[1] - self._clock() > _REFRESH_MARGIN_S:
            return cached[0]
        resp = httpx.post(
            f"{_API}/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {make_app_jwt(self._app_id, self._pem)}",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=20)
        resp.raise_for_status()
        data = resp.json()
        expires = datetime.fromisoformat(data["expires_at"]).astimezone(UTC).timestamp()
        self._cache[installation_id] = (data["token"], expires)
        return data["token"]
