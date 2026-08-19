from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from prcrew.db import Base, Installation, Repo, Review
from prcrew.models import PRContext
from prcrew.settings import Settings
from prcrew.worker import tasks
from prcrew.worker import tasks as tasks_mod
from prcrew.worker.celery_app import app, make_celery
from prcrew.worker.tasks import Deps, handle_pr_event, refresh_index
from tests.test_clones import head_sha, make_origin


def test_make_celery_config():
    config_app = make_celery(Settings())
    assert config_app.conf.task_acks_late is True
    assert config_app.conf.broker_url.startswith("redis://")


def test_ping_eager():
    # Set eager mode on the module-level app that tasks.ping is bound to
    prior_eager = app.conf.task_always_eager
    try:
        app.conf.task_always_eager = True
        # Use delay() to route through eager mode (not apply())
        assert tasks.ping.delay().get() == "pong"
    finally:
        app.conf.task_always_eager = prior_eager


@pytest.fixture(autouse=True)
def _celery_eager():
    # Route delay() through eager mode instead of a real Redis broker/backend.
    prior_eager = app.conf.task_always_eager
    app.conf.task_always_eager = True
    yield
    app.conf.task_always_eager = prior_eager


class FakeChecks:
    def __init__(self):
        self.created: list[tuple] = []
        self.completed: list[tuple] = []

    def create(self, installation_id, owner, repo, head_sha):
        self.created.append((installation_id, owner, repo, head_sha))
        return 555

    def complete(self, installation_id, owner, repo, check_run_id, conclusion, title, summary):
        self.completed.append((check_run_id, conclusion, title, summary))


class DoubleFailChecks(FakeChecks):
    """A checks client whose create() succeeds but complete() also raises,
    so tests can prove a completion failure never masks the original one."""
    def complete(self, *a, **kw):
        raise RuntimeError("github down")


class FakeTokens:
    def token(self, installation_id):
        return "ghs_test"


class FakeAppClient:
    """Unused by default: fetch_pr and post_review are monkeypatched at
    their source modules in these tests, so the real AppClient (and its
    real HTTP calls) never gets exercised."""


def _route_clone_to_local_origin(monkeypatch, origin: Path):
    """The task builds its clone URL as https://...@github.com/<repo>.git,
    which tests can't reach. Wrap the real ensure_clone so it still runs
    for real (real git subprocess calls, real checkout) but against a
    local origin repo instead of the network."""
    import prcrew.worker.clones as clones_mod
    real_ensure_clone = clones_mod.ensure_clone

    def wrapper(clone_url, dest, ref, sha, token=None):
        return real_ensure_clone(f"file://{origin}", dest, ref, sha, token=token)

    monkeypatch.setattr(clones_mod, "ensure_clone", wrapper)


def _route_clone_to_missing_origin(monkeypatch, tmp_path: Path):
    """Same seam as above, but pointed at a path with no repo, so the real
    ensure_clone deterministically raises CloneError (no network needed)."""
    import prcrew.worker.clones as clones_mod
    real_ensure_clone = clones_mod.ensure_clone
    missing = tmp_path / "no-such-origin"

    def wrapper(clone_url, dest, ref, sha, token=None):
        return real_ensure_clone(f"file://{missing}", dest, ref, sha, token=token)

    monkeypatch.setattr(clones_mod, "ensure_clone", wrapper)


@pytest.fixture()
def worker_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/worker.db")
    Base.metadata.create_all(engine)
    from prgraph.db import Base as GraphBase
    GraphBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    checks = FakeChecks()
    settings = Settings(allowed_installation_ids="111", clones_dir=str(tmp_path / "clones"))
    deps = Deps(factory, checks, FakeAppClient(), FakeTokens(), settings)
    monkeypatch.setattr(tasks_mod, "_deps", lambda: deps)
    with factory() as s:
        s.add(Installation(id=111, account_login="x"))
        s.add(Repo(id=999, installation_id=111, full_name="x/y",
                   default_branch="main", index_status="pending"))
        s.commit()
    return factory, checks, settings, monkeypatch


def kwargs_for(origin: Path, pr_number: int = 1, sha: str | None = None) -> dict:
    return {"installation_id": 111, "repo_id": 999, "repo_full_name": "x/y",
            "pr_number": pr_number, "head_sha": sha or head_sha(origin)}


# A diff whose only hunk covers lines 1-2 of app.py -- matches the file
# make_origin() writes, and gives an intent finding on line 2 a changed
# range to map inline against.
DIFF = ("diff --git a/app.py b/app.py\n"
        "index 0000000..1111111 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def f():\n"
        "-    return 1\n"
        "+    return 1\n")


def make_ctx(**overrides) -> PRContext:
    fields = {"owner": "x", "repo": "y", "number": 1, "title": "Fix parser",
              "body": "Fixes #9", "linked_issue": None, "diff": DIFF,
              "changed_files": 1, "changed_lines": 2}
    fields.update(overrides)
    return PRContext(**fields)


def fake_fetch_pr(ctx, meta=None):
    def _fetch(client, installation_id, owner, repo, number):
        return ctx, (meta or {})
    return _fetch


def install_fetch_pr(monkeypatch, ctx, meta=None):
    import prcrew.github.pr_data as pr_data_mod
    monkeypatch.setattr(pr_data_mod, "fetch_pr", fake_fetch_pr(ctx, meta))


def install_post_review(monkeypatch, calls: list, review_id: int = 4242):
    import prcrew.github.pr_reviews as pr_reviews_mod

    def fake_post_review(client, installation_id, owner, repo, number, body, comments):
        calls.append({"installation_id": installation_id, "owner": owner, "repo": repo,
                      "number": number, "body": body, "comments": comments})
        return review_id

    monkeypatch.setattr(pr_reviews_mod, "post_review", fake_post_review)


def two_findings_result():
    intent_finding = {"id": "intent-0", "agent": "intent", "file": "app.py", "line": 2,
                      "severity": "major", "claim": "diverges from description",
                      "evidence": "the diff drops validation the PR body promises",
                      "verdict": "confirmed", "reason": "checked against the description"}
    correctness_finding = {"id": "correctness-0", "agent": "correctness", "file": "app.py",
                           "line": 2, "severity": "minor", "claim": "no error handling",
                           "evidence": "bare return", "verdict": "confirmed",
                           "reason": "plausible but not blocking"}
    result = {"review": "## Full crew review\n\nLooks fine overall.",
              "verified": [intent_finding, correctness_finding],
              "usage": {"input_tokens": 123, "output_tokens": 45, "cost_usd": 0.001}}
    events = [{"type": "node_started", "node": "intake", "seq": 1},
              {"type": "node_finished", "node": "intake", "seq": 2},
              {"type": "done", "seq": 3}]
    return result, events


def install_run_crew(monkeypatch, result=None, events=None, side_effect=None):
    calls = []

    def fake_run_crew(ctx, slice_text, toolbelt, settings):
        calls.append({"ctx": ctx, "slice_text": slice_text, "toolbelt": toolbelt,
                      "settings": settings})
        if side_effect is not None:
            return side_effect(calls)
        return result, events

    monkeypatch.setattr(tasks_mod, "_run_crew", fake_run_crew)
    return calls


def never_called(name):
    def _boom(*a, **kw):
        raise AssertionError(f"{name} should not have been called")
    return _boom


def test_happy_path_completes(worker_env, tmp_path, monkeypatch):
    factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)
    result, events = two_findings_result()
    run_crew_calls = install_run_crew(monkeypatch, result=result, events=events)
    post_review_calls: list = []
    install_post_review(monkeypatch, post_review_calls)

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "completed"
    assert len(run_crew_calls) == 1

    with factory() as s:
        review = s.execute(select(Review)).scalar_one()
        repo = s.get(Repo, 999)

    assert review.status == "done"
    assert review.result_json["review"] == result["review"]
    assert review.result_json["usage"] == result["usage"]
    assert review.events_json[-1] == {"type": "done", "seq": 3}
    assert review.usage_json == review.result_json["usage"]
    assert review.github_review_id == 4242

    assert repo.index_status == "ready"
    assert repo.indexed_commit == kwargs["head_sha"]

    assert len(checks.created) == 1
    (check_run_id, conclusion, title, _summary) = checks.completed[0]
    assert check_run_id == 555 and conclusion == "neutral"
    assert "confirmed finding" in title

    assert len(post_review_calls) == 1
    comments = post_review_calls[0]["comments"]
    assert len(comments) == 1
    assert comments[0]["path"] == "app.py" and comments[0]["line"] == 2


def test_duplicate_skipped(worker_env, tmp_path, monkeypatch):
    _factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)
    result, events = two_findings_result()
    install_run_crew(monkeypatch, result=result, events=events)
    install_post_review(monkeypatch, [])

    assert handle_pr_event.delay(**kwargs).get() == "completed"
    assert handle_pr_event.delay(**kwargs).get() == "duplicate"
    assert len(checks.created) == 1


def test_supersede_on_enqueue(worker_env, tmp_path, monkeypatch):
    factory, _checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    old_sha = "a" * 40
    with factory() as s:
        s.add(Review(id="old-review", source="github", repo_id=999, pr_number=1,
                     head_sha=old_sha, pr_url="https://github.com/x/y/pull/1",
                     status="running", check_run_id=111))
        s.commit()

    kwargs = kwargs_for(origin)  # new head sha, same repo/pr
    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)
    result, events = two_findings_result()
    install_run_crew(monkeypatch, result=result, events=events)
    install_post_review(monkeypatch, [])

    assert handle_pr_event.delay(**kwargs).get() == "completed"

    with factory() as s:
        old_row = s.get(Review, "old-review")
        new_row = s.execute(
            select(Review).where(Review.head_sha == kwargs["head_sha"])).scalar_one()
    assert old_row.status == "superseded"
    assert new_row.status == "done"


def test_supersede_mid_flight(worker_env, tmp_path, monkeypatch):
    factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)
    result, events = two_findings_result()

    def flip_to_superseded(_calls):
        with factory() as s:
            row = s.execute(
                select(Review).where(Review.repo_id == 999, Review.pr_number == 1,
                                     Review.head_sha == kwargs["head_sha"])).scalar_one()
            row.status = "superseded"
            s.commit()
        return result, events

    install_run_crew(monkeypatch, side_effect=flip_to_superseded)
    post_review_calls: list = []
    install_post_review(monkeypatch, post_review_calls)

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "superseded"
    assert post_review_calls == []  # never reached post_review
    with factory() as s:
        review = s.execute(select(Review)).scalar_one()
    assert review.status == "superseded"
    assert review.result_json is None  # never overwritten to "done"

    (check_run_id, conclusion, title, _summary) = checks.completed[0]
    assert check_run_id == 555 and conclusion == "neutral"
    assert "superseded" in title


def test_ineligible_too_large(worker_env, tmp_path, monkeypatch):
    factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    install_fetch_pr(monkeypatch, make_ctx(changed_files=100, changed_lines=5))
    monkeypatch.setattr(tasks_mod, "_run_crew", never_called("_run_crew"))
    import prcrew.github.pr_reviews as pr_reviews_mod
    monkeypatch.setattr(pr_reviews_mod, "post_review", never_called("post_review"))

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "ineligible"
    with factory() as s:
        review = s.execute(select(Review)).scalar_one()
    assert review.status == "skipped"
    (_id, conclusion, _title, summary) = checks.completed[0]
    assert conclusion == "neutral"
    assert "too large" in summary


def test_ineligible_daily_cap(worker_env, tmp_path, monkeypatch):
    factory, checks, _settings, mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    capped_settings = Settings(allowed_installation_ids="111",
                               clones_dir=str(tmp_path / "clones"), daily_repo_cap=1)
    deps = Deps(factory, checks, FakeAppClient(), FakeTokens(), capped_settings)
    mp.setattr(tasks_mod, "_deps", lambda: deps)

    # One github review already counts toward today's cap for this repo
    # (different PR so it doesn't collide with the new review's uniqueness).
    with factory() as s:
        s.add(Review(id="prior-review", source="github", repo_id=999, pr_number=2,
                     head_sha="c" * 40, pr_url="https://github.com/x/y/pull/2",
                     status="done"))
        s.commit()

    install_fetch_pr(monkeypatch, make_ctx())
    monkeypatch.setattr(tasks_mod, "_run_crew", never_called("_run_crew"))

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "ineligible"
    with factory() as s:
        review = s.execute(
            select(Review).where(Review.head_sha == kwargs["head_sha"])).scalar_one()
    assert review.status == "skipped"
    (_id, conclusion, _title, summary) = checks.completed[0]
    assert conclusion == "neutral"
    assert "cap" in summary.lower()


def test_clone_failure_retries_genuinely_and_final_failure_creates_nothing(
        worker_env, tmp_path, monkeypatch):
    # Regression for a production defect found in round 1: check_run_id and
    # review_id used to be created *before* the clone was attempted, so a
    # CloneError -> self.retry() redelivery hit its own "running" row via
    # the idempotency check and returned "duplicate" forever -- the check
    # run sat in_progress forever and the clone was never actually retried.
    # Now check_run_id/review_id are only created after ensure_clone
    # succeeds, so every redelivery (up to max_retries=2, i.e. 3 attempts
    # total) genuinely re-attempts the clone from a clean slate.
    factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_missing_origin(monkeypatch, tmp_path)
    monkeypatch.setattr(tasks_mod, "_run_crew", never_called("_run_crew"))
    import prcrew.github.pr_reviews as pr_reviews_mod
    monkeypatch.setattr(pr_reviews_mod, "post_review", never_called("post_review"))

    # Empirically verified (not assumed) in eager mode: self.retry(exc=e,
    # ...) raises celery.exceptions.Retry while retries remain, which
    # Task.apply() catches and recursively re-invokes the whole task from
    # scratch (celery.app.task.Task.apply / Task.retry source). Once
    # max_retries is exhausted, retry()'s own `raise_with_context(exc)`
    # re-raises the *original* CloneError (since exc=e was supplied) from
    # inside our nested `except CloneError` block -- so it is caught by
    # this task's own `except Exception:` handler before it ever escapes to
    # Celery's outer machinery (no MaxRetriesExceededError surfaces here).
    # Because check_run_id/review_id are still None at that point (the
    # clone never once succeeded), the guarded handler creates neither a
    # check run nor a review row: nothing is left stranded in_progress.
    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "failed"
    assert checks.created == []
    with factory() as s:
        assert s.execute(select(Review)).scalars().all() == []


def test_redelivery_after_prior_failed_row_completes_cleanly(worker_env, tmp_path, monkeypatch):
    # Regression for the second round-1 defect: the idempotency SELECT
    # excludes "failed" rows (so a retry-after-failure isn't treated as a
    # duplicate), but the review-row INSERT used to be unconditional -- a
    # redelivery after a prior "failed" row for the same (repo_id,
    # pr_number, head_sha) crashed uncaught on uq_reviews_repo_pr_sha. The
    # purge (delete stale "failed" rows for this key) right after the
    # idempotency check makes the later insert safe by construction.
    factory, _checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    with factory() as s:
        s.add(Review(id="prior-failed", source="github", repo_id=999, pr_number=1,
                     head_sha=kwargs["head_sha"],
                     pr_url="https://github.com/x/y/pull/1", status="failed"))
        s.commit()

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)
    result, events = two_findings_result()
    install_run_crew(monkeypatch, result=result, events=events)
    install_post_review(monkeypatch, [])

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "completed"  # not an uncaught IntegrityError
    with factory() as s:
        rows = s.execute(
            select(Review).where(Review.repo_id == 999, Review.pr_number == 1,
                                 Review.head_sha == kwargs["head_sha"])).scalars().all()
    assert len(rows) == 1  # the stale "failed" row was purged, not duplicated
    assert rows[0].status == "done"


def test_crew_failure_returns_failed_even_if_check_completion_also_raises(
        worker_env, tmp_path, monkeypatch):
    factory, _checks, _settings, mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    bad_checks = DoubleFailChecks()
    deps = Deps(factory, bad_checks, FakeAppClient(), FakeTokens(), _settings)
    mp.setattr(tasks_mod, "_deps", lambda: deps)

    install_fetch_pr(monkeypatch, make_ctx())
    _route_clone_to_local_origin(monkeypatch, origin)

    def boom(_calls):
        raise RuntimeError("crew blew up")

    install_run_crew(monkeypatch, side_effect=boom)
    import prcrew.github.pr_reviews as pr_reviews_mod
    monkeypatch.setattr(pr_reviews_mod, "post_review", never_called("post_review"))

    # Must return "failed", not raise, even though checks.complete() raises too.
    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "failed"
    with factory() as s:
        review = s.execute(select(Review)).scalar_one()
    assert review.status == "failed"
    assert bad_checks.created  # create() succeeded before complete() blew up


def test_kill_switch(worker_env, tmp_path):
    factory, checks, _settings, mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)
    disabled = Settings(allowed_installation_ids="111", reviews_enabled=False)
    deps = Deps(factory, checks, FakeAppClient(), FakeTokens(), disabled)
    mp.setattr(tasks_mod, "_deps", lambda: deps)
    assert handle_pr_event.delay(**kwargs).get() == "disabled"
    assert checks.created == []


def test_disallowed_installation(worker_env, tmp_path):
    origin = make_origin(tmp_path)
    kwargs = {**kwargs_for(origin), "installation_id": 42}
    assert handle_pr_event.delay(**kwargs).get() == "not_allowed"


@pytest.fixture()
def worker_env_with_origin(worker_env, tmp_path, monkeypatch):
    """worker_env plus a real git origin routed in place of the network clone
    -- same plumbing test_happy_path_completes uses for handle_pr_event,
    reused here so refresh_index exercises a real clone+index against sqlite."""
    factory, checks, settings, _mp = worker_env
    origin = make_origin(tmp_path)
    _route_clone_to_local_origin(monkeypatch, origin)
    sha = head_sha(origin)
    return factory, checks, settings, monkeypatch, origin, sha


def test_refresh_index_clones_and_indexes(worker_env_with_origin):
    factory, _checks, _settings, _mp, _origin, sha = worker_env_with_origin
    result = refresh_index.delay(installation_id=111, repo_id=999,
                                 repo_full_name="x/y", head_sha=sha,
                                 default_branch="main").get()
    assert result == "indexed"
    with factory() as s:
        row = s.get(Repo, 999)
    assert row.index_status == "ready" and row.indexed_commit == sha


def test_refresh_index_disallowed(worker_env_with_origin):
    _factory, _checks, _settings, _mp, _origin, sha = worker_env_with_origin
    outcome = refresh_index.delay(installation_id=42, repo_id=999,
                                  repo_full_name="x/y", head_sha=sha,
                                  default_branch="main").get()
    assert outcome == "not_allowed"


def test_refresh_index_clone_failure_returns_failed(worker_env, tmp_path, monkeypatch):
    # Uses worker_env (not worker_env_with_origin) directly: the latter
    # already routes ensure_clone to a wrapper closing over the real
    # function, and _route_clone_to_missing_origin would then wrap *that*
    # wrapper instead of the real ensure_clone, silently succeeding against
    # the local origin instead of failing. Mirrors
    # test_clone_failure_retries_genuinely_and_final_failure_creates_nothing.
    factory, _checks, _settings, _mp = worker_env
    _route_clone_to_missing_origin(monkeypatch, tmp_path)
    outcome = refresh_index.delay(installation_id=111, repo_id=999,
                                  repo_full_name="x/y", head_sha="d" * 40,
                                  default_branch="main").get()
    assert outcome == "failed"
    with factory() as s:
        row = s.get(Repo, 999)
    assert row.index_status == "pending"  # unchanged: clone never succeeded


def test_deps_reuses_engine(monkeypatch, tmp_path):
    # Drives the REAL _deps() (not the worker_env fixture's monkeypatched
    # seam) to verify engines are cached per DATABASE_URL rather than
    # rebuilt on every task invocation.
    import prcrew.db as db_mod

    made: list[str] = []
    real_make_sync_engine = db_mod.make_sync_engine

    def counting(url):
        made.append(url)
        return real_make_sync_engine(url)

    monkeypatch.setattr(db_mod, "make_sync_engine", counting)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/deps-test.db")
    tasks_mod._ENGINES.clear()
    try:
        deps1 = tasks_mod._deps()
        tasks_mod._deps()
        assert isinstance(deps1, Deps)
        assert deps1.session_factory is not None
        assert len(made) == 1
    finally:
        for engine in tasks_mod._ENGINES.values():
            engine.dispose()
        tasks_mod._ENGINES.clear()


def test_fetch_failure_completes_visible_check(worker_env, tmp_path, monkeypatch):
    factory, checks, _settings, _mp = worker_env
    origin = make_origin(tmp_path)
    kwargs = kwargs_for(origin)

    import prcrew.github.pr_data as pr_data_mod
    from prcrew.github.client import GitHubError

    def boom(client, installation_id, owner, repo, number):
        raise GitHubError(502, "bad gateway")

    monkeypatch.setattr(pr_data_mod, "fetch_pr", boom)

    outcome = handle_pr_event.delay(**kwargs).get()

    assert outcome == "failed"
    assert checks.created            # a check run WAS created
    assert checks.completed[0][1] == "neutral"
    assert "could not fetch" in checks.completed[0][3]
    with factory() as s:             # and no review row exists
        assert s.execute(select(Review)).scalars().all() == []


def test_run_crew_shapes_result_and_stamps_events(monkeypatch):
    # Fakes the graph build itself (build_graph), not the LLM: the point of
    # this test is _run_crew's own plumbing -- aggregating usage, shaping
    # the web-facing result dict, and seq-stamping every emitted event
    # ending in {"type": "done"} -- not the graph's internal behavior
    # (covered separately by tests/test_graph.py).
    import prcrew.graph.build as build_mod
    from prcrew.models import NodeUsage, VerifiedFinding

    class StubGraph:
        async def ainvoke(self, state, config):
            emit = config["configurable"]["emit"]
            await emit({"type": "node_started", "node": "intake"})
            await emit({"type": "node_finished", "node": "intake"})
            return {
                "review": "## stub review",
                "verified": [VerifiedFinding(agent="intent", file="a.py", line=1,
                                             severity="minor", claim="c", evidence="e",
                                             verdict="confirmed", reason="r")],
                "usage": [NodeUsage(node="intake", input_tokens=10, output_tokens=5,
                                    cost_usd=0.01),
                         NodeUsage(node="synth", input_tokens=20, output_tokens=8,
                                    cost_usd=0.02)],
            }

    def fake_build_graph(specialist_llm, synth_llm, intent_node=None):
        return StubGraph()

    monkeypatch.setattr(build_mod, "build_graph", fake_build_graph)

    ctx = make_ctx()
    result, events = tasks_mod._run_crew(ctx, "slice text", toolbelt=None,
                                         settings=Settings())

    assert result["review"] == "## stub review"
    assert len(result["verified"]) == 1
    assert result["verified"][0]["agent"] == "intent"
    assert result["usage"] == {"input_tokens": 30, "output_tokens": 13, "cost_usd": 0.03}

    assert [e["type"] for e in events] == ["node_started", "node_finished", "done"]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[-1] == {"type": "done", "seq": 3}
