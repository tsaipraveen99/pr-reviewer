"""Command-line interface for prgraph.

Two subcommands:
  - `prgraph index <path>` -- run create_schema + index_repo against a repo
    checkout, printing one line of IndexStats.
  - `prgraph slice <path> --file <relpath>[:<start>-<end>] ...` -- build a
    context_slice around the given changed files/ranges, printing one entry
    per line (or a JSON array with --json).
"""

import argparse
import json
import sys
from pathlib import Path

from prgraph.db import create_schema, make_engine, make_session_factory
from prgraph.indexer import index_repo
from prgraph.slice import SliceEntry, context_slice

DEFAULT_DB = "sqlite:///.prgraph.db"


def _parse_file_arg(raw: str) -> tuple[str, list[tuple[int, int]]]:
    """Parse one `--file` value.

    Accepts a bare relpath (whole file, i.e. an empty range list) or
    `relpath:start-end[,start-end...]` (one or more line ranges on that file).

    Args:
        raw: The raw `--file` argument value.

    Returns:
        (relpath, ranges) -- ranges is empty for a bare relpath.
    """
    if ":" not in raw:
        return raw, []
    path, range_part = raw.split(":", 1)
    ranges = []
    for chunk in range_part.split(","):
        start_str, _, end_str = chunk.partition("-")
        ranges.append((int(start_str), int(end_str)))
    return path, ranges


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prgraph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser(
        "index", help="Index a repo checkout into the graph store."
    )
    index_parser.add_argument("path", help="Path to the repo checkout to index.")
    index_parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"Database URL (default: {DEFAULT_DB})."
    )
    index_parser.add_argument(
        "--repo-id", type=int, default=0, help="Repository id (default: 0)."
    )

    slice_parser = subparsers.add_parser(
        "slice", help="Build a context slice around changed files/lines."
    )
    slice_parser.add_argument(
        "path", help="Path to the repo checkout (used to read snippets)."
    )
    slice_parser.add_argument(
        "--file",
        dest="files",
        action="append",
        required=True,
        metavar="relpath[:start-end]",
        help="Changed file, optionally with one or more line ranges. Repeatable.",
    )
    slice_parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"Database URL (default: {DEFAULT_DB})."
    )
    slice_parser.add_argument(
        "--repo-id", type=int, default=0, help="Repository id (default: 0)."
    )
    slice_parser.add_argument(
        "--json", action="store_true", help="Print entries as a JSON array."
    )

    return parser


def _require_existing_path(parser: argparse.ArgumentParser, raw_path: str) -> Path:
    """Resolve `raw_path`, or exit 2 via argparse's own error path if it's missing."""
    path = Path(raw_path)
    if not path.exists():
        parser.error(f"path does not exist: {raw_path}")
    return path


def _cmd_index(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root = _require_existing_path(parser, args.path)

    engine = make_engine(args.db)
    create_schema(engine)
    session_factory = make_session_factory(engine)

    stats = index_repo(session_factory, repo_id=args.repo_id, root=root)
    print(
        f"parsed={stats.parsed} skipped={stats.skipped} deleted={stats.deleted} "
        f"errors={stats.errors} symbols={stats.symbols} edges={stats.edges}"
    )
    return 0


def _format_entry_line(entry: SliceEntry) -> str:
    return f"{entry.role} {entry.qualified_name} {entry.path}:{entry.start_line}-{entry.end_line}"


def _cmd_slice(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root = _require_existing_path(parser, args.path)

    engine = make_engine(args.db)
    create_schema(engine)
    session_factory = make_session_factory(engine)

    merged: dict[str, list[tuple[int, int]]] = {}
    for raw in args.files:
        file_path, ranges = _parse_file_arg(raw)
        merged.setdefault(file_path, []).extend(ranges)
    changed = list(merged.items())

    result = context_slice(
        session_factory, repo_id=args.repo_id, root=root, changed=changed
    )

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "role": e.role,
                        "qualified_name": e.qualified_name,
                        "path": e.path,
                        "start_line": e.start_line,
                        "end_line": e.end_line,
                        "snippet": e.snippet,
                    }
                    for e in result.entries
                ]
            )
        )
    else:
        for e in result.entries:
            print(_format_entry_line(e))

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (excluding program name). Defaults to sys.argv[1:].

    Returns:
        Process exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "index":
        return _cmd_index(parser, args)
    return _cmd_slice(parser, args)


if __name__ == "__main__":
    sys.exit(main())
