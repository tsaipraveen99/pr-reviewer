import pytest

from prcrew.api.review_store import ReviewStore
from prcrew.db import Base, make_engine, make_session_factory


@pytest.fixture
async def store(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield ReviewStore(make_session_factory(engine))
    await engine.dispose()


async def test_save_load_roundtrip(store):
    await store.save("r1", "https://github.com/o/r/pull/1", "done",
                     {"review": "## R", "verified": []},
                     [{"type": "done", "seq": 1}], {"input_tokens": 5})
    got = await store.load("r1")
    assert got == {"status": "done", "pr_url": "https://github.com/o/r/pull/1",
                   "result": {"review": "## R", "verified": []},
                   "events": [{"type": "done", "seq": 1}]}


async def test_save_is_upsert(store):
    await store.save("r1", "u", "running", None, [], None)
    await store.save("r1", "u", "done", {"review": "x", "verified": []}, [], None)
    assert (await store.load("r1"))["status"] == "done"


async def test_load_missing_returns_none(store):
    assert await store.load("nope") is None
