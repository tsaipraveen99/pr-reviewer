"""Tests for prgraph.slice.context_slice."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from prgraph.db import (
    Edge,
    File,
    Symbol,
    create_schema,
    make_engine,
    make_session_factory,
)
from prgraph.indexer import index_repo
from prgraph.slice import Slice, SliceEntry, context_slice

FIXTURES = Path(__file__).parent / "fixtures"


def _index_pyrepo(tmp_path: Path):
    """Copy the pyrepo fixture into tmp_path, index it, and return (root, session_factory)."""
    root = tmp_path / "pyrepo"
    shutil.copytree(FIXTURES / "pyrepo", root)
    engine = make_engine(f"sqlite:///{tmp_path / 'graph.db'}")
    create_schema(engine)
    session_factory = make_session_factory(engine)
    index_repo(session_factory, repo_id=1, root=root)
    return root, session_factory


class TestContextSlicePyrepo:
    """Scenario from the task brief: changing pkg/models.py's `helper` line."""

    def test_changed_helper_line_produces_expected_roles(self, tmp_path):
        root, session_factory = _index_pyrepo(tmp_path)

        # Line 10 is exactly `def helper():` -- it overlaps the helper Symbol
        # (lines 10-13) but not the nested inner Symbol (lines 11-12), so only
        # helper itself lands in the "changed" role.
        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("pkg/models.py", [(10, 10)])],
        )

        assert isinstance(result, Slice)
        assert [(e.role, e.qualified_name) for e in result.entries] == [
            ("changed", "pkg.models.helper"),
            ("caller", "main.run"),
            ("importer", "main"),
        ]

        changed_entry = result.entries[0]
        assert changed_entry == SliceEntry(
            role="changed",
            qualified_name="pkg.models.helper",
            path="pkg/models.py",
            start_line=10,
            end_line=13,
            snippet=(
                "def helper():\n    def inner():\n        return 1\n    return inner"
            ),
        )

        caller_entry = result.entries[1]
        assert caller_entry.path == "main.py"
        assert caller_entry.start_line == 5
        assert caller_entry.end_line == 9
        assert "def run():" in caller_entry.snippet

        importer_entry = result.entries[2]
        assert importer_entry.role == "importer"
        assert importer_entry.qualified_name == "main"
        assert importer_entry.path == "main.py"
        assert importer_entry.start_line == 1
        assert importer_entry.end_line == 9

    def test_max_symbols_cap_keeps_only_the_changed_entry(self, tmp_path):
        root, session_factory = _index_pyrepo(tmp_path)

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("pkg/models.py", [(10, 10)])],
            max_symbols=1,
        )

        assert len(result.entries) == 1
        assert result.entries[0].role == "changed"
        assert result.entries[0].qualified_name == "pkg.models.helper"

    def test_empty_ranges_means_whole_file(self, tmp_path):
        root, session_factory = _index_pyrepo(tmp_path)

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("pkg/models.py", [])],
        )

        changed_names = {
            e.qualified_name for e in result.entries if e.role == "changed"
        }
        assert changed_names == {
            "pkg.models.User",
            "pkg.models.User.save",
            "pkg.models.User.label",
            "pkg.models.helper",
            "pkg.models.helper.inner",
        }
        # Module symbol itself is never in the "changed" role.
        assert "pkg.models" not in changed_names

    def test_missing_changed_file_in_db_is_skipped(self, tmp_path):
        root, session_factory = _index_pyrepo(tmp_path)

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("nonexistent.py", [])],
        )

        assert result.entries == []


def _make_bare_session_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    create_schema(engine)
    return make_session_factory(engine)


class TestDedupPriority:
    """A symbol that is simultaneously a caller and a callee keeps only the
    higher-priority "caller" role, and appears exactly once.
    """

    def test_caller_takes_priority_over_callee_for_same_symbol(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "x.py").write_text(
            "def changed():\n    pass\n\ndef other():\n    pass\n"
        )

        session_factory = _make_bare_session_factory(tmp_path)
        now = datetime.now(UTC)
        with session_factory() as session:
            file_row = File(
                repo_id=1, path="x.py", lang="python", content_hash="h", parsed_at=now
            )
            session.add(file_row)
            session.flush()

            changed_sym = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="changed",
                qualified_name="x.changed",
                kind="function",
                start_line=1,
                end_line=2,
            )
            other_sym = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="other",
                qualified_name="x.other",
                kind="function",
                start_line=4,
                end_line=5,
            )
            session.add_all([changed_sym, other_sym])
            session.flush()

            # other -> changed (makes `other` a caller of the changed symbol)
            session.add(
                Edge(
                    repo_id=1,
                    src_symbol_id=other_sym.id,
                    dst_symbol_id=changed_sym.id,
                    dst_qualified_name="x.changed",
                    kind="call",
                )
            )
            # changed -> other (makes `other` also a callee of the changed symbol)
            session.add(
                Edge(
                    repo_id=1,
                    src_symbol_id=changed_sym.id,
                    dst_symbol_id=other_sym.id,
                    dst_qualified_name="x.other",
                    kind="call",
                )
            )
            session.commit()

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("x.py", [(1, 2)])],
        )

        other_entries = [e for e in result.entries if e.qualified_name == "x.other"]
        assert len(other_entries) == 1
        assert other_entries[0].role == "caller"


class TestCapsAndSnippetHandling:
    def test_snippet_capped_at_sixty_lines(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        body = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(100)) + "\n"
        (root / "big.py").write_text(body)

        session_factory = _make_bare_session_factory(tmp_path)
        now = datetime.now(UTC)
        with session_factory() as session:
            file_row = File(
                repo_id=1, path="big.py", lang="python", content_hash="h", parsed_at=now
            )
            session.add(file_row)
            session.flush()
            sym = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="big",
                qualified_name="big.big",
                kind="function",
                start_line=1,
                end_line=101,
            )
            session.add(sym)
            session.commit()

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("big.py", [])],
        )

        assert len(result.entries) == 1
        assert result.entries[0].snippet.count("\n") == 59  # 60 lines

    def test_missing_file_on_disk_skips_entry(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        # Note: no "ghost.py" written to disk.

        session_factory = _make_bare_session_factory(tmp_path)
        now = datetime.now(UTC)
        with session_factory() as session:
            file_row = File(
                repo_id=1,
                path="ghost.py",
                lang="python",
                content_hash="h",
                parsed_at=now,
            )
            session.add(file_row)
            session.flush()
            sym = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="ghost",
                qualified_name="ghost.ghost",
                kind="function",
                start_line=1,
                end_line=2,
            )
            session.add(sym)
            session.commit()

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("ghost.py", [])],
        )

        assert result.entries == []

    def test_max_chars_drops_lowest_priority_entries_first(self, tmp_path):
        root, session_factory = _index_pyrepo(tmp_path)

        full = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("pkg/models.py", [(10, 10)])],
        )
        assert [e.role for e in full.entries] == ["changed", "caller", "importer"]
        full_chars = sum(len(e.snippet) for e in full.entries)
        changed_chars = len(full.entries[0].snippet)
        caller_chars = len(full.entries[1].snippet)

        # Budget for "changed" + "caller" but not "importer".
        budget = changed_chars + caller_chars
        assert budget < full_chars

        trimmed = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("pkg/models.py", [(10, 10)])],
            max_chars=budget,
        )

        assert [e.role for e in trimmed.entries] == ["changed", "caller"]
