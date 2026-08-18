"""Repository walker with language detection and content hashing."""

import hashlib
import os
from pathlib import Path

# Mapping of file extensions to programming languages
LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Set of directory names to ignore at any depth
IGNORE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "__pycache__",
        ".next",
        "coverage",
    }
)

# Maximum file size in bytes (1 MiB)
MAX_FILE_SIZE = 1048576


def content_hash(data: bytes) -> str:
    """Compute SHA256 hash of data and return as hex string.

    Args:
        data: Bytes to hash.

    Returns:
        64-character hex string representing the SHA256 hash.
    """
    return hashlib.sha256(data).hexdigest()


def walk_repo(root: Path) -> list[tuple[str, str]]:
    """Walk a repository and return list of supported source files with their languages.

    Walks the directory tree starting from root, yielding (relative_path, language)
    tuples for all supported source files. Skips directories in IGNORE_DIRS at any
    depth and files larger than MAX_FILE_SIZE.

    Args:
        root: Path to the repository root.

    Returns:
        Sorted list of (relative_path, language) tuples where relative_path uses
        forward slashes.
    """
    results = []

    for dirpath, dirnames, filenames in os.walk(str(root)):
        # Prune ignored directories in-place (modifies dirnames in-place to affect os.walk)
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        # Process files in current directory
        for filename in filenames:
            # Check if file has a supported extension
            file_path = Path(filename)
            ext = file_path.suffix.lower()

            if ext not in LANG_BY_EXT:
                continue

            # Build full file path
            full_path = Path(dirpath) / filename

            # Skip files larger than MAX_FILE_SIZE
            try:
                file_size = full_path.stat().st_size
                if file_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                # Skip if we can't stat the file
                continue

            # Compute relative path with forward slashes
            rel_path = full_path.relative_to(root)
            rel_path_str = rel_path.as_posix()

            # Get language for this file
            lang = LANG_BY_EXT[ext]

            results.append((rel_path_str, lang))

    # Sort by relative path
    results.sort(key=lambda x: x[0])

    return results
