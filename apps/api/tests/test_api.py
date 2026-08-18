import time

import pytest
from fastapi.testclient import TestClient

from prcrew.api.app import create_app
from prcrew.api.runs import RunManager
from prcrew.github.client import PrivateRepoError, PRTooLargeError
from prcrew.graph.build import build_graph
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
    return TestClient(create_app(run_manager=make_manager(), github=github))

def test_post_review_starts_run():
    c = client_with(FakeGitHub(result=CTX))
    resp = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    # poll until done (graph runs in background)
    for _ in range(50):
        status = c.get(f"/reviews/{run_id}").json()
        if status["status"] == "done": break
        time.sleep(0.05)
    assert status["result"]["review"] == "## R"

@pytest.mark.parametrize("error,code", [
    (PrivateRepoError("private"), 403),
    (PRTooLargeError("big"), 413),
])
def test_guard_errors_map_to_http(error, code):
    c = client_with(FakeGitHub(error=error))
    resp = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"})
    assert resp.status_code == code

def test_invalid_url_400():
    c = client_with(FakeGitHub(result=CTX))
    assert c.post("/reviews", json={"pr_url": "nope"}).status_code == 400

def test_stream_replays_events_and_terminates():
    c = client_with(FakeGitHub(result=CTX))
    run_id = c.post("/reviews", json={"pr_url": "https://github.com/o/r/pull/1"}).json()["run_id"]
    with c.stream("GET", f"/reviews/{run_id}/stream") as resp:
        body = "".join(chunk for chunk in resp.iter_text())
    assert "node_started" in body and "review_complete" in body

def test_unknown_run_404():
    c = client_with(FakeGitHub(result=CTX))
    assert c.get("/reviews/nope").status_code == 404
