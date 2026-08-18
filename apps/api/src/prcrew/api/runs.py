import asyncio
import uuid
from dataclasses import dataclass, field

from prcrew.models import PRContext

TERMINAL = {"done", "run_failed"}


@dataclass
class Run:
    id: str
    status: str = "running"
    events: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    result: dict | None = None


class RunManager:
    def __init__(self, graph):
        self._graph = graph
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def start(self, pr_context: PRContext) -> str:
        run = Run(id=uuid.uuid4().hex)
        self._runs[run.id] = run
        asyncio.create_task(self._execute(run, pr_context))
        return run.id

    async def _execute(self, run: Run, pr_context: PRContext) -> None:
        seq = 0

        async def emit(event: dict) -> None:
            nonlocal seq
            seq += 1
            stamped = {**event, "seq": seq}
            run.events.append(stamped)
            await run.queue.put(stamped)

        try:
            result = await self._graph.ainvoke(
                {"pr_context": pr_context}, {"configurable": {"emit": emit}}
            )
            run.result = {
                "review": result.get("review", ""),
                "verified": [v.model_dump() for v in result.get("verified", [])],
            }
            # Emit the terminal event before flipping status: the SSE
            # generator's fallback exit checks `run.status != "running"`, so
            # flipping status first could let it observe "done"/"failed"
            # before the terminal event is appended and close the stream
            # without ever delivering it.
            await emit({"type": "done"})
            run.status = "done"
        except Exception as e:  # noqa: BLE001
            await emit({"type": "run_failed", "error": str(e)})
            run.status = "failed"
