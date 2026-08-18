"""Read-only, sandboxed tools for the intent agent, plus slice rendering."""

import fnmatch
import re
from pathlib import Path

from prgraph.db import Edge, Symbol
from prgraph.slice import Slice
from sqlalchemy import select

_READ_CAP_LINES = 120
_GREP_CAP_MATCHES = 30
_GREP_FILE_CAP = 1_000_000
_NEIGHBOR_CAP = 20

GRAPH_NEIGHBORS_TOOL = {
    "name": "graph_neighbors",
    "description": "Callers, callees, and importers of a symbol from the repo's "
                    "code graph. Use qualified names like 'pkg.module.func'.",
    "input_schema": {"type": "object",
                      "properties": {"qualified_name": {"type": "string"}},
                      "required": ["qualified_name"]},
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read lines [start, end] of a repo file (1-indexed, max 120 lines).",
    "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "start": {"type": "integer"},
                                     "end": {"type": "integer"}},
                      "required": ["path"]},
}

GREP_TOOL = {
    "name": "grep",
    "description": "Search repo files with a Python regex. glob filters filenames "
                    "(e.g. '*.py'). Returns up to 30 matching lines with locations.",
    "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"},
                                     "glob": {"type": "string"}},
                      "required": ["pattern"]},
}


def render_slice(sl: Slice) -> str:
    parts = []
    for e in sl.entries:
        parts.append(f"[{e.role}] {e.qualified_name} ({e.path}:{e.start_line}-{e.end_line})\n{e.snippet}")
    return "\n\n".join(parts) or "(no graph context available)"


class ToolBelt:
    def __init__(self, root: Path, session_factory, repo_id: int):
        self._root = root.resolve()
        self._session_factory = session_factory
        self._repo_id = repo_id

    def executors(self) -> dict:
        return {"graph_neighbors": self.graph_neighbors,
                "read_file": self.read_file, "grep": self.grep}

    def graph_neighbors(self, args: dict) -> str:
        qname = args.get("qualified_name", "")
        with self._session_factory() as session:
            sym = session.execute(
                select(Symbol).where(Symbol.repo_id == self._repo_id,
                                      Symbol.qualified_name == qname)).scalars().first()
            if sym is None:
                return f"no symbol named {qname!r} in the graph"
            out = [f"{qname} ({sym.kind}, {self._path_of(session, sym)}:{sym.start_line}-{sym.end_line})"]
            callers = session.execute(
                select(Symbol).join(Edge, Edge.src_symbol_id == Symbol.id)
                .where(Edge.repo_id == self._repo_id, Edge.dst_symbol_id == sym.id,
                       Edge.kind == "calls").limit(_NEIGHBOR_CAP)).scalars().all()
            callees = session.execute(
                select(Symbol).join(Edge, Edge.dst_symbol_id == Symbol.id)
                .where(Edge.repo_id == self._repo_id, Edge.src_symbol_id == sym.id,
                       Edge.kind == "calls").limit(_NEIGHBOR_CAP)).scalars().all()
            importers = session.execute(
                select(Symbol).join(Edge, Edge.src_symbol_id == Symbol.id)
                .where(Edge.repo_id == self._repo_id, Edge.dst_symbol_id == sym.id,
                       Edge.kind == "imports").limit(_NEIGHBOR_CAP)).scalars().all()
            for label, rows in (("callers", callers), ("callees", callees),
                                ("importers", importers)):
                names = ", ".join(r.qualified_name for r in rows) or "(none)"
                out.append(f"{label}: {names}")
            return "\n".join(out)

    def _path_of(self, session, sym) -> str:
        from prgraph.db import File
        f = session.get(File, sym.file_id)
        return f.path if f else "?"

    def read_file(self, args: dict) -> str:
        target = (self._root / args.get("path", "")).resolve()
        if not target.is_relative_to(self._root):
            return "refused: path is outside the repository"
        if not target.is_file():
            return f"no such file: {args.get('path')}"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(args.get("start") or 1))
        end = int(args.get("end") or start + _READ_CAP_LINES - 1)
        end = min(end, start + _READ_CAP_LINES - 1, len(lines))
        body = "\n".join(f"{n}: {line}" for n, line in
                          enumerate(lines[start - 1:end], start=start))
        return body or "(empty range)"

    def grep(self, args: dict) -> str:
        try:
            rx = re.compile(args.get("pattern", ""))
        except re.error as e:
            return f"invalid regex: {e}"
        glob = args.get("glob") or "*"
        matches: list[str] = []
        for path in sorted(self._root.rglob("*")):
            if len(matches) >= _GREP_CAP_MATCHES:
                break
            if not path.is_file() or ".git" in path.parts:
                continue
            rel = path.relative_to(self._root)
            if not fnmatch.fnmatch(path.name, glob):
                continue
            try:
                if path.stat().st_size > _GREP_FILE_CAP:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    matches.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(matches) >= _GREP_CAP_MATCHES:
                        break
        return "\n".join(matches) or "(no matches)"
