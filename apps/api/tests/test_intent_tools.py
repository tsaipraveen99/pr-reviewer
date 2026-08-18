
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from prcrew.graph.intent_tools import ToolBelt, render_slice


@pytest.fixture()
def belt(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "app.py").write_text("def caller():\n    return helper()\n\n\ndef helper():\n    return 1\n")
    (root / "notes.md").write_text("hello grep target\n")
    engine = create_engine(f"sqlite:///{tmp_path}/g.db")
    from prgraph.db import Base as GraphBase
    GraphBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    from prgraph.indexer import index_repo
    index_repo(factory, 99, root)
    return ToolBelt(root=root, session_factory=factory, repo_id=99)


def test_graph_neighbors(belt):
    out = belt.graph_neighbors({"qualified_name": "app.helper"})
    assert "app.caller" in out and "caller" in out.lower()


def test_graph_neighbors_unknown_symbol(belt):
    assert "no symbol" in belt.graph_neighbors({"qualified_name": "nope.nothing"}).lower()


def test_read_file_windows_and_caps(belt):
    out = belt.read_file({"path": "app.py", "start": 1, "end": 2})
    assert "def caller" in out and "helper()" in out and "return 1" not in out


def test_read_file_escapes_sandbox(belt):
    assert "outside" in belt.read_file({"path": "../secrets.txt"}).lower()


def test_grep(belt):
    out = belt.grep({"pattern": "grep target", "glob": "*.md"})
    assert "notes.md" in out


def test_grep_bad_regex_is_reported_not_raised(belt):
    assert "invalid" in belt.grep({"pattern": "(unclosed"}).lower()


def test_render_slice(belt):
    from prcrew.diffs import ChangedFile
    from prcrew.worker.indexing import build_slice
    sl = build_slice(belt._session_factory, 99, belt._root, [ChangedFile("app.py", [(4, 5)])])
    text = render_slice(sl)
    assert "[changed] app.helper" in text and "[caller] app.caller" in text


def test_grep_ignores_symlinks_escaping_the_sandbox(belt, tmp_path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SUPER_SECRET_TOKEN=abc123\n")
    (belt._root / "innocuous.txt").symlink_to(outside)
    out = belt.grep({"pattern": "SUPER_SECRET", "glob": "*"})
    assert "abc123" not in out
    assert out == "(no matches)"
