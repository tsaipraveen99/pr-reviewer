import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from prcrew.api.app import client_ip, create_app
from prcrew.api.runs import RunManager
from prcrew.github.client import GitHubError, PrivateRepoError, PRTooLargeError
from prcrew.graph.build import build_graph
from prcrew.settings import Settings
from tests.fakes import FakeLLM
from tests.test_graph import findings_payload
from tests.test_specialists import CTX


class FakeGitHub:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
    async def fetch_pr(self, owner, repo, number):
        if self.error: raise self.error
        return self.result

def make_manager():
    specialist = FakeLLM([findings_payload("c")] * 4 +
                         [{"verdicts": [{"index": i, "verdict": "confirmed", "reason": "ok"}
                                        for i in range(4)]}])
    return RunManager(graph=build_graph(specialist, FakeLLM(["## R"])))

def client_with(github):
    # Must be entered via `with` so TestClient reuses a single portal/event
    # loop across requests -- that's also how it behaves under real uvicorn
    # (one persistent loop). Without `with`, TestClient spins up a fresh
    # portal per call, and a run's background task (started via
    # `asyncio.create_task` inside the POST handler) would never survive to
    # a later GET/stream call on that same run.
    return TestClient(create_app(run_manager=make_manager(), github=github))

def test_post_review_starts_run():
    with client_with(FakeGitHub(result=CTX)) as c:
        resp = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        # poll until done (graph runs in background)
        for _ in range(50):
            status = c.get(f"/reviews/{run_id}").json()
            if status["status"] == "done": break
            time.sleep(0.05)
        assert status["result"]["review"] == "## R"
        assert status["result"]["usage"]["input_tokens"] > 0
        assert status["result"]["usage"]["cost_usd"] > 0

@pytest.mark.parametrize("error,code", [
    (PrivateRepoError("private"), 403),
    (PRTooLargeError("big"), 413),
    (GitHubError(404, "Not Found"), 404),
    (GitHubError(500, "boom"), 502),
])
def test_guard_errors_map_to_http(error, code):
    with client_with(FakeGitHub(error=error)) as c:
        resp = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
        assert resp.status_code == code

def test_invalid_url_400():
    with client_with(FakeGitHub(result=CTX)) as c:
        assert c.post("/reviews", json={"pr_url": "nope"}).status_code == 400

def test_stream_replays_events_and_terminates():
    with client_with(FakeGitHub(result=CTX)) as c:
        run_id = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"}).json()["run_id"]
        with c.stream("GET", f"/reviews/{run_id}/stream") as resp:
            body = "".join(chunk for chunk in resp.iter_text())
        assert "node_started" in body and "review_complete" in body

def test_unknown_run_404():
    with client_with(FakeGitHub(result=CTX)) as c:
        assert c.get("/reviews/nope").status_code == 404

async def test_two_stream_consumers_both_receive_terminal_event():
    # Regression: a shared asyncio.Queue woke exactly one waiting consumer per
    # event, so a second open stream (second tab / overlapping reconnect)
    # hung forever. The Condition broadcast must deliver to both.
    app = create_app(run_manager=make_manager(), github=FakeGitHub(result=CTX))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
        run_id = resp.json()["run_id"]

        async def consume() -> str:
            async with c.stream("GET", f"/reviews/{run_id}/stream") as s:
                return "".join([chunk async for chunk in s.aiter_text()])

        body1, body2 = await asyncio.wait_for(
            asyncio.gather(consume(), consume()), timeout=10)
    for body in (body1, body2):
        assert "review_complete" in body
        assert "event: done" in body


class InstantGraph:
    async def ainvoke(self, state, config):
        return {"review": "## R", "verified": []}

async def test_runs_dict_evicts_oldest_finished_run(monkeypatch):
    monkeypatch.setattr("prcrew.api.runs.MAX_RUNS", 2)
    mgr = RunManager(graph=InstantGraph())
    first = await mgr.start(CTX)
    second = await mgr.start(CTX)
    for _ in range(50):  # let both background runs finish
        if all(mgr.get(r).status == "done" for r in (first, second)):
            break
        await asyncio.sleep(0.01)
    third = await mgr.start(CTX)
    assert mgr.get(first) is None  # oldest finished run evicted
    assert mgr.get(second) is not None and mgr.get(third) is not None

async def test_runs_dict_never_evicts_running_runs(monkeypatch):
    monkeypatch.setattr("prcrew.api.runs.MAX_RUNS", 2)
    mgr = RunManager(graph=InstantGraph())
    # Start 4 without yielding: all still "running" when eviction runs.
    ids = [await mgr.start(CTX) for _ in range(4)]
    assert all(mgr.get(i) is not None for i in ids)


def _request_with(headers: dict[str, str] | None = None, client=("10.0.0.1", 4242)):
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    return Request(scope)

def test_client_ip_uses_rightmost_forwarded_entry():
    req = _request_with({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert client_ip(req) == "5.6.7.8"

def test_client_ip_ignores_spoofed_left_entries():
    req = _request_with({"X-Forwarded-For": "9.9.9.9, 1.2.3.4, 5.6.7.8"})
    assert client_ip(req) == "5.6.7.8"

def test_client_ip_falls_back_to_socket_peer():
    assert client_ip(_request_with()) == "10.0.0.1"


def test_rate_limit_returns_429_after_quota():
    settings = Settings(daily_rate_limit="2/day")
    app = create_app(run_manager=make_manager(), github=FakeGitHub(result=CTX),
                     settings=settings)
    with TestClient(app) as c:
        url = {"pr_url": "https://github.com/o/r/pull/1"}
        assert c.post("/reviews", json=url).status_code == 202
        assert c.post("/reviews", json=url).status_code == 202
        assert c.post("/reviews", json=url).status_code == 429
