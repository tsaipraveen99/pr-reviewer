import pytest
from sqlalchemy import select

from prcrew.db import Base, Review, make_engine, make_session_factory


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
