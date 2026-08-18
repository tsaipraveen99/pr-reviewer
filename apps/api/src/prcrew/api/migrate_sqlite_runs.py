"""One-time migration script: SQLite runs -> Postgres reviews.

Reads from legacy SQLite DB with schema:
  runs(id TEXT PRIMARY KEY, created_at TEXT, pr_url TEXT, status TEXT,
       result_json TEXT, events_json TEXT)

Writes to reviews table, preserving legacy created_at timestamps, extracting
usage from result_json when present, setting source="web" for all legacy rows.

Usage: uv run python scripts/migrate_sqlite_runs.py <legacy.db>
  Reads DATABASE_URL from environment.
"""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prcrew.db import Base, Review, make_engine, make_session_factory
from prcrew.settings import Settings


async def migrate(old_db_path: str, session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Migrate all rows from legacy SQLite runs table to Postgres reviews.

    Reads synchronously from SQLite, writes asynchronously via session.merge().
    Preserves legacy created_at timestamps when parseable (ISO 8601 with Z suffix).
    Uses session.merge (upsert) for idempotency.

    Args:
        old_db_path: Path to legacy SQLite database file.
        session_factory: AsyncSessionMaker for target Postgres database.

    Returns:
        Number of rows migrated.
    """
    # Read all rows from legacy SQLite DB
    rows = []
    conn = sqlite3.connect(old_db_path)
    try:
        cursor = conn.execute(
            "SELECT id, created_at, pr_url, status, result_json, events_json "
            "FROM runs"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    # Write each row via session.merge, preserving created_at
    async with session_factory() as session:
        for row_id, created_at_str, pr_url, status, result_json_str, events_json_str in rows:
            result = json.loads(result_json_str) if result_json_str else None
            events = json.loads(events_json_str) if events_json_str else []

            # Extract usage from result_json if present
            usage = None
            if result is not None and "usage" in result:
                usage = result["usage"]

            # Parse legacy created_at; if unparseable or empty, leave unset for server_default
            parsed_created_at: datetime | None = None
            if created_at_str:
                try:
                    parsed_created_at = datetime.fromisoformat(created_at_str)
                except ValueError:
                    pass  # Leave unset; server_default will apply

            # Merge the Review object directly to preserve created_at
            review = Review(
                id=row_id,
                source="web",
                pr_url=pr_url,
                status=status,
                result_json=result,
                events_json=events,
                usage_json=usage,
            )
            if parsed_created_at is not None:
                review.created_at = parsed_created_at

            await session.merge(review)

        await session.commit()

    return len(rows)


async def main():
    """Main entry point: read legacy DB path from CLI, migrate to Postgres."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_sqlite_runs.py <legacy.db>")
        print("  DATABASE_URL must be set in environment")
        sys.exit(1)

    old_db_path = sys.argv[1]
    if not Path(old_db_path).exists():
        print(f"Error: {old_db_path} not found", file=sys.stderr)
        sys.exit(1)

    # Build engine and session factory from settings
    settings = Settings()
    engine = make_engine(settings.database_url)

    # Ensure schema exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = make_session_factory(engine)

    try:
        count = await migrate(old_db_path, session_factory)
        print(f"Migrated {count} rows from {old_db_path}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
