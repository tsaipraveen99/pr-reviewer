import json
import sqlite3

import pytest

from prcrew.api.migrate_sqlite_runs import migrate
from prcrew.api.review_store import ReviewStore
from prcrew.db import Base, make_engine, make_session_factory


@pytest.fixture
async def postgres_store(tmp_path):
    """Create a temp Postgres-backed ReviewStore for testing."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/reviews.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield ReviewStore(make_session_factory(engine))
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
async def test_migrate_legacy_runs(tmp_path, postgres_store):
    """Test that migrate() copies legacy SQLite runs to ReviewStore without duplicates."""
    # Create legacy DB with 2 rows
    legacy_db_path = create_legacy_db(tmp_path)

    # Get the session factory from the store
    session_factory = postgres_store._sessions

    # First migration
    count = await migrate(legacy_db_path, session_factory)
    assert count == 2, f"Expected 2 rows migrated, got {count}"

    # Verify both rows are in the store
    run1 = await postgres_store.load("run1")
    assert run1 is not None
    assert run1["pr_url"] == "https://github.com/o/r/pull/1"
    assert run1["status"] == "done"
    assert run1["result"]["review"] == "## Review 1"

    run2 = await postgres_store.load("run2")
    assert run2 is not None
    assert run2["pr_url"] == "https://github.com/o/r/pull/2"
    assert run2["status"] == "done"
    assert run2["result"]["review"] == "## Review 2"

    # Re-run migration and verify no duplicates (merge should upsert)
    count2 = await migrate(legacy_db_path, session_factory)
    assert count2 == 2, f"Expected 2 rows on second run (idempotent), got {count2}"

    # Verify data is still intact
    run1_again = await postgres_store.load("run1")
    assert run1_again == run1
    run2_again = await postgres_store.load("run2")
    assert run2_again == run2
