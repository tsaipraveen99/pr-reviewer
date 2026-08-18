import anthropic


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
        last_err: Exception | None = None
        for _ in range(2):  # one retry
            try:
                return await self._client.messages.create(
                    model=self.model, max_tokens=4096, system=system,
                    messages=[{"role": "user", "content": user}], **kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise last_err


def _usage(resp) -> dict:
    return {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
