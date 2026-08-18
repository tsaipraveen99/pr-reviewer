from prcrew.api.store import RunStore

RESULT = {"review": "## R", "verified": [], "usage": {"input_tokens": 1,
          "output_tokens": 1, "cost_usd": 0.0}}
EVENTS = [{"type": "node_started", "node": "intake", "seq": 1}]


def test_round_trip_save_and_load(tmp_path):
    store = RunStore(str(tmp_path / "sub" / "runs.db"))
    store.save("r1", "2026-08-18T00:00:00Z", "https://github.com/o/r/pull/1", "done",
               RESULT, EVENTS)
    assert store.load("r1") == {
        "status": "done",
        "pr_url": "https://github.com/o/r/pull/1",
        "result": RESULT,
        "events": EVENTS,
    }

def test_load_missing_run_returns_none(tmp_path):
    store = RunStore(str(tmp_path / "runs.db"))
    assert store.load("nope") is None

def test_creates_parent_dirs_on_init(tmp_path):
    db_path = tmp_path / "a" / "b" / "runs.db"
    RunStore(str(db_path))
    assert db_path.parent.is_dir()

def test_save_overwrites_existing_row_for_same_run_id(tmp_path):
    store = RunStore(str(tmp_path / "runs.db"))
    store.save("r1", "t0", "https://github.com/o/r/pull/1", "running", None, [])
    store.save("r1", "t0", "https://github.com/o/r/pull/1", "done", RESULT, EVENTS)
    assert store.load("r1")["status"] == "done"

def test_store_survives_across_instances_pointed_at_same_file(tmp_path):
    db_path = str(tmp_path / "runs.db")
    RunStore(db_path).save("r1", "t0", "https://github.com/o/r/pull/1", "done", RESULT, EVENTS)
    reopened = RunStore(db_path)
    assert reopened.load("r1")["result"] == RESULT
