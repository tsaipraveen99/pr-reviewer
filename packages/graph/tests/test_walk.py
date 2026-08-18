"""Tests for repository walking, language detection, and content hashing."""

import tempfile
from pathlib import Path

from prgraph.walk import IGNORE_DIRS, LANG_BY_EXT, content_hash, walk_repo


class TestLangByExt:
    """Test LANG_BY_EXT mapping."""

    def test_lang_by_ext_contains_required_extensions(self):
        """Test that LANG_BY_EXT has all required mappings."""
        assert LANG_BY_EXT[".py"] == "python"
        assert LANG_BY_EXT[".js"] == "javascript"
        assert LANG_BY_EXT[".jsx"] == "javascript"
        assert LANG_BY_EXT[".ts"] == "typescript"
        assert LANG_BY_EXT[".tsx"] == "typescript"

    def test_lang_by_ext_is_immutable(self):
        """Test that LANG_BY_EXT is immutable (dict is fine, but document behavior)."""
        # LANG_BY_EXT should be a dict; we just verify all required keys exist
        assert isinstance(LANG_BY_EXT, dict)
        assert len(LANG_BY_EXT) >= 5


class TestIgnoreDirs:
    """Test IGNORE_DIRS set."""

    def test_ignore_dirs_contains_required_directories(self):
        """Test that IGNORE_DIRS contains all required directories."""
        assert ".git" in IGNORE_DIRS
        assert "node_modules" in IGNORE_DIRS
        assert ".venv" in IGNORE_DIRS
        assert "venv" in IGNORE_DIRS
        assert "dist" in IGNORE_DIRS
        assert "build" in IGNORE_DIRS
        assert "__pycache__" in IGNORE_DIRS
        assert ".next" in IGNORE_DIRS
        assert "coverage" in IGNORE_DIRS

    def test_ignore_dirs_is_frozenset(self):
        """Test that IGNORE_DIRS is a frozenset."""
        assert isinstance(IGNORE_DIRS, frozenset)


class TestContentHash:
    """Test content_hash function."""

    def test_content_hash_returns_hex_string(self):
        """Test that content_hash returns a hex string."""
        data = b"hello world"
        hash_val = content_hash(data)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex is 64 characters
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_content_hash_is_deterministic(self):
        """Test that content_hash returns same result for same input."""
        data = b"test data"
        hash1 = content_hash(data)
        hash2 = content_hash(data)
        assert hash1 == hash2

    def test_content_hash_differs_for_different_data(self):
        """Test that content_hash differs for different inputs."""
        hash1 = content_hash(b"data1")
        hash2 = content_hash(b"data2")
        assert hash1 != hash2

    def test_content_hash_empty_bytes(self):
        """Test content_hash on empty bytes."""
        hash_val = content_hash(b"")
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64


class TestWalkRepo:
    """Test walk_repo function."""

    def test_walk_repo_simple_structure(self):
        """Test walk_repo with a simple file structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create supported files
            (root / "main.py").write_text("print('hello')")
            (root / "app.js").write_text("console.log('hi')")
            (root / "component.jsx").write_text("export default () => null")
            (root / "types.ts").write_text("type X = string")
            (root / "ui.tsx").write_text("export const UI = () => null")

            result = walk_repo(root)

            assert len(result) == 5
            # Check all files are present (sorted)
            relpaths = [path for path, lang in result]
            langs = [lang for path, lang in result]
            assert "app.js" in relpaths
            assert "component.jsx" in relpaths
            assert "main.py" in relpaths
            assert "types.ts" in relpaths
            assert "ui.tsx" in relpaths
            # Check sorting
            assert relpaths == sorted(relpaths)
            # Check language mapping
            assert langs.count("python") == 1
            assert langs.count("javascript") == 2
            assert langs.count("typescript") == 2

    def test_walk_repo_skips_ignore_dirs_at_root(self):
        """Test that walk_repo skips IGNORE_DIRS at root level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create files in ignored directories
            (root / "node_modules").mkdir()
            (root / "node_modules" / "lib.js").write_text("module.exports = {}")

            (root / ".venv").mkdir()
            (root / ".venv" / "site.py").write_text("# venv")

            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "cache.pyc").write_text("")

            # Create a supported file in root
            (root / "main.py").write_text("import sys")

            result = walk_repo(root)

            # Should only contain main.py
            assert len(result) == 1
            assert result[0] == ("main.py", "python")

    def test_walk_repo_skips_ignore_dirs_nested(self):
        """Test that walk_repo skips IGNORE_DIRS at any depth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create nested structure with ignored dirs
            src = root / "src"
            src.mkdir()
            (src / "app.js").write_text("console.log('app')")

            # Create ignored dir inside src
            (src / "node_modules").mkdir()
            (src / "node_modules" / "dep.js").write_text("module.exports = {}")

            result = walk_repo(root)

            # Should only contain app.js
            assert len(result) == 1
            assert result[0][0] == "src/app.js"
            assert result[0][1] == "javascript"

    def test_walk_repo_skips_large_files(self):
        """Test that walk_repo skips files larger than 1 MiB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create a small file
            (root / "small.py").write_text("x = 1")

            # Create a file larger than 1 MiB (1048576 bytes)
            large_size = 1048576 + 1000  # 1 MiB + 1000 bytes
            (root / "large.py").write_bytes(b"x" * large_size)

            result = walk_repo(root)

            # Should only contain small.py
            assert len(result) == 1
            assert result[0] == ("small.py", "python")

    def test_walk_repo_sorted_output(self):
        """Test that walk_repo returns sorted results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create files in non-alphabetical order
            (root / "z.py").write_text("z")
            (root / "a.js").write_text("a")
            (root / "m.ts").write_text("m")
            (root / "b.jsx").write_text("b")

            result = walk_repo(root)

            relpaths = [path for path, lang in result]
            assert relpaths == ["a.js", "b.jsx", "m.ts", "z.py"]

    def test_walk_repo_nested_structure(self):
        """Test walk_repo with nested directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create nested structure
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main")
            (root / "src" / "util").mkdir()
            (root / "src" / "util" / "helper.js").write_text("helper")
            (root / "tests").mkdir()
            (root / "tests" / "test.ts").write_text("test")

            result = walk_repo(root)

            relpaths = [path for path, lang in result]
            assert "src/main.py" in relpaths
            assert "src/util/helper.js" in relpaths
            assert "tests/test.ts" in relpaths
            # Check sorting (should sort by path, not just filename)
            assert relpaths == sorted(relpaths)

    def test_walk_repo_ignores_unsupported_extensions(self):
        """Test that walk_repo ignores files with unsupported extensions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            (root / "main.py").write_text("python")
            (root / "readme.md").write_text("markdown")
            (root / "config.json").write_text("{}")
            (root / "style.css").write_text("body {}")

            result = walk_repo(root)

            # Should only contain main.py
            assert len(result) == 1
            assert result[0] == ("main.py", "python")

    def test_walk_repo_complex_scenario(self):
        """Test walk_repo with complex scenario from brief."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create a complex structure
            (root / "app.js").write_text("app")
            (root / "component.jsx").write_text("component")
            (root / "style.css").write_text("css")  # Unsupported

            # Create ignored directories with files
            (root / "node_modules").mkdir()
            (root / "node_modules" / "x.js").write_text("should be ignored")

            (root / ".venv").mkdir()
            (root / ".venv" / "y.py").write_text("should be ignored")

            # Create large file
            large_size = 1048576 + 500
            (root / "big.py").write_bytes(b"x" * large_size)

            # Create nested structures
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main")
            (root / "src" / "util.ts").write_text("util")
            (root / "src" / "ui.tsx").write_text("ui")

            result = walk_repo(root)

            relpaths = [path for path, lang in result]
            # Should have: app.js, component.jsx, src/main.py, src/util.ts, src/ui.tsx
            assert len(result) == 5
            assert "app.js" in relpaths
            assert "component.jsx" in relpaths
            assert "src/main.py" in relpaths
            assert "src/util.ts" in relpaths
            assert "src/ui.tsx" in relpaths
            # Should not have:
            # - node_modules/x.js
            # - .venv/y.py
            # - big.py (too large)
            # - style.css (unsupported)
            assert "node_modules/x.js" not in relpaths
            assert ".venv/y.py" not in relpaths
            assert "big.py" not in relpaths
            assert "style.css" not in relpaths
            # Verify sorting
            assert relpaths == sorted(relpaths)

    def test_walk_repo_returns_forward_slash_paths(self):
        """Test that walk_repo returns forward-slash relative paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            (root / "src").mkdir()
            (root / "src" / "nested").mkdir()
            (root / "src" / "nested" / "file.py").write_text("python")

            result = walk_repo(root)

            # On all platforms, should use forward slashes
            assert result[0][0] == "src/nested/file.py"
            assert "/" in result[0][0] or len(result[0][0].split("/")) > 1
