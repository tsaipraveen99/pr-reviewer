"""prgraph indexing + context slices for the worker pipeline."""

from pathlib import Path

from prgraph.indexer import index_repo
from prgraph.slice import Slice, context_slice

from prcrew.db import Repo
from prcrew.diffs import ChangedFile


def ensure_index(session_factory, repo_id: int, root: Path, head_sha: str) -> None:
    """Incrementally index the checkout and record the outcome on the repos row."""
    try:
        index_repo(session_factory, repo_id, root)
    except Exception:
        with session_factory() as session:
            row = session.get(Repo, repo_id)
            if row is not None:
                row.index_status = "failed"
                session.commit()
        raise
    with session_factory() as session:
        row = session.get(Repo, repo_id)
        if row is not None:
            row.index_status = "ready"
            row.indexed_commit = head_sha
            session.commit()


def build_slice(session_factory, repo_id: int, root: Path,
                files: list[ChangedFile]) -> Slice:
    changed = [(f.path, f.ranges) for f in files]
    return context_slice(session_factory, repo_id, root, changed)
