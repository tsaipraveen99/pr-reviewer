import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.testclient import TestClient

from prcrew.api.webhook_routes import make_webhook_router
from prcrew.db import Base, Installation, Repo, make_session_factory
from prcrew.github.webhooks import RecentDeliveries
from prcrew.settings import Settings

SECRET = "whsec"


@pytest.fixture()
def harness(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/wh.db")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_setup())
    factory = make_session_factory(engine)
    enqueued: list[dict] = []
    settings = Settings(github_webhook_secret=SECRET, allowed_installation_ids="111")
    router = make_webhook_router(settings, factory, enqueued.append, RecentDeliveries())
    app = FastAPI()
    app.include_router(router)
    yield app, factory, enqueued
    asyncio.run(engine.dispose())


def post(client, event: str, payload: dict, delivery: str = "d-1", secret: str = SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": event, "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": sig, "Content-Type": "application/json"})


PR_PAYLOAD = {
    "action": "opened",
    "installation": {"id": 111},
    "repository": {"id": 999, "full_name": "x/y", "default_branch": "main"},
    "pull_request": {"number": 7, "draft": False,
                     "head": {"sha": "b" * 40},
                     "user": {"type": "User"}},
}


def test_bad_signature_401(harness):
    app, _, enqueued = harness
    with TestClient(app) as client:
        assert post(client, "pull_request", PR_PAYLOAD, secret="wrong").status_code == 401
    assert enqueued == []


def test_pr_opened_enqueues(harness):
    app, _, enqueued = harness
    with TestClient(app) as client:
        r = post(client, "pull_request", PR_PAYLOAD)
    assert r.status_code == 202
    assert enqueued == [{"installation_id": 111, "repo_id": 999, "repo_full_name": "x/y",
                         "pr_number": 7, "head_sha": "b" * 40}]


def test_duplicate_delivery_not_reenqueued(harness):
    app, _, enqueued = harness
    with TestClient(app) as client:
        post(client, "pull_request", PR_PAYLOAD, delivery="same")
        r = post(client, "pull_request", PR_PAYLOAD, delivery="same")
    assert r.status_code == 202
    assert len(enqueued) == 1


def test_draft_bot_and_irrelevant_actions_skipped(harness):
    app, _, enqueued = harness
    draft = json.loads(json.dumps(PR_PAYLOAD)); draft["pull_request"]["draft"] = True
    bot = json.loads(json.dumps(PR_PAYLOAD)); bot["pull_request"]["user"]["type"] = "Bot"
    closed = json.loads(json.dumps(PR_PAYLOAD)); closed["action"] = "closed"
    with TestClient(app) as client:
        for i, p in enumerate((draft, bot, closed)):
            assert post(client, "pull_request", p, delivery=f"d-{i}").status_code == 202
    assert enqueued == []


def test_disallowed_installation_skipped(harness):
    app, _, enqueued = harness
    p = json.loads(json.dumps(PR_PAYLOAD)); p["installation"]["id"] = 42
    with TestClient(app) as client:
        assert post(client, "pull_request", p).status_code == 202
    assert enqueued == []


def test_installation_created_and_repo_upkeep(harness):
    app, factory, _ = harness
    created = {"action": "created",
               "installation": {"id": 111, "account": {"login": "tsaipraveen99"}},
               "repositories": [{"id": 999, "full_name": "x/y"}]}
    with TestClient(app) as client:
        assert post(client, "installation", created, delivery="i-1").status_code == 202
        added = {"action": "added", "installation": {"id": 111},
                 "repositories_added": [{"id": 1000, "full_name": "x/z"}],
                 "repositories_removed": []}
        assert post(client, "installation_repositories", added, delivery="i-2").status_code == 202

    async def _check():
        async with factory() as session:
            inst = (await session.execute(select(Installation))).scalar_one()
            repos = (await session.execute(select(Repo))).scalars().all()
            return inst, sorted(r.id for r in repos)
    inst, repo_ids = asyncio.run(_check())
    assert inst.id == 111 and inst.account_login == "tsaipraveen99"
    assert repo_ids == [999, 1000]


def test_installation_created_redelivery_is_idempotent(harness):
    # GitHub redelivers webhooks with a new delivery id but the same payload;
    # the "created" branch must upsert (session.merge) rather than insert, or
    # a redelivery raises IntegrityError -> 500.
    app, factory, _ = harness
    created = {"action": "created",
               "installation": {"id": 111, "account": {"login": "tsaipraveen99"}},
               "repositories": [{"id": 999, "full_name": "x/y"}]}
    with TestClient(app) as client:
        r1 = post(client, "installation", created, delivery="i-1")
        r2 = post(client, "installation", created, delivery="i-2")
    assert r1.status_code == 202
    assert r2.status_code == 202

    async def _check():
        async with factory() as session:
            insts = (await session.execute(select(Installation))).scalars().all()
            repos = (await session.execute(select(Repo))).scalars().all()
            return insts, repos
    insts, repos = asyncio.run(_check())
    assert len(insts) == 1
    assert insts[0].id == 111 and insts[0].account_login == "tsaipraveen99"
    assert len(repos) == 1
    assert repos[0].id == 999


def test_installation_repositories_added_redelivery_is_idempotent(harness):
    app, factory, _ = harness
    created = {"action": "created",
               "installation": {"id": 111, "account": {"login": "u"}},
               "repositories": []}
    added = {"action": "added", "installation": {"id": 111},
             "repositories_added": [{"id": 1000, "full_name": "x/z"}],
             "repositories_removed": []}
    with TestClient(app) as client:
        post(client, "installation", created, delivery="i-1")
        r1 = post(client, "installation_repositories", added, delivery="i-2")
        r2 = post(client, "installation_repositories", added, delivery="i-3")
    assert r1.status_code == 202
    assert r2.status_code == 202

    async def _check():
        async with factory() as session:
            repos = (await session.execute(
                select(Repo).where(Repo.id == 1000))).scalars().all()
            return repos
    repos = asyncio.run(_check())
    assert len(repos) == 1
    assert repos[0].full_name == "x/z"


def test_installation_deleted_removes_rows(harness):
    app, factory, _ = harness
    created = {"action": "created",
               "installation": {"id": 111, "account": {"login": "u"}},
               "repositories": [{"id": 999, "full_name": "x/y"}]}
    deleted = {"action": "deleted", "installation": {"id": 111, "account": {"login": "u"}}}
    with TestClient(app) as client:
        post(client, "installation", created, delivery="i-1")
        post(client, "installation", deleted, delivery="i-2")

    async def _count():
        async with factory() as session:
            insts = (await session.execute(select(Installation))).scalars().all()
            repos = (await session.execute(select(Repo))).scalars().all()
            return len(insts), len(repos)
    assert asyncio.run(_count()) == (0, 0)


def test_repo_redelivery_preserves_index_state(harness):
    app, factory, _ = harness
    added = {"action": "added", "installation": {"id": 111},
             "repositories_added": [{"id": 1000, "full_name": "x/z"}],
             "repositories_removed": []}
    with TestClient(app) as client:
        post(client, "installation_repositories", added, delivery="ix-1")

    async def _mark_ready():
        async with factory() as session:
            row = await session.get(Repo, 1000)
            row.index_status = "ready"
            row.indexed_commit = "deadbeef"
            await session.commit()
    asyncio.run(_mark_ready())

    with TestClient(app) as client:
        post(client, "installation_repositories", added, delivery="ix-2")

    async def _check():
        async with factory() as session:
            return await session.get(Repo, 1000)
    row = asyncio.run(_check())
    assert row.index_status == "ready"
    assert row.indexed_commit == "deadbeef"


def test_create_app_mounts_injected_router(harness):
    from prcrew.api.app import create_app
    # build a router with a fake enqueue, inject it, and assert the route is mounted.
    # FastAPI 0.141's app.routes wraps included routers in a private
    # _IncludedRouter with no flat `.path`, so we assert mounting behaviorally:
    # a request against the path must reach our router (401, from the deliberately
    # wrong signature) rather than fall through to a 404.
    _, factory, _ = harness
    router = make_webhook_router(Settings(github_webhook_secret=SECRET), factory,
                                 lambda kw: None, RecentDeliveries())
    app = create_app(run_manager=object(), github=object(), webhook_router=router)
    with TestClient(app) as client:
        r = client.post("/webhooks/github", content=b"{}", headers={
            "X-GitHub-Event": "ping", "X-GitHub-Delivery": "d-mount",
            "X-Hub-Signature-256": "sha256=bad", "Content-Type": "application/json"})
    assert r.status_code == 401
