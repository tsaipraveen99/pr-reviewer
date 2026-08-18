"""Tests for the incremental store writer (prgraph.indexer.index_repo)."""

import shutil
from pathlib import Path

from sqlalchemy import select

from prgraph.db import (
    Edge,
    File,
    Symbol,
    create_schema,
    make_engine,
    make_session_factory,
)
from prgraph.indexer import IndexStats, index_repo

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    """Copy the named fixture repo (tests/fixtures/<name>) into tmp_path/<name>."""
    dest = tmp_path / name
    shutil.copytree(FIXTURES / name, dest)
    return dest


def _make_session_factory(tmp_path: Path, name: str = "graph.db"):
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    create_schema(engine)
    return make_session_factory(engine)


def _edge_tuples(session, repo_id: int) -> set[tuple[str, str | None, str, str]]:
    """(src_qualified, dst_qualified_or_None, dst_qualified_name, kind) for every edge."""
    src = select(Symbol.id, Symbol.qualified_name).where(Symbol.repo_id == repo_id)
    names_by_id = dict(session.execute(src).all())

    rows = session.execute(select(Edge).where(Edge.repo_id == repo_id)).scalars()
    result = set()
    for edge in rows:
        dst_resolved = (
            names_by_id.get(edge.dst_symbol_id) if edge.dst_symbol_id else None
        )
        result.add(
            (
                names_by_id[edge.src_symbol_id],
                dst_resolved,
                edge.dst_qualified_name,
                edge.kind,
            )
        )
    return result


class TestFullIndexPyrepo:
    """Scenario (a): full index of pyrepo -> exact symbol count and specific edges."""

    def test_full_index_pyrepo_exact_state(self, tmp_path):
        root = _copy_fixture("pyrepo", tmp_path)
        both_fixtures_present = (FIXTURES / "tsrepo").is_dir()
        assert both_fixtures_present  # both fixture repos exist under tests/fixtures

        session_factory = _make_session_factory(tmp_path)
        stats = index_repo(session_factory, repo_id=1, root=root)

        assert stats == IndexStats(parsed=3, skipped=0, deleted=0, symbols=9, edges=8)

        with session_factory() as session:
            assert (
                session.execute(select(File).where(File.repo_id == 1)).scalars().all()
            )
            paths = {
                f.path
                for f in session.execute(
                    select(File).where(File.repo_id == 1)
                ).scalars()
            }
            assert paths == {"main.py", "pkg/__init__.py", "pkg/models.py"}

            symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            assert symbol_names == {
                "main",
                "main.run",
                "pkg",
                "pkg.models",
                "pkg.models.User",
                "pkg.models.User.save",
                "pkg.models.User.label",
                "pkg.models.helper",
                "pkg.models.helper.inner",
            }

            edges = _edge_tuples(session, repo_id=1)
            assert edges == {
                ("main", "pkg.models", "pkg.models", "import"),
                ("main", "pkg.models.User", "pkg.models.User", "import"),
                ("main", "pkg.models.helper", "pkg.models.helper", "import"),
                ("main.run", "pkg.models.User", "pkg.models.User", "call"),
                ("main.run", None, "u.save", "call"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "call"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "call"),
                # @property on User.label: decorator call, attributed to the
                # enclosing class scope; "property" is a builtin, not a repo
                # symbol, so it's unresolved.
                ("pkg.models.User", None, "property", "call"),
            }


class TestFullIndexTsrepo:
    """Dispatch requirement: javascript/typescript files route through parse_jsts."""

    def test_full_index_tsrepo_exact_state(self, tmp_path):
        root = _copy_fixture("tsrepo", tmp_path)
        session_factory = _make_session_factory(tmp_path)

        stats = index_repo(session_factory, repo_id=2, root=root)

        assert stats == IndexStats(parsed=2, skipped=0, deleted=0, symbols=7, edges=5)

        with session_factory() as session:
            edges = _edge_tuples(session, repo_id=2)
            assert edges == {
                ("src/app", "src/api.fetchUser", "src/api.fetchUser", "import"),
                ("src/app", "src/api.Client", "src/api.Client", "import"),
                ("src/app", "src/api.Client", "src/api.Client", "call"),
                ("src/app.main", "src/api.fetchUser", "src/api.fetchUser", "call"),
                ("src/app.main", None, "c.get", "call"),
            }


class TestNoOpReindex:
    """Scenario (b): touch nothing, re-index -> parsed=0, skipped=all, symbols unchanged."""

    def test_reindex_with_no_changes_is_a_no_op(self, tmp_path):
        root = _copy_fixture("pyrepo", tmp_path)
        session_factory = _make_session_factory(tmp_path)

        first = index_repo(session_factory, repo_id=1, root=root)
        second = index_repo(session_factory, repo_id=1, root=root)

        assert second == IndexStats(
            parsed=0, skipped=3, deleted=0, symbols=first.symbols, edges=first.edges
        )

        with session_factory() as session:
            edges = _edge_tuples(session, repo_id=1)
            assert edges == {
                ("main", "pkg.models", "pkg.models", "import"),
                ("main", "pkg.models.User", "pkg.models.User", "import"),
                ("main", "pkg.models.helper", "pkg.models.helper", "import"),
                ("main.run", "pkg.models.User", "pkg.models.User", "call"),
                ("main.run", None, "u.save", "call"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "call"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "call"),
                ("pkg.models.User", None, "property", "call"),
            }


class TestRenameHealing:
    """Scenario (c): rename helper->helper2 in models.py; cross-file edges heal (or stay
    unresolved) and stale symbols disappear.
    """

    def test_rename_symbol_invalidates_and_reresolves_cross_file_edges(self, tmp_path):
        root = _copy_fixture("pyrepo", tmp_path)
        session_factory = _make_session_factory(tmp_path)
        index_repo(session_factory, repo_id=1, root=root)

        models_path = root / "pkg" / "models.py"
        models_path.write_text(models_path.read_text().replace("helper", "helper2"))

        stats = index_repo(session_factory, repo_id=1, root=root)

        assert stats == IndexStats(parsed=1, skipped=2, deleted=0, symbols=9, edges=8)

        with session_factory() as session:
            symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            # Stale "pkg.models.helper" symbols are gone; the renamed ones exist.
            assert "pkg.models.helper" not in symbol_names
            assert "pkg.models.helper.inner" not in symbol_names
            assert "pkg.models.helper2" in symbol_names
            assert "pkg.models.helper2.inner" in symbol_names

            edges = _edge_tuples(session, repo_id=1)
            # main.py wasn't touched (unchanged hash), so its edges' dst_qualified_name
            # values are exactly what were parsed the first time -- "pkg.models.helper" --
            # and since no symbol has that qualified_name anymore, they're unresolved.
            assert edges == {
                ("main", "pkg.models", "pkg.models", "import"),
                ("main", "pkg.models.User", "pkg.models.User", "import"),
                ("main", None, "pkg.models.helper", "import"),
                ("main.run", "pkg.models.User", "pkg.models.User", "call"),
                ("main.run", None, "u.save", "call"),
                ("main.run", None, "pkg.models.helper", "call"),
                ("main.run", None, "pkg.models.helper", "call"),
                ("pkg.models.User", None, "property", "call"),
            }


class TestFileDeletion:
    """Scenario (d): delete main.py from disk -> its symbols/edges removed, deleted=1."""

    def test_deleting_a_file_removes_its_symbols_and_edges(self, tmp_path):
        root = _copy_fixture("pyrepo", tmp_path)
        session_factory = _make_session_factory(tmp_path)
        index_repo(session_factory, repo_id=1, root=root)

        (root / "main.py").unlink()

        stats = index_repo(session_factory, repo_id=1, root=root)

        assert stats == IndexStats(parsed=0, skipped=2, deleted=1, symbols=7, edges=1)

        with session_factory() as session:
            paths = {
                f.path
                for f in session.execute(
                    select(File).where(File.repo_id == 1)
                ).scalars()
            }
            assert paths == {"pkg/__init__.py", "pkg/models.py"}

            symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            assert "main" not in symbol_names
            assert "main.run" not in symbol_names

            # main.py's edges (3 imports + 4 calls) are gone; only the
            # unrelated property-decorator edge in pkg/models.py remains.
            edges = _edge_tuples(session, repo_id=1)
            assert edges == {("pkg.models.User", None, "property", "call")}


class TestRepoIsolation:
    """Two repos sharing one DB don't cross-contaminate each other's symbols/edges."""

    def test_two_repos_in_one_db_stay_isolated(self, tmp_path):
        py_root = _copy_fixture("pyrepo", tmp_path)
        ts_root = _copy_fixture("tsrepo", tmp_path)
        session_factory = _make_session_factory(tmp_path)

        py_stats = index_repo(session_factory, repo_id=1, root=py_root)
        ts_stats = index_repo(session_factory, repo_id=2, root=ts_root)

        assert py_stats.symbols == 9
        assert ts_stats.symbols == 7

        with session_factory() as session:
            repo1_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            repo2_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 2)
                ).scalars()
            }
            assert repo1_names.isdisjoint(repo2_names)
