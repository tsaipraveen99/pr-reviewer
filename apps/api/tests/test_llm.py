from unittest.mock import AsyncMock, MagicMock

import pytest

from prcrew.llm import AgentLLM


def _resp_with_tool_use(payload):
    block = MagicMock(); block.type = "tool_use"; block.input = payload
    resp = MagicMock(); resp.content = [block]
    return resp

async def test_structured_extracts_tool_input():
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_resp_with_tool_use({"findings": []}))
    llm = AgentLLM(model="m", client=client)
    out = await llm.structured("sys", "user", {"name": "report", "input_schema": {}})
    assert out == {"findings": []}
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "report"}

async def test_retries_once_then_succeeds():
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[RuntimeError("boom"), _resp_with_tool_use({"ok": 1})])
    out = await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert out == {"ok": 1}

async def test_raises_after_second_failure():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await AgentLLM("m", client=client).structured("s", "u", {"name": "t", "input_schema": {}})
    assert client.messages.create.call_count == 2
