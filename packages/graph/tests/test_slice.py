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
                    kind="calls",
                )
            )
            # changed -> other (makes `other` also a callee of the changed symbol)
            session.add(
                Edge(
                    repo_id=1,
                    src_symbol_id=changed_sym.id,
                    dst_symbol_id=other_sym.id,
                    dst_qualified_name="x.other",
                    kind="calls",
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


class TestDeterministicOrdering:
    """M7: two entries tied on (role priority, path, start_line) must still
    sort in a fixed order -- qualified_name breaks the tie -- so results
    don't depend on incidental row-return order (which Postgres doesn't
    guarantee the way sqlite's rowid-ish default often does).
    """

    def test_same_role_path_and_start_line_breaks_tie_on_qualified_name(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "x.py").write_text("pass\n")

        session_factory = _make_bare_session_factory(tmp_path)
        now = datetime.now(UTC)
        with session_factory() as session:
            file_row = File(
                repo_id=1, path="x.py", lang="python", content_hash="h", parsed_at=now
            )
            session.add(file_row)
            session.flush()

            # Inserted "zebra" first (lower id) and "apple" second (higher
            # id), both same start_line -- so a sort keyed only on (role,
            # path, start_line) would preserve this insertion order (zebra
            # before apple) via Python's stable sort. The qualified_name
            # tiebreak must force alphabetical order instead.
            zebra = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="zebra",
                qualified_name="x.zebra",
                kind="function",
                start_line=1,
                end_line=1,
            )
            apple = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="apple",
                qualified_name="x.apple",
                kind="function",
                start_line=1,
                end_line=1,
            )
            session.add_all([zebra, apple])
            session.commit()

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("x.py", [(1, 1)])],
        )

        assert [e.qualified_name for e in result.entries] == ["x.apple", "x.zebra"]


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

    def test_non_utf8_file_snippet_is_read_with_replacement_not_a_crash(self, tmp_path):
        """A file on disk that isn't valid UTF-8 (e.g. latin-1 source the
        indexer indexed at the bytes level) must not crash slice-time reads;
        undecodable bytes are replaced rather than raising UnicodeDecodeError.
        """
        root = tmp_path / "repo"
        root.mkdir()
        # latin-1 "naïve" -- 0xEF is not valid standalone UTF-8.
        (root / "naive.py").write_bytes(
            b'def naive():\n    x = "na\xefve"\n    return x\n'
        )

        session_factory = _make_bare_session_factory(tmp_path)
        now = datetime.now(UTC)
        with session_factory() as session:
            file_row = File(
                repo_id=1,
                path="naive.py",
                lang="python",
                content_hash="h",
                parsed_at=now,
            )
            session.add(file_row)
            session.flush()
            sym = Symbol(
                repo_id=1,
                file_id=file_row.id,
                name="naive",
                qualified_name="naive.naive",
                kind="function",
                start_line=1,
                end_line=3,
            )
            session.add(sym)
            session.commit()

        result = context_slice(
            session_factory,
            repo_id=1,
            root=root,
            changed=[("naive.py", [])],
        )

        assert len(result.entries) == 1
        assert "def naive():" in result.entries[0].snippet
        assert "�" in result.entries[0].snippet
