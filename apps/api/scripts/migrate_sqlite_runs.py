"""Wrapper script to run the migration.

This script reads from a legacy SQLite database and writes to Postgres
via the ReviewStore. See prcrew.api.migrate_sqlite_runs for details.

Usage: uv run python scripts/migrate_sqlite_runs.py <legacy.db>
  DATABASE_URL must be set in environment.
"""

import asyncio

from prcrew.api.migrate_sqlite_runs import main

if __name__ == "__main__":
    asyncio.run(main())
