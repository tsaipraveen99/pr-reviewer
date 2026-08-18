
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from prcrew.db import Base, Installation, Repo
from prcrew.diffs import ChangedFile
from prcrew.worker.indexing import build_slice, ensure_index


def make_env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/ix.db")
    Base.metadata.create_all(engine)
    from prgraph.db import Base as GraphBase
    GraphBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        s.add(Installation(id=1, account_login="x"))
        s.add(Repo(id=99, installation_id=1, full_name="x/y",
                   default_branch="main", index_status="pending"))
        s.commit()
    root = tmp_path / "work"
    root.mkdir()
    (root / "app.py").write_text("def caller():\n    return helper()\n\n\ndef helper():\n    return 1\n")
    return factory, root


def test_ensure_index_indexes_and_marks_ready(tmp_path):
    factory, root = make_env(tmp_path)
    ensure_index(factory, 99, root, "e" * 40)
    from prgraph.db import Symbol
    with factory() as s:
        names = {r.qualified_name for r in s.execute(select(Symbol)).scalars()}
        repo = s.get(Repo, 99)
    assert "app.caller" in names and "app.helper" in names
    assert repo.index_status == "ready" and repo.indexed_commit == "e" * 40


def test_build_slice_includes_callers(tmp_path):
    factory, root = make_env(tmp_path)
    ensure_index(factory, 99, root, "e" * 40)
    sl = build_slice(factory, 99, root, [ChangedFile(path="app.py", ranges=[(4, 5)])])
    roles = {(e.role, e.qualified_name) for e in sl.entries}
    assert ("changed", "app.helper") in roles
    assert ("caller", "app.caller") in roles


def test_ensure_index_failure_marks_failed(tmp_path, monkeypatch):
    factory, root = make_env(tmp_path)
    import prcrew.worker.indexing as ix
    monkeypatch.setattr(ix, "index_repo", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    import pytest
    with pytest.raises(RuntimeError):
        ensure_index(factory, 99, root, "f" * 40)
    with factory() as s:
        assert s.get(Repo, 99).index_status == "failed"
