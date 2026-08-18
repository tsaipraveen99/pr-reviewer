"""Tests for the incremental store writer (prgraph.indexer.index_repo)."""

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest
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
                ("main", "pkg.models", "pkg.models", "imports"),
                ("main", "pkg.models.User", "pkg.models.User", "imports"),
                ("main", "pkg.models.helper", "pkg.models.helper", "imports"),
                ("main.run", "pkg.models.User", "pkg.models.User", "calls"),
                ("main.run", None, "u.save", "calls"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "calls"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "calls"),
                # @property on User.label: decorator call, attributed to the
                # enclosing class scope; "property" is a builtin, not a repo
                # symbol, so it's unresolved.
                ("pkg.models.User", None, "property", "calls"),
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
                ("src/app", "src/api.fetchUser", "src/api.fetchUser", "imports"),
                ("src/app", "src/api.Client", "src/api.Client", "imports"),
                ("src/app", "src/api.Client", "src/api.Client", "calls"),
                ("src/app.main", "src/api.fetchUser", "src/api.fetchUser", "calls"),
                ("src/app.main", None, "c.get", "calls"),
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
                ("main", "pkg.models", "pkg.models", "imports"),
                ("main", "pkg.models.User", "pkg.models.User", "imports"),
                ("main", "pkg.models.helper", "pkg.models.helper", "imports"),
                ("main.run", "pkg.models.User", "pkg.models.User", "calls"),
                ("main.run", None, "u.save", "calls"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "calls"),
                ("main.run", "pkg.models.helper", "pkg.models.helper", "calls"),
                ("pkg.models.User", None, "property", "calls"),
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
                ("main", "pkg.models", "pkg.models", "imports"),
                ("main", "pkg.models.User", "pkg.models.User", "imports"),
                ("main", None, "pkg.models.helper", "imports"),
                ("main.run", "pkg.models.User", "pkg.models.User", "calls"),
                ("main.run", None, "u.save", "calls"),
                ("main.run", None, "pkg.models.helper", "calls"),
                ("main.run", None, "pkg.models.helper", "calls"),
                ("pkg.models.User", None, "property", "calls"),
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
            assert edges == {("pkg.models.User", None, "property", "calls")}


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


class TestErrorIsolation:
    """F1: a single file's read/parse crash must not abort the whole run --
    it's skipped, counted in IndexStats.errors, and every other file still
    indexes normally.
    """

    def test_unicode_decode_error_is_isolated_and_counted(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "good.py").write_text("def good():\n    return 1\n")
        # subscript-call target isn't a bare identifier/attribute, so the
        # parser falls back to decoding the whole node's raw text; 0xEF is
        # not valid standalone UTF-8, so that decode raises.
        (root / "bad.py").write_bytes(
            b'def run():\n    funcs = {}\n    funcs["na\xefve"]()\n'
        )

        session_factory = _make_session_factory(tmp_path)
        stats = index_repo(session_factory, repo_id=1, root=root)

        assert stats.errors == 1
        assert stats.parsed == 1
        assert stats.skipped == 0

        with session_factory() as session:
            paths = {
                f.path
                for f in session.execute(
                    select(File).where(File.repo_id == 1)
                ).scalars()
            }
            assert paths == {"good.py"}

            symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            assert symbol_names == {"good", "good.good"}

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod-based unreadable files aren't meaningful on Windows",
    )
    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root ignores file permission bits, so chmod 000 wouldn't crash the read",
    )
    def test_permission_error_is_isolated_and_counted(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "good.py").write_text("def good():\n    return 1\n")
        unreadable = root / "unreadable.py"
        unreadable.write_text("def secret():\n    return 1\n")
        unreadable.chmod(0)

        try:
            session_factory = _make_session_factory(tmp_path)
            stats = index_repo(session_factory, repo_id=1, root=root)

            assert stats.errors == 1
            assert stats.parsed == 1

            with session_factory() as session:
                paths = {
                    f.path
                    for f in session.execute(
                        select(File).where(File.repo_id == 1)
                    ).scalars()
                }
                assert paths == {"good.py"}
        finally:
            # Restore permissions so tmp_path cleanup doesn't fail.
            unreadable.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_recursion_error_is_isolated_and_counted(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "good.js").write_text("function good() {\n  return 1;\n}\n")

        # 5000 nested calls -- deep enough to blow the recursive
        # _collect_calls walk's Python stack (default recursion limit 1000)
        # well under the walker's own 1 MiB file-size cap.
        depth = 5000
        nested = (
            "function f(x) { return x; }\n" + "f(" * depth + "1" + ")" * depth + ";\n"
        )
        (root / "vendor.min.js").write_text(nested)

        session_factory = _make_session_factory(tmp_path)
        stats = index_repo(session_factory, repo_id=1, root=root)

        assert stats.errors == 1
        assert stats.parsed == 1

        with session_factory() as session:
            paths = {
                f.path
                for f in session.execute(
                    select(File).where(File.repo_id == 1)
                ).scalars()
            }
            assert paths == {"good.js"}

    def test_file_that_starts_parseable_then_fails_keeps_old_rows_untouched(
        self, tmp_path
    ):
        """A file that indexed fine on run 1 and is edited into unparseable
        content on run 2 keeps its run-1 File/Symbol rows exactly as they
        were -- stale-but-present context beats losing it outright. (This
        falls out of the try/except placement in index_repo: the parse
        happens *before* the old File/Symbol rows are touched, so a raised
        exception never reaches the delete/update code.)
        """
        root = tmp_path / "repo"
        root.mkdir()
        target = root / "flaky.py"
        target.write_text("def flaky():\n    return 1\n")

        session_factory = _make_session_factory(tmp_path)
        first = index_repo(session_factory, repo_id=1, root=root)
        assert first == IndexStats(
            parsed=1, skipped=0, deleted=0, errors=0, symbols=2, edges=0
        )

        with session_factory() as session:
            before_file = session.execute(
                select(File).where(File.repo_id == 1, File.path == "flaky.py")
            ).scalar_one()
            before_hash = before_file.content_hash
            before_symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }

        # Corrupt it: same shape of crash as the UnicodeDecodeError case above.
        target.write_bytes(b'def flaky():\n    funcs = {}\n    funcs["na\xefve"]()\n')

        second = index_repo(session_factory, repo_id=1, root=root)
        assert second.errors == 1
        assert second.parsed == 0
        assert second.skipped == 0

        with session_factory() as session:
            after_file = session.execute(
                select(File).where(File.repo_id == 1, File.path == "flaky.py")
            ).scalar_one()
            # Row untouched: same stale hash as before the failed re-parse.
            assert after_file.content_hash == before_hash

            after_symbol_names = {
                s.qualified_name
                for s in session.execute(
                    select(Symbol).where(Symbol.repo_id == 1)
                ).scalars()
            }
            assert after_symbol_names == before_symbol_names


class TestBareNameHealingGuard:
    """F4: the indexer-level unique-bare-name fallback in `_resolve_call_dst`
    must store the RESOLVED symbol's real qualified_name (not the bare
    callee text), and the healing pass must never try to heal a row whose
    dst_qualified_name is still just a bare name -- otherwise an unrelated,
    later-added same-named symbol can silently "heal" onto it.
    """

    def test_by_name_resolved_edge_stores_the_qualified_name(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        # `a.helper` is the only Symbol anywhere named "helper".
        (root / "a.py").write_text("def helper():\n    return 1\n")
        # b.make's `helper()` call is bare, not a local def of b, not an
        # import alias in b -- the parser leaves it unresolved, so the
        # indexer's unique-bare-name fallback is what resolves it.
        (root / "b.py").write_text(
            "def make():\n    helper = something()\n    helper()\n"
        )

        session_factory = _make_session_factory(tmp_path)
        index_repo(session_factory, repo_id=1, root=root)

        with session_factory() as session:
            edges = _edge_tuples(session, repo_id=1)
            # dst_qualified_name is "a.helper" (the resolved symbol's real
            # qualified name), not the bare callee text "helper".
            assert ("b.make", "a.helper", "a.helper", "calls") in edges
            assert not any(dst_q == "helper" for _, _, dst_q, _ in edges)

    def test_unresolved_bare_name_call_is_not_healed_onto_a_later_added_module(
        self, tmp_path
    ):
        root = tmp_path / "repo"
        root.mkdir()
        # `utils()` is a bare call to a name that resolves to nothing in the
        # repo at index time: not a local def, not an import alias, and no
        # Symbol anywhere is named "utils" yet.
        (root / "b.py").write_text(
            "def make():\n    utils = get_closure()\n    utils()\n"
        )

        session_factory = _make_session_factory(tmp_path)
        index_repo(session_factory, repo_id=1, root=root)

        with session_factory() as session:
            edges = _edge_tuples(session, repo_id=1)
            assert ("b.make", None, "utils", "calls") in edges

        # Now add utils.py -- its module Def's qualified_name is exactly
        # "utils", the reviewer's confirmed false-positive scenario: a
        # bare-name-stored dangling edge must NOT heal onto it.
        (root / "utils.py").write_text("def unrelated():\n    return 1\n")

        index_repo(session_factory, repo_id=1, root=root)

        with session_factory() as session:
            edges = _edge_tuples(session, repo_id=1)
            # Still unresolved -- not fabricated onto the new "utils" module.
            assert ("b.make", None, "utils", "calls") in edges
            assert not any(
                src == "b.make" and dst_q == "utils" and dst is not None
                for src, dst, dst_q, _kind in edges
            )
