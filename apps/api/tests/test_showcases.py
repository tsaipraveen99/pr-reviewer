import json

from fastapi.testclient import TestClient

from prcrew.api.app import create_app
from prcrew.showcases import store

SAMPLE = {"slug": "sample", "title": "Sample PR", "pr_url": "https://github.com/o/r/pull/1",
          "recorded_at": "2026-08-17T00:00:00Z",
          "events": [{"type": "node_started", "node": "intake", "seq": 1, "at_ms": 0}],
          "review": "## R"}

def _write_sample(tmp_path, monkeypatch):
    (tmp_path / "sample.json").write_text(json.dumps(SAMPLE))
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

def test_list_showcases(tmp_path, monkeypatch):
    _write_sample(tmp_path, monkeypatch)
    c = TestClient(create_app(run_manager=object(), github=object()))
    listed = c.get("/showcases").json()
    assert listed == [{"slug": "sample", "title": "Sample PR",
                       "pr_url": "https://github.com/o/r/pull/1"}]

def test_get_showcase_and_404(tmp_path, monkeypatch):
    _write_sample(tmp_path, monkeypatch)
    c = TestClient(create_app(run_manager=object(), github=object()))
    assert c.get("/showcases/sample").json()["review"] == "## R"
    assert c.get("/showcases/missing").status_code == 404
