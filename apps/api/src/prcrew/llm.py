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

    async def tool_loop(self, system: str, user: str, tools: list[dict],
                        executors: dict, final_tool: dict,
                        max_tool_calls: int = 10, max_tokens: int = 4096,
                        token_budget: int | None = None) -> tuple[dict, dict]:
        """Bounded manual tool-use loop ending in a forced structured report."""
        # The first message is a content-block list (rather than a plain
        # string) so it can carry a cache_control breakpoint: system + tools
        # + this message form the loop's stable prefix, resent verbatim on
        # every iteration, so caching it is where the savings are.
        messages: list[dict] = [{"role": "user", "content": [
            {"type": "text", "text": user, "cache_control": {"type": "ephemeral"}}]}]
        total = {"input_tokens": 0, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        calls_used = 0
        force_final = False
        forced_attempts = 0
        while True:
            forcing = force_final or calls_used >= max_tool_calls
            kwargs: dict = {"tools": [*tools, final_tool]}
            if forcing:
                # tool_choice forcing is normally honored; the attempt cap
                # exists so a non-compliant model can't spin paid calls forever.
                if forced_attempts >= 3:
                    raise RuntimeError(
                        "model did not produce the final tool report after 3 forced attempts")
                forced_attempts += 1
                # Keep the FULL tools list here (not just [final_tool]): tools
                # + system + the first message form the cacheable prefix, and
                # this is the loop's last request whenever the cap is hit --
                # shrinking the tools list here would miss cache on exactly
                # that request. tool_choice alone is enough to force the call.
                kwargs = {"tools": [*tools, final_tool],
                          "tool_choice": {"type": "tool", "name": final_tool["name"]}}
            resp = await self._call(system=system, messages=messages,
                                    max_tokens=max_tokens, **kwargs)
            u = _usage(resp)
            total["input_tokens"] += u["input_tokens"]
            total["output_tokens"] += u["output_tokens"]
            total["cache_creation_input_tokens"] += u["cache_creation_input_tokens"]
            total["cache_read_input_tokens"] += u["cache_read_input_tokens"]
            # The budget bounds plain (uncached) input growth only -- cache
            # reads/writes are excluded because a hot cache is exactly why
            # repeated context stays cheap and shouldn't count against it.
            if token_budget is not None and total["input_tokens"] >= token_budget:
                force_final = True
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            final = next((b for b in tool_uses if b.name == final_tool["name"]), None)
            if final is not None:
                return final.input, total
            if not tool_uses:
                force_final = True
                continue
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in tool_uses:
                calls_used += 1
                try:
                    out = executors[block.name](block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(out)})
                except Exception as e:  # noqa: BLE001
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"tool error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})

    async def _call(self, *, system: str, user: str | None = None,
                    messages: list | None = None, max_tokens: int = 4096, **kwargs):
        messages = messages or [{"role": "user", "content": user}]
        max_attempts = 3
        backoff_seconds = [1.0, 2.0]
        for attempt in range(max_attempts):
            try:
                return await self._client.messages.create(
                    model=self.model, max_tokens=max_tokens, system=system,
                    messages=messages, **kwargs)
            except Exception as e:
                last_attempt = attempt == max_attempts - 1
                if not _is_retryable(e) or last_attempt:
                    raise
                await _sleep(backoff_seconds[attempt] + random.uniform(0, 0.5))
        raise AssertionError("unreachable: loop above always returns or raises")


def _usage(resp) -> dict:
    return {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        # getattr-with-default keeps fakes without these attrs working; `or 0`
        # covers the SDK's real default of None when caching wasn't used.
        "cache_creation_input_tokens": getattr(
            resp.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(
            resp.usage, "cache_read_input_tokens", 0) or 0,
    }
