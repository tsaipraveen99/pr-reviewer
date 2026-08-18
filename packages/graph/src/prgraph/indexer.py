"""Incremental store writer: walks a repo, parses changed files, and updates
the Symbol/Edge graph in a SQL database in one transaction per run.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from prgraph.db import Edge, File, Symbol
from prgraph.ir import Call, FileIR, Import
from prgraph.parsers.jsts import parse_jsts
from prgraph.parsers.python import parse_python
from prgraph.walk import content_hash, walk_repo


@dataclass(frozen=True)
class IndexStats:
    """Outcome of one `index_repo` run.

    Attributes:
        parsed: Number of files (re-)parsed because their content hash changed
            (or they're new).
        skipped: Number of files whose content hash matched the stored File
            row, so they were left untouched.
        deleted: Number of File rows removed because their path no longer
            exists on disk.
        symbols: Total Symbol row count for this repo after the run.
        edges: Total Edge row count for this repo after the run.
    """

    parsed: int
    skipped: int
    deleted: int
    symbols: int
    edges: int


def _parse_file(relpath: str, source: bytes, lang: str) -> FileIR:
    """Dispatch to the right parser for `lang`."""
    if lang == "python":
        return parse_python(relpath, source)
    return parse_jsts(relpath, source, lang)


def _resolve_import_dst(imp: Import, by_qualified: dict[str, int]) -> int | None:
    """Resolve an Import's destination Symbol id.

    Primary lookup is qualified_name == target_qualified; if that misses and
    the import names an in-repo module, fall back to qualified_name ==
    target_module (the module symbol itself).
    """
    dst_id = by_qualified.get(imp.target_qualified)
    if dst_id is None and imp.target_module is not None:
        dst_id = by_qualified.get(imp.target_module)
    return dst_id


def _resolve_call_dst(
    call: Call, by_qualified: dict[str, int], by_name: dict[str, list[int]]
) -> tuple[int | None, str]:
    """Resolve a Call's destination Symbol id and the dst_qualified_name to store.

    Primary lookup is the parser's resolved_qualified, if any. Failing that,
    a *bare* (dot-free) callee_name gets one more try: if exactly one Symbol
    in the repo has that name, resolve to it. Dotted (attribute/receiver)
    callee names never get this fallback -- they stay unresolved.
    """
    if call.resolved_qualified is not None:
        return by_qualified.get(call.resolved_qualified), call.resolved_qualified

    if "." not in call.callee_name:
        candidates = by_name.get(call.callee_name, [])
        if len(candidates) == 1:
            return candidates[0], call.callee_name

    return None, call.callee_name


def index_repo(
    session_factory: sessionmaker[Session], repo_id: int, root: Path
) -> IndexStats:
    """Incrementally index `root` (a repo checkout) into the graph store for `repo_id`.

    Algorithm (all in one transaction):
      1. Walk the repo; load existing File rows for repo_id.
      2. Per file: hash bytes; if unchanged, skip. Else parse via the right
         extractor, delete the file's old Symbols (cascades kill outgoing
         edges and SET NULL incoming ones), upsert the File row, insert new
         Symbols, and stage the FileIR for the edge phase.
      3. Files present in the DB but gone from disk: delete their File rows
         (cascade), counting each as `deleted`.
      4. Edge phase, run only after every Symbol (changed and unchanged
         files alike) exists in the DB: for each staged FileIR, insert
         import and call edges.
      5. Healing pass: for any Edge with a NULL dst_symbol_id, re-resolve it
         against the now-complete repo-wide qualified_name -> Symbol map.
         This repairs both edges SET NULL by a cross-file rename/delete and
         forward references seen on a file's first index.

    Args:
        session_factory: SQLAlchemy sessionmaker bound to the target engine.
        repo_id: Repository identifier to scope all rows to.
        root: Filesystem path to the repo checkout.

    Returns:
        IndexStats summarizing this run.
    """
    with session_factory() as session:
        now = datetime.now(UTC)

        entries = walk_repo(root)
        disk_paths = {relpath for relpath, _lang in entries}

        existing_files: dict[str, File] = {
            f.path: f
            for f in session.execute(
                select(File).where(File.repo_id == repo_id)
            ).scalars()
        }

        parsed = 0
        skipped = 0
        staged: list[FileIR] = []

        for relpath, lang in entries:
            data = (root / relpath).read_bytes()
            new_hash = content_hash(data)

            existing = existing_files.get(relpath)
            if existing is not None and existing.content_hash == new_hash:
                skipped += 1
                continue

            file_ir = _parse_file(relpath, data, lang)
            parsed += 1

            if existing is not None:
                # Cascades: kills this file's outgoing edges, SET NULLs
                # other files' edges that pointed at these symbols.
                session.execute(delete(Symbol).where(Symbol.file_id == existing.id))
                existing.lang = lang
                existing.content_hash = new_hash
                existing.parsed_at = now
                file_row = existing
            else:
                file_row = File(
                    repo_id=repo_id,
                    path=relpath,
                    lang=lang,
                    content_hash=new_hash,
                    parsed_at=now,
                )
                session.add(file_row)
                session.flush()  # need file_row.id for the Symbols below

            for d in sorted(file_ir.defs, key=lambda d: d.start_line):
                session.add(
                    Symbol(
                        repo_id=repo_id,
                        file_id=file_row.id,
                        name=d.name,
                        qualified_name=d.qualified_name,
                        kind=d.kind,
                        start_line=d.start_line,
                        end_line=d.end_line,
                    )
                )

            staged.append(file_ir)

        deleted = 0
        for relpath, existing in existing_files.items():
            if relpath not in disk_paths:
                session.delete(existing)  # cascade kills its Symbols + Edges
                deleted += 1

        session.flush()

        # Repo-wide symbol lookups, built only after every insert/delete above
        # has landed -- so both changed and unchanged files' symbols are in it.
        # Ordered by id (== insertion order, itself path-then-start_line) so
        # by_qualified/by_name collisions resolve deterministically.
        all_symbols = list(
            session.execute(
                select(Symbol).where(Symbol.repo_id == repo_id).order_by(Symbol.id)
            ).scalars()
        )
        by_qualified: dict[str, int] = {}
        by_name: dict[str, list[int]] = {}
        for sym in all_symbols:
            by_qualified.setdefault(sym.qualified_name, sym.id)
            by_name.setdefault(sym.name, []).append(sym.id)

        for file_ir in staged:
            module_symbol_id = by_qualified.get(file_ir.module_qualified)

            for imp in file_ir.imports:
                if module_symbol_id is None:
                    continue
                session.add(
                    Edge(
                        repo_id=repo_id,
                        src_symbol_id=module_symbol_id,
                        dst_symbol_id=_resolve_import_dst(imp, by_qualified),
                        dst_qualified_name=imp.target_qualified,
                        kind="import",
                    )
                )

            for call in file_ir.calls:
                src_id = by_qualified.get(call.caller_qualified)
                if src_id is None:
                    continue
                dst_id, dst_qualified_name = _resolve_call_dst(
                    call, by_qualified, by_name
                )
                session.add(
                    Edge(
                        repo_id=repo_id,
                        src_symbol_id=src_id,
                        dst_symbol_id=dst_id,
                        dst_qualified_name=dst_qualified_name,
                        kind="call",
                    )
                )

        session.flush()

        # Healing pass: repair any edge left dangling (SET NULL by a
        # cross-file symbol delete above, or an unresolved forward reference
        # from a prior run) now that every symbol exists.
        dangling = session.execute(
            select(Edge).where(Edge.repo_id == repo_id, Edge.dst_symbol_id.is_(None))
        ).scalars()
        for edge in dangling:
            match = by_qualified.get(edge.dst_qualified_name)
            if match is not None:
                edge.dst_symbol_id = match

        total_edges = (
            session.execute(select(Edge).where(Edge.repo_id == repo_id)).scalars().all()
        )

        session.commit()

        return IndexStats(
            parsed=parsed,
            skipped=skipped,
            deleted=deleted,
            symbols=len(all_symbols),
            edges=len(total_edges),
        )
