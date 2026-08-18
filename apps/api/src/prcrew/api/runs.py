import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from prcrew.models import PRContext

logger = logging.getLogger(__name__)

TERMINAL = {"done", "run_failed"}

# Cap on stored runs; oldest finished runs are evicted on start().
MAX_RUNS = 200


@dataclass
class Run:
    id: str
    status: str = "running"
    events: list[dict] = field(default_factory=list)
    # Broadcast primitive: every emit appends to `events` then notify_all()s,
    # so any number of concurrent SSE consumers wake up and re-read the list.
    # (An asyncio.Queue would wake exactly one waiting consumer per event.)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
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
        self._evict_finished()
        asyncio.create_task(self._execute(run, pr_context))
        return run.id

    def _evict_finished(self) -> None:
        """Evict oldest non-running runs until at most MAX_RUNS remain."""
        while len(self._runs) > MAX_RUNS:
            victim = next(
                (rid for rid, r in self._runs.items() if r.status != "running"), None
            )
            if victim is None:  # everything is still running; nothing safe to evict
                break
            del self._runs[victim]

    async def _execute(self, run: Run, pr_context: PRContext) -> None:
        seq = 0

        async def emit(event: dict) -> None:
            nonlocal seq
            seq += 1
            stamped = {**event, "seq": seq}
            run.events.append(stamped)
            async with run.condition:
                run.condition.notify_all()

        try:
            result = await self._graph.ainvoke(
                {"pr_context": pr_context}, {"configurable": {"emit": emit}}
            )
            usage_list = result.get("usage", [])
            run.result = {
                "review": result.get("review", ""),
                "verified": [v.model_dump() for v in result.get("verified", [])],
                "usage": {
                    "input_tokens": sum(u.input_tokens for u in usage_list),
                    "output_tokens": sum(u.output_tokens for u in usage_list),
                    "cost_usd": round(
                        sum(u.cost_usd for u in usage_list if u.cost_usd is not None), 6),
                },
            }
            # Emit the terminal event before flipping status: the SSE
            # generator's fallback exit checks `run.status != "running"`, so
            # flipping status first could let it observe "done"/"failed"
            # before the terminal event is appended and close the stream
            # without ever delivering it.
            await emit({"type": "done"})
            run.status = "done"
        except Exception:
            # Never surface raw exception text to anonymous clients.
            logger.exception("run %s failed", run.id)
            await emit({"type": "run_failed", "error": "internal error running the review"})
            run.status = "failed"
