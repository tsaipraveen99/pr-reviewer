"""Tests for the prgraph CLI (prgraph.cli.main), invoked in-process via main([...])."""

import json
import shutil
from pathlib import Path

import pytest

from prgraph.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_pyrepo(tmp_path: Path) -> Path:
    root = tmp_path / "pyrepo"
    shutil.copytree(FIXTURES / "pyrepo", root)
    return root


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'graph.db'}"


class TestIndexCommand:
    def test_index_prints_one_line_stats(self, tmp_path, capsys):
        root = _copy_pyrepo(tmp_path)

        exit_code = main(["index", str(root), "--db", _db_url(tmp_path)])

        assert exit_code == 0
        out = capsys.readouterr().out.strip()
        assert out == "parsed=3 skipped=0 deleted=0 symbols=9 edges=8"

    def test_index_unknown_path_exits_2(self, tmp_path, capsys):
        missing = tmp_path / "does-not-exist"

        with pytest.raises(SystemExit) as exc_info:
            main(["index", str(missing), "--db", _db_url(tmp_path)])

        assert exc_info.value.code == 2


class TestSliceCommand:
    def _index_first(self, tmp_path: Path) -> Path:
        root = _copy_pyrepo(tmp_path)
        main(["index", str(root), "--db", _db_url(tmp_path)])
        return root

    def test_slice_text_mode_matches_task9_expected_entries(self, tmp_path, capsys):
        root = self._index_first(tmp_path)
        capsys.readouterr()  # discard index output

        exit_code = main(
            [
                "slice",
                str(root),
                "--file",
                "pkg/models.py:10-10",
                "--db",
                _db_url(tmp_path),
            ]
        )

        assert exit_code == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines == [
            "changed pkg.models.helper pkg/models.py:10-13",
            "caller main.run main.py:5-9",
            "importer main main.py:1-9",
        ]

    def test_slice_json_mode_parses(self, tmp_path, capsys):
        root = self._index_first(tmp_path)
        capsys.readouterr()

        exit_code = main(
            [
                "slice",
                str(root),
                "--file",
                "pkg/models.py:10-10",
                "--db",
                _db_url(tmp_path),
                "--json",
            ]
        )

        assert exit_code == 0
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)

        assert [e["role"] for e in parsed] == ["changed", "caller", "importer"]
        assert parsed[0]["qualified_name"] == "pkg.models.helper"
        assert parsed[0]["path"] == "pkg/models.py"
        assert parsed[0]["start_line"] == 10
        assert parsed[0]["end_line"] == 13
        assert "def helper():" in parsed[0]["snippet"]

    def test_slice_unknown_path_exits_2(self, tmp_path):
        missing = tmp_path / "does-not-exist"

        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "slice",
                    str(missing),
                    "--file",
                    "pkg/models.py:10-10",
                    "--db",
                    _db_url(tmp_path),
                ]
            )

        assert exc_info.value.code == 2

    def test_slice_whole_file_no_range(self, tmp_path, capsys):
        root = self._index_first(tmp_path)
        capsys.readouterr()

        exit_code = main(
            [
                "slice",
                str(root),
                "--file",
                "pkg/models.py",
                "--db",
                _db_url(tmp_path),
            ]
        )

        assert exit_code == 0
        out = capsys.readouterr().out
        changed_names = {
            line.split(" ", 2)[1]
            for line in out.strip().splitlines()
            if line.startswith("changed ")
        }
        assert changed_names == {
            "pkg.models.User",
            "pkg.models.User.save",
            "pkg.models.User.label",
            "pkg.models.helper",
            "pkg.models.helper.inner",
        }
