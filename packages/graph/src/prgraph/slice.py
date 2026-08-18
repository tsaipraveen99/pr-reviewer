"""context_slice: assemble a bounded, role-tagged code context around a set of
changed line ranges, for handing to a review/summarization prompt.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from prgraph.db import Edge, File, Symbol

_SNIPPET_LINE_CAP = 60

# Dedup priority when the same symbol qualifies for more than one role:
# changed > caller > callee > importer. Also used as the primary sort key.
_ROLE_PRIORITY = {"changed": 0, "caller": 1, "callee": 2, "importer": 3}


@dataclass(frozen=True)
class SliceEntry:
    """One symbol included in a context slice.

    Attributes:
        role: Why this symbol was included: "changed" | "caller" | "callee" |
            "importer".
        qualified_name: The symbol's fully qualified name.
        path: Repo-relative path of the file containing the symbol.
        start_line: 1-indexed start line of the symbol (inclusive).
        end_line: 1-indexed end line of the symbol (inclusive).
        snippet: Source text for the symbol's line range, capped at 60 lines.
    """

    role: str
    qualified_name: str
    path: str
    start_line: int
    end_line: int
    snippet: str


@dataclass(frozen=True)
class Slice:
    """A bounded, deduped, role-tagged set of SliceEntry rows."""

    entries: list[SliceEntry]


def _ranges_overlap_symbol(
    start_line: int, end_line: int, ranges: list[tuple[int, int]]
) -> bool:
    """True if [start_line, end_line] overlaps any (start, end) in `ranges`."""
    return any(
        start_line <= range_end and end_line >= range_start
        for range_start, range_end in ranges
    )


def _read_snippet(root: Path, path: str, start_line: int, end_line: int) -> str | None:
    """Read lines [start_line, end_line] (1-indexed, inclusive) of `root/path`,
    capped at `_SNIPPET_LINE_CAP` lines. Returns None if the file is missing on disk.
    """
    file_path = root / path
    if not file_path.is_file():
        return None
    lines = file_path.read_text().splitlines()
    snippet_lines = lines[start_line - 1 : end_line][:_SNIPPET_LINE_CAP]
    return "\n".join(snippet_lines)


def context_slice(
    session_factory: sessionmaker[Session],
    repo_id: int,
    root: Path,
    changed: list[tuple[str, list[tuple[int, int]]]],
    *,
    max_symbols: int = 30,
    max_chars: int = 15000,
) -> Slice:
    """Build a context slice for a set of changed (path, line-ranges) pairs.

    Roles (dedup priority changed > caller > callee > importer):
      - changed: non-module Symbols in the changed files that overlap any of
        that file's given ranges (an empty range list means the whole file --
        every non-module Symbol in it).
      - caller: src Symbols of `call` Edges whose dst is a changed Symbol.
      - callee: resolved dst Symbols of `call` Edges whose src is a changed
        Symbol (unresolved calls, dst_symbol_id IS NULL, contribute nothing).
      - importer: src Symbols (always module Symbols) of `import` Edges whose
        dst is any Symbol -- module or def -- belonging to a changed file.

    Entries are ordered by (role priority, path, start_line). `max_symbols`
    truncates that ordered list. Each surviving entry's snippet is read from
    `root` by line range and capped at 60 lines; a symbol whose file is
    missing on disk is dropped. If the total snippet length still exceeds
    `max_chars`, whole entries are dropped from the end (lowest priority
    first) until it fits.

    Args:
        session_factory: SQLAlchemy sessionmaker bound to the target engine.
        repo_id: Repository identifier to scope all queries to.
        root: Filesystem path to the repo checkout, for reading snippets.
        changed: (repo-relative path, [(start_line, end_line), ...]) pairs.
        max_symbols: Maximum number of entries to keep before char-trimming.
        max_chars: Maximum total snippet characters across all entries.

    Returns:
        A Slice with entries ordered by (role priority, path, start_line).
    """
    with session_factory() as session:
        changed_symbol_ids: set[int] = set()
        changed_file_symbol_ids: set[int] = set()

        for path, ranges in changed:
            file_row = session.execute(
                select(File).where(File.repo_id == repo_id, File.path == path)
            ).scalar_one_or_none()
            if file_row is None:
                continue

            file_symbols = list(
                session.execute(
                    select(Symbol).where(
                        Symbol.repo_id == repo_id, Symbol.file_id == file_row.id
                    )
                ).scalars()
            )
            changed_file_symbol_ids.update(s.id for s in file_symbols)

            for sym in file_symbols:
                if sym.kind == "module":
                    continue
                if not ranges or _ranges_overlap_symbol(
                    sym.start_line, sym.end_line, ranges
                ):
                    changed_symbol_ids.add(sym.id)

        caller_ids: set[int] = set()
        if changed_symbol_ids:
            caller_ids = {
                sid
                for sid in session.execute(
                    select(Edge.src_symbol_id).where(
                        Edge.repo_id == repo_id,
                        Edge.kind == "call",
                        Edge.dst_symbol_id.in_(changed_symbol_ids),
                    )
                ).scalars()
                if sid is not None
            }

        callee_ids: set[int] = set()
        if changed_symbol_ids:
            callee_ids = {
                sid
                for sid in session.execute(
                    select(Edge.dst_symbol_id).where(
                        Edge.repo_id == repo_id,
                        Edge.kind == "call",
                        Edge.src_symbol_id.in_(changed_symbol_ids),
                    )
                ).scalars()
                if sid is not None
            }

        importer_ids: set[int] = set()
        if changed_file_symbol_ids:
            importer_ids = {
                sid
                for sid in session.execute(
                    select(Edge.src_symbol_id).where(
                        Edge.repo_id == repo_id,
                        Edge.kind == "import",
                        Edge.dst_symbol_id.in_(changed_file_symbol_ids),
                    )
                ).scalars()
                if sid is not None
            }

        role_by_id: dict[int, str] = {}
        for sid in changed_symbol_ids:
            role_by_id[sid] = "changed"
        for sid in caller_ids:
            role_by_id.setdefault(sid, "caller")
        for sid in callee_ids:
            role_by_id.setdefault(sid, "callee")
        for sid in importer_ids:
            role_by_id.setdefault(sid, "importer")

        if not role_by_id:
            return Slice(entries=[])

        symbol_rows = list(
            session.execute(
                select(Symbol).where(Symbol.id.in_(role_by_id.keys()))
            ).scalars()
        )
        file_ids = {sym.file_id for sym in symbol_rows}
        files_by_id = {
            f.id: f
            for f in session.execute(
                select(File).where(File.id.in_(file_ids))
            ).scalars()
        }

        ordered = sorted(
            symbol_rows,
            key=lambda sym: (
                _ROLE_PRIORITY[role_by_id[sym.id]],
                files_by_id[sym.file_id].path,
                sym.start_line,
            ),
        )

        capped = ordered[:max_symbols]

        entries: list[SliceEntry] = []
        for sym in capped:
            file_row = files_by_id[sym.file_id]
            snippet = _read_snippet(root, file_row.path, sym.start_line, sym.end_line)
            if snippet is None:
                continue
            entries.append(
                SliceEntry(
                    role=role_by_id[sym.id],
                    qualified_name=sym.qualified_name,
                    path=file_row.path,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    snippet=snippet,
                )
            )

        total_chars = sum(len(e.snippet) for e in entries)
        while total_chars > max_chars and entries:
            dropped = entries.pop()
            total_chars -= len(dropped.snippet)

        return Slice(entries=entries)
