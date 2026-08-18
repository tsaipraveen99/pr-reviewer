from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from prcrew import llm as llm_module
from prcrew.llm import AgentLLM, _is_retryable


def _resp_with_tool_use(payload, input_tokens=10, output_tokens=20):
    block = MagicMock(); block.type = "tool_use"; block.input = payload
    resp = MagicMock(); resp.content = [block]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp

def _status_error(code: int) -> anthropic.APIStatusError:
    response = httpx.Response(code, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.APIStatusError("boom", response=response, body=None)

def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

def _timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))


@pytest.fixture(autouse=True)
def instant_sleep(monkeypatch):
    """Every test in this module runs the real retry/backoff code path, but
    with sleeping stubbed out so retry tests are instant instead of taking
    real seconds."""
    delays: list[float] = []
    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
    monkeypatch.setattr(llm_module, "_sleep", fake_sleep)
    return delays


async def test_structured_extracts_tool_input():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_resp_with_tool_use({"findings": []}))
    llm = AgentLLM(model="m", client=client)
    out, _usage = await llm.structured("sys", "user", {"name": "report", "input_schema": {}})
    assert out == {"findings": []}
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "report"}

async def test_structured_returns_usage_from_response():
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_resp_with_tool_use({"ok": 1}, input_tokens=42, output_tokens=7))
    llm = AgentLLM(model="m", client=client)
    _out, usage = await llm.structured("s", "u", {"name": "t", "input_schema": {}})
    assert usage == {"input_tokens": 42, "output_tokens": 7}


# --- _is_retryable -----------------------------------------------------

def test_retryable_status_codes():
    for code in (429, 500, 502, 503, 529):
        assert _is_retryable(_status_error(code))

def test_non_retryable_status_codes():
    for code in (400, 401, 403, 404, 422):
        assert not _is_retryable(_status_error(code))

def test_connection_and_timeout_errors_are_retryable():
    assert _is_retryable(_connection_error())
    assert _is_retryable(_timeout_error())

def test_generic_exception_is_not_retryable():
    assert not _is_retryable(RuntimeError("boom"))


# --- retry/backoff behavior in _call ------------------------------------

async def test_429_retries_then_succeeds(instant_sleep):
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_status_error(429), _resp_with_tool_use({"ok": 1})])
    out, _usage = await AgentLLM("m", client=client).structured(
        "s", "u", {"name": "t", "input_schema": {}})
    assert out == {"ok": 1}
    assert client.messages.create.call_count == 2
    assert len(instant_sleep) == 1  # one backoff sleep between the two attempts

async def test_non_retryable_400_raises_immediately_with_one_call(instant_sleep):
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=_status_error(400))
    with pytest.raises(anthropic.APIStatusError):
        await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert client.messages.create.call_count == 1
    assert instant_sleep == []  # no backoff at all for a non-retryable error

async def test_connection_error_retries(instant_sleep):
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_connection_error(), _resp_with_tool_use({"ok": 1})])
    out, _usage = await AgentLLM("m", client=client).structured(
        "s", "u", {"name": "t", "input_schema": {}})
    assert out == {"ok": 1}
    assert client.messages.create.call_count == 2

async def test_retries_exhausted_raises_after_three_attempts(instant_sleep):
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=_status_error(503))
    with pytest.raises(anthropic.APIStatusError):
        await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert client.messages.create.call_count == 3  # 1 original + 2 retries
    assert len(instant_sleep) == 2

async def test_backoff_delays_are_1s_then_2s_plus_jitter(instant_sleep):
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=_status_error(500))
    with pytest.raises(anthropic.APIStatusError):
        await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    first, second = instant_sleep
    assert 1.0 <= first <= 1.5
    assert 2.0 <= second <= 2.5
