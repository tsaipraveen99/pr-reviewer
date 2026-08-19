class FakeLLM:
    """Drop-in for AgentLLM in tests. `responses` is popped per call;
    an Exception instance is raised instead of returned. Each successful
    call returns a fixed nominal usage alongside the payload so cost/token
    aggregation is assertable. `model` defaults to a priced model so
    cost_usd(...) resolves to a real number in tests that don't care about
    pricing specifically."""
    def __init__(self, responses: list, model: str = "claude-sonnet-5-20260101"):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.tool_loop_calls: list[dict] = []
        self.model = model

    async def structured(self, system: str, user: str, tool: dict) -> tuple[dict, dict]:
        return self._next(system, user)

    async def text(self, system: str, user: str) -> tuple[str, dict]:
        return self._next(system, user)

    async def tool_loop(self, system: str, user: str, tools: list, executors: dict,
                        final_tool: dict, max_tool_calls: int = 10,
                        max_tokens: int = 4096, token_budget: int | None = None,
                        ) -> tuple[dict, dict]:
        self.tool_loop_calls.append({
            "system": system, "user": user, "tools": tools, "executors": executors,
            "final_tool": final_tool, "max_tool_calls": max_tool_calls,
            "max_tokens": max_tokens, "token_budget": token_budget,
        })
        return self._next(system, user)

    def _next(self, system, user):
        self.calls.append((system, user))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"input_tokens": 100, "output_tokens": 50}
