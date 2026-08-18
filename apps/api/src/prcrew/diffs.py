"""Parse unified diffs into new-side changed line ranges."""

import re
from dataclasses import dataclass

_FILE_RE = re.compile(r"^\+\+\+ (?:b/(.+)|/dev/null)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class ChangedFile:
    path: str
    ranges: list[tuple[int, int]]


def changed_ranges(diff: str) -> list[ChangedFile]:
    """New-side (path, [(start, end)]) pairs for every hunk in a unified diff.

    Deleted files (+++ /dev/null) and hunks with a zero-length new side are
    excluded. Ranges are the full new-side hunk span: what reviewers can
    anchor inline comments to, and what context_slice treats as changed.
    """
    files: list[ChangedFile] = []
    path: str | None = None
    ranges: list[tuple[int, int]] = []
    prev_line: str | None = None

    def flush() -> None:
        nonlocal path, ranges
        if path is not None and ranges:
            files.append(ChangedFile(path=path, ranges=ranges))
        path, ranges = None, []

    for line in diff.splitlines():
        m = _FILE_RE.match(line)
        if m and prev_line and prev_line.startswith("--- "):
            flush()
            path = m.group(1)  # None for /dev/null
            prev_line = line
            continue
        m = _HUNK_RE.match(line)
        if m and path is not None:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count > 0:
                ranges.append((start, start + count - 1))
        prev_line = line
    flush()
    return files


def line_is_changed(files: list[ChangedFile], path: str, line: int) -> bool:
    return any(
        start <= line <= end
        for f in files
        if f.path == path
        for start, end in f.ranges
    )
