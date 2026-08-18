from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prcrew.db import Review


class ReviewStore:
    """Postgres/sqlite-backed persistence for reviews, via SQLAlchemy async.

    `save` upserts by primary key using `session.merge`: a transient Review
    with only the changed fields set (created_at left unset) merges onto the
    existing row without nulling out columns it didn't touch.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def save(self, run_id: str, pr_url: str, status: str,
                   result: dict | None, events: list,
                   usage: dict | None, source: str = "web") -> None:
        async with self._sessions() as s:
            await s.merge(Review(id=run_id, source=source, pr_url=pr_url,
                                 status=status, result_json=result,
                                 events_json=events, usage_json=usage))
            await s.commit()

    async def load(self, run_id: str) -> dict | None:
        async with self._sessions() as s:
            row = (await s.execute(
                select(Review).where(Review.id == run_id))).scalar_one_or_none()
            if row is None:
                return None
            return {"status": row.status, "pr_url": row.pr_url,
                    "result": row.result_json, "events": row.events_json or []}
