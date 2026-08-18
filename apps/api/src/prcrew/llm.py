import asyncio
import random

import anthropic

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Module-level indirection so tests can patch this to something instant
# instead of really sleeping through backoff delays.
_sleep = asyncio.sleep


def _is_retryable(exc: Exception) -> bool:
    """True for errors worth a backoff-and-retry: connection drops, timeouts,
    and server-side/rate-limit HTTP statuses. Everything else (4xx client
    errors like bad requests or auth failures) is not retryable -- retrying
    them just wastes time and repeats the same failure."""
    if isinstance(exc, anthropic.APIConnectionError | anthropic.APITimeoutError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


class AgentLLM:
    def __init__(self, model: str, client: anthropic.AsyncAnthropic | None = None):
        self.model = model
        self._client = client or anthropic.AsyncAnthropic()

    async def structured(self, system: str, user: str, tool: dict) -> tuple[dict, dict]:
        resp = await self._call(system=system, user=user, tools=[tool],
                                tool_choice={"type": "tool", "name": tool["name"]})
        block = next(b for b in resp.content if b.type == "tool_use")
        return block.input, _usage(resp)

    async def text(self, system: str, user: str) -> tuple[str, dict]:
        resp = await self._call(system=system, user=user)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, _usage(resp)

    async def _call(self, *, system: str, user: str, **kwargs):
        max_attempts = 3
        backoff_seconds = [1.0, 2.0]
        for attempt in range(max_attempts):
            try:
                return await self._client.messages.create(
                    model=self.model, max_tokens=4096, system=system,
                    messages=[{"role": "user", "content": user}], **kwargs)
            except Exception as e:
                last_attempt = attempt == max_attempts - 1
                if not _is_retryable(e) or last_attempt:
                    raise
                await _sleep(backoff_seconds[attempt] + random.uniform(0, 0.5))
        raise AssertionError("unreachable: loop above always returns or raises")


def _usage(resp) -> dict:
    return {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
