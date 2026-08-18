import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    pr_url TEXT,
    status TEXT,
    result_json TEXT,
    events_json TEXT
)
"""


class RunStore:
    """Sqlite-backed persistence for finished (and in-flight) runs.

    Opens and closes one connection per operation -- simple and safe for
    this app's write volume, and avoids sharing a sqlite connection across
    the asyncio.to_thread workers that call in from RunManager.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(_SCHEMA)
        finally:
            conn.close()

    def save(self, run_id: str, created_at_iso: str, pr_url: str, status: str,
              result: dict | None, events: list) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runs "
                    "(id, created_at, pr_url, status, result_json, events_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (run_id, created_at_iso, pr_url, status,
                     json.dumps(result), json.dumps(events)),
                )
        finally:
            conn.close()

    def load(self, run_id: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT pr_url, status, result_json, events_json FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        pr_url, status, result_json, events_json = row
        return {
            "status": status,
            "pr_url": pr_url,
            "result": json.loads(result_json) if result_json is not None else None,
            "events": json.loads(events_json) if events_json is not None else [],
        }
