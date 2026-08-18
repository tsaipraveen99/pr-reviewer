from unittest.mock import AsyncMock, MagicMock

import pytest

from prcrew.llm import AgentLLM


def _resp_with_tool_use(payload, input_tokens=10, output_tokens=20):
    block = MagicMock(); block.type = "tool_use"; block.input = payload
    resp = MagicMock(); resp.content = [block]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp

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

async def test_retries_once_then_succeeds():
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[RuntimeError("boom"), _resp_with_tool_use({"ok": 1})])
    out, _usage = await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert out == {"ok": 1}

async def test_raises_after_second_failure():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert client.messages.create.call_count == 2
