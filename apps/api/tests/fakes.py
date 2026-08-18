class FakeLLM:
    """Drop-in for AgentLLM in tests. `responses` is popped per call;
    an Exception instance is raised instead of returned."""
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def structured(self, system: str, user: str, tool: dict) -> dict:
        return self._next(system, user)

    async def text(self, system: str, user: str) -> str:
        return self._next(system, user)

    def _next(self, system, user):
        self.calls.append((system, user))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
