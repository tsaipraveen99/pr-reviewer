import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from prcrew.db import Base, Installation, Repo, Review
from prcrew.settings import Settings
from prcrew.worker import tasks
from prcrew.worker import tasks as tasks_mod
from prcrew.worker.celery_app import app, make_celery
from prcrew.worker.tasks import handle_pr_event


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


@pytest.fixture()
def worker_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/worker.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    checks = FakeChecks()
    settings = Settings(allowed_installation_ids="111")
    monkeypatch.setattr(tasks_mod, "_deps", lambda: (factory, checks, settings))
    with factory() as s:
        s.add(Installation(id=111, account_login="x"))
        s.add(Repo(id=999, installation_id=111, full_name="x/y",
                   default_branch="main", index_status="pending"))
        s.commit()
    return factory, checks, settings, monkeypatch


KWARGS = {"installation_id": 111, "repo_id": 999, "repo_full_name": "x/y",
          "pr_number": 7, "head_sha": "b" * 40}


def test_happy_path_round_trip(worker_env):
    factory, checks, _, _ = worker_env
    assert handle_pr_event.delay(**KWARGS).get() == "completed"
    assert checks.created == [(111, "x", "y", "b" * 40)]
    (run_id, conclusion, _, _summary) = checks.completed[0]
    assert run_id == 555 and conclusion == "neutral"
    with factory() as s:
        review = s.execute(select(Review)).scalar_one()
    assert review.source == "github"
    assert review.repo_id == 999 and review.pr_number == 7
    assert review.check_run_id == 555
    assert review.status == "done"
    assert review.pr_url == "https://github.com/x/y/pull/7"


def test_duplicate_skipped(worker_env):
    _, checks, _, _ = worker_env
    handle_pr_event.delay(**KWARGS).get()
    assert handle_pr_event.delay(**KWARGS).get() == "duplicate"
    assert len(checks.created) == 1


def test_kill_switch(worker_env):
    factory, checks, _settings, monkeypatch = worker_env
    disabled = Settings(allowed_installation_ids="111", reviews_enabled=False)
    monkeypatch.setattr(tasks_mod, "_deps", lambda: (factory, checks, disabled))
    assert handle_pr_event.delay(**KWARGS).get() == "disabled"
    assert checks.created == []


def test_disallowed_installation(worker_env):
    assert handle_pr_event.delay(**{**KWARGS, "installation_id": 42}).get() == "not_allowed"


def test_failure_completes_check_run_neutral(worker_env):
    factory, checks, settings, monkeypatch = worker_env

    class ExplodingFactory:
        calls = 0

        def __call__(self):
            # first call (idempotency check) works, second (persist) explodes
            ExplodingFactory.calls += 1
            if ExplodingFactory.calls >= 2:
                raise RuntimeError("db down")
            return factory()

    monkeypatch.setattr(tasks_mod, "_deps",
                        lambda: (ExplodingFactory(), checks, settings))
    assert handle_pr_event.delay(**KWARGS).get() == "failed"
    assert checks.completed and checks.completed[0][1] == "neutral"


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

    tasks_mod._deps()
    tasks_mod._deps()

    assert len(made) == 1


def test_failure_when_complete_also_raises(worker_env):
    factory, _checks, settings, monkeypatch = worker_env

    class DoubleFailChecks(FakeChecks):
        def complete(self, *a, **kw):
            raise RuntimeError("github down")

    bad = DoubleFailChecks()

    class ExplodingFactory:
        calls = 0

        def __call__(self):
            ExplodingFactory.calls += 1
            if ExplodingFactory.calls >= 2:
                raise RuntimeError("db down")
            return factory()

    monkeypatch.setattr(tasks_mod, "_deps", lambda: (ExplodingFactory(), bad, settings))
    # must return "failed", not raise, even though complete() raises too
    assert handle_pr_event.delay(**KWARGS).get() == "failed"
