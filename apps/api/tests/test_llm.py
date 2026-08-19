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

def _tool_use_block(name, id, input):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = id
    block.input = input
    return block

def _text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block

def _resp(content, input_tokens=10, output_tokens=20):
    resp = MagicMock()
    resp.content = content
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


# --- tool_loop -----------------------------------------------------------

READ_TOOL = {"name": "read_file", "input_schema": {}}
FINAL_TOOL = {"name": "report_findings", "input_schema": {}}


async def test_tool_loop_executes_then_returns_final():
    client = MagicMock()
    resp1 = _resp([_tool_use_block("read_file", "t1", {"path": "a.py"})],
                   input_tokens=10, output_tokens=20)
    resp2 = _resp([_tool_use_block("report_findings", "t2", {"findings": []})],
                   input_tokens=5, output_tokens=7)
    client.messages.create = AsyncMock(side_effect=[resp1, resp2])
    llm = AgentLLM(model="m", client=client)
    executors = {"read_file": lambda args: f"CONTENT:{args['path']}"}

    payload, usage = await llm.tool_loop("sys", "user", [READ_TOOL], executors, FINAL_TOOL)

    assert payload == {"findings": []}
    assert usage == {"input_tokens": 15, "output_tokens": 27}
    second_kwargs = client.messages.create.call_args_list[1].kwargs
    tool_result_msg = second_kwargs["messages"][-1]
    assert tool_result_msg["role"] == "user"
    tool_result = tool_result_msg["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "t1"
    assert tool_result["content"] == "CONTENT:a.py"


async def test_tool_loop_executor_error_becomes_is_error_result():
    client = MagicMock()
    resp1 = _resp([_tool_use_block("read_file", "t1", {"path": "a.py"})])
    resp2 = _resp([_tool_use_block("report_findings", "t2", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp1, resp2])
    llm = AgentLLM(model="m", client=client)

    def raise_err(_args):
        raise ValueError("nope")

    executors = {"read_file": raise_err}

    payload, _usage = await llm.tool_loop("sys", "user", [READ_TOOL], executors, FINAL_TOOL)

    assert payload == {"findings": []}
    second_kwargs = client.messages.create.call_args_list[1].kwargs
    tool_result = second_kwargs["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "nope" in tool_result["content"]


async def test_tool_loop_forces_final_after_cap():
    client = MagicMock()
    resp1 = _resp([_tool_use_block("read_file", "t1", {"path": "a.py"})])
    resp2 = _resp([_tool_use_block("read_file", "t2", {"path": "b.py"})])
    resp3 = _resp([_tool_use_block("report_findings", "t3", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp1, resp2, resp3])
    llm = AgentLLM(model="m", client=client)
    executors = {"read_file": lambda args: "ok"}

    payload, _usage = await llm.tool_loop(
        "sys", "user", [READ_TOOL], executors, FINAL_TOOL, max_tool_calls=1)

    assert payload == {"findings": []}
    assert client.messages.create.call_count == 3
    second_kwargs = client.messages.create.call_args_list[1].kwargs
    assert second_kwargs["tool_choice"] == {"type": "tool", "name": "report_findings"}
    assert second_kwargs["tools"] == [FINAL_TOOL]


async def test_tool_loop_text_only_response_forces_final():
    client = MagicMock()
    resp1 = _resp([_text_block("thinking...")])
    resp2 = _resp([_tool_use_block("report_findings", "t2", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp1, resp2])
    llm = AgentLLM(model="m", client=client)
    executors = {"read_file": lambda args: "ok"}

    payload, _usage = await llm.tool_loop("sys", "user", [READ_TOOL], executors, FINAL_TOOL)

    assert payload == {"findings": []}
    second_kwargs = client.messages.create.call_args_list[1].kwargs
    assert second_kwargs["tool_choice"] == {"type": "tool", "name": "report_findings"}
    assert second_kwargs["tools"] == [FINAL_TOOL]


async def test_tool_loop_gives_up_after_repeated_noncompliant_forced_responses():
    client = MagicMock()
    text_only = _resp([_text_block("still refusing")])
    client.messages.create = AsyncMock(side_effect=[text_only, text_only, text_only, text_only])
    llm = AgentLLM(model="m", client=client)

    with pytest.raises(RuntimeError, match="forced attempts"):
        await llm.tool_loop("sys", "user", [READ_TOOL], {}, FINAL_TOOL)

    # 1 unforced + 3 forced attempts, then give up — never a 5th paid call.
    assert client.messages.create.call_count == 4


async def test_tool_loop_first_message_carries_cache_breakpoint():
    client = MagicMock()
    resp = _resp([_tool_use_block("report_findings", "t1", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp])
    llm = AgentLLM(model="m", client=client)
    await llm.tool_loop("sys", "big context", [READ_TOOL], {}, FINAL_TOOL)
    first_msgs = client.messages.create.call_args_list[0].kwargs["messages"]
    block = first_msgs[0]["content"][0]
    assert block["type"] == "text" and block["text"] == "big context"
    assert block["cache_control"] == {"type": "ephemeral"}


async def test_tool_loop_token_budget_forces_final():
    client = MagicMock()
    # resp1 burns 150k input tokens and asks for a tool; budget 100k -> the
    # NEXT request must force the final tool even though only 1 call was used
    resp1 = _resp([_tool_use_block("read_file", "t1", {"path": "a.py"})],
                  input_tokens=150_000, output_tokens=10)
    resp2 = _resp([_tool_use_block("report_findings", "t2", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp1, resp2])
    llm = AgentLLM(model="m", client=client)
    payload, _ = await llm.tool_loop("sys", "user", [READ_TOOL],
                                     {"read_file": lambda a: "ok"}, FINAL_TOOL,
                                     token_budget=100_000)
    assert payload == {"findings": []}
    second = client.messages.create.call_args_list[1].kwargs
    assert second["tool_choice"] == {"type": "tool", "name": "report_findings"}


async def test_tool_loop_passes_max_tokens():
    client = MagicMock()
    resp = _resp([_tool_use_block("report_findings", "t1", {"findings": []})])
    client.messages.create = AsyncMock(side_effect=[resp])
    llm = AgentLLM(model="m", client=client)
    await llm.tool_loop("sys", "u", [READ_TOOL], {}, FINAL_TOOL, max_tokens=8192)
    assert client.messages.create.call_args_list[0].kwargs["max_tokens"] == 8192
