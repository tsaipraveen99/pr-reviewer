import json
import sqlite3
from datetime import datetime

import pytest

from prcrew.api.migrate_sqlite_runs import migrate
from prcrew.api.review_store import ReviewStore
from prcrew.db import Base, Review, make_engine, make_session_factory


@pytest.fixture
async def session_factory(tmp_path):
    """Create a temp SQLite session factory for testing."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/reviews.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    yield factory
    await engine.dispose()


def create_legacy_db(tmp_path) -> str:
    """Create a temp SQLite DB with the legacy runs schema and 2 test rows."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT,
                    pr_url TEXT,
                    status TEXT,
                    result_json TEXT,
                    events_json TEXT
                )
            """)
            # Row 1: without usage
            conn.execute(
                "INSERT INTO runs (id, created_at, pr_url, status, result_json, events_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run1", "2026-08-18T10:00:00Z", "https://github.com/o/r/pull/1",
                 "done", json.dumps({"review": "## Review 1"}),
                 json.dumps([{"type": "done", "seq": 1}]))
            )
            # Row 2: with usage in result
            conn.execute(
                "INSERT INTO runs (id, created_at, pr_url, status, result_json, events_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run2", "2026-08-18T11:00:00Z", "https://github.com/o/r/pull/2",
                 "done", json.dumps({
                     "review": "## Review 2",
                     "usage": {"input_tokens": 100, "output_tokens": 50}
                 }),
                 json.dumps([{"type": "done", "seq": 1}]))
            )
    finally:
        conn.close()
    return db_path


@pytest.mark.asyncio
async def test_migrate_legacy_runs(tmp_path, session_factory):
    """Test that migrate() copies legacy SQLite runs to Postgres, preserving created_at."""
    # Create legacy DB with 2 rows
    legacy_db_path = create_legacy_db(tmp_path)

    # First migration
    count = await migrate(legacy_db_path, session_factory)
    assert count == 2, f"Expected 2 rows migrated, got {count}"

    # Create a ReviewStore for verification
    store = ReviewStore(session_factory)

    # Verify both rows are in the store with correct data
    run1 = await store.load("run1")
    assert run1 is not None
    assert run1["pr_url"] == "https://github.com/o/r/pull/1"
    assert run1["status"] == "done"
    assert run1["result"]["review"] == "## Review 1"

    run2 = await store.load("run2")
    assert run2 is not None
    assert run2["pr_url"] == "https://github.com/o/r/pull/2"
    assert run2["status"] == "done"
    assert run2["result"]["review"] == "## Review 2"

    # Verify created_at is preserved by querying the Review directly
    # Parse legacy timestamps; fromisoformat handles Z suffix and creates aware datetimes,
    # but SQLite stores as naive, so we compare the naive version.
    expected_run1_created_at = datetime.fromisoformat("2026-08-18T10:00:00Z").replace(tzinfo=None)
    expected_run2_created_at = datetime.fromisoformat("2026-08-18T11:00:00Z").replace(tzinfo=None)

    async with session_factory() as s:
        row1 = await s.get(Review, "run1")
        assert row1 is not None
        assert row1.created_at == expected_run1_created_at

        row2 = await s.get(Review, "run2")
        assert row2 is not None
        assert row2.created_at == expected_run2_created_at

    # Re-run migration and verify no duplicates (merge should upsert)
    count2 = await migrate(legacy_db_path, session_factory)
    assert count2 == 2, f"Expected 2 rows on second run (idempotent), got {count2}"

    # Verify data is still intact and created_at unchanged after re-run
    run1_again = await store.load("run1")
    assert run1_again == run1

    async with session_factory() as s:
        row1_again = await s.get(Review, "run1")
        assert row1_again.created_at == expected_run1_created_at  # Still naive datetime
