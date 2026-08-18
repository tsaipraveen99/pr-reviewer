# prgraph

`prgraph` builds a symbol-and-call graph of a Python/JavaScript/TypeScript
repository and uses it to assemble a bounded, role-tagged code **context
slice** around a set of changed lines — the pieces of context (callers,
callees, importers) an LLM reviewer needs to judge a diff without being
handed the whole repo.

It ships as a library (`prgraph.indexer`, `prgraph.slice`, `prgraph.db`) and
a small CLI (`prgraph`) for driving both from the command line.

## IR and graph model

Each source file is parsed (via `tree-sitter`) into a `FileIR`
(`prgraph.ir`): a flat list of `Def`s (functions/classes/methods/modules,
each with a dotted `qualified_name` and 1-indexed line range), `Import`s, and
`Call`s. Two parsers currently implement this contract:
`prgraph.parsers.python` and `prgraph.parsers.jsts` (JS/TS, one Tree-sitter
grammar per of `.js`/`.jsx`/`.ts`/`.tsx`).

`prgraph.indexer.index_repo` walks a repo, parses every changed file (by
content hash, so unchanged files are skipped on re-runs), and writes the
result into three SQL tables (`prgraph.db`):

- **`files`** — one row per source file, keyed by `(repo_id, path)`, with a
  content hash for incremental re-indexing.
- **`symbols`** — one row per `Def`: name, dotted `qualified_name`, `kind`
  (`module`/`class`/`function`/`method`), and line range.
- **`edges`** — one row per `Import` or `Call`, linking a source `Symbol` to
  a destination `Symbol` when resolution succeeds (`dst_symbol_id`) and
  always recording the raw target name (`dst_qualified_name`) even when it
  doesn't. Deleting a file cascades to its symbols and their outgoing edges;
  deleting a symbol `SET NULL`s edges that pointed at it from elsewhere, and
  a healing pass in `index_repo` tries to re-resolve those against the
  post-run symbol table (repairs renames and forward references).

`prgraph.slice.context_slice` then takes a `(repo_id, root, changed)` triple
— `changed` being `(path, [(start_line, end_line), ...])` pairs, or an empty
range list for "the whole file" — and returns a `Slice` of `SliceEntry`
rows, each tagged with a `role`:

- **changed** — non-module symbols in the changed files that overlap a
  given range.
- **caller** — symbols with a `calls` edge *into* a changed symbol.
- **callee** — symbols a changed symbol has a resolved `calls` edge *into*.
- **importer** — symbols with an `imports` edge into anything in a changed
  file.

Roles dedupe by priority (changed > caller > callee > importer — a symbol
that's both keeps only the higher one), the result is capped at
`max_symbols` entries, and each entry's source snippet is read from disk
(capped at 60 lines) with whole low-priority entries dropped from the end if
the total exceeds `max_chars`.

## CLI

```
prgraph index <path> [--db sqlite:///.prgraph.db] [--repo-id 0]
prgraph slice <path> --file <relpath>[:<start>-<end>[,<start>-<end>...]] ... [--db sqlite:///.prgraph.db] [--repo-id 0] [--json]
```

`<path>` must exist on disk (exit code 2 otherwise). `--file` is repeatable;
a bare `relpath` (no `:range`) means the whole file. `--db` accepts any
SQLAlchemy URL; the default is a `.prgraph.db` SQLite file in the current
directory. Both commands run `create_schema` first, so a fresh `--db`
target is created on demand.

### Example (real output, captured indexing this monorepo's `apps/api/src`)

```
$ uv run prgraph index ../../apps/api/src --db sqlite:////tmp/prcrew-graph.db
parsed=27 skipped=0 deleted=0 errors=0 symbols=104 edges=449

$ uv run prgraph slice ../../apps/api/src \
    --file prcrew/graph/verifier.py:58-58 \
    --db sqlite:////tmp/prcrew-graph.db
changed prcrew.graph.verifier.make_verifier prcrew/graph/verifier.py:58-112
caller prcrew.graph.build.build_graph prcrew/graph/build.py:18-32
importer prcrew.graph.build prcrew/graph/build.py:1-32
```

That's the whole point of the tool: pointing at the one line that defines
`make_verifier` in `prcrew/graph/verifier.py` pulls in exactly its one real
caller (`build_graph`, which wires it into the LangGraph review pipeline)
and its importing module — not the other 26 parsed files.

`--json` prints the same entries (plus `snippet`) as a JSON array instead of
one `role qualified_name path:start-end` line per entry:

```
$ uv run prgraph slice ../../apps/api/src \
    --file prcrew/graph/verifier.py:58-58 \
    --db sqlite:////tmp/prcrew-graph.db --json
[{"role": "changed", "qualified_name": "prcrew.graph.verifier.make_verifier", "path": "prcrew/graph/verifier.py", "start_line": 58, "end_line": 112, "snippet": "..."}, ...]
```

## Known limitations

- **Dynamic imports/calls are unresolved by design.** `importlib.import_module(...)`,
  `__import__(...)`, JS/TS dynamic `import(...)`, and any call whose callee
  isn't a literal identifier or dotted-attribute expression at parse time
  produce a `Call`/`Import` with no static target — they show up as
  unresolved (`dst_symbol_id` is `None`) rather than guessed at.
- **No re-exports.** `export { x } from "./y"` (JS/TS) and Python's
  `from .sub import x` re-exported via `__init__.py` are not traced through
  to the original definition; a consumer importing the re-exporting module
  gets an edge to that module/name, not to the underlying symbol.
- **JS/TS `this.method(...)` calls are unresolved.** The callee text is the
  dotted name `this.method`; since `this` is never a recorded import alias
  or local def, the resolver's prefix-matching ladder never terminates on it
  and it's left unresolved rather than assumed to be same-class dispatch.
- **Bare-name calls can resolve to the wrong symbol when the name is
  reused across the repo but not through an import.** If a call's callee is
  a single dot-free name that isn't traceable to a local def or import alias
  (e.g. it's a plain local variable holding a closure), `index_repo` falls
  back to "if exactly one `Symbol` in the whole repo has this name, resolve
  to it." This is usually right for singleton helpers, but it's a real
  false-positive source: indexing `apps/api/src` above, every `emit =
  emit_from(config); await emit(...)` call site in
  `graph/{build,verifier,synthesizer,specialists}.py` resolves as a `call`
  edge to `prcrew.api.runs.RunManager._execute.emit` — the *only* function
  actually named `def emit` anywhere in the repo — even though those sites
  are calling an unrelated local closure returned by `emit_from`, not that
  method. Treat single-candidate bare-name resolution as a heuristic, not a
  guarantee.
- **No cross-repo or third-party resolution.** Only in-repo, statically
  resolvable targets ever get a `dst_symbol_id`; imports of external
  packages keep `target_module=None` and stay as name-only edges.

## Development

```
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
```
