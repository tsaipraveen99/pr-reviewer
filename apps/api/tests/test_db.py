import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from prcrew.db import (
    Base,
    Installation,
    Repo,
    Review,
    make_engine,
    make_session_factory,
    make_sync_engine,
    sync_url,
)


@pytest.fixture
async def session_factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    await engine.dispose()


async def test_review_roundtrip(session_factory):
    async with session_factory() as s:
        s.add(Review(id="abc", source="web", pr_url="https://github.com/o/r/pull/1",
                     status="done", result_json={"review": "## R"},
                     events_json=[{"type": "done", "seq": 1}],
                     usage_json={"input_tokens": 1}))
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(Review).where(Review.id == "abc"))).scalar_one()
        assert row.result_json["review"] == "## R"
        assert row.events_json[0]["type"] == "done"
        assert row.created_at is not None
        assert row.repo_id is None and row.pr_number is None


def test_sync_url_strips_async_drivers():
    assert sync_url("sqlite+aiosqlite:///./data/app.db") == "sqlite:///./data/app.db"
    assert sync_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_make_sync_engine_is_sync_sqlite(tmp_path):
    engine = make_sync_engine(f"sqlite+aiosqlite:///{tmp_path}/x.db")
    assert engine.dialect.name == "sqlite"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("select 1").scalar_one() == 1
    engine.dispose()


async def test_installation_and_repo_roundtrip(session_factory):
    async with session_factory() as session:
        session.add(Installation(id=111, account_login="tsaipraveen99"))
        session.add(Repo(id=999, installation_id=111, full_name="tsaipraveen99/pr-reviewer",
                         default_branch="main", index_status="pending"))
        await session.commit()
    async with session_factory() as session:
        repo = (await session.execute(select(Repo))).scalar_one()
        assert repo.full_name == "tsaipraveen99/pr-reviewer"
        assert repo.indexed_commit is None


async def test_reviews_idempotency_unique_index(session_factory):
    async with session_factory() as session:
        session.add(Installation(id=111, account_login="x"))
        session.add(Repo(id=999, installation_id=111, full_name="x/y",
                         default_branch="main", index_status="pending"))
        session.add(Review(id="r1", source="github", repo_id=999, pr_number=1,
                           head_sha="a" * 40, pr_url="https://github.com/x/y/pull/1",
                           status="done"))
        await session.commit()
    async with session_factory() as session:
        session.add(Review(id="r2", source="github", repo_id=999, pr_number=1,
                           head_sha="a" * 40, pr_url="https://github.com/x/y/pull/1",
                           status="done"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_web_reviews_with_null_repo_do_not_collide(session_factory):
    async with session_factory() as session:
        session.add(Review(id="w1", source="web", pr_url="https://github.com/a/b/pull/1",
                           status="done"))
        session.add(Review(id="w2", source="web", pr_url="https://github.com/a/b/pull/2",
                           status="done"))
        await session.commit()  # NULLs are distinct in the unique index
