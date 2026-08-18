import asyncio
import threading
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
    """Runs graphs on a dedicated background event loop/thread, owned for the
    lifetime of this manager. This is deliberate: `asyncio.create_task`
    scheduled from inside a request handler only survives if the caller's
    event loop keeps running after the handler returns. FastAPI/Starlette's
    TestClient spins up a *fresh* event loop per call unless used as a `with`
    context manager, so a task created during a POST would be silently
    orphaned the instant that request's loop tears down. Submitting the run
    to our own persistent loop via `run_coroutine_threadsafe` decouples
    execution from whichever short-lived loop triggered `start()`."""

    def __init__(self, graph):
        self._graph = graph
        self._runs: dict[str, Run] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def start(self, pr_context: PRContext) -> str:
        run = Run(id=uuid.uuid4().hex)
        self._runs[run.id] = run
        asyncio.run_coroutine_threadsafe(self._execute(run, pr_context), self._loop)
        return run.id

    async def _execute(self, run: Run, pr_context: PRContext) -> None:
        seq = 0
        async def emit(event: dict) -> None:
            nonlocal seq
            seq += 1
            stamped = {**event, "seq": seq}
            # `run.events` (a plain list) is the cross-thread source of
            # truth: appends here are read by pollers on whatever event loop
            # served the HTTP request. `run.queue` is not used for delivery
            # since it would be awaited from a different loop than the one
            # that constructed/writes it -- see class docstring.
            run.events.append(stamped)
        try:
            result = await self._graph.ainvoke(
                {"pr_context": pr_context},
                {"configurable": {"emit": emit}})
            run.result = {"review": result.get("review", ""),
                          "verified": [v.model_dump() for v in result.get("verified", [])]}
            run.status = "done"
            await emit({"type": "done"})
        except Exception as e:  # noqa: BLE001
            run.status = "failed"
            await emit({"type": "run_failed", "error": str(e)})
